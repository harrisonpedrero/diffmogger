from __future__ import annotations

import signal

from ..errors import *
from ..jsonio import *
from ..target import *

from diffmogger.runtime import ticket_run
from diffmogger import supervision
from diffmogger.runtime.state_store import (
    automation_control_state,
    load_runner_state as load_canonical_runner_state,
    runner_projection_path_for_target,
    state_snapshot as canonical_state_snapshot,
    write_runner_state as write_canonical_runner_state,
)

RUNNER_STOP_GRACE_SECONDS = 8
CONVEYOR_PROCESS_MARKERS = (
    "diffmogger.orchestration.cli",
    "run_temporal_worker.sh",
)
TARGET_OWNED_DESCENDANT_MARKERS = (
    *CONVEYOR_PROCESS_MARKERS,
    "run_role_automation.sh",
    "codex exec",
)
MCP_PROCESS_MARKERS = (
    "context7",
    "@upstash/context7-mcp",
    "playwright-mcp",
    "run_playwright_mcp.sh",
    "mcp-server-playwright",
)

def prereq_rows(items: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "ok": bool(item.ok),
            "required": bool(item.required),
            "category": "required" if bool(item.required) else "optional",
            "detail": item.detail,
        }
        for item in items
    ]

def effective_backend_path(dashboard_app: Any | None = None) -> str:
    native_path = os.environ.get("DIFFMOGGER_NATIVE_APP_PATH") or os.environ.get("PATH", "")
    explicit = os.environ.get("CODEX_AUTOMATION_PATH", "").strip()
    default_path = explicit
    if not default_path and dashboard_app is not None:
        default_path = str(getattr(dashboard_app, "DEFAULT_AUTOMATION_PATH", ""))
    if not default_path:
        default_path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    parts: list[str] = []
    seen: set[str] = set()
    for raw_path in [default_path, native_path]:
        for part in raw_path.split(os.pathsep):
            item = part.strip()
            if item and item not in seen:
                seen.add(item)
                parts.append(item)
    return os.pathsep.join(parts)

