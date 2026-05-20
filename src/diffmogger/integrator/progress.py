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
    # SQLite plus CODEX_AUTOMATION_TASKS.md are the generated target state surface.
    # update_task_file appends the small generated handoff note.
    return

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
