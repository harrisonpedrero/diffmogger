from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from .run_schedule import (
    automation_status_snapshot,
    native_prerequisites,
    prereq_rows,
    run_subprocess_streamed,
    runtime_environment_snapshot,
    setup_fix_suggestions,
    tool_status,
)

def required_file_flags(target: Path) -> list[str]:
    intake = load_intake(target)
    flags: list[str] = []
    bridge_mode = human_bridge_mode_from_state(target)
    flags.extend(["--human-bridge-mode", bridge_mode])
    if bool(intake.get("write_worker_agents_allowed", False)):
        flags.append("--write-workers-enabled")
    role_profile = str(intake.get("automation_role_profile") or "").strip()
    if role_profile != "single_lane" and bool(intake.get("multi_role_automations_allowed", False)):
        flags.append("--multi-role-enabled")
    if str(intake.get("automation_run_mode") or "") == "ticket_campaign":
        flags.append("--ticket-campaign-enabled")
    if intake.get("optional_mcp_servers"):
        flags.append("--optional-mcp-enabled")
    return flags

def run_subprocess(command: list[str], *, cwd: Path = KIT_ROOT) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return {
        "command": " ".join(command),
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }

def command_safety_run_check(args: argparse.Namespace) -> dict[str, Any]:
    selected_target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    check_target = dashboard_app.resolve_integration_safety_target(selected_target)
    if check_target == KIT_ROOT and not dashboard_app.has_integration_safety_tree(selected_target):
        stream_event(
            args,
            "safety",
            "Selected target does not include starter-kit integration files; checking the Diffmogger kit source instead.",
            level="warning",
        )
    command = dashboard_app.integration_safety_command(check_target)
    result = run_subprocess_streamed(args, command, cwd=KIT_ROOT, stage="safety")
    try:
        record_path = dashboard_app.write_integration_safety_record(
            selected_target,
            check_target,
            command,
            int(result["exit_code"]),
        )
    except OSError as exc:
        raise BackendError(
            "Could not record integration safety result.",
            error_type="safety_record_failed",
            details={"target": str(selected_target), "exception": str(exc)},
        ) from exc
    write_dashboard_action_state(
        selected_target,
        last_action="safety_check_completed" if result["exit_code"] == 0 else "safety_check_failed",
        updates={"last_safety_check_exit_code": result["exit_code"]},
    )
    return {
        "target": target_metadata(selected_target),
        "checked_target": str(check_target),
        "record_path": str(record_path),
        "status": "pass" if result["exit_code"] == 0 else "fail",
        "result": result,
    }

def command_diagnostics_run_checks(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    bridge_mode = human_bridge_mode_from_state(target)
    prerequisites = native_prerequisites(target, dashboard_app)
    prerequisite_rows = [
        {
            "name": item.name,
            "ok": item.ok,
            "required": item.required,
            "category": "required" if item.required else "optional",
            "detail": item.detail,
        }
        for item in prerequisites
    ]
    required_failures = [item for item in prerequisite_rows if item["required"] and not item["ok"]]

    has_generated_state = (
        existing_or_target_path(target, ".agentic/automation_prompt.md").exists()
        or existing_or_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md").exists()
    )
    if has_generated_state:
        required_files = run_subprocess(
            [
                sys.executable,
                str(CHECK_REQUIRED_SCRIPT),
                *required_file_flags(target),
                str(target),
            ]
        )
        required_files["status"] = "pass" if required_files["exit_code"] == 0 else "fail"
    else:
        required_files = {
            "status": "not_run",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "command": "",
            "reason": "Target does not contain generated Diffmogger automation state yet.",
        }

    safety_target = dashboard_app.resolve_integration_safety_target(target)
    safety = run_subprocess([sys.executable, str(CHECK_INTEGRATION_SAFETY_SCRIPT), str(safety_target)])
    safety["status"] = "pass" if safety["exit_code"] == 0 else "fail"
    safety["checked_target"] = str(safety_target)
    automation = automation_status_snapshot(target, dashboard_app)

    target_writable = os.access(target, os.W_OK)
    state_dir = preferred_target_path(target, "docs/CODEX_AUTOMATION_TASKS.md").parent
    docs_writable = os.access(state_dir, os.W_OK) if state_dir.exists() else os.access(target, os.W_OK)
    runtime_environment = runtime_environment_snapshot(dashboard_app)
    fix_suggestions = setup_fix_suggestions(runtime_environment)
    backend_schema = {
        "schema_version": SCHEMA_VERSION,
        "commands": {
            "project": 1,
            "brief": 1,
            "run": 1,
            "inbox": 1,
            "review": 1,
            "advanced": 1,
        },
    }

    return {
        "target": target_metadata(target),
        "prerequisites": {
            "status": "pass" if not required_failures else "fail",
            "items": prerequisite_rows,
            "required_failures": required_failures,
        },
        "required_files": required_files,
        "integration_safety": safety,
        "tools": [
            tool_status("codex", ["--version"], required=True, path=runtime_environment.get("effective_path")),
            tool_status("python3", ["--version"], required=True, path=runtime_environment.get("effective_path")),
            tool_status("bash", ["--version"], required=True, path=runtime_environment.get("effective_path")),
            tool_status("git", ["--version"], required=True, path=runtime_environment.get("effective_path")),
        ],
        "target_writability": {
            "target": target_writable,
            "docs": docs_writable,
            "status": "pass" if target_writable and docs_writable else "fail",
        },
        "macos_permissions": {
            "status": "info",
            "detail": "On macOS, grant file access for target folders if folder picking or automation logs fail.",
        },
        "notifier_health": {
            "configured": bridge_mode in {"local_notifier", "discord_notifier"},
            "bridge_mode": bridge_mode,
            "status": "not_configured" if bridge_mode == "file_only" else "unknown",
            "detail": "File-only mode does not require notifier credentials."
            if bridge_mode == "file_only"
            else "Use the notifier service health check before relying on external delivery.",
        },
        "automation": automation,
        "runtime_environment": runtime_environment,
        "fix_suggestions": fix_suggestions,
        "backend": backend_schema,
    }

def command_diagnostics_environment(args: argparse.Namespace) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    runtime_environment = runtime_environment_snapshot(dashboard_app)
    tools = runtime_environment.get("tools") if isinstance(runtime_environment.get("tools"), list) else []
    required_failures = [
        item for item in tools
        if isinstance(item, dict) and item.get("required") and not item.get("ok")
    ]
    return {
        "status": "pass" if not required_failures else "fail",
        "runtime_environment": runtime_environment,
        "fix_suggestions": setup_fix_suggestions(runtime_environment),
        "required_failures": required_failures,
        "setup_mode": "guide_and_copy",
    }
