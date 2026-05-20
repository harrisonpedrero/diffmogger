"""JSON backend command layer for the Diffmogger native dashboard."""

from __future__ import annotations

import argparse
import os
from typing import Any, Callable

from .errors import BackendArgumentParser, BackendError
from .jsonio import emit, emit_jsonl, failure, success
from .target import load_repo_dotenv_for_backend
from .commands.brief import (
    command_brief_generate_intake,
    command_brief_load,
    command_brief_save_draft,
    command_brief_scaffold,
    command_brief_scaffold_preview,
)
from .commands.context import command_context_import
from .commands.diagnostics import command_diagnostics_environment, command_diagnostics_run_checks, command_safety_run_check
from .commands.project import command_project_list_recent, command_project_load_snapshot
from .commands.run_control import (
    command_automation_start,
    command_automation_stop,
    command_blocker_recheck_baseline,
    command_run_once,
)
from .commands.state import command_state_brief, command_state_snapshot, command_state_validate, command_state_watch
from .commands.tickets import (
    command_ticket_accept_draft,
    command_ticket_accept_split,
    command_ticket_add,
    command_ticket_delete,
    command_ticket_draft_from_intake,
    command_ticket_import,
    command_ticket_load,
    command_ticket_split_preview,
    command_ticket_update,
)
from .commands.workers import (
    command_execution_group_cancel,
    command_execution_group_export_debug_bundle,
    command_execution_group_load,
    command_execution_group_retry_failed,
    command_execution_group_start,
    command_lease_release_stale,
    command_validation_jobs_load,
    command_worker_launch_read_only_group,
    command_worker_launch_write_group,
    command_worker_run_integrator,
    command_worker_run_read_only,
    command_worker_run_write,
)

def add_target_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="Target project directory")

