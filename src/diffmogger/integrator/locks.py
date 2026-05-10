from __future__ import annotations

from .common import *

@dataclass
class LockHandle:
    path: Path
    script_managed: bool

def acquire_lock(target: Path, run_id: str, *, dry_run: bool) -> LockHandle | None:
    if dry_run:
        return None
    lock_path = runtime_path(target, "target/codex_automation.lock")
    acquire = existing_or_target_path(target, "scripts/acquire_codex_lock.sh")
    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOCK_PATH": str(lock_path),
            "CODEX_RUN_ID": run_id,
            "CODEX_LOCK_OWNER_PID": str(os.getpid()),
        }
    )
    if acquire.exists():
        result = run(["bash", str(acquire), "multi-role integrator"], cwd=target, env=env)
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            raise SystemExit(1)
        return LockHandle(path=lock_path, script_managed=True)

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        print(f"Active Codex automation lock exists; refusing to acquire: {lock_path}", file=sys.stderr)
        raise SystemExit(1)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()}\nrun_id={run_id}\ncreated_at={utc_now().isoformat(timespec='seconds')}\n")
    return LockHandle(path=lock_path, script_managed=False)

def release_lock(target: Path, run_id: str, lock: LockHandle | None) -> None:
    if lock is None:
        return
    release = existing_or_target_path(target, "scripts/release_codex_lock.sh")
    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOCK_PATH": str(lock.path),
            "CODEX_RUN_ID": run_id,
            "CODEX_LOCK_OWNER_PID": str(os.getpid()),
        }
    )
    if lock.script_managed and release.exists():
        result = run(["bash", str(release)], cwd=target, env=env)
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
        return
    try:
        lock.path.unlink()
    except FileNotFoundError:
        pass
