from __future__ import annotations

from .common import *
from .baseline import (
    attach_baseline_fields,
    baseline_blocker_detail,
    baseline_record_blocks_full_suite,
    baseline_record_from_result,
    baseline_repair_accepts_failure,
    write_baseline_record,
)
from .commits import commit_current_patch, hardener_test_change_requires_rationale
from .git_safety import apply_check, apply_patch_file, changed_since_base, classify_apply_failure, head, reset_to
from .progress import progress_inline, scrub_local_references
from .queue import resolve_patch_path, write_manifest
from .runtime_state import (
    apply_runtime_state_actions,
    runtime_state_deferral_detail,
    runtime_state_deferral_reason,
    runtime_state_has_blocking_results,
)
from .verification import (
    classify_deferral_cause,
    manifest_is_baseline_repair,
    manifest_requires_full_verification,
    run_verification,
)

def mark_deferred(
    path: Path,
    manifest: dict[str, Any],
    *,
    target: Path,
    reason: str,
    detail: str,
    head_before_integration: str,
    checkpoint_commit: str | None,
    checks_run: list[str] | None = None,
    dry_run: bool,
) -> None:
    if reason not in DEFERRAL_REASONS:
        reason = "other"
    category, root_cause = classify_deferral_cause(reason, detail)
    if category in ENVIRONMENT_FAILURE_CATEGORIES and reason == "verification_failure":
        reason = "verification_environment_failure"
    sanitized_detail = scrub_local_references(detail, target)
    update = {
        "status": "deferred",
        "deferral_reason": reason,
        "deferral_category": category,
        "deferral_root_cause": progress_inline(root_cause, target, limit=300),
        "deferral_detail": sanitized_detail,
        "head_before_integration": head_before_integration,
        "integrated_at": utc_now().isoformat(timespec="seconds"),
        "checkpoint_commit": checkpoint_commit,
    }
    if checks_run is not None:
        update["checks_run"] = checks_run
    manifest.update(update)
    write_manifest(path, manifest, dry_run=dry_run)

def mark_applied(
    path: Path,
    manifest: dict[str, Any],
    *,
    accepted_commit: str | None,
    head_before_integration: str,
    checkpoint_commit: str | None,
    checks_run: list[str],
    dry_run: bool,
) -> None:
    manifest.update(
        {
            "status": "applied",
            "deferral_reason": None,
            "deferral_detail": "",
            "head_before_integration": head_before_integration,
            "integrated_at": utc_now().isoformat(timespec="seconds"),
            "checkpoint_commit": checkpoint_commit,
            "accepted_commit": accepted_commit,
            "checks_run": checks_run,
        }
    )
    write_manifest(path, manifest, dry_run=dry_run)

def patch_is_empty(patch: Path) -> bool:
    return not patch.exists() or patch.stat().st_size == 0

