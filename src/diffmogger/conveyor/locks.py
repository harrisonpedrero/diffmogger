from __future__ import annotations

from .state import *

def read_lock_fields(path: Path) -> dict[str, str]:
    text = read_text(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items()}
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields

def lock_is_active(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "no lock"
    fields = read_lock_fields(path)
    pid_text = fields.get("pid", "")
    pid = int(pid_text) if pid_text.isdigit() else None
    epoch_text = fields.get("created_at_epoch", "")
    stale_text = fields.get("stale_after_seconds", "")
    now_epoch = int(time.time())
    created_epoch = int(epoch_text) if epoch_text.isdigit() else int(path.stat().st_mtime)
    stale_after = int(stale_text) if stale_text.isdigit() else 14400
    age = max(0, now_epoch - created_epoch)
    if process_alive(pid):
        return True, f"pid {pid} is still running"
    if age < stale_after:
        run = fields.get("run_id", "unknown")
        return True, f"lock {run} is fresh but owner pid is not visible"
    return False, f"stale lock age_seconds={age}"

def acquire_conveyor_lock(path: Path, stale_seconds: int) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    now_epoch = int(time.time())
    if path.exists():
        fields = read_lock_fields(path)
        pid_text = fields.get("pid", "")
        pid = int(pid_text) if pid_text.isdigit() else None
        epoch_text = fields.get("created_at_epoch", "")
        created_epoch = int(epoch_text) if epoch_text.isdigit() else int(path.stat().st_mtime)
        age = max(0, now_epoch - created_epoch)
        if process_alive(pid):
            print(f"CONVEYOR_LOCK_ACTIVE path={path} pid={pid}", flush=True)
            return False
        if age < stale_seconds:
            print(f"CONVEYOR_LOCK_FRESH path={path} age_seconds={age}", flush=True)
            return False
        path.unlink()

    payload = {
        "pid": os.getpid(),
        "created_at": utc_now(),
        "created_at_epoch": now_epoch,
        "stale_after_seconds": stale_seconds,
        "command": "run_conveyor_automation.py",
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        print(f"CONVEYOR_LOCK_RACE path={path}", flush=True)
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"CONVEYOR_LOCK_ACQUIRED path={path} pid={os.getpid()}", flush=True)
    return True

def release_conveyor_lock(path: Path) -> None:
    if not path.exists():
        return
    fields = read_lock_fields(path)
    pid_text = fields.get("pid", "")
    if pid_text and pid_text != str(os.getpid()):
        print(f"CONVEYOR_LOCK_NOT_RELEASED path={path} owner_pid={pid_text}", flush=True)
        return
    try:
        path.unlink()
        print(f"CONVEYOR_LOCK_RELEASED path={path}", flush=True)
    except OSError as exc:
        print(f"CONVEYOR_LOCK_RELEASE_FAILED path={path} error={exc}", flush=True)
