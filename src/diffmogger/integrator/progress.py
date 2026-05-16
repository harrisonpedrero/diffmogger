from __future__ import annotations

from .common import *
from .baseline import read_baseline_record
from .commits import first_summary_line
from .queue import all_role_manifests, parse_created_at, read_manifest, write_manifest
from .verification import classify_deferral_cause, missing_pytest_failure
from diffmogger.runtime.paths import target_rel
from diffmogger.runtime.state_store import automation_control_state

def scrub_local_references(text: str, target: Path) -> str:
    text = ANSI_RE.sub("", str(text))
    replacements = {
        str(target): "<target>",
        str(Path.home()): "<home>",
        "agentic-kit-" + "lab": "<workspace>",
    }
    for old, new in replacements.items():
        if old:
            text = text.replace(old, new)
    return LOCAL_PATH_RE.sub("<local-path>", text)

def progress_inline(text: str, target: Path, *, limit: int = 240) -> str:
    scrubbed = scrub_local_references(text, target)
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip()
    if not scrubbed:
        return "No detail."
    if len(scrubbed) > limit:
        return scrubbed[: limit - 3].rstrip() + "..."
    return scrubbed

def summarize_deferral_for_progress(item: dict[str, Any], target: Path) -> str:
    category = str(item.get("deferral_category") or "").strip()
    root_cause = str(item.get("deferral_root_cause") or "").strip()
    if category and root_cause:
        return progress_inline(f"{category}: {root_cause}", target)
    detail = str(item.get("deferral_detail") or "")
    if missing_pytest_failure("pytest", detail):
        return "missing pytest in the verification environment; raw detail stays in the manifest."
    inferred_category, inferred_root_cause = classify_deferral_cause(str(item.get("deferral_reason") or "other"), detail)
    if inferred_category != "other":
        return progress_inline(f"{inferred_category}: {inferred_root_cause}", target)
    first_line = next((line.strip() for line in detail.splitlines() if line.strip()), detail)
    return progress_inline(first_line, target)

def compact_progress_section(text: str, target: Path, *, max_chars: int = 6000) -> str:
    scrubbed = scrub_local_references(text, target)
    lines: list[str] = []
    for line in scrubbed.splitlines():
        if len(line) > 320:
            line = line[:317].rstrip() + "..."
        lines.append(line)
    compacted = "\n".join(lines).strip()
    if len(compacted) <= max_chars:
        return compacted
    tail = compacted[-max_chars:].lstrip()
    first_newline = tail.find("\n")
    if first_newline != -1:
        tail = tail[first_newline + 1 :]
    return "- Older progress entries compacted to keep generated state skimmable.\n" + tail.strip()

def split_h2_sections(text: str) -> tuple[str, dict[str, str]]:
    lines = text.splitlines()
    header_lines: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        if line.startswith("## "):
            current = line.removeprefix("## ").strip()
            sections[current] = []
        elif current is None:
            header_lines.append(line)
        else:
            sections[current].append(line)
    return "\n".join(header_lines).strip(), {key: "\n".join(value).strip() for key, value in sections.items()}

def deferred_manifests(target: Path) -> list[dict[str, Any]]:
    return [manifest for _, manifest in all_role_manifests(target) if manifest.get("status") == "deferred"]

