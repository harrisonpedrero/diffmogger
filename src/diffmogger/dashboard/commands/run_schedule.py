from __future__ import annotations

import signal

from ..errors import *
from ..jsonio import *
from ..target import *

from .inbox import inbox_snapshot

RUNNER_STOP_GRACE_SECONDS = 8

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
    for data in (load_intake(target), load_dashboard_state(target)):
        profile = str(data.get("automation_role_profile") or "").strip()
        if profile == "single_lane":
            return False
        if profile == "planner_builder_hardener_integrator":
            return bool(data.get("multi_role_automations_allowed", True))
        if "multi_role_automations_allowed" in data:
            return bool(data.get("multi_role_automations_allowed"))
    for marker_path in [
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
    ]:
        if marker_path.exists():
            text = marker_path.read_text(encoding="utf-8", errors="replace")
            if "Role profile: `single_lane`" in text:
                return False
            if "Role profile: `planner_builder_hardener_integrator`" in text:
                return True
            if "Multi-role automations allowed: true" in text:
                return True
            if "Multi-role automations allowed: false" in text:
                return False
    return False

def target_ticket_campaign_enabled(target: Path) -> bool:
    for data in (load_intake(target), load_dashboard_state(target)):
        if str(data.get("automation_run_mode") or "") == "ticket_campaign":
            return True
    return False

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

def automation_ready(target: Path, dashboard_app: Any) -> tuple[bool, str]:
    target = target.expanduser().resolve()
    required = [
        existing_or_target_path(target, ".agentic/project_intake.json"),
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/INITIAL_BOOTSTRAP_PROMPT.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
        target_script_path(target, "scripts/run_codex_automation.sh"),
        target_script_path(target, "scripts/run_conveyor_automation.sh"),
        target_script_path(target, "scripts/run_conveyor_automation.py"),
    ]
    if target_multi_role_enabled(target):
        required.extend(
            [
                existing_or_target_path(target, ".agentic/roles/planner.md"),
                existing_or_target_path(target, ".agentic/roles/builder.md"),
                existing_or_target_path(target, ".agentic/roles/hardener.md"),
                existing_or_target_path(target, ".agentic/roles/integrator.md"),
                existing_or_target_path(target, "docs/MULTI_ROLE_PROGRESS.md"),
                target_script_path(target, "scripts/run_role_automation.sh"),
                target_script_path(target, "scripts/integrate_role_outputs.py"),
                target_script_path(target, "scripts/list_deferred_patches.py"),
            ]
        )
    if target_ticket_campaign_enabled(target):
        required.append(existing_or_target_path(target, "docs/TICKET_RUN.md"))
    missing = [path.relative_to(target).as_posix() for path in required if not path.exists()]
    if missing:
        return False, "Missing " + ", ".join(missing)
    if not dashboard_app.target_has_initial_commit(target):
        return False, "Continuous automation requires an initialized git repo with an initial commit."
    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    task_text = task_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    if "Current baseline: not bootstrapped yet" in task_text:
        return False, "Bootstrap has not completed yet."
    status_match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    if not status_match:
        return False, f"Missing AUTOMATION_STATUS in {task_path.relative_to(target)}."
    status = status_match.group(1).strip().upper()
    if status not in dashboard_app.SCHEDULABLE_STATUSES:
        return False, f"Automation status is {status}; scheduling requires ACTIVE or ACTIVE_WITH_PENDING_USER_INPUT."
    return True, "Ready."

def run_once_ready(target: Path, dashboard_app: Any) -> tuple[bool, str]:
    target = target.expanduser().resolve()
    required = [
        existing_or_target_path(target, ".agentic/automation_prompt.md"),
        existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md"),
        target_script_path(target, "scripts/run_codex_automation.sh"),
    ]
    missing = [path.relative_to(target).as_posix() for path in required if not path.exists()]
    if missing:
        return False, "Missing " + ", ".join(missing)
    task_path = existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md")
    task_text = task_path.read_text(
        encoding="utf-8",
        errors="replace",
    )
    status_match = re.search(r"^AUTOMATION_STATUS:\s*(\S+)", task_text, re.MULTILINE)
    if not status_match:
        return False, f"Missing AUTOMATION_STATUS in {task_path.relative_to(target)}."
    status = status_match.group(1).strip().upper()
    if status not in dashboard_app.SCHEDULABLE_STATUSES:
        return False, f"Automation status is {status}; run-once requires ACTIVE or ACTIVE_WITH_PENDING_USER_INPUT."
    return True, "Ready."

