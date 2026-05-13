"""Integrate queued multi-role automation patches in a local target repo."""

from __future__ import annotations

from .baseline import baseline_record_is_current, read_baseline_record, run_baseline_verification
from .cleanup import cleanup_artifacts
from .commits import checkpoint_dirty_main, commit_automation_state
from .common import *
from .git_safety import GitIndexLockBlocked, ensure_local_only, head, require_git_repo, reset_to, scan_push_hooks, update_info_exclude
from .locks import acquire_lock, release_lock
from .patching import batch_apply, integrate_individually, replay_and_commit
from .progress import deferred_manifests, triage_deferred_equivalents, update_progress, update_task_file
from .queue import all_role_manifests, create_integrator_manifest, load_queued_manifests
from .verification import manifest_requires_full_verification

def load_target_automation_env(target: Path) -> bool:
    """Load target dotenv values into this fresh CLI process without logging them."""

    try:
        from diffmogger.runtime.load_automation_env import build_environment
    except Exception:
        return False
    env = build_environment(target, dict(os.environ))
    os.environ.clear()
    os.environ.update(env)
    return True

def integrate(
    target: Path,
    run_id: str,
    *,
    dry_run: bool,
    force_baseline: bool = False,
    baseline_only: bool = False,
) -> int:
    if force_baseline:
        load_target_automation_env(target)
    require_git_repo(target)
    ensure_local_only(target)
    scan_push_hooks(target)
    update_info_exclude(target, dry_run=dry_run)
    lock = acquire_lock(target, run_id, dry_run=dry_run)
    checkpoint_commit: str | None = None
    dirty_files: list[str] = []
    head_before: str | None = None
    committed: list[tuple[Path, dict[str, Any], str | None]] = []
    deferred_count = 0
    verification_status = "not run"
    baseline_record: dict[str, Any] | None = None
    try:
        checkpoint_commit, dirty_files = checkpoint_dirty_main(target, run_id, dry_run=dry_run)
        head_before = head(target)
        if baseline_only:
            baseline_record = run_baseline_verification(
                target,
                head_value=head_before,
                dry_run=dry_run,
                force=True,
            )
            verification_status = f"baseline recheck {baseline_record.get('status') or 'unknown'}"
            triage_summary = triage_deferred_equivalents(target, dry_run=dry_run)
            cleanup_summary = [*triage_summary, *cleanup_artifacts(target, dry_run=dry_run)]
            deferred_count = len(deferred_manifests(target))
            update_progress(
                target,
                run_id=run_id,
                verification_status=verification_status,
                committed=[],
                deferred_count=deferred_count,
                checkpoint_commit=checkpoint_commit,
                cleanup_summary=cleanup_summary,
                dry_run=dry_run,
            )
            update_task_file(
                target,
                run_id=run_id,
                checkpoint_commit=checkpoint_commit,
                dirty_files=dirty_files,
                committed=[],
                deferred_count=deferred_count,
                dry_run=dry_run,
            )
            create_integrator_manifest(
                target,
                run_id=run_id,
                status="applied",
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                summary=f"Forced baseline recheck completed with status: {baseline_record.get('status') or 'unknown'}.",
                dry_run=dry_run,
            )
            commit_automation_state(target, run_id, dry_run=dry_run)
            print(
                f"BASELINE_RECHECK_COMPLETE run_id={run_id} status={baseline_record.get('status') or 'unknown'}"
            )
            if dry_run:
                print("DRY RUN: no files were modified.")
            return 0
        queued = load_queued_manifests(target)
        if not queued:
            existing_baseline = read_baseline_record(target)
            if force_baseline or not baseline_record_is_current(target, existing_baseline, head_before):
                baseline_record = run_baseline_verification(
                    target,
                    head_value=head_before,
                    dry_run=dry_run,
                    force=force_baseline,
                )
                verification_status = f"baseline {baseline_record.get('status') or 'unknown'}"
            else:
                baseline_record = existing_baseline
            triage_summary = triage_deferred_equivalents(target, dry_run=dry_run)
            cleanup_summary = [*triage_summary, *cleanup_artifacts(target, dry_run=dry_run)]
            update_progress(
                target,
                run_id=run_id,
                verification_status=verification_status if baseline_record else "no queued patches",
                committed=[],
                deferred_count=len(deferred_manifests(target)),
                checkpoint_commit=checkpoint_commit,
                cleanup_summary=cleanup_summary,
                dry_run=dry_run,
            )
            update_task_file(
                target,
                run_id=run_id,
                checkpoint_commit=checkpoint_commit,
                dirty_files=dirty_files,
                committed=[],
                deferred_count=len(deferred_manifests(target)),
                dry_run=dry_run,
            )
            create_integrator_manifest(
                target,
                run_id=run_id,
                status="applied",
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                summary=(
                    (
                        f"No queued patches. Baseline verification status: {baseline_record.get('status')}. "
                        if baseline_record
                        else "No queued patches. "
                    )
                    + ("Deferred duplicate triage updated existing manifests." if triage_summary else "")
                ).strip(),
                dry_run=dry_run,
            )
            commit_automation_state(target, run_id, dry_run=dry_run)
            print("No queued multi-role patches.")
            return 0

        if any(manifest_requires_full_verification(manifest) for _, manifest in queued):
            baseline_record = run_baseline_verification(
                target,
                head_value=head_before,
                dry_run=dry_run,
                force=force_baseline,
            )

        ok, accepted, deferred = batch_apply(
            target,
            queued,
            head_before=head_before,
            checkpoint_commit=checkpoint_commit,
            baseline=baseline_record,
            dry_run=dry_run,
        )
        deferred_count += len(deferred)
        if ok:
            checks = accepted[0][1].get("checks_run") if accepted else []
            committed = replay_and_commit(
                target,
                accepted,
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                checks_run=[str(item) for item in checks],
                dry_run=dry_run,
            )
            verification_status = "passed"
        else:
            verification_status = "batch failed; individual fallback used"
            reset_to(target, head_before, [manifest for _, manifest in queued], dry_run=dry_run)
            committed = integrate_individually(
                target,
                queued,
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                baseline=baseline_record,
                dry_run=dry_run,
            )
            deferred_count = sum(
                1
                for _, manifest in all_role_manifests(target)
                if manifest.get("status") == "deferred" and manifest.get("integrated_at")
            )
        triage_summary = triage_deferred_equivalents(target, dry_run=dry_run)
        cleanup_summary = [*triage_summary, *cleanup_artifacts(target, dry_run=dry_run)]
        deferred_count = len(deferred_manifests(target))
        update_progress(
            target,
            run_id=run_id,
            verification_status=verification_status,
            committed=committed,
            deferred_count=deferred_count,
            checkpoint_commit=checkpoint_commit,
            cleanup_summary=cleanup_summary,
            dry_run=dry_run,
        )
        update_task_file(
            target,
            run_id=run_id,
            checkpoint_commit=checkpoint_commit,
            dirty_files=dirty_files,
            committed=committed,
            deferred_count=deferred_count,
            dry_run=dry_run,
        )
        create_integrator_manifest(
            target,
            run_id=run_id,
            status="applied",
            head_before=head_before,
            checkpoint_commit=checkpoint_commit,
            summary=f"Accepted {len(committed)} patches; deferred {deferred_count}.",
            dry_run=dry_run,
        )
        commit_automation_state(target, run_id, dry_run=dry_run)
        print(f"INTEGRATION_COMPLETE run_id={run_id} accepted={len(committed)} deferred={deferred_count}")
        if dry_run:
            print("DRY RUN: no files were modified.")
        return 0
    except GitIndexLockBlocked as exc:
        detail = str(exc)
        print(f"INTEGRATOR_GIT_INDEX_LOCK_BLOCKED run_id={run_id} {detail}", file=sys.stderr)
        try:
            create_integrator_manifest(
                target,
                run_id=run_id,
                status="failed",
                head_before=head_before,
                checkpoint_commit=checkpoint_commit,
                summary=detail,
                dry_run=dry_run,
            )
        except OSError as record_exc:
            print(
                f"WARN: could not record integrator Git index lock failure for {run_id}: {record_exc}",
                file=sys.stderr,
            )
        return 1
    finally:
        release_lock(target, run_id, lock)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--run-id", default=f"{now_id()}-integrator", help="Run id for lock and manifest records")
    parser.add_argument("--dry-run", action="store_true", help="Report actions without mutating files")
    parser.add_argument("--force-baseline", action="store_true", help="Rerun baseline verification even if the ledger is current")
    parser.add_argument("--baseline-only", action="store_true", help="Only refresh baseline verification; do not integrate queued patches")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    return integrate(
        target,
        args.run_id,
        dry_run=args.dry_run,
        force_baseline=args.force_baseline,
        baseline_only=args.baseline_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
