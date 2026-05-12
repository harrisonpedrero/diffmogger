from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from .brief import command_brief_load
from .run_control import command_run_load

def command_project_load_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    brief = command_brief_load(args)
    run = command_run_load(args)
    dashboard_app = load_dashboard_module()
    files = [
        describe_registered_file(target, record)
        for record in file_registry(dashboard_app).values()
    ]
    return {
        "target": target_metadata(target),
        "brief": brief,
        "run": run,
        "files": files,
        "home": {
            "title": str(brief.get("project_name") or target.name),
            "automation_status": (run.get("task") or {}).get("status") or "UNKNOWN",
            "current_horizon": (run.get("task") or {}).get("horizon") or "unknown",
            "next_action": ((run.get("scorecard") or {}).get("action_plan") or {}).get("recommendation")
            or (run.get("task") or {}).get("suggested_next_task")
            or "No next action recorded yet.",
            "pending_human_requests": int((run.get("human") or {}).get("pending_requests", 0) or 0),
            "unhandled_inbox": int((run.get("human") or {}).get("unhandled_inbox", 0) or 0),
            "queued_patches": int(((run.get("queue") or {}).get("totals") or {}).get("queued", 0) or 0),
            "deferred_patches": int(((run.get("queue") or {}).get("totals") or {}).get("deferred", 0) or 0),
        },
    }

def configured_recent_projects() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    env_value = os.environ.get("DIFFMOGGER_RECENT_PROJECTS", "")
    for raw in [item for item in env_value.split(os.pathsep) if item.strip()]:
        target = str(Path(raw).expanduser())
        if target in seen:
            continue
        seen.add(target)
        records.append({"target": target, "source": "environment", "label": Path(target).name})
    return records

def command_project_list_recent(_args: argparse.Namespace) -> dict[str, Any]:
    return {"projects": configured_recent_projects()}