def build_parser() -> argparse.ArgumentParser:
    parser = BackendArgumentParser(description=__doc__)
    parser.add_argument("--stream-jsonl", action="store_true", help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
        "project.load_snapshot": command_project_load_snapshot,
        "project.list_recent": command_project_list_recent,
        "brief.load": command_brief_load,
        "brief.generate_intake": command_brief_generate_intake,
        "brief.save_draft": command_brief_save_draft,
        "brief.scaffold_preview": command_brief_scaffold_preview,
        "brief.scaffold": command_brief_scaffold,
        "context.import": command_context_import,
        "run.once": command_run_once,
        "automation.start": command_automation_start,
        "automation.stop": command_automation_stop,
        "blocker.recheck_baseline": command_blocker_recheck_baseline,
        "ticket.load": command_ticket_load,
        "ticket.add": command_ticket_add,
        "ticket.update": command_ticket_update,
        "ticket.delete": command_ticket_delete,
        "ticket.import": command_ticket_import,
        "ticket.draft_from_intake": command_ticket_draft_from_intake,
        "ticket.accept_draft": command_ticket_accept_draft,
        "ticket.split_preview": command_ticket_split_preview,
        "ticket.accept_split": command_ticket_accept_split,
        "safety.run_check": command_safety_run_check,
        "worker.run_read_only": command_worker_run_read_only,
        "worker.launch_read_only_group": command_worker_launch_read_only_group,
        "worker.launch_write_group": command_worker_launch_write_group,
        "worker.run_write": command_worker_run_write,
        "worker.run_integrator": command_worker_run_integrator,
        "execution_group.load": command_execution_group_load,
        "execution_group.start": command_execution_group_start,
        "execution_group.cancel": command_execution_group_cancel,
        "execution_group.retry_failed": command_execution_group_retry_failed,
        "execution_group.export_debug_bundle": command_execution_group_export_debug_bundle,
        "validation_jobs.load": command_validation_jobs_load,
        "lease.release_stale": command_lease_release_stale,
        "state.snapshot": command_state_snapshot,
        "state.brief": command_state_brief,
        "state.validate": command_state_validate,
        "state.watch": command_state_watch,
        "diagnostics.environment": command_diagnostics_environment,
        "diagnostics.run_checks": command_diagnostics_run_checks,
    }
    for name, handler in commands.items():
        subparser = subparsers.add_parser(name)
        subparser.set_defaults(handler=handler)
        if name not in {"project.list_recent", "diagnostics.environment"}:
            add_target_arg(subparser)
        if name == "state.watch":
            subparser.add_argument("--after-event-id", type=int, default=0, help="Only emit runtime events after this event id")
            subparser.add_argument("--poll-interval", type=float, default=0.75, help=argparse.SUPPRESS)
            subparser.add_argument("--heartbeat-seconds", type=float, default=5.0, help=argparse.SUPPRESS)
            subparser.add_argument("--max-events", type=int, default=0, help=argparse.SUPPRESS)
            subparser.add_argument("--max-heartbeats", type=int, default=0, help=argparse.SUPPRESS)
        if name in {"brief.save_draft", "brief.scaffold_preview", "brief.scaffold"}:
            subparser.add_argument("--intake-json", required=True, help="JSON object with intake fields")
        if name == "brief.generate_intake":
            subparser.add_argument("--body", required=True, help="Short description of what the user wants to build")
        if name == "context.import":
            subparser.add_argument("--files-json", required=True, help="JSON list of context file paths")
            subparser.add_argument("--project-name", default="", help="Project name for the context index")
        if name == "worker.run_write":
            subparser.add_argument("--ownership", required=True, help="Disjoint file or module ownership scope")
        if name == "worker.launch_read_only_group":
            subparser.add_argument("--execution-group-id", default="", help="Optional proposed read-only execution group id")
            subparser.add_argument("--max-workers", type=int, default=2, help="Maximum read-only workers to launch")
        if name == "worker.launch_write_group":
            subparser.add_argument("--execution-group-id", default="", help="Optional proposed write-worker execution group id")
            subparser.add_argument("--max-workers", type=int, default=0, help="Maximum write workers to launch; default uses intake cap")
        if name in {"execution_group.load", "execution_group.start", "execution_group.cancel", "execution_group.retry_failed"}:
            subparser.add_argument("--execution-group-id", default="", help="Execution group id")
        if name == "execution_group.start":
            subparser.add_argument("--mode", default="auto", choices=["auto", "read_only", "write_workers", "validation"], help="Execution group mode to start")
            subparser.add_argument("--max-workers", type=int, default=0, help="Maximum workers to launch when starting worker groups")
        if name == "lease.release_stale":
            subparser.add_argument("--lease-id", required=True, help="Active lease id to release")
        if name in {"brief.scaffold_preview", "brief.scaffold"}:
            subparser.add_argument("--force", action="store_true", help="Overwrite existing scaffold-managed files")
        if name in {"ticket.add", "ticket.update"}:
            subparser.add_argument("--ticket-json", required=True, help="JSON object with ticket fields")
        if name in {"ticket.update", "ticket.delete"}:
            subparser.add_argument("--ticket-id", required=True, help="Ticket id to update or delete")
        if name == "ticket.import":
            subparser.add_argument("--format", dest="import_format", required=True, choices=["markdown", "csv", "json"], help="Import source format")
            subparser.add_argument("--mode", dest="import_mode", choices=["append", "replace-placeholder", "replace-all"], default="", help="Import write mode")
            subparser.add_argument("--input-file", default="", help="Path to import file")
            subparser.add_argument("--input-json", default="", help="JSON import payload")
            subparser.add_argument("--input-text", default="", help="Markdown or CSV import payload")
            subparser.add_argument("--preview", action="store_true", help="Preview import without writing")
        if name in {"ticket.draft_from_intake", "ticket.accept_draft", "ticket.split_preview", "ticket.accept_split"}:
            subparser.add_argument("--ticket-file", default="", help=argparse.SUPPRESS)
        if name == "ticket.draft_from_intake":
            subparser.add_argument("--direction", default="", help="Optional guidance for Codex ticket drafting")
        if name == "ticket.split_preview":
            subparser.add_argument("--ticket-id", required=True, help="Pending ticket id to split")
        if name == "ticket.accept_draft":
            subparser.add_argument("--draft-id", required=True, help="Stored draft id")
            subparser.add_argument("--ticket-ids", default="", help="Comma-separated candidate ticket ids to accept")
            subparser.add_argument("--mode", dest="import_mode", choices=["append", "replace-placeholder", "replace-all"], default="", help="Import write mode")
        if name == "ticket.accept_split":
            subparser.add_argument("--draft-id", required=True, help="Stored split preview draft id")
    return parser

def main(argv: list[str] | None = None) -> int:
    loaded = load_repo_dotenv_for_backend()
    if loaded:
        os.environ["DIFFMOGGER_BACKEND_DOTENV_LOADED"] = "1"
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        command = str(args.command)
        data = args.handler(args)
        payload = success(command, data)
        if bool(getattr(args, "stream_jsonl", False)):
            emit_jsonl(payload)
        else:
            emit(payload)
        return 0
    except BackendError as exc:
        command = "unknown"
        if "args" in locals() and getattr(args, "command", None):
            command = str(args.command)
        payload = failure(command, exc)
        if "args" in locals() and bool(getattr(args, "stream_jsonl", False)):
            emit_jsonl(payload)
        else:
            emit(payload)
        return exc.exit_code
    except BrokenPipeError:  # pragma: no cover - shell pipeline behavior.
        return 1
    except Exception as exc:  # pragma: no cover - defensive structured fallback.
        command = "unknown"
        if "args" in locals() and getattr(args, "command", None):
            command = str(args.command)
        error = BackendError(
            "Unhandled backend CLI error.",
            error_type=exc.__class__.__name__,
            details={"exception": str(exc)},
        )
        payload = failure(command, error)
        if "args" in locals() and bool(getattr(args, "stream_jsonl", False)):
            emit_jsonl(payload)
        else:
            emit(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
