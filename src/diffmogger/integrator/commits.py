from __future__ import annotations

from .common import *
from .git_safety import dirty_status, git, head
from .notifier import notify_commit_progress
from .queue import resolve_patch_path

COMMIT_DENY_EXACT_PATHS = {
    ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
    ".diffmogger/runtime/canonical_state_brief.md",
    ".diffmogger/runtime/automation_runner.json",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "target/automation_runner.json",
    "target/baseline_verification.json",
    "target/canonical_state_brief.md",
    "target/codex_automation.lock",
    "target/orchestration.sqlite3",
    "target/orchestration.sqlite3-shm",
    "target/orchestration.sqlite3-wal",
    "target/ticket_run_completion.json",
}

COMMIT_DENY_PREFIXES = (
    ".agentic/",
    ".diffmogger/agentic/",
    ".diffmogger/context/",
    ".diffmogger/lib/",
    ".diffmogger/runtime/",
    ".diffmogger/state/",
    ".git/",
    ".hg/",
    ".svn/",
    ".pnpm-store/",
    ".yarn/cache/",
    "coverage/",
    "dist/",
    "build/",
    "out/",
    "target/",
)

COMMIT_DENY_PARTS = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".parcel-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".turbo",
    ".venv",
    "__pycache__",
    "automation_logs",
    "automation_queue",
    "automation_venvs",
    "automation_worktrees",
    "node_modules",
    "secrets",
    "tmp",
    "venv",
}

COMMIT_DENY_NAMES = {
    ".DS_Store",
    ".env",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}

COMMIT_DENY_SUFFIXES = (
    ".7z",
    ".db",
    ".gz",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".zip",
)

ENV_PLACEHOLDER_NAMES = {
    ".env.example",
    ".env.sample",
    ".env.template",
}


def bool_setting(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def automation_checkpoint_commits_enabled(target: Path) -> bool:
    for name in ("DIFFMOGGER_AUTOMATION_CHECKPOINT_COMMITS", "AUTOMATION_CHECKPOINT_COMMITS"):
        raw = os.environ.get(name)
        if raw is not None and raw.strip():
            return bool_setting(raw, True)
    return bool_setting(project_intake(target).get("automation_checkpoint_commits"), True)


def normalize_commit_path(path: str) -> str:
    rel = str(path or "").replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def commit_path_is_safe(path: str) -> tuple[bool, str]:
    rel = normalize_commit_path(path)
    if not rel:
        return False, "empty path"
    rel_path = Path(rel)
    if rel_path.is_absolute() or any(part in {"", ".", ".."} for part in rel_path.parts):
        return False, "path escapes target checkout"
    if rel in COMMIT_DENY_EXACT_PATHS:
        return False, "generated Diffmogger projection or runtime state"
    if any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in COMMIT_DENY_PREFIXES):
        return False, "runtime, cache, or build output path"
    parts = set(rel_path.parts)
    if parts & COMMIT_DENY_PARTS:
        return False, "runtime, dependency, cache, or secret-bearing directory"
    name = rel_path.name
    if name in COMMIT_DENY_NAMES:
        return False, "local secret or noisy system file"
    if name.startswith(".env.") and name not in ENV_PLACEHOLDER_NAMES:
        return False, "local environment file"
    lowered = name.lower()
    if lowered.endswith(COMMIT_DENY_SUFFIXES):
        return False, "local database, log, archive, bytecode, or key material"
    return True, ""