def batch_apply(
    target: Path,
    queued: list[tuple[Path, dict[str, Any]]],
    *,
    head_before: str,
    checkpoint_commit: str | None,
    baseline: dict[str, Any] | None,
    dry_run: bool,
) -> tuple[bool, list[tuple[Path, dict[str, Any]]], list[tuple[Path, dict[str, Any], str]]]:
    accepted: list[tuple[Path, dict[str, Any]]] = []
    deferred: list[tuple[Path, dict[str, Any], str]] = []
    for path, manifest in queued:
        patch = resolve_patch_path(target, manifest)
        manifest["head_before_integration"] = head_before
        if hardener_test_change_requires_rationale(manifest, target):
            mark_deferred(
                path,
                manifest,
                target=target,
                reason="guardrail_violation",
                detail="Hardener removed or substantially rewrote tests without a `Test change rationale:` summary line.",
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            deferred.append((path, manifest, "guardrail_violation"))
            continue
        if (
            manifest_requires_full_verification(manifest)
            and not manifest_is_baseline_repair(manifest)
            and baseline_record_blocks_full_suite(baseline)
        ):
            attach_baseline_fields(manifest, baseline)
            mark_deferred(
                path,
                manifest,
                target=target,
                reason="baseline_verification_blocker",
                detail=baseline_blocker_detail(target, baseline or {}),
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=[str(item) for item in (baseline or {}).get("checks_run") or []],
                dry_run=dry_run,
            )
            deferred.append((path, manifest, "baseline_verification_blocker"))
            continue
        if patch_is_empty(patch):
            accepted.append((path, manifest))
            continue
        check = apply_check(target, patch)
        if check.returncode != 0:
            reason, detail = classify_apply_failure(target, manifest, head_before, check.stderr)
            mark_deferred(
                path,
                manifest,
                target=target,
                reason=reason,
                detail=detail,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            deferred.append((path, manifest, reason))
            continue
        apply_result = apply_patch_file(target, patch, dry_run=dry_run)
        if apply_result.returncode != 0:
            mark_deferred(
                path,
                manifest,
                target=target,
                reason="conflict",
                detail=apply_result.stderr.strip() or "git apply failed after check",
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            deferred.append((path, manifest, "conflict"))
            continue
        accepted.append((path, manifest))
    verification = run_verification(target, [manifest for _, manifest in accepted])
    for _, manifest in accepted:
        manifest["checks_run"] = verification.checks_run
    return verification.ok, accepted, deferred

def replay_and_commit(
    target: Path,
    accepted: list[tuple[Path, dict[str, Any]]],
    *,
    head_before: str,
    checkpoint_commit: str | None,
    checks_run: list[str],
    dry_run: bool,
) -> list[tuple[Path, dict[str, Any], str | None]]:
    committed: list[tuple[Path, dict[str, Any], str | None]] = []
    reset_to(target, head_before, [manifest for _, manifest in accepted], dry_run=dry_run)
    for path, manifest in accepted:
        current_head = head(target) if not dry_run else head_before
        patch = resolve_patch_path(target, manifest)
        if not patch_is_empty(patch):
            result = apply_patch_file(target, patch, dry_run=dry_run)
            if result.returncode != 0:
                mark_deferred(
                    path,
                    manifest,
                    target=target,
                    reason="conflict",
                    detail=result.stderr.strip() or "Patch failed while replaying accepted batch.",
                    head_before_integration=head_before,
                    checkpoint_commit=checkpoint_commit,
                    dry_run=dry_run,
                )
                continue
        apply_runtime_state_actions(target, manifest, dry_run=dry_run)
        if runtime_state_has_blocking_results(manifest):
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            mark_deferred(
                path,
                manifest,
                target=target,
                reason=runtime_state_deferral_reason(manifest),
                detail=runtime_state_deferral_detail(manifest),
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=checks_run,
                dry_run=dry_run,
            )
            continue
        commit_hash = commit_current_patch(target, manifest, str(manifest.get("run_id") or ""), dry_run=dry_run)
        mark_applied(
            path,
            manifest,
            accepted_commit=commit_hash,
            head_before_integration=head_before,
            checkpoint_commit=checkpoint_commit,
            checks_run=checks_run,
            dry_run=dry_run,
        )
        committed.append((path, manifest, commit_hash))
    return committed

def integrate_individually(
    target: Path,
    queued: list[tuple[Path, dict[str, Any]]],
    *,
    head_before: str,
    checkpoint_commit: str | None,
    baseline: dict[str, Any] | None,
    dry_run: bool,
) -> list[tuple[Path, dict[str, Any], str | None]]:
    committed: list[tuple[Path, dict[str, Any], str | None]] = []
    for path, manifest in queued:
        patch = resolve_patch_path(target, manifest)
        current_head = head(target) if not dry_run else head_before
        if hardener_test_change_requires_rationale(manifest, target):
            mark_deferred(
                path,
                manifest,
                target=target,
                reason="guardrail_violation",
                detail="Hardener removed or substantially rewrote tests without a `Test change rationale:` summary line.",
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            continue
        if (
            manifest_requires_full_verification(manifest)
            and not manifest_is_baseline_repair(manifest)
            and baseline_record_blocks_full_suite(baseline)
        ):
            attach_baseline_fields(manifest, baseline)
            mark_deferred(
                path,
                manifest,
                target=target,
                reason="baseline_verification_blocker",
                detail=baseline_blocker_detail(target, baseline or {}),
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=[str(item) for item in (baseline or {}).get("checks_run") or []],
                dry_run=dry_run,
            )
            continue
        if patch_is_empty(patch):
            apply_runtime_state_actions(target, manifest, dry_run=dry_run)
            if runtime_state_has_blocking_results(manifest):
                mark_deferred(
                    path,
                    manifest,
                    target=target,
                    reason=runtime_state_deferral_reason(manifest),
                    detail=runtime_state_deferral_detail(manifest),
                    head_before_integration=head_before,
                    checkpoint_commit=checkpoint_commit,
                    checks_run=["No patch changes to apply."],
                    dry_run=dry_run,
                )
                continue
            mark_applied(
                path,
                manifest,
                accepted_commit=None,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=["No patch changes to apply."],
                dry_run=dry_run,
            )
            committed.append((path, manifest, None))
            continue
        check = apply_check(target, patch)
        if check.returncode != 0:
            reason, detail = classify_apply_failure(target, manifest, current_head, check.stderr)
            mark_deferred(
                path,
                manifest,
                target=target,
                reason=reason,
                detail=detail,
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            continue
        result = apply_patch_file(target, patch, dry_run=dry_run)
        if result.returncode != 0:
            mark_deferred(
                path,
                manifest,
                target=target,
                reason="conflict",
                detail=result.stderr.strip() or "git apply failed",
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                dry_run=dry_run,
            )
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            continue
        verification = run_verification(target, manifest)
        if not verification.ok:
            if not baseline_repair_accepts_failure(target, manifest, baseline, verification):
                mark_deferred(
                    path,
                    manifest,
                    target=target,
                    reason=verification.reason or "verification_failure",
                    detail=verification.detail,
                    head_before_integration=head_before,
                    checkpoint_commit=checkpoint_commit,
                    checks_run=verification.checks_run,
                    dry_run=dry_run,
                )
                reset_to(target, current_head, [manifest], dry_run=dry_run)
                continue
        apply_runtime_state_actions(target, manifest, dry_run=dry_run)
        if runtime_state_has_blocking_results(manifest):
            reset_to(target, current_head, [manifest], dry_run=dry_run)
            mark_deferred(
                path,
                manifest,
                target=target,
                reason=runtime_state_deferral_reason(manifest),
                detail=runtime_state_deferral_detail(manifest),
                head_before_integration=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=verification.checks_run,
                dry_run=dry_run,
            )
            continue
        commit_hash = commit_current_patch(target, manifest, str(manifest.get("run_id") or ""), dry_run=dry_run)
        if manifest_is_baseline_repair(manifest):
            post_head = head(target) if not dry_run else current_head
            record = baseline_record_from_result(target, verification, head_value=post_head, previous=baseline)
            write_baseline_record(target, record, dry_run=dry_run)
            attach_baseline_fields(manifest, record)
        mark_applied(
            path,
            manifest,
            accepted_commit=commit_hash,
            head_before_integration=head_before,
            checkpoint_commit=checkpoint_commit,
            checks_run=verification.checks_run,
            dry_run=dry_run,
        )
        committed.append((path, manifest, commit_hash))
    return committed