def automation_log_dir(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), "target/automation_logs")

def automation_runner_path(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), "target/automation_runner.json")

def load_runner_state(target: Path) -> dict[str, Any]:
    state = read_json_file(automation_runner_path(target))
    return state if isinstance(state, dict) else {}

def write_runner_state(target: Path, state: dict[str, Any]) -> Path:
    state = dict(state)
    state["schema_version"] = int(state.get("schema_version") or 1)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = automation_runner_path(target)
    write_json_file(path, state)
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
    if state.get("state") == "running" and process_is_alive(state.get("pid")):
        return state
    return mark_stale_runner(target, state)

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
            else "Run `git init`, `git add .`, and `git commit -m 'chore: initial commit'` before starting continuous automation.",
        )
    )
    if (
        human_bridge_mode_from_state(target) in {"local_notifier", "discord_notifier"}
        and bool(load_dashboard_state(target).get("local_notifications_enabled", True))
    ):
        osascript_path = shutil.which("osascript")
        items.append(
            dashboard_app.PrerequisiteItem(
                "macOS desktop notifications",
                bool(osascript_path),
                False,
                osascript_path
                or f"osascript unavailable; notifier delivery will record LOCAL_NOTIFICATION_FAILED in {sidecar_rel('docs/HUMAN_OUTBOX.md')}.",
            )
        )
    return items