def deferred_equivalence_key(manifest: dict[str, Any]) -> str:
    role = str(manifest.get("role") or "role").strip().lower()
    changed_files = sorted(str(item).strip() for item in manifest.get("changed_files") or [] if str(item).strip())
    category = str(manifest.get("deferral_category") or manifest.get("deferral_reason") or "other").strip().lower()
    if not changed_files:
        patch_path = str(manifest.get("patch_path") or "")
        patch_name = Path(patch_path).name if patch_path else "no-patch"
        changed_files = [patch_name]
    payload = json.dumps([role, changed_files, category], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

def triage_status_for_deferred(manifest: dict[str, Any]) -> tuple[str, str]:
    reason = str(manifest.get("deferral_reason") or "other")
    category = str(manifest.get("deferral_category") or "")
    if reason == "baseline_verification_blocker":
        return "retryable-after-baseline-repair", "Repair or replace the baseline verification failure, then retry from current HEAD."
    if reason in {"staleness", "conflict"} or category in {"stale_patch", "apply_conflict"}:
        return "replace-from-current-HEAD", "Replace this work from current HEAD before retrying."
    if reason == "verification_environment_failure" or category in ENVIRONMENT_FAILURE_CATEGORIES:
        return "retryable-after-environment-repair", "Repair the environment or fixtures, then retry from current HEAD."
    if reason == "verification_failure":
        return "retryable", "Fix the failing assertion or provider/mock expectation, then retry from current HEAD."
    if reason == "guardrail_violation":
        return "superseded", "Archive this patch and replace it with a guardrail-compliant change if the intent still matters."
    return "needs-triage", "Inspect this deferred patch before launching more equivalent builder work."

def triage_deferred_equivalents(target: Path, *, dry_run: bool) -> list[str]:
    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path, manifest in all_role_manifests(target):
        if manifest.get("status") != "deferred":
            continue
        key = deferred_equivalence_key(manifest)
        grouped.setdefault(key, []).append((path, manifest))

    summary: list[str] = []
    for key, items in sorted(grouped.items()):
        if len(items) < 2:
            continue
        items.sort(key=lambda item: (parse_created_at(item[1], item[0].stat().st_mtime), str(item[0])))
        latest_path, latest = items[-1]
        latest_status, latest_action = triage_status_for_deferred(latest)
        latest.update(
            {
                "deferral_equivalence_key": key,
                "deferral_triage_status": latest_status,
                "deferral_next_action": latest_action,
                "deferral_triaged_at": utc_now().isoformat(timespec="seconds"),
            }
        )
        write_manifest(latest_path, latest, dry_run=dry_run)
        for path, manifest in items[:-1]:
            manifest.update(
                {
                    "status": "superseded",
                    "deferral_equivalence_key": key,
                    "deferral_triage_status": "superseded",
                    "deferral_next_action": f"Superseded by equivalent deferred patch {latest.get('run_id') or latest_path.parent.name}.",
                    "superseded_by_run_id": latest.get("run_id") or latest_path.parent.name,
                    "deferral_triaged_at": utc_now().isoformat(timespec="seconds"),
                }
            )
            write_manifest(path, manifest, dry_run=dry_run)
        role = str(latest.get("role") or "role")
        files = ", ".join(str(item) for item in latest.get("changed_files") or []) or "unrecorded files"
        summary.append(
            f"triaged {len(items)} equivalent {role} deferred patches for {files}; "
            f"kept {latest.get('run_id') or latest_path.parent.name} as {latest_status}"
        )
    return summary

def progress_counts(target: Path) -> tuple[dict[str, int], dict[str, int], int]:
    accepted = {role: 0 for role in QUEUE_ROLES}
    deferred = {role: 0 for role in QUEUE_ROLES}
    integrator_runs = 0
    for _, manifest in all_role_manifests(target):
        role = str(manifest.get("role") or "")
        if role == "integrator":
            integrator_runs += 1
        if role in accepted and manifest.get("status") == "applied":
            accepted[role] += 1
        if role in deferred and manifest.get("status") == "deferred":
            deferred[role] += 1
    return accepted, deferred, integrator_runs

def update_progress(
    target: Path,
    *,
    run_id: str,
    verification_status: str,
    committed: list[tuple[Path, dict[str, Any], str | None]],
    deferred_count: int,
    checkpoint_commit: str | None,
    cleanup_summary: list[str],
    dry_run: bool,
) -> None:
    progress = dpath(target, "docs/MULTI_ROLE_PROGRESS.md")
    sqlite_rel = target_rel(target, "target/orchestration.sqlite3")
    header = "\n\n".join(
        [
            "# Multi-Role Progress",
            f"Generated dashboard/export projection for optional multi-role automation. SQLite in `{sqlite_rel}` is the live state authority.",
            "Continuous DAG scheduler mode prioritizes queued integration, baseline repair, typed human-message triage, fast-follow replanning after planner deferral changes, review/hardening, validation, targeted repairs, and compatible build waves.",
        ]
    )
    sections: dict[str, str] = {}
    accepted_counts, deferred_counts, integrator_runs = progress_counts(target)
    deferred_items = deferred_manifests(target)
    control = automation_control_state(target)
    baseline = read_baseline_record(target)
    baseline_status = progress_inline(str(baseline.get("status") or "not_recorded"), target, limit=80)
    baseline_root = progress_inline(str(baseline.get("root_cause") or "No baseline verification recorded."), target)
    baseline_next = progress_inline(str(baseline.get("next_action") or "Run integrator baseline preflight."), target)
    accepted_lines = [
        f"- {progress_inline(str(manifest.get('role') or 'role'), target)} `{progress_inline(str(manifest.get('run_id') or 'unknown'), target, limit=80)}` -> {commit or 'no commit'}: {progress_inline(first_summary_line(str(manifest.get('summary') or '')) or 'No summary.', target)}"
        for _, manifest, commit in committed
    ] or ["- None."]
    backlog_lines = [
        f"- {progress_inline(str(item.get('role') or 'role'), target)} `{progress_inline(str(item.get('run_id') or 'unknown'), target, limit=80)}`: {progress_inline(str(item.get('deferral_reason') or 'other'), target, limit=80)}; {summarize_deferral_for_progress(item, target)}"
        for item in deferred_items
    ] or ["- None."]
    changed_files = sorted(
        {progress_inline(str(file), target, limit=160) for _, manifest, _ in committed for file in (manifest.get("changed_files") or [])}
    )
    recent_body = ""
    entry_lines = [
        f"### {utc_now().isoformat(timespec='seconds')} {run_id}",
        "",
        f"- verification: {progress_inline(verification_status, target)}",
        f"- baseline_verification: {baseline_status}; {baseline_root}",
        f"- accepted_patches: {len(committed)}",
        f"- deferred_patches: {deferred_count}",
        f"- checkpoint_commit: {checkpoint_commit or 'none'}",
        "- accepted:",
        *accepted_lines,
        "- files_changed:",
        *([f"  - {file}" for file in changed_files] or ["  - none"]),
    ]
    if cleanup_summary:
        entry_lines.extend(["- cleanup:", *[f"  - {line}" for line in cleanup_summary]])
    recent_body = (recent_body.rstrip() + "\n\n" + "\n".join(entry_lines)).strip()
    sections["Project State At Last Integration"] = "\n".join(
        [
            f"- Current product horizon: {progress_inline(str(control.get('horizon') or 'unknown'), target)}",
            f"- Horizon decision: {progress_inline(str(control.get('horizon_decision') or 'unknown'), target, limit=120)}",
            f"- Latest evidence: integrator run `{run_id}` accepted {len(committed)} patches and deferred {deferred_count}.",
            f"- Last integrator run: {utc_now().isoformat(timespec='seconds')}",
            f"- Last verification status: {progress_inline(verification_status, target)}",
            f"- Baseline verification: {baseline_status}; {baseline_root}",
            f"- Baseline next action: {baseline_next}",
        ]
    )
    sections["Cumulative Metrics"] = "\n".join(
        [
            f"- Total integrator runs: {integrator_runs}",
            "- Accepted patches by role:",
            *[f"  - {role}: {accepted_counts[role]}" for role in QUEUE_ROLES],
            "- Deferred patches by role:",
            *[f"  - {role}: {deferred_counts[role]}" for role in QUEUE_ROLES],
            f"- Current deferred queue depth: {len(deferred_items)}",
            "- Mean time from role-run completion to integration: not computed",
            "- Human messages handled: recorded in typed human-message state",
            "- Human requests created: recorded in typed human-message state",
            "- Human requests resolved: recorded in typed human-message state",
        ]
    )
    sections["Recent Activity Log"] = recent_body
    sections["Historical Summary"] = "- Historical progress is represented by role manifests and SQLite events."
    sections["Deferred-Patch Backlog"] = "\n".join(backlog_lines)
    sections["Architectural Decisions"] = "- None recorded in typed state."
    sections["Role Health"] = "\n".join(
        [
            f"- {role}: accepted={accepted_counts.get(role, 0)} deferred={deferred_counts.get(role, 0)}"
            for role in QUEUE_ROLES
        ]
        + [f"- integrator: runs={integrator_runs}"]
    )
    body = header.rstrip() + "\n\n"
    for section in PROGRESS_SECTIONS:
        body += f"## {section}\n\n{sections.get(section, '').strip()}\n\n"
    body = scrub_local_references(body, target)
    if not dry_run:
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(body.rstrip() + "\n", encoding="utf-8")

def update_task_file(
    target: Path,
    *,
    run_id: str,
    checkpoint_commit: str | None,
    dirty_files: list[str],
    committed: list[tuple[Path, dict[str, Any], str | None]],
    deferred_count: int,
    dry_run: bool,
) -> None:
    task = dpath(target, "docs/CODEX_AUTOMATION_TASKS.md")
    if not task.exists() or dry_run:
        return
    text = task.read_text(encoding="utf-8").rstrip()
    lines = [
        "",
        "",
        f"## Multi-Role Integration {run_id}",
        "",
        f"- checkpoint_commit: {checkpoint_commit or 'none'}",
        f"- dirty_files_checkpointed: {', '.join(dirty_files) if dirty_files else 'none'}",
        f"- accepted_patches: {len(committed)}",
        f"- deferred_patches: {deferred_count}",
        "- accepted_commits:",
        *[f"  - {manifest.get('role')} `{manifest.get('run_id')}` -> {commit or 'no commit'}" for _, manifest, commit in committed],
    ]
    task.write_text(text + "\n".join(lines).rstrip() + "\n", encoding="utf-8")
