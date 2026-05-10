from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

def context_record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "rel_path": str(record.rel_path),
        "original_name": str(record.original_name),
        "size_bytes": int(record.size_bytes),
    }

def resolve_context_sources(raw_files: str) -> list[Path]:
    files = parse_json_arg(raw_files, label="files-json")
    if not isinstance(files, list):
        raise BackendError(
            "files-json must decode to a list of file paths.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "files-json"},
        )
    resolved: list[Path] = []
    for raw in files:
        path = Path(str(raw)).expanduser()
        try:
            source = path.resolve()
        except OSError as exc:
            raise BackendError(
                "Could not resolve context file path.",
                exit_code=2,
                error_type="invalid_context_file",
                details={"path": str(raw), "exception": str(exc)},
            ) from exc
        if not source.exists():
            raise BackendError(
                "Context file does not exist.",
                exit_code=2,
                error_type="invalid_context_file",
                details={"path": str(source)},
            )
        if not source.is_file():
            raise BackendError(
                "Context path must be a file.",
                exit_code=2,
                error_type="invalid_context_file",
                details={"path": str(source)},
            )
        resolved.append(source)
    return resolved

def merge_context_files(existing: Any, additions: list[str]) -> list[str]:
    merged: list[str] = []
    for value in [*normalize_string_list(existing), *additions]:
        if value not in merged:
            merged.append(value)
    return merged

def update_context_index(target: Path, project_name: str, records: list[Any], *, force: bool = False) -> Path | None:
    if not records:
        return None
    dashboard_app = load_dashboard_module()
    context_path = preferred_target_path(target, "docs/PROJECT_CONTEXT.md")
    context_index_existed = context_path.exists()
    if force or not context_index_existed:
        context_text = dashboard_app.render_project_context(project_name, records)
    else:
        existing_context = context_path.read_text(encoding="utf-8", errors="replace") if context_path.exists() else ""
        context_text = dashboard_app.upsert_context_imports(existing_context, project_name, records)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(context_text, encoding="utf-8")
    return context_path

def command_context_import(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    context_sources = resolve_context_sources(args.files_json)
    dashboard_app = load_dashboard_module()
    logs: list[str] = []
    records = dashboard_app.copy_context_files(target, context_sources, logs.append)
    record_paths = [str(record.rel_path) for record in records]

    dashboard_state = load_dashboard_state(target)
    draft_intake = dashboard_state.get("brief_draft_intake")
    if not isinstance(draft_intake, dict):
        draft_intake = load_intake(target)
    project_name = str(args.project_name or draft_intake.get("project_name") or target.name or "New Project")
    if not draft_intake:
        draft_intake = {"project_name": project_name, "additional_context_files": []}
    context_path = update_context_index(target, project_name, records)

    intake_path = preferred_target_path(target, ".agentic/project_intake.json")
    if intake_path.exists():
        intake = load_intake(target)
        intake["additional_context_files"] = merge_context_files(intake.get("additional_context_files"), record_paths)
        write_json_file(intake_path, intake)

    draft_intake["additional_context_files"] = merge_context_files(draft_intake.get("additional_context_files"), record_paths)
    write_dashboard_state_from_intake(target, draft_intake, last_action="context_files_imported")

    return {
        "target": target_metadata(target),
        "records": [context_record_to_dict(record) for record in records],
        "imported_count": len(records),
        "project_context_path": str(context_path) if context_path else None,
        "dashboard_state_path": str(preferred_target_path(target, ".agentic/dashboard_state.json")),
        "log": logs,
    }
