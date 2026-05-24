"""launchd-first runner supervision with a portable local fallback."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from diffmogger.runtime.paths import target_path


def launchd_available() -> bool:
    return sys.platform == "darwin" and bool(shutil_which("launchctl"))


def shutil_which(command: str) -> str | None:
    from shutil import which

    return which(command)


def runner_label(target: Path) -> str:
    digest = hashlib.sha256(str(target.expanduser().resolve()).encode("utf-8")).hexdigest()[:12]
    return f"com.diffmogger.runner.{digest}"


def runner_state_path(target: Path) -> Path:
    path = target_path(target.expanduser().resolve(), "target/automation_runner.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def runner_log_dir(target: Path) -> Path:
    path = target_path(target.expanduser().resolve(), "target/automation_logs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def launch_agent_path(target: Path) -> Path:
    root = Path.home() / "Library" / "LaunchAgents"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{runner_label(target)}.plist"


RUNNER_REQUIRED_IMPORTS = ("diffmogger", "pydantic", "temporalio")


def _package_import_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runner_import_root(target: Path) -> Path:
    bundled = target.expanduser().resolve() / ".diffmogger" / "lib"
    if (bundled / "diffmogger").exists():
        return bundled
    return _package_import_root()


def _venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = str(Path(item).expanduser()) if item else ""
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _common_path(base_path: str = "") -> str:
    parts = [
        base_path or os.environ.get("PATH", ""),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    values: list[str] = []
    seen: set[str] = set()
    for chunk in parts:
        for item in chunk.split(os.pathsep):
            if item and item not in seen:
                seen.add(item)
                values.append(item)
    return os.pathsep.join(values)


def _resolve_executable(candidate: str) -> str | None:
    value = candidate.strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_absolute() or os.sep in value:
        return str(path) if path.exists() and os.access(path, os.X_OK) else None
    resolved = shutil_which(value)
    return resolved


def runner_python_candidates(target: Path) -> list[str]:
    target = target.expanduser().resolve()
    import_root = _package_import_root()
    candidates: list[str] = []
    env_python = os.environ.get("DIFFMOGGER_PYTHON", "").strip()
    if env_python:
        candidates.append(env_python)
    virtual_env = os.environ.get("VIRTUAL_ENV", "").strip()
    if virtual_env:
        candidates.append(str(_venv_python(Path(virtual_env).expanduser())))
    candidates.append(sys.executable)
    for base in (import_root.parent, import_root.parent.parent, target):
        candidates.append(str(_venv_python(base / ".venv")))
    candidates.append(str(_venv_python(target_path(target, "target/automation_venvs/diffmogger"))))
    candidates.append(str(_venv_python(target_path(target, "target/automation_venvs/root"))))
    candidates.append("python3")
    return _dedupe(candidates)


def _python_probe(executable: str, target: Path) -> dict[str, Any]:
    resolved = _resolve_executable(executable)
    if not resolved:
        return {"candidate": executable, "ok": False, "reason": "not_executable"}
    script = (
        "import importlib.util, sys; "
        "missing=[name for name in sys.argv[1:] if importlib.util.find_spec(name) is None]; "
        "print(','.join(missing)); "
        "raise SystemExit(1 if missing else 0)"
    )
    env = {
        "HOME": str(Path.home()),
        "PATH": _common_path(),
        "PYTHONPATH": str(runner_import_root(target)),
    }
    try:
        result = subprocess.run(
            [resolved, "-c", script, *RUNNER_REQUIRED_IMPORTS],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"candidate": executable, "path": resolved, "ok": False, "reason": type(exc).__name__}
    missing = result.stdout.strip()
    if result.returncode == 0:
        return {"candidate": executable, "path": resolved, "ok": True, "reason": "imports_available"}
    return {
        "candidate": executable,
        "path": resolved,
        "ok": False,
        "reason": "missing_imports",
        "missing": missing.split(",") if missing else list(RUNNER_REQUIRED_IMPORTS),
    }


def runner_python_record(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    probes = [_python_probe(candidate, target) for candidate in runner_python_candidates(target)]
    for probe in probes:
        if probe.get("ok") and probe.get("path"):
            return {"path": str(probe["path"]), "status": "ok", "probes": probes}
    fallback = _resolve_executable(sys.executable) or sys.executable
    return {"path": fallback, "status": "fallback_missing_runtime_imports", "probes": probes}


def runner_python(target: Path) -> str:
    return str(runner_python_record(target)["path"])


def runner_environment(target: Path, python: str | None = None, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or {})
    import_root = str(runner_import_root(target))
    existing_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [import_root, *[part for part in existing_pythonpath.split(os.pathsep) if part]]
    return {
        "HOME": env.get("HOME") or str(Path.home()),
        "PATH": _common_path(env.get("PATH", "")),
        "PYTHONPATH": os.pathsep.join(_dedupe(pythonpath_parts)),
        "PYTHONUNBUFFERED": "1",
        "DIFFMOGGER_PYTHON": python or runner_python(target),
        "DIFFMOGGER_WORKER_EXECUTION": env.get("DIFFMOGGER_WORKER_EXECUTION") or "codex",
    }


def temporal_command(target: Path, *, run_id: str = "launchd-cycle", max_fanout: int | None = None) -> list[str]:
    module = "diffmogger.orchestration.cli"
    command = [
        runner_python(target),
        "-m",
        module,
        "campaign-cycle",
        "--target",
        str(target.expanduser().resolve()),
        "--run-id",
        run_id,
    ]
    if max_fanout is not None:
        command.extend(["--max-fanout", str(max_fanout)])
    return command


def write_state(target: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = runner_state_path(target)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def read_state(target: Path) -> dict[str, Any]:
    try:
        data = json.loads(runner_state_path(target).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _domain_target() -> str:
    return f"gui/{os.getuid()}"


def write_launchd_plist(target: Path, command: list[str], *, keep_alive: bool = True) -> Path:
    label = runner_label(target)
    logs = runner_log_dir(target)
    plist = {
        "Label": label,
        "ProgramArguments": command,
        "WorkingDirectory": str(target.expanduser().resolve()),
        "RunAtLoad": True,
        "KeepAlive": keep_alive,
        "StandardOutPath": str(logs / "launchd.stdout.log"),
        "StandardErrorPath": str(logs / "launchd.stderr.log"),
        "EnvironmentVariables": runner_environment(target, command[0]),
    }
    path = launch_agent_path(target)
    with path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=True)
    return path


def launchd_start(target: Path) -> dict[str, Any]:
    python_record = runner_python_record(target)
    command = temporal_command(target)
    plist_path = write_launchd_plist(target, command)
    label = runner_label(target)
    subprocess.run(["launchctl", "bootout", _domain_target(), str(plist_path)], capture_output=True, text=True, check=False)
    result = subprocess.run(["launchctl", "bootstrap", _domain_target(), str(plist_path)], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        subprocess.run(["launchctl", "kickstart", "-k", f"{_domain_target()}/{label}"], capture_output=True, text=True, check=False)
    state = {
        "state": "running" if result.returncode == 0 else "start_failed",
        "supervisor": "launchd",
        "label": label,
        "plist_path": str(plist_path),
        "command": command,
        "command_display": shlex.join(command),
        "python": python_record.get("path"),
        "python_status": python_record.get("status"),
        "python_probes": python_record.get("probes", []),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "exit_code": result.returncode,
    }
    return write_state(target, state)


def launchd_stop(target: Path) -> dict[str, Any]:
    plist_path = launch_agent_path(target)
    label = runner_label(target)
    result = subprocess.run(["launchctl", "bootout", _domain_target(), str(plist_path)], capture_output=True, text=True, check=False)
    state = {
        "state": "stopped" if result.returncode == 0 else "stop_recorded",
        "supervisor": "launchd",
        "label": label,
        "plist_path": str(plist_path),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "exit_code": result.returncode,
    }
    return write_state(target, state)


def fallback_start(target: Path) -> dict[str, Any]:
    python_record = runner_python_record(target)
    command = temporal_command(target)
    logs = runner_log_dir(target)
    stdout = (logs / "fallback.stdout.log").open("ab")
    stderr = (logs / "fallback.stderr.log").open("ab")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(target.expanduser().resolve()),
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            close_fds=True,
            env={**os.environ, **runner_environment(target, command[0], base_env=os.environ)},
        )
    finally:
        stdout.close()
        stderr.close()
    return write_state(
        target,
        {
            "state": "running",
            "supervisor": "portable-subprocess",
            "pid": process.pid,
            "command": command,
            "command_display": shlex.join(command),
            "python": python_record.get("path"),
            "python_status": python_record.get("status"),
            "python_probes": python_record.get("probes", []),
        },
    )


def fallback_stop(target: Path) -> dict[str, Any]:
    state = read_state(target)
    pid = int(state.get("pid") or 0)
    stopped = False
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except OSError:
            stopped = False
    state.update({"state": "stopped" if stopped else "stale", "stopped_pid": pid})
    return write_state(target, state)


def start_runner(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    if launchd_available():
        return launchd_start(target)
    return fallback_start(target)


def stop_runner(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    state = read_state(target)
    if state.get("supervisor") == "launchd" or launchd_available():
        return launchd_stop(target)
    return fallback_stop(target)


def status(target: Path) -> dict[str, Any]:
    state = read_state(target)
    supervisor = state.get("supervisor") or ("launchd" if launchd_available() else "portable-subprocess")
    return {
        "state": state.get("state") or "stopped",
        "supervisor": supervisor,
        "runner_state_path": str(runner_state_path(target)),
        "launchd_available": launchd_available(),
        "label": runner_label(target),
        "runner": state,
    }
