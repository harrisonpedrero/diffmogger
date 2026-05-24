from __future__ import annotations

from .common import *
from .git_safety import dirty_status, git, head
from .notifier import notify_commit_progress
from .queue import resolve_patch_path

def checkpoint_dirty_main(target: Path, run_id: str, *, dry_run: bool) -> tuple[str | None, list[str]]:
    status = dirty_status(target)
    if not status:
        return None, []
    dirty_files = [line[3:] if len(line) > 3 else line for line in status.splitlines()]
    if dry_run:
        return "DRY-RUN-CHECKPOINT", dirty_files

    git(target, "add", "-A", check=True)
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
        f"Run: {run_id}"
    )
    result = git(target, "commit", "-m", message, env=env)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(1)
    checkpoint = git(target, "rev-parse", "HEAD", check=True).stdout.strip()
    notify_commit_progress(
        target,
        commit_hash=checkpoint,
        commit_message=message,
        description=f"Checkpointed dirty main changes before integrator run {run_id}: {', '.join(dirty_files[:8]) or 'tracked local state'}.",
        run_id=run_id,
        dry_run=dry_run,
    )
    return checkpoint, dirty_files

def staged_or_worktree_changes(target: Path) -> bool:
    return bool(git(target, "status", "--porcelain").stdout.strip())

def commit_current_patch(target: Path, manifest: dict[str, Any], run_id: str, *, dry_run: bool) -> str | None:
    if dry_run:
        return "DRY-RUN-COMMIT"
    if not staged_or_worktree_changes(target):
        return None
    git(target, "add", "-A", check=True)
    role = str(manifest.get("role") or "role")
    patch_run_id = str(manifest.get("run_id") or "unknown")
    summary = first_summary_line(str(manifest.get("summary") or ""))
    message = semantic_commit_message(manifest, target, patch_run_id)
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

def commit_automation_state(target: Path, run_id: str, *, dry_run: bool) -> str | None:
    if dry_run:
        return "DRY-RUN-STATE-COMMIT"
    paths = [
        "docs/CODEX_AUTOMATION_TASKS.md",
    ]
    existing = [dpath(target, path).relative_to(target).as_posix() for path in paths if dpath(target, path).exists()]
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
        "integrate role work",
        "misc",
        "no summary",
        "update files",
        "update project",
        "work",
    }:
        return True
    return bool(re.fullmatch(r"(integrate|update|improve|change|modify) (builder|hardener|planner|role|automation)? ?work", lower))

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

def semantic_commit_message(manifest: dict[str, Any], target: Path, patch_run_id: str) -> str:
    role = str(manifest.get("role") or "role").strip().lower() or "role"
    changed_files = semantic_changed_files([str(path) for path in manifest.get("changed_files") or [] if isinstance(path, str)])
    intent = parse_commit_intent(str(manifest.get("summary") or ""), changed_files)
    commit_type = intent.get("type") or semantic_commit_type(changed_files)
    scope = intent.get("scope") or semantic_commit_scope(changed_files, role)
    action = intent.get("action") or semantic_commit_action(changed_files, role, semantic_patch_text(manifest, target), scope)
    return f"{commit_type}({scope}): {action}\n\nRole: {role}\nPatch-run: {patch_run_id}"

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