def tool_status(name: str, args: list[str], *, required: bool, path: str | None = None) -> dict[str, Any]:
    search_path = path or os.environ.get("PATH", "")
    resolved = shutil.which(name, path=search_path)
    if not resolved:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "path": "",
            "detail": f"{name} not found on PATH.",
        }
    try:
        result = subprocess.run(
            [resolved, *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=4,
            check=False,
            env={**os.environ, "PATH": search_path},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "path": resolved,
            "detail": str(exc),
        }
    detail = (result.stdout or result.stderr).strip().splitlines()
    first_detail = detail[0] if detail else resolved
    ok = result.returncode == 0
    if name == "python3":
        match = re.search(r"Python\s+(\d+)\.(\d+)(?:\.\d+)?", first_detail)
        if match:
            version_tuple = (int(match.group(1)), int(match.group(2)))
            if version_tuple < (3, 10):
                ok = False
                first_detail = f"{first_detail} (need Python 3.10+)."
    return {
        "name": name,
        "ok": ok,
        "required": required,
        "path": resolved,
        "detail": first_detail,
    }

def runtime_environment_snapshot(dashboard_app: Any | None = None) -> dict[str, Any]:
    dashboard_app = dashboard_app or load_dashboard_module()
    backend_path = effective_backend_path(dashboard_app)
    tools = [
        tool_status("python3", ["--version"], required=True, path=backend_path),
        tool_status("codex", ["--version"], required=True, path=backend_path),
        tool_status("bash", ["--version"], required=True, path=backend_path),
        tool_status("git", ["--version"], required=True, path=backend_path),
        tool_status("node", ["--version"], required=False, path=backend_path),
        tool_status("npm", ["--version"], required=False, path=backend_path),
        tool_status("npx", ["--version"], required=False, path=backend_path),
    ]
    return {
        "kit_root": str(KIT_ROOT),
        "backend_python": sys.executable,
        "backend_python_version": sys.version.split()[0],
        "native_app_path": os.environ.get("DIFFMOGGER_NATIVE_APP_PATH") or os.environ.get("PATH", ""),
        "effective_path": backend_path,
        "codex_automation_path_override": os.environ.get("CODEX_AUTOMATION_PATH", ""),
        "dotenv_loaded": bool(os.environ.get("DIFFMOGGER_BACKEND_DOTENV_LOADED")),
        "tools": tools,
    }

def setup_fix_suggestions(environment: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    environment = environment or runtime_environment_snapshot()
    tools = {str(item.get("name")): item for item in environment.get("tools", []) if isinstance(item, dict)}
    suggestions: list[dict[str, Any]] = []
    if not bool(tools.get("python3", {}).get("ok")):
        suggestions.append(
            {
                "id": "install-python",
                "title": "Install Homebrew Python",
                "detail": "Diffmogger's native backend needs Python 3.10 or newer.",
                "command": "brew install python",
            }
        )
    if not bool(tools.get("codex", {}).get("ok")):
        suggestions.append(
            {
                "id": "install-codex",
                "title": "Install and sign in to Codex CLI",
                "detail": "Run Codex once in Terminal so the native app and continuous automation can reuse the same account.",
                "command": "npm install -g @openai/codex && codex",
            }
        )
    if not bool(tools.get("node", {}).get("ok")) or not bool(tools.get("npx", {}).get("ok")):
        suggestions.append(
            {
                "id": "install-node",
                "title": "Install Node for optional MCP integrations",
                "detail": "Node and npx are advisory unless Context7 or Playwright MCP are enabled.",
                "command": "brew install node",
            }
        )
    suggestions.append(
        {
            "id": "rerun-native-checks",
            "title": "Rerun native environment checks",
            "detail": "Use this exact backend command from the cloned Diffmogger repo to reproduce the native setup doctor.",
            "command": "python3 scripts/dashboard_backend_cli.py diagnostics.environment",
        }
    )
    return suggestions

def native_prerequisites(target: Path, dashboard_app: Any) -> list[Any]:
    return dashboard_app.check_prerequisites(
        target,
        human_bridge_mode_from_state(target),
        optional_mcp_from_state(target, dashboard_app),
    )

def target_multi_role_enabled(target: Path) -> bool:
    return True

def target_ticket_campaign_enabled(target: Path) -> bool:
    for data in (load_intake(target), load_dashboard_state(target)):
        mode = str(data.get("campaign_mode") or data.get("automation_run_mode") or "").strip().lower()
        mode = mode.replace("-", "_").replace(" ", "_")
        if mode in {"bounded", "ticket_campaign"}:
            return True
    return False

def target_relative_display(target: Path, path: Path) -> str:
    try:
        return path.relative_to(target).as_posix()
    except ValueError:
        return str(path)

def target_allow_remotes(target: Path) -> bool:
    for data in (load_dashboard_state(target), load_intake(target)):
        if "multi_role_allow_remotes" in data:
            return bool(data.get("multi_role_allow_remotes"))
    return False

def target_git_remotes(target: Path) -> str:
    result = subprocess.run(
        ["git", "remote", "-v"],
        cwd=str(target),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return (result.stdout or result.stderr).strip() if result.returncode == 0 else ""

def task_file_control_state(target: Path) -> tuple[Path, dict[str, Any], str]:
    """Return typed automation control state plus the generated task projection path."""
    control = automation_control_state(target)
    status = str(control.get("status") or "").strip().upper()
    return existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"), control, status

def startable_statuses(dashboard_app: Any) -> set[str]:
    statuses = getattr(
        dashboard_app,
        "STARTABLE_STATUSES",
        {"ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT", "BLOCKED_ON_USER", "BLOCKED_ON_ENVIRONMENT"},
    )
    return {str(item).upper() for item in statuses}

def automation_ready(target: Path, dashboard_app: Any, *, allow_bootstrap_pending: bool = False) -> tuple[bool, str]:
    target = target.expanduser().resolve()
    ticket_campaign_enabled = target_ticket_campaign_enabled(target)
    required = [
        existing_or_target_path(target, ".agentic/project_intake.json"),
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
        target_script_path(target, "scripts/run_temporal_worker.sh"),
        target_script_path(target, "scripts/orchestration_cli.py"),
        existing_or_target_path(target, ".agentic/roles/planner.md"),
        existing_or_target_path(target, ".agentic/roles/builder.md"),
        existing_or_target_path(target, ".agentic/roles/hardener.md"),
        existing_or_target_path(target, ".agentic/roles/integrator.md"),
        target_script_path(target, "scripts/run_role_automation.sh"),
        target_script_path(target, "scripts/integrate_role_outputs.py"),
        target_script_path(target, "scripts/list_deferred_patches.py"),
    ]
    missing = [target_relative_display(target, path) for path in required if not path.exists()]
    if missing:
        return False, "Missing " + ", ".join(missing)
    if not dashboard_app.target_has_initial_commit(target):
        return False, "Continuous automation requires an initialized git repo with an initial commit."
    task_path, control_state, status = task_file_control_state(target)
    if not status:
        return False, "Missing typed automation control status in SQLite."
    if status == "CRITICAL_STOP":
        return False, "Automation status is CRITICAL_STOP; start requires a non-critical automation status."
    if ticket_campaign_enabled:
        ticket_state = ticket_run.ticket_source_state(target)
        if not bool(ticket_state.get("actionable")):
            return False, str(ticket_state.get("start_reason") or "Ticket campaign has no actionable ticket.")
    return True, "Ready."

def run_once_ready(target: Path, dashboard_app: Any) -> tuple[bool, str]:
    target = target.expanduser().resolve()
    required = [
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
        target_script_path(target, "scripts/run_temporal_worker.sh"),
    ]
    missing = [path.relative_to(target).as_posix() for path in required if not path.exists()]
    if missing:
        return False, "Missing " + ", ".join(missing)
    task_path, _control_state, status = task_file_control_state(target)
    if not status:
        return False, "Missing typed automation control status in SQLite."
    if status == "CRITICAL_STOP":
        return False, "Automation status is CRITICAL_STOP; run-once requires a non-critical automation status."
    return True, "Ready."

def automation_log_dir(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), "target/automation_logs")

def automation_runner_path(target: Path) -> Path:
    return supervision.runner_state_path(target)

def load_runner_state(target: Path) -> dict[str, Any]:
    state = load_canonical_runner_state(automation_runner_path(target))
    return state if isinstance(state, dict) else {}

def write_runner_state(target: Path, state: dict[str, Any]) -> Path:
    state = dict(state)
    state["schema_version"] = int(state.get("schema_version") or 1)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = automation_runner_path(target)
    write_canonical_runner_state(path, state)
    return path

def process_is_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    if hasattr(os, "waitpid"):
        try:
            waited_pid, _status = os.waitpid(value, os.WNOHANG)
        except ChildProcessError:
            waited_pid = 0
        except OSError:
            waited_pid = 0
        if waited_pid == value:
            return False
    return True

def automation_conveyor_lock_path(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), "target/codex_automation.lock")

def read_process_table() -> dict[int, dict[str, Any]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid=,command="],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except OSError:
        return {}
    table: dict[int, dict[str, Any]] = {}
    if result.returncode != 0:
        return table
    for raw in result.stdout.splitlines():
        parts = raw.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            pgid = int(parts[2])
        except ValueError:
            continue
        command = parts[3] if len(parts) > 3 else ""
        table[pid] = {"pid": pid, "ppid": ppid, "pgid": pgid, "command": command}
    return table

def read_conveyor_lock(target: Path) -> dict[str, Any]:
    path = automation_conveyor_lock_path(target)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def process_command_matches_target(target: Path, command: str, markers: tuple[str, ...] = CONVEYOR_PROCESS_MARKERS) -> bool:
    if not command:
        return False
    target_text = str(target.expanduser().resolve())
    return target_text in command and any(marker in command for marker in markers)

def process_command_is_target_runner(command: str) -> bool:
    return any(marker in command for marker in CONVEYOR_PROCESS_MARKERS)

def process_command_is_mcp(command: str) -> bool:
    lowered = str(command or "").lower()
    return any(marker.lower() in lowered for marker in MCP_PROCESS_MARKERS)

def process_command_has_target_owned_path(target: Path, command: str) -> bool:
    if not command:
        return False
    raw_target_text = str(target.expanduser())
    try:
        target_text = str(target.expanduser().resolve())
    except OSError:
        target_text = raw_target_text
    target_variants = sorted({raw_target_text, target_text})
    owned_markers = tuple(
        marker
        for base in target_variants
        for marker in (
            base,
            f"{base}/.diffmogger/",
            f"{base}/target/automation_",
            f"{base}/target/validation_jobs/",
        )
    )
    return any(marker in command for marker in owned_markers)

def descendant_pids(root_pids: set[int], table: dict[int, dict[str, Any]]) -> set[int]:
    descendants: set[int] = set()
    frontier = set(root_pids)
    while frontier:
        next_frontier: set[int] = set()
        for pid, row in table.items():
            if pid in root_pids or pid in descendants:
                continue
            if int(row.get("ppid") or 0) in frontier:
                descendants.add(pid)
                next_frontier.add(pid)
        frontier = next_frontier
    return descendants

def owned_mcp_cleanup_pids(target: Path, live: dict[str, Any], table: dict[int, dict[str, Any]]) -> list[int]:
    roots = {int(item) for item in live.get("roots") or [] if int(item) > 0}
    descendants = descendant_pids(roots, table) if roots else set()
    owned_existing = {int(item) for item in live.get("pids") or [] if int(item) > 0}
    candidates: set[int] = set()
    for pid, row in table.items():
        command = str(row.get("command") or "")
        if not process_command_is_mcp(command):
            continue
        if pid in descendants or pid in owned_existing:
            candidates.add(pid)
            continue
        ppid = int(row.get("ppid") or 0)
        parent = table.get(ppid)
        parent_command = str((parent or {}).get("command") or "")
        parent_codex_alive = parent is not None and "codex" in parent_command.lower()
        if not parent_codex_alive and process_command_has_target_owned_path(target, command):
            candidates.add(pid)
    return sorted(pid for pid in candidates if process_is_alive(pid))

def cleanup_owned_mcp_processes(target: Path, live: dict[str, Any], *, grace_seconds: float = 2.0) -> dict[str, Any]:
    table = read_process_table()
    pids = owned_mcp_cleanup_pids(target, live, table)
    if not pids:
        return {"pids": [], "terminated": False, "killed": False}
    signal_pids(pids, signal.SIGTERM)
    terminated = wait_for_processes_to_exit(pids, grace_seconds)
    killed = False
    if not terminated:
        killed = True
        signal_pids(pids, signal.SIGKILL)
        terminated = wait_for_processes_to_exit(pids, 1)
    return {"pids": pids, "terminated": terminated, "killed": killed}

def live_target_conveyor_processes(target: Path, runner_state: dict[str, Any] | None = None) -> dict[str, Any]:
    target = target.expanduser().resolve()
    table = read_process_table()
    roots: set[int] = set()
    sources: list[str] = []
    runner_state = runner_state or load_runner_state(target)
    runner_pid = runner_state.get("pid")
    if process_is_alive(runner_pid):
        pid_int = int(runner_pid)
        row = table.get(pid_int, {})
        if (
            str(runner_state.get("target") or "") == str(target)
            or process_command_matches_target(target, str(row.get("command") or ""))
            or process_command_is_target_runner(str(row.get("command") or ""))
        ):
            roots.add(pid_int)
            sources.append("runner_projection")
    lock = read_conveyor_lock(target)
    lock_pid = lock.get("pid")
    if process_is_alive(lock_pid):
        pid_int = int(lock_pid)
        row = table.get(pid_int, {})
        if process_command_matches_target(target, str(row.get("command") or "")) or process_command_is_target_runner(
            str(row.get("command") or lock.get("command") or "")
        ):
            roots.add(pid_int)
            sources.append("conveyor_lock")
    for pid, row in table.items():
        command = str(row.get("command") or "")
        if process_command_matches_target(target, command):
            roots.add(pid)
            sources.append("process_scan")
    if not roots:
        return {}
    descendants = descendant_pids(roots, table)
    owned = sorted(roots | descendants)
    root_pid = sorted(roots)[0]
    return {
        "root_pid": root_pid,
        "roots": sorted(roots),
        "pids": owned,
        "pgid": int(table.get(root_pid, {}).get("pgid") or root_pid),
        "sources": sorted(set(sources)),
        "lock": lock,
        "processes": {str(pid): table.get(pid, {}) for pid in owned},
    }

def attach_live_runner_state(target: Path, live: dict[str, Any]) -> dict[str, Any]:
    root_pid = int(live.get("root_pid") or 0)
    state = {
        "state": "running",
        "message": "Continuous automation is already running for this target.",
        "pid": root_pid,
        "pgid": int(live.get("pgid") or root_pid),
        "target": str(target.expanduser().resolve()),
        "attached": True,
        "process_sources": list(live.get("sources") or []),
        "owned_pids": list(live.get("pids") or []),
    }
    lock = live.get("lock") if isinstance(live.get("lock"), dict) else {}
    if lock.get("created_at"):
        state["started_at"] = str(lock.get("created_at"))
    write_runner_state(target, state)
    return load_runner_state(target)

def mark_stale_runner(target: Path, state: dict[str, Any]) -> dict[str, Any]:
    if state and state.get("state") == "running":
        state = dict(state)
        state["state"] = "stale"
        state["message"] = "Recorded automation runner is no longer alive."
        state["stale_detected_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_runner_state(target, state)
    return state

def running_runner_state(target: Path) -> dict[str, Any]:
    state = load_runner_state(target)
    live = live_target_conveyor_processes(target, state)
    if live:
        return attach_live_runner_state(target, live)
    if state.get("state") == "running" and process_is_alive(state.get("pid")):
        return state
    return mark_stale_runner(target, state)

def signal_pids(pids: list[int], sig: int) -> None:
    for pid in sorted({int(item) for item in pids if int(item) > 0}, reverse=True):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except OSError:
            continue

def signal_process_group_if_safe(live: dict[str, Any], sig: int) -> None:
    root_pid = int(live.get("root_pid") or 0)
    pgid = int(live.get("pgid") or 0)
    if root_pid > 0 and pgid == root_pid:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass
        except OSError:
            pass

def wait_for_processes_to_exit(pids: list[int], timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not any(process_is_alive(pid) for pid in pids):
            return True
        time.sleep(0.2)
    return not any(process_is_alive(pid) for pid in pids)

def cleanup_conveyor_lock_if_owned(target: Path, live: dict[str, Any]) -> None:
    path = automation_conveyor_lock_path(target)
    if not path.exists():
        return
    lock_pid = str((live.get("lock") if isinstance(live.get("lock"), dict) else {}).get("pid") or "")
    roots = {str(item) for item in live.get("roots") or []}
    if not lock_pid or lock_pid in roots or not process_is_alive(lock_pid):
        try:
            path.unlink()
        except OSError:
            pass

def automation_prerequisites(target: Path, dashboard_app: Any) -> list[Any]:
    items = native_prerequisites(target, dashboard_app)
    has_initial_commit = dashboard_app.target_has_initial_commit(target)
    items.append(
        dashboard_app.PrerequisiteItem(
            "Initial git commit for continuous automation",
            has_initial_commit,
            True,
            "Target has an initial git commit."
            if has_initial_commit
            else "Run scaffold again to create the local git repo and initial commit, or manually run `git init`, `git add .`, and `git commit -m 'chore: initial commit'`.",
        )
    )
    return items

def automation_status_snapshot(target: Path, dashboard_app: Any) -> dict[str, Any]:
    ready, ready_reason = automation_ready(target, dashboard_app)
    runner = supervision.status(target)
    running = runner.get("state") == "running"
    if running:
        state = "running"
        supervisor = runner.get("supervisor") or "unknown"
        message = f"Continuous automation is running under {supervisor}."
    elif ready:
        state = "stopped"
        message = "Continuous automation is ready to start."
    else:
        state = "not_ready"
        message = f"Continuous automation is not ready. {ready_reason}"
    log_dir = automation_log_dir(target)
    return {
        "state": state,
        "message": message,
        "platform": sys.platform,
        "pid": int(runner.get("runner", {}).get("pid") or 0) if running and isinstance(runner.get("runner"), dict) else None,
        "started_at": runner.get("runner", {}).get("started_at") if isinstance(runner.get("runner"), dict) else None,
        "runner_state_path": str(automation_runner_path(target)),
        "log_dir": str(log_dir),
        "log_paths": {
            "stdout": str(log_dir / "launchd.stdout.log"),
            "stderr": str(log_dir / "launchd.stderr.log"),
        },
        "ready": ready,
        "ready_reason": ready_reason,
        "can_start": ready and not running,
        "can_stop": running,
        "runner": runner,
    }

def latest_run_log(target: Path, dashboard_app: Any, *, max_lines: int = 160) -> dict[str, Any]:
    log_dir = automation_log_dir(target)
    candidates: list[Path] = []
    if log_dir.exists():
        candidates.extend(path for path in log_dir.glob("*.log") if path.is_file())
    if not candidates:
        return {
            "exists": False,
            "path": None,
            "rel_path": None,
            "modified_at": None,
            "content": "",
            "lines": [],
            "truncated": False,
        }
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    text, truncated = read_text_file(latest, max_bytes=120_000)
    raw_lines = text.splitlines()[-max_lines:]
    modified_at = mtime_iso(latest)
    return {
        "exists": True,
        "path": str(latest),
        "rel_path": latest.relative_to(target).as_posix() if latest.is_relative_to(target) else str(latest),
        "modified_at": modified_at,
        "content": "\n".join(raw_lines),
        "lines": [{"timestamp": modified_at, "text": line} for line in raw_lines],
        "truncated": truncated or len(text.splitlines()) > max_lines,
    }

def worker_controls_snapshot(target: Path, dashboard_app: Any, strategy: dict[str, Any]) -> dict[str, Any]:
    name = compact_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    worker_helper_exists = target_script_path(target, "scripts/spawn_worker_agent.sh").exists()
    integrator_helper_exists = (
        target_script_path(target, "scripts/run_role_automation.sh").exists()
        and existing_or_target_path(target, ".agentic/roles/integrator.md").exists()
    )
    return {
        "strategy": name,
        "worker_helper_exists": worker_helper_exists,
        "integrator_helper_exists": integrator_helper_exists,
        "can_run_read_only": worker_helper_exists and name in dashboard_app.WORKER_REPORT_STRATEGIES,
        "can_run_write": worker_helper_exists and name == "WRITE_WORKERS",
        "can_run_integrator": integrator_helper_exists and name == "INTEGRATION_ONLY",
        "read_only_reason": "Supported by current worker strategy." if worker_helper_exists and name in dashboard_app.WORKER_REPORT_STRATEGIES else f"Current strategy is {name}.",
        "write_reason": "Supported by current worker strategy." if worker_helper_exists and name == "WRITE_WORKERS" else f"Current strategy is {name}.",
        "integrator_reason": "Supported by current worker strategy." if integrator_helper_exists and name == "INTEGRATION_ONLY" else f"Current strategy is {name}.",
    }

def baseline_blocker_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    state = snapshot.get("state") if isinstance(snapshot.get("state"), dict) else {}
    rows: list[dict[str, Any]] = []
    for blocker in state.get("open_blockers") or []:
        if not isinstance(blocker, dict) or str(blocker.get("kind") or "") != "baseline_verification":
            continue
        review = blocker.get("blocker_review") if isinstance(blocker.get("blocker_review"), dict) else {}
        rows.append(
            {
                "name": "Baseline verification",
                "ok": False,
                "required": True,
                "category": "baseline",
                "kind": "baseline_verification",
                "status": str(blocker.get("status") or "open"),
                "detail": compact_text(blocker.get("summary") or review.get("summary") or "Baseline verification is blocked."),
                "blocker_id": str(blocker.get("blocker_id") or review.get("blocker_id") or ""),
                "can_recheck": True,
                "recheck_command": "blocker.recheck_baseline",
                "recheck_label": "Recheck blocker",
            }
        )
    return rows

def run_controls_snapshot(target: Path, dashboard_app: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    active_role_run = snapshot.get("conveyor", {}).get("active_role_run") if isinstance(snapshot.get("conveyor"), dict) else {}
    automation = automation_status_snapshot(target, dashboard_app)
    is_running = bool(active_role_run) or automation.get("state") == "running"
    return {
        "is_scaffolded": target_metadata(target)["automation_task_exists"],
        "is_running": is_running,
        "can_start_automation": bool(automation.get("can_start")) and not bool(active_role_run),
        "start_automation_reason": automation.get("message"),
        "bootstrap_pending": False,
        "can_bootstrap_and_start": False,
        "bootstrap_start_reason": "Start launches automation directly after scaffold.",
        "can_stop_automation": bool(automation.get("can_stop")),
        "stop_automation_reason": automation.get("message"),
        "can_run_safety_check": True,
    }

def run_subprocess_streamed(
    args: argparse.Namespace,
    command: list[str],
    *,
    cwd: Path,
    stage: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    stream_event(args, stage, "$ " + shlex.join(str(part) for part in command), data={"cwd": str(cwd)})
    lines: list[str] = []
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise BackendError(
            "Could not start backend command.",
            error_type="process_start_failed",
            details={"command": command, "cwd": str(cwd), "exception": str(exc)},
        ) from exc
    assert process.stdout is not None
    for line in process.stdout:
        text = line.rstrip("\n")
        lines.append(text)
        stream_event(args, stage, text)
    exit_code = process.wait()
    stream_event(
        args,
        stage,
        f"Command exited with code {exit_code}.",
        level="info" if exit_code == 0 else "error",
        data={"exit_code": exit_code},
    )
    return {
        "command": shlex.join(str(part) for part in command),
        "exit_code": exit_code,
        "stdout": "\n".join(lines).strip(),
        "stderr": "",
    }

def runtime_script_for_target(target: Path, legacy_rel: str) -> Path:
    script = target_script_path(target, legacy_rel)
    if script.exists():
        return script
    fallback = KIT_ROOT / "scripts" / "runtime" / Path(legacy_rel).name
    return fallback if fallback.exists() else script

def baseline_recheck_command(target: Path, run_id: str) -> list[str]:
    integrator = runtime_script_for_target(target, "scripts/integrate_role_outputs.py")
    if not integrator.exists():
        raise BackendError(
            "Baseline recheck requires the integrator runtime script.",
            error_type="baseline_recheck_unavailable",
            details={"missing": str(integrator)},
        )
    command = [
        sys.executable,
        str(integrator),
        str(target),
        "--run-id",
        run_id,
        "--force-baseline",
        "--baseline-only",
    ]
    loader = runtime_script_for_target(target, "scripts/load_automation_env.py")
    if loader.exists():
        return [sys.executable, str(loader), "--target", str(target), "--", *command]
    return command

def command_blocker_recheck_baseline(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    run_id = dashboard_app.dashboard_run_id("dashboard-baseline-recheck")
    command = baseline_recheck_command(target, run_id)
    env = {**os.environ, **dashboard_app.automation_environment(target)}
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_subprocess_streamed(args, command, cwd=target, stage="baseline", env=env)
    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    baseline = read_json_file(existing_or_target_path(target, "target/baseline_verification.json"))
    state = canonical_state_snapshot(target)
    baseline_status = str(baseline.get("status") or "unknown")
    write_dashboard_action_state(
        target,
        last_action="baseline_recheck_passed" if baseline_status == "passing" else "baseline_recheck_recorded",
        updates={
            "last_baseline_recheck_run_id": run_id,
            "last_baseline_recheck_started_at": started_at,
            "last_baseline_recheck_finished_at": finished_at,
            "last_baseline_recheck_status": baseline_status,
        },
    )
    return {
        "target": target_metadata(target),
        "run_id": run_id,
        "status": "pass" if baseline_status == "passing" else "blocked",
        "baseline_verification": baseline,
        "open_blockers": state.get("open_blockers") if isinstance(state.get("open_blockers"), list) else [],
        "result": result,
        "started_at": started_at,
        "finished_at": finished_at,
    }

def command_run_once(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    ready, reason = run_once_ready(target, dashboard_app)
    if not ready:
        raise BackendError(
            "Automation is not ready to run.",
            error_type="automation_not_ready",
            details={"reason": reason},
        )
    run_id = dashboard_app.dashboard_run_id("dashboard-run-once")
    command = supervision.temporal_command(target, run_id=run_id)
    base_env = {**os.environ, **dashboard_app.automation_environment(target)}
    env = {**base_env, **supervision.runner_environment(target, command[0], base_env=base_env)}
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = run_subprocess_streamed(args, command, cwd=target, stage="run", env=env)
    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_dashboard_action_state(
        target,
        last_action="run_once_completed" if result["exit_code"] == 0 else "run_once_failed",
        updates={
            "last_run_once_started_at": started_at,
            "last_run_once_finished_at": finished_at,
            "last_run_once_exit_code": result["exit_code"],
        },
    )
    return {
        "target": target_metadata(target),
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "started_at": started_at,
        "finished_at": finished_at,
        "result": result,
        "run_log": latest_run_log(target, dashboard_app),
    }

def command_automation_start(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    existing = supervision.status(target)
    if existing.get("state") == "running":
        stream_event(args, "automation", "Continuous automation is already running.")
        write_dashboard_action_state(target, last_action="automation_start_noop")
        return {
            "target": target_metadata(target),
            "automation": automation_status_snapshot(target, dashboard_app),
            "runner": existing,
            "started": False,
        }
    ready, reason = automation_ready(target, dashboard_app)
    if not ready:
        raise BackendError(
            "Automation is not ready to start.",
            error_type="automation_not_ready",
            details={"reason": reason},
        )
    items = automation_prerequisites(target, dashboard_app)
    failures = dashboard_app.required_failures(items)
    if failures:
        raise BackendError(
            "Fix required prerequisites before starting continuous automation.",
            error_type="prerequisites_failed",
            details={"failures": prereq_rows(failures)},
        )
    allow_remotes = target_allow_remotes(target)
    remotes = target_git_remotes(target)
    if remotes and not allow_remotes:
        raise BackendError(
            "Remote opt-in is required before starting continuous automation in a repo with configured remotes.",
            error_type="remote_opt_in_required",
            details={"remotes": remotes},
        )
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stream_event(args, "automation", "Starting supervised Temporal scheduler runner.", data={"cwd": str(target)})
    try:
        runner = supervision.start_runner(target)
    except OSError as exc:
        raise BackendError(
            "Could not start continuous automation.",
            error_type="automation_start_failed",
            details={"exception": str(exc)},
        ) from exc
    runner["started_at"] = started_at
    supervision.write_state(target, runner)
    write_dashboard_action_state(target, last_action="automation_started")
    stream_event(args, "automation", f"Started continuous automation under {runner.get('supervisor')}.")
    return {
        "target": target_metadata(target),
        "automation": automation_status_snapshot(target, dashboard_app),
        "runner": runner,
        "started": True,
    }

def command_automation_stop(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    runner = supervision.status(target)
    if runner.get("state") != "running":
        stream_event(args, "automation", "Continuous automation is not currently running.", level="warning")
        write_dashboard_action_state(target, last_action="automation_stop_noop")
        return {
            "target": target_metadata(target),
            "automation": automation_status_snapshot(target, dashboard_app),
            "runner": runner,
            "stopped": False,
            "forced": False,
        }

    stream_event(args, "automation", "Stopping supervised automation.")
    stopped_runner = supervision.stop_runner(target)
    stopped = stopped_runner.get("state") in {"stopped", "stop_recorded"}
    write_dashboard_action_state(target, last_action="automation_stopped" if stopped else "automation_stop_failed")
    return {
        "target": target_metadata(target),
        "automation": automation_status_snapshot(target, dashboard_app),
        "runner": stopped_runner,
        "stopped": stopped,
        "forced": False,
        "mcp_cleanup": {"pids": [], "terminated": False, "killed": False},
    }