def automation_status_snapshot(target: Path, dashboard_app: Any) -> dict[str, Any]:
    ready, ready_reason = automation_ready(target, dashboard_app)
    runner = running_runner_state(target)
    running = runner.get("state") == "running" and process_is_alive(runner.get("pid"))
    if running:
        state = "running"
        message = f"Continuous automation is running (pid {runner.get('pid')})."
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
        "pid": int(runner.get("pid") or 0) if running else None,
        "started_at": runner.get("started_at") if running else None,
        "runner_state_path": str(automation_runner_path(target)),
        "log_dir": str(log_dir),
        "log_paths": {
            "stdout": str(log_dir / "conveyor.runner.stdout.log"),
            "stderr": str(log_dir / "conveyor.runner.stderr.log"),
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

def run_controls_snapshot(target: Path, dashboard_app: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    active_role_run = snapshot.get("conveyor", {}).get("active_role_run") if isinstance(snapshot.get("conveyor"), dict) else {}
    automation = automation_status_snapshot(target, dashboard_app)
    is_running = bool(active_role_run) or automation.get("state") == "running"
    return {
        "is_scaffolded": target_metadata(target)["automation_task_exists"],
        "is_running": is_running,
        "can_start_automation": bool(automation.get("can_start")) and not bool(active_role_run),
        "start_automation_reason": automation.get("message"),
        "can_stop_automation": bool(automation.get("can_stop")),
        "stop_automation_reason": automation.get("message"),
        "can_run_safety_check": True,
        "can_export_review": target_metadata(target)["automation_task_exists"],
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

def command_run_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    snapshot = build_observatory_snapshot(target)
    strategy = snapshot.get("worker_strategy") if isinstance(snapshot.get("worker_strategy"), dict) else {}
    automation = automation_status_snapshot(target, dashboard_app)
    controls = run_controls_snapshot(target, dashboard_app, snapshot)
    prerequisites = automation_prerequisites(target, dashboard_app)
    environment_blockers = [
        row for row in prereq_rows(prerequisites)
        if row["required"] and not row["ok"]
    ]
    latest_worker_result = dashboard_app.latest_worker_result(target)
    return {
        "target": target_metadata(target),
        "task": snapshot.get("task") or {},
        "human": snapshot.get("human") or {},
        "git": snapshot.get("git") or {},
        "queue": snapshot.get("queue") or {},
        "conveyor": snapshot.get("conveyor") or {},
        "progress": snapshot.get("progress") or {},
        "signals": snapshot.get("signals") or {},
        "scorecard": snapshot.get("scorecard") or {},
        "first_review": snapshot.get("first_review") or {},
        "follow_through": snapshot.get("follow_through") or {},
        "recommendation_history": snapshot.get("recommendation_history") or {},
        "worker_strategy": snapshot.get("worker_strategy") or {},
        "review": snapshot.get("review") or {},
        "baseline_verification": snapshot.get("baseline_verification") or {},
        "progress_recent": snapshot.get("progress_recent"),
        "empty_states": snapshot.get("empty_states") or {},
        "logs": snapshot.get("logs") or [],
        "controls": controls,
        "automation": automation,
        "run_log": latest_run_log(target, dashboard_app),
        "worker_controls": worker_controls_snapshot(target, dashboard_app, strategy),
        "latest_worker_result": latest_worker_result,
        "environment_blockers": environment_blockers,
        "snapshot_generated_at": snapshot.get("generated_at"),
    }

def command_run_load_log(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    return {
        "target": target_metadata(target),
        "run_log": latest_run_log(target, dashboard_app, max_lines=500),
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
    command = ["bash", str(target_script_path(target, "scripts/run_codex_automation.sh"))]
    env = {**os.environ, **dashboard_app.automation_environment(target)}
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
    existing = running_runner_state(target)
    if existing.get("state") == "running" and process_is_alive(existing.get("pid")):
        stream_event(args, "automation", f"Continuous automation is already running (pid {existing.get('pid')}).")
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
    log_dir = automation_log_dir(target)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "conveyor.runner.stdout.log"
    stderr_path = log_dir / "conveyor.runner.stderr.log"
    command = ["bash", str(target_script_path(target, "scripts/run_conveyor_automation.sh"))]
    env = {**os.environ, **dashboard_app.automation_environment(target, allow_remotes=allow_remotes)}
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stream_event(args, "automation", "$ " + shlex.join(command), data={"cwd": str(target)})
    try:
        stdout_handle = stdout_path.open("ab")
        stderr_handle = stderr_path.open("ab")
        process = subprocess.Popen(
            command,
            cwd=str(target),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise BackendError(
            "Could not start continuous automation.",
            error_type="automation_start_failed",
            details={"command": command, "exception": str(exc)},
        ) from exc
    finally:
        try:
            stdout_handle.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        try:
            stderr_handle.close()  # type: ignore[possibly-undefined]
        except Exception:
            pass
    runner = {
        "state": "running",
        "message": "Continuous automation is running.",
        "pid": process.pid,
        "started_at": started_at,
        "command": command,
        "command_display": shlex.join(command),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "target": str(target),
    }
    write_runner_state(target, runner)
    write_dashboard_action_state(target, last_action="automation_started")
    stream_event(args, "automation", f"Started continuous automation (pid {process.pid}).")
    return {
        "target": target_metadata(target),
        "automation": automation_status_snapshot(target, dashboard_app),
        "runner": runner,
        "started": True,
    }

def command_automation_stop(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    runner = load_runner_state(target)
    pid = runner.get("pid")
    if not process_is_alive(pid):
        stale = mark_stale_runner(target, runner)
        stream_event(args, "automation", "Continuous automation is not currently running.", level="warning")
        write_dashboard_action_state(target, last_action="automation_stop_noop")
        return {
            "target": target_metadata(target),
            "automation": automation_status_snapshot(target, dashboard_app),
            "runner": stale,
            "stopped": False,
            "forced": False,
        }

    pid_int = int(pid)
    stopped = False
    forced = False
    stream_event(args, "automation", f"Stopping continuous automation (pid {pid_int}).")
    try:
        os.killpg(pid_int, signal.SIGTERM)
    except ProcessLookupError:
        stopped = True
    except OSError:
        try:
            os.kill(pid_int, signal.SIGTERM)
        except ProcessLookupError:
            stopped = True
    deadline = time.monotonic() + RUNNER_STOP_GRACE_SECONDS
    while not stopped and time.monotonic() < deadline:
        if not process_is_alive(pid_int):
            stopped = True
            break
        time.sleep(0.2)
    if not stopped and process_is_alive(pid_int):
        forced = True
        try:
            os.killpg(pid_int, signal.SIGKILL)
        except ProcessLookupError:
            stopped = True
        except OSError:
            try:
                os.kill(pid_int, signal.SIGKILL)
            except ProcessLookupError:
                stopped = True
        deadline = time.monotonic() + 3
        while not stopped and time.monotonic() < deadline:
            if not process_is_alive(pid_int):
                stopped = True
                break
            time.sleep(0.1)

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    runner = dict(runner)
    runner["state"] = "stopped" if stopped else "stop_failed"
    runner["message"] = "Continuous automation stopped." if stopped else "Continuous automation did not stop cleanly."
    runner["stopped_at"] = finished_at
    runner["forced_stop"] = forced
    write_runner_state(target, runner)
    write_dashboard_action_state(target, last_action="automation_stopped" if stopped else "automation_stop_failed")
    return {
        "target": target_metadata(target),
        "automation": automation_status_snapshot(target, dashboard_app),
        "runner": runner,
        "stopped": stopped,
        "forced": forced,
    }