def filter_commit_paths(paths: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    allowed: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        rel = normalize_commit_path(path)
        if not rel or rel in seen:
            continue
        seen.add(rel)
        ok, reason = commit_path_is_safe(rel)
        if ok:
            allowed.append(rel)
        else:
            skipped.append({"path": rel, "reason": reason})
    return allowed, skipped


def git_changed_paths(target: Path) -> list[str]:
    tracked = git(target, "diff", "--name-only", "-z", "HEAD", "--")
    untracked = git(target, "ls-files", "--others", "--exclude-standard", "-z", "--")
    paths: list[str] = []
    for output in (tracked.stdout, untracked.stdout):
        paths.extend(path for path in output.split("\0") if path)
    return paths


def committable_changed_paths(target: Path) -> tuple[list[str], list[dict[str, str]]]:
    return filter_commit_paths(git_changed_paths(target))


def stage_filtered_changes(target: Path, paths: list[str]) -> bool:
    git(target, "reset", "-q", check=True)
    if not paths:
        return False
    add = git(target, "add", "-A", "--", *paths)
    if add.returncode != 0:
        sys.stderr.write(add.stderr)
        raise SystemExit(1)
    diff = git(target, "diff", "--cached", "--quiet", "--exit-code")
    if diff.returncode == 0:
        return False
    if diff.returncode != 1:
        sys.stderr.write(diff.stderr)
        raise SystemExit(1)
    return True


def checkpoint_dirty_main(target: Path, run_id: str, *, dry_run: bool) -> tuple[str | None, list[str]]:
    status = dirty_status(target)
    if not status:
        return None, []
    if not automation_checkpoint_commits_enabled(target):
        return None, []
    safe_paths, skipped_paths = committable_changed_paths(target)
    if not safe_paths:
        return None, []
    if dry_run:
        return "DRY-RUN-CHECKPOINT", safe_paths

    if not stage_filtered_changes(target, safe_paths):
        return None, []
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    message = (
        "chore(integrator): checkpoint preexisting local changes\n\n"
        "Diffmogger-Checkpoint: preexisting-local-changes\n"
        f"Diffmogger-Run: {run_id}"
    )
    result = git(target, "commit", "-m", message, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    checkpoint = git(target, "rev-parse", "HEAD", check=True).stdout.strip()
    skipped_note = f"; skipped unsafe/noisy paths: {len(skipped_paths)}" if skipped_paths else ""
    notify_commit_progress(
        target,
        commit_hash=checkpoint,
        commit_message=message,
        description=(
            f"Checkpointed dirty main changes before integrator run {run_id}: "
            f"{', '.join(safe_paths[:8]) or 'tracked local state'}{skipped_note}."
        ),
        run_id=run_id,
        dry_run=dry_run,
    )
    return checkpoint, safe_paths


def git_checkout_available(target: Path) -> bool:
    return git(target, "rev-parse", "--is-inside-work-tree").returncode == 0


def stage_filtered_changes_nonfatal(target: Path, paths: list[str]) -> tuple[bool, str]:
    reset = git(target, "reset", "-q")
    if reset.returncode != 0:
        return False, reset.stderr.strip() or reset.stdout.strip() or "git reset failed"
    if not paths:
        return False, "no safe paths to stage"
    add = git(target, "add", "-A", "--", *paths)
    if add.returncode != 0:
        return False, add.stderr.strip() or add.stdout.strip() or "git add failed"
    diff = git(target, "diff", "--cached", "--quiet", "--exit-code")
    if diff.returncode == 0:
        return False, "no staged changes after filtering"
    if diff.returncode != 1:
        return False, diff.stderr.strip() or diff.stdout.strip() or "git diff --cached failed"
    return True, ""


def checkpoint_runtime_work(
    target: Path,
    run_id: str,
    *,
    group_id: str = "",
    ticket_ids: list[str] | None = None,
    node_ids: list[str] | None = None,
    summary: str = "",
    dry_run: bool,
) -> dict[str, Any]:
    ticket_ids = [item for item in (ticket_ids or []) if item]
    node_ids = [item for item in (node_ids or []) if item]
    result: dict[str, Any] = {
        "status": "skipped",
        "commit_hash": None,
        "paths": [],
        "skipped_paths": [],
        "reason": "",
    }
    if not git_checkout_available(target):
        result["reason"] = "target is not a git checkout"
        return result
    if not automation_checkpoint_commits_enabled(target):
        result["reason"] = "automation checkpoint commits are disabled"
        return result

    safe_paths, skipped_paths = committable_changed_paths(target)
    result["paths"] = safe_paths
    result["skipped_paths"] = skipped_paths
    if not safe_paths:
        result["reason"] = "no safe project changes to commit"
        return result
    if dry_run:
        result["status"] = "dry_run"
        result["commit_hash"] = "DRY-RUN-RUNTIME-CHECKPOINT"
        return result

    staged, reason = stage_filtered_changes_nonfatal(target, safe_paths)
    if not staged:
        result["reason"] = reason
        return result

    commit_type = semantic_commit_type(safe_paths)
    scope = semantic_commit_scope(safe_paths, "builder")
    action = trim_commit_action(summary) or semantic_commit_action(safe_paths, "builder", "", scope)
    body = [
        "Diffmogger-Checkpoint: runtime-work",
        f"Diffmogger-Run: {run_id or 'unknown'}",
    ]
    if group_id:
        body.append(f"Diffmogger-Group: {group_id}")
    if len(ticket_ids) == 1:
        body.append(f"Diffmogger-Ticket: {ticket_ids[0]}")
    elif ticket_ids:
        body.append(f"Diffmogger-Tickets: {', '.join(ticket_ids)}")
    if node_ids:
        body.append(f"Diffmogger-Nodes: {', '.join(node_ids[:8])}")
    body.append(f"Changed-Paths: {', '.join(safe_paths[:12])}")
    if len(safe_paths) > 12:
        body.append(f"Changed-Paths-Truncated: {len(safe_paths) - 12}")

    message = f"{commit_type}({scope}): {action}\n\n" + "\n".join(body)
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    commit = git(target, "commit", "-m", message, env=env)
    if commit.returncode != 0:
        result["reason"] = commit.stderr.strip() or commit.stdout.strip() or "git commit failed"
        return result

    commit_hash = head(target)
    result["status"] = "committed"
    result["commit_hash"] = commit_hash
    notify_commit_progress(
        target,
        commit_hash=commit_hash,
        commit_message=message,
        description=f"Checkpointed completed runtime work for {', '.join(ticket_ids) or group_id or run_id}.",
        run_id=run_id,
        dry_run=dry_run,
    )
    return result


def staged_or_worktree_changes(target: Path) -> bool:
    return bool(git(target, "status", "--porcelain").stdout.strip())


def commit_current_patch(target: Path, manifest: dict[str, Any], run_id: str, *, dry_run: bool) -> str | None:
    if dry_run:
        return "DRY-RUN-COMMIT"
    if not automation_checkpoint_commits_enabled(target):
        return None
    safe_paths, _skipped_paths = committable_changed_paths(target)
    if not safe_paths:
        return None
    if not stage_filtered_changes(target, safe_paths):
        return None
    role = str(manifest.get("role") or "role")
    patch_run_id = str(manifest.get("run_id") or "unknown")
    summary = first_summary_line(str(manifest.get("summary") or ""))
    message = semantic_commit_message(manifest, target, run_id or patch_run_id)
    if summary:
        message += f"\n\n{summary}"
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    result = git(target, "commit", "-m", message, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    commit_hash = head(target)
    notify_commit_progress(
        target,
        commit_hash=commit_hash,
        commit_message=message,
        description=summary or f"Integrated {role} patch {patch_run_id}.",
        run_id=run_id,
        dry_run=dry_run,
    )
    return commit_hash


def existing_safe_automation_state_paths(target: Path, paths: list[str]) -> list[str]:
    existing: list[str] = []
    for path in paths:
        destination = dpath(target, path)
        if not destination.exists():
            continue
        rel = destination.relative_to(target).as_posix()
        if commit_path_is_safe(rel)[0]:
            existing.append(rel)
    return existing


def commit_automation_state(target: Path, run_id: str, *, dry_run: bool) -> str | None:
    if not automation_checkpoint_commits_enabled(target):
        return None
    if dry_run:
        return "DRY-RUN-STATE-COMMIT"
    paths = [
        "docs/CODEX_AUTOMATION_TASKS.md",
    ]
    existing = existing_safe_automation_state_paths(target, paths)
    if not existing:
        return None
    result = git(target, "add", *existing)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return None
    diff = git(target, "diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return None
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Diffmogger Integrator",
            "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Integrator",
            "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
        }
    )
    message = f"chore(integrator): update multi-role state {run_id}"
    result = git(target, "commit", "-m", message, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    commit_hash = head(target)
    notify_commit_progress(
        target,
        commit_hash=commit_hash,
        commit_message=message,
        description=f"Updated multi-role progress and automation task state for integrator run {run_id}.",
        run_id=run_id,
        dry_run=dry_run,
    )
    return commit_hash

def normalize_summary_line(raw: str) -> str:
    line = raw.strip()
    line = line.lstrip("#>*- \t").strip()
    line = line.strip("` ")
    return re.sub(r"\s+", " ", line)

def is_generic_commit_action(action: str) -> bool:
    lower = re.sub(r"\s+", " ", action.strip().lower().strip(".:;"))
    if not lower:
        return True
    if lower.startswith(("base_commit", "codex_exit_code", "patch:", "review /", "review `<")):
        return True
    if "raw codex output" in lower or " role run " in lower:
        return True
    if lower in {
        "changes",
        "document automation progress",
        "integrate builder work",
        "integrate hardener work",
        "integrate planner work",
        "integrate designer work",
        "integrate role work",
        "misc",
        "no summary",
        "update files",
        "update project",
        "work",
    }:
        return True
    return bool(re.fullmatch(r"(integrate|update|improve|change|modify) (builder|designer|hardener|planner|role|automation)? ?work", lower))

def first_summary_line(text: str) -> str:
    skipped_prefixes = (
        "base_commit",
        "checks run:",
        "codex_exit_code",
        "commit scope:",
        "commit subject:",
        "commit type:",
        "patch:",
    )
    skipped_headings = {"checks", "checks run", "commit intent", "output", "summary"}
    for raw in text.splitlines():
        line = normalize_summary_line(raw)
        lower = line.lower()
        if not line or lower in skipped_headings:
            continue
        if lower.startswith(skipped_prefixes) or " role run " in lower:
            continue
        if is_generic_commit_action(line):
            continue
        return line[:200]
    return ""

def summary_field(text: str, field_name: str) -> str:
    prefix = f"{field_name.lower()}:"
    for raw in text.splitlines():
        line = normalize_summary_line(raw)
        if line.lower().startswith(prefix):
            return line[len(prefix) :].strip(" `")
    return ""

def normalize_commit_type(value: str) -> str:
    commit_type = re.sub(r"[^a-z]", "", value.strip().lower())
    return commit_type if commit_type in SEMANTIC_COMMIT_TYPES else ""

def slugify_scope(value: str) -> str:
    scope = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return scope[:48].strip("-")

def normalize_commit_scope(value: str) -> str:
    scope = slugify_scope(value)
    if not scope or scope in {"work", "changes", "files"}:
        return ""
    return scope

def trim_commit_action(action: str) -> str:
    action = normalize_summary_line(action).strip(".:;")
    conventional = CONVENTIONAL_SUBJECT_RE.match(action)
    if conventional:
        action = conventional.group("action").strip()
    if action[:1].isupper() and not action[:2].isupper():
        action = action[:1].lower() + action[1:]
    action = re.sub(r"\s+", " ", action).strip()
    if len(action) > 72:
        action = action[:72].rsplit(" ", 1)[0].strip()
    return "" if is_generic_commit_action(action) else action

def parse_commit_intent(summary: str, changed_files: list[str]) -> dict[str, str]:
    subject = summary_field(summary, "Commit subject") or summary_field(summary, "Commit message")
    if not subject:
        return {}

    intent: dict[str, str] = {}
    conventional = CONVENTIONAL_SUBJECT_RE.match(subject.strip())
    if conventional:
        intent["type"] = normalize_commit_type(conventional.group("type"))
        intent["scope"] = normalize_commit_scope(conventional.group("scope") or "")
        intent["action"] = trim_commit_action(conventional.group("action"))
    else:
        intent["type"] = normalize_commit_type(summary_field(summary, "Commit type"))
        intent["scope"] = normalize_commit_scope(summary_field(summary, "Commit scope"))
        intent["action"] = trim_commit_action(subject)

    if not intent.get("action"):
        return {}
    if intent.get("type") == "docs" and not docs_only(changed_files):
        intent.pop("type", None)
    if intent.get("scope") == "docs" and not docs_only(changed_files):
        intent.pop("scope", None)
    return {key: value for key, value in intent.items() if value}

def manifest_ticket_id(manifest: dict[str, Any]) -> str:
    for key in ("ticket_id", "task_id"):
        value = str(manifest.get(key) or "").strip()
        if value:
            return value
    for key in ("ticket_ids", "tickets", "ticket_cluster"):
        value = manifest.get(key)
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
        elif isinstance(value, str) and value.strip():
            return value.strip()
    for result in manifest.get("runtime_state_results") or []:
        if not isinstance(result, dict):
            continue
        value = str(result.get("ticket_id") or "").strip()
        if value:
            return value
    haystack = "\n".join(
        [
            str(manifest.get("run_id") or ""),
            str(manifest.get("worker_id") or ""),
            str(manifest.get("execution_group_id") or ""),
            str(manifest.get("patch_id") or ""),
            str(manifest.get("summary") or ""),
            "\n".join(str(item) for item in manifest.get("changed_files") or []),
        ]
    )
    match = re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", haystack, flags=re.IGNORECASE)
    return match.group(0).upper() if match else ""


def validation_summary_line(manifest: dict[str, Any]) -> str:
    checks = [str(item).strip() for item in manifest.get("checks_run") or [] if str(item).strip()]
    if checks:
        text = "; ".join(checks[:4])
        return text[:240]
    evidence = manifest.get("validation_evidence")
    if isinstance(evidence, list):
        summaries: list[str] = []
        for item in evidence:
            if isinstance(item, dict):
                command = str(item.get("command") or item.get("detail") or item.get("status") or "").strip()
                if command:
                    summaries.append(command)
            elif str(item).strip():
                summaries.append(str(item).strip())
        if summaries:
            return "; ".join(summaries[:4])[:240]
    return "not recorded"


def semantic_commit_message(manifest: dict[str, Any], target: Path, run_id: str) -> str:
    role = str(manifest.get("role") or "role").strip().lower() or "role"
    patch_run_id = str(manifest.get("run_id") or "").strip()
    changed_files = semantic_changed_files([str(path) for path in manifest.get("changed_files") or [] if isinstance(path, str)])
    intent = parse_commit_intent(str(manifest.get("summary") or ""), changed_files)
    commit_type = intent.get("type") or semantic_commit_type(changed_files)
    scope = intent.get("scope") or semantic_commit_scope(changed_files, role)
    action = intent.get("action") or semantic_commit_action(changed_files, role, semantic_patch_text(manifest, target), scope)
    body = [
        f"Diffmogger-Run: {run_id or patch_run_id or 'unknown'}",
    ]
    ticket_id = manifest_ticket_id(manifest)
    if ticket_id:
        body.append(f"Diffmogger-Ticket: {ticket_id}")
    body.append(f"Diffmogger-Role: {role}")
    if patch_run_id and patch_run_id != run_id:
        body.append(f"Diffmogger-Patch-Run: {patch_run_id}")
    body.append(f"Validation: {validation_summary_line(manifest)}")
    return f"{commit_type}({scope}): {action}\n\n" + "\n".join(body)

def semantic_changed_files(changed_files: list[str]) -> list[str]:
    meaningful = [
        path
        for path in changed_files
        if path not in AUTOMATION_BOOKKEEPING_FILES
        and not path.startswith(("target/", ".diffmogger/runtime/", ".diffmogger/state/", ".diffmogger/agentic/", ".diffmogger/scripts/", ".diffmogger/lib/"))
    ]
    return meaningful or changed_files

def is_doc_path(path: str) -> bool:
    return path == "README.md" or path.startswith("docs/") or path.endswith(".md")

def docs_only(changed_files: list[str]) -> bool:
    return bool(changed_files) and all(is_doc_path(path) for path in changed_files)

def is_test_path(path: str) -> bool:
    name = Path(path).name
    return path.startswith(("tests/", "test/")) or ".test." in name or ".spec." in name

def is_source_path(path: str) -> bool:
    return path.startswith(("src/", "services/")) and not is_test_path(path)

def semantic_commit_type(changed_files: list[str]) -> str:
    if not changed_files:
        return "chore"
    if docs_only(changed_files):
        return "docs"
    if any(is_source_path(path) for path in changed_files):
        return "feat"
    if any("browser_smoke" in path for path in changed_files):
        return "test"
    if any(path.startswith("services/") for path in changed_files):
        return "feat"
    if any(path.startswith(("scripts/", "templates/")) for path in changed_files):
        return "feat"
    if any(is_test_path(path) for path in changed_files):
        return "test"
    return "chore"

def semantic_commit_scope(changed_files: list[str], role: str) -> str:
    joined = "\n".join(changed_files)
    for marker, scope in [
        ("run_observatory.py", "observatory"),
        ("run_temporal_worker.sh", "orchestration"),
        ("orchestration_cli.py", "orchestration"),
        ("integrate_role_outputs.py", "integrator"),
        ("run_role_automation.sh", "role-runner"),
        ("check_integration_safety.py", "safety"),
        ("check_required_files.py", "scaffold"),
        ("validate_starter_kit.sh", "validation"),
        ("agentic-dashboard", "dashboard"),
        ("agentic-notifier", "notifier"),
    ]:
        if marker in joined:
            return scope

    for path in changed_files:
        if path.startswith("src/lib/"):
            stem = Path(path).stem
            return slugify_scope(re.sub(r"\.(test|spec)$", "", stem)) or "lib"
    if any(path.startswith("src/App.") for path in changed_files):
        return "app"
    if any(path.startswith("src/styles.") for path in changed_files):
        return "styles"
    if "browser_smoke" in joined:
        return "browser-smoke"

    if docs_only(changed_files):
        for marker, scope in [
            ("docs/DASHBOARD.md", "dashboard"),
            ("docs/FRESH_PROJECT_SETUP.md", "setup"),
            ("docs/LOCAL_FIRST_BASELINE.md", "local-first"),
            ("docs/DEVELOPMENT.md", "development"),
            ("docs/OPERATING_MODEL.md", "operating-model"),
        ]:
            if marker in changed_files:
                return scope
        return "docs"

    for path in changed_files:
        if path.startswith("scripts/"):
            return slugify_scope(Path(path).stem) or "scripts"
    return role or "automation"

def semantic_patch_text(manifest: dict[str, Any], target: Path) -> str:
    try:
        patch = resolve_patch_path(target, manifest)
        if patch.exists() and patch.is_file():
            return patch.read_text(encoding="utf-8", errors="replace")[:60_000]
    except OSError:
        pass
    return ""

def manifest_test_change_rationale(manifest: dict[str, Any]) -> str:
    value = str(manifest.get("test_change_rationale") or "").strip()
    if value:
        return value
    return summary_field(str(manifest.get("summary") or ""), "Test change rationale")

def hardener_test_change_requires_rationale(manifest: dict[str, Any], target: Path) -> bool:
    if str(manifest.get("role") or "").strip().lower() != "hardener":
        return False
    changed_tests = [str(path) for path in manifest.get("changed_files") or [] if is_test_path(str(path))]
    if not changed_tests or manifest_test_change_rationale(manifest):
        return False
    patch_text = semantic_patch_text(manifest, target)
    current_file = ""
    removed_lines = 0
    deleted_test_file = False
    for raw in patch_text.splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split()
            current_file = parts[3][2:] if len(parts) >= 4 and parts[3].startswith("b/") else ""
            continue
        if raw.startswith("deleted file mode") and is_test_path(current_file):
            deleted_test_file = True
        if is_test_path(current_file) and raw.startswith("-") and not raw.startswith("---"):
            removed_lines += 1
    return deleted_test_file or removed_lines >= 10

def semantic_commit_action(changed_files: list[str], role: str, patch_text: str = "", scope: str | None = None) -> str:
    joined = "\n".join(changed_files)
    lower_patch = patch_text.lower()
    scope = scope or semantic_commit_scope(changed_files, role)
    if "closure checklist" in lower_patch:
        return "add review closure checklist"
    if "baseline comparison" in lower_patch and (
        "no saved baseline" in lower_patch or "saving comparison baselines" in lower_patch
    ):
        return "add baseline comparison guidance"
    if "chrome-launch-diagnostics" in lower_patch or (
        "chrome" in lower_patch and "diagnostics" in lower_patch and "browser_smoke" in joined
    ):
        return "report browser smoke launch diagnostics"
    if "check_required_files.py" in joined:
        return "enforce generated target contracts"
    if "check_integration_safety.py" in joined:
        return "enforce local integration safety"
    if "integrate_role_outputs.py" in joined and "run_role_automation.sh" in joined:
        return "propagate ignored runtime state"
    if "run_observatory.py" in joined:
        return "surface automation progress details"
    if "run_temporal_worker.sh" in joined or "orchestration_cli.py" in joined:
        return "improve orchestration routing"
    if "agentic-dashboard" in joined:
        return "improve dashboard automation controls"
    if "validate_starter_kit.sh" in joined:
        return "strengthen starter kit validation"
    if docs_only(changed_files):
        if scope == "dashboard":
            return "document dashboard workflow"
        if scope == "setup":
            return "document project setup"
        if scope == "local-first":
            return "document local-first baseline"
        if scope == "development":
            return "document development workflow"
        return "update documentation"
    if "browser_smoke" in joined:
        return "harden browser smoke diagnostics"
    if any(is_test_path(path) for path in changed_files) and not any(is_source_path(path) for path in changed_files):
        return f"cover {scope} behavior"
    if any(is_source_path(path) for path in changed_files):
        if scope == "planning":
            return "update weekly planning workflow"
        return f"update {scope} workflow"
    if any(path.startswith(("scripts/", "templates/")) for path in changed_files):
        return f"improve {scope} automation"
    return f"update {scope} workflow"
