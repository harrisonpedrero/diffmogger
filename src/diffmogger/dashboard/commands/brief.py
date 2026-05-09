from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from .context import merge_context_files
from .diagnostics import run_subprocess

def command_brief_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = load_intake(target)
    dashboard_state = load_dashboard_state(target)
    draft_intake = dashboard_state.get("brief_draft_intake")
    if not isinstance(draft_intake, dict):
        draft_intake = intake
    project_name = (
        draft_intake.get("project_name")
        or intake.get("project_name")
        or dashboard_state.get("project_name")
        or target.name
        or str(target)
    )
    return {
        "target": target_metadata(target),
        "exists": bool(intake),
        "project_name": project_name,
        "project_mode": draft_intake.get("project_mode") or intake.get("project_mode") or dashboard_state.get("project_mode") or "unknown",
        "intake": intake,
        "draft_intake": draft_intake,
        "dashboard_state": dashboard_state,
        "context_files": list(intake.get("additional_context_files") or []),
        "detected": detect_target_context(target),
    }

def command_brief_save_draft(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    state_path = write_dashboard_state_from_intake(target, intake, last_action="brief_draft_saved")
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "intake": intake,
        "detected": detect_target_context(target),
    }

def run_required_file_check_for_intake(target: Path, intake: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        str(CHECK_REQUIRED_SCRIPT),
        "--human-bridge-mode",
        str(intake.get("human_bridge_mode") or "file_only"),
    ]
    if intake.get("write_worker_agents_allowed"):
        command.append("--write-workers-enabled")
    role_profile = str(intake.get("automation_role_profile") or "").strip()
    if role_profile != "single_lane" and bool(intake.get("multi_role_automations_allowed", True)):
        command.append("--multi-role-enabled")
    if str(intake.get("automation_run_mode") or "") == "ticket_campaign":
        command.append("--ticket-campaign-enabled")
    if intake.get("optional_mcp_servers"):
        command.append("--optional-mcp-enabled")
    command.append(str(target))
    result = run_subprocess(command)
    result["status"] = "pass" if result["exit_code"] == 0 else "fail"
    return result

def scaffold_template_included(scaffold_module: Any, rel_path: str, values: dict[str, str]) -> bool:
    if hasattr(scaffold_module, "template_included"):
        return bool(scaffold_module.template_included(rel_path, values))
    if values.get("HUMAN_BRIDGE_MODE") == "disabled" and rel_path in scaffold_module.HUMAN_BRIDGE_FILES:
        return False
    if values.get("AUTOMATION_RUN_MODE") != "ticket_campaign" and rel_path in scaffold_module.TICKET_RUN_FILES:
        return False
    if values.get("MCP_ENABLED") != "true" and rel_path in scaffold_module.MCP_FILES:
        return False
    if values.get("PLAYWRIGHT_MCP_ENABLED") != "true" and rel_path in scaffold_module.PLAYWRIGHT_MCP_FILES:
        return False
    return True

def scaffold_file_preview(target: Path, intake: dict[str, Any], *, force: bool) -> list[dict[str, Any]]:
    scaffold_module = load_dashboard_module().load_scaffold_module()
    scaffold_intake = project_intake_payload(intake)
    values = scaffold_module.placeholders(scaffold_intake)
    mode = values.get("PROJECT_MODE", "fresh_project")
    records: list[dict[str, Any]] = []
    for template_path in sorted(scaffold_module.TEMPLATE_ROOT.rglob("*")):
        if template_path.is_dir():
            continue
        if "__pycache__" in template_path.parts or template_path.suffix == ".pyc":
            continue
        rel = template_path.relative_to(scaffold_module.TEMPLATE_ROOT)
        rel_path = rel.as_posix()
        if not scaffold_template_included(scaffold_module, rel_path, values):
            continue

        dest_rel = (
            scaffold_module.template_destination_rel(rel_path)
            if hasattr(scaffold_module, "template_destination_rel")
            else rel_path
        )
        dest = target / dest_rel
        exists = dest.exists()
        managed_kind = scaffold_module.MANAGED_EXISTING_PROJECT_FILES.get(rel_path)
        managed = False
        action = "create"
        detail = "Will create this target-local generated file."

        if mode == "existing_project" and managed_kind and exists:
            action = "managed_section_update"
            managed = True
            detail = f"Will update only the Diffmogger-managed {managed_kind} section and preserve surrounding content."
        elif mode == "existing_project" and managed_kind:
            managed = True
            detail = f"Will create this file with a Diffmogger-managed {managed_kind} section."
        elif exists and force:
            action = "overwrite"
            detail = "Will overwrite this scaffold-managed file because force is enabled."
        elif exists:
            if not dest_rel.startswith(".diffmogger/"):
                action = "conflict_requires_user_choice"
                detail = "A project-facing path already exists; Diffmogger will not silently overwrite or skip it."
            else:
                action = "skip_existing"
                detail = "Will not overwrite the existing sidecar file with force disabled."

        records.append(
            {
                "rel_path": dest_rel,
                "template_rel_path": rel_path,
                "path": str(dest),
                "exists": exists,
                "action": action,
                "managed_section": managed,
                "detail": detail,
            }
        )

    manifest = target / ".diffmogger" / "manifest.json"
    records.append(
        {
            "rel_path": ".diffmogger/manifest.json",
            "path": str(manifest),
            "exists": manifest.exists(),
            "action": "create" if not manifest.exists() else ("overwrite" if force else "skip_existing"),
            "managed_section": True,
            "detail": "Will write the sidecar ownership manifest used by runners, validation, and local excludes.",
        }
    )

    if (target / ".git").exists():
        exclude = target / ".git" / "info" / "exclude"
        records.append(
            {
                "rel_path": ".git/info/exclude",
                "path": str(exclude),
                "exists": exclude.exists(),
                "action": "update_local_exclude",
                "managed_section": True,
                "detail": "Will merge Diffmogger runtime ignore entries into the local git exclude file.",
            }
        )
    return records

def preview_summary(files: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for record in files:
        action = str(record.get("action") or "unknown")
        summary[action] = summary.get(action, 0) + 1
    return summary

def prereq_snapshot(target: Path, intake: dict[str, Any]) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    bridge_mode = str(intake.get("human_bridge_mode") or "file_only")
    optional_mcp = dashboard_app.optional_mcp_servers_from_value(intake.get("optional_mcp_servers"))
    items = dashboard_app.check_prerequisites(target, bridge_mode, optional_mcp)
    rows = [
        {
            "name": item.name,
            "ok": item.ok,
            "required": item.required,
            "detail": item.detail,
        }
        for item in items
    ]
    required_failures = [item for item in rows if item["required"] and not item["ok"]]
    advisory_warnings = [item for item in rows if not item["required"] and not item["ok"]]
    return {
        "status": "pass" if not required_failures else "fail",
        "items": rows,
        "required_failures": required_failures,
        "advisory_warnings": advisory_warnings,
    }

def git_warnings_from_detected(detected: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if detected.get("is_git_repo") and int(detected.get("git_dirty_count") or 0) > 0:
        warnings.append(
            {
                "type": "dirty_git",
                "level": "warning",
                "message": f"Git has {detected.get('git_dirty_count')} changed file(s). Review the working tree before scaffolding into an existing repo.",
            }
        )
    return warnings

def build_scaffold_preview(target: Path, intake: dict[str, Any], *, force: bool) -> dict[str, Any]:
    files = scaffold_file_preview(target, intake, force=force)
    detected = detect_target_context(target)
    prerequisites = prereq_snapshot(target, intake)
    warnings = git_warnings_from_detected(detected)
    warnings.extend(
        {
            "type": "missing_prerequisite",
            "level": "warning",
            "message": f"{item['name']}: {item['detail']}",
        }
        for item in prerequisites["required_failures"]
    )
    warnings.extend(
        {
            "type": "advisory_prerequisite",
            "level": "info",
            "message": f"{item['name']}: {item['detail']}",
        }
        for item in prerequisites["advisory_warnings"]
    )
    return {
        "target": target_metadata(target),
        "project_mode": str(intake.get("project_mode") or "fresh_project"),
        "force": force,
        "files": files,
        "summary": preview_summary(files),
        "warnings": warnings,
        "prerequisites": prerequisites,
        "detected": detected,
    }

def command_brief_scaffold_preview(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    return build_scaffold_preview(target, intake, force=bool(args.force))

def native_next_state_from_target(target: Path) -> dict[str, Any]:
    try:
        snapshot = build_observatory_snapshot(target)
    except BackendError as exc:
        return {
            "state": "READY_TO_RUN",
            "reason": f"Scaffold completed, but Observatory snapshot could not be built yet: {exc.message}",
            "first_review_status": "unknown",
            "task_status": "unknown",
        }
    first_review = snapshot.get("first_review") if isinstance(snapshot.get("first_review"), dict) else {}
    task = snapshot.get("task") if isinstance(snapshot.get("task"), dict) else {}
    first_review_status = str(first_review.get("status") or "unknown")
    if first_review_status != "ready":
        return {
            "state": "FIRST_REVIEW_NEEDED",
            "reason": first_review.get("summary") or "Scaffold completed; complete first-review readiness before leaving automation unattended.",
            "first_review_status": first_review_status,
            "task_status": task.get("status") or "unknown",
        }
    return {
        "state": "READY_TO_RUN",
        "reason": first_review.get("summary") or "Scaffold completed and first-review readiness is recorded.",
        "first_review_status": first_review_status,
        "task_status": task.get("status") or "unknown",
    }

def command_brief_scaffold_bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    intake = parse_json_arg(args.intake_json, label="intake-json")
    if not isinstance(intake, dict):
        raise BackendError(
            "intake-json must decode to an object.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": "intake-json"},
        )
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to scaffold into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )

    log_lines: list[dict[str, Any]] = []

    def log(stage: str, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        record = {
            "stage": stage,
            "level": level,
            "message": message,
            "data": data or {},
        }
        log_lines.append(record)
        stream_event(args, stage, message, level=level, data=data)

    log("preflight", "Building scaffold preview and prerequisite summary.")
    preflight = build_scaffold_preview(target, intake, force=bool(args.force))
    required_failures = list((preflight.get("prerequisites") or {}).get("required_failures") or [])
    if required_failures and bool(args.run_codex):
        log(
            "preflight",
            "Required prerequisites are missing; Codex bootstrap cannot start.",
            level="error",
            data={"required_failures": required_failures},
        )
        raise BackendError(
            "Required prerequisites are missing before Codex bootstrap.",
            error_type="prerequisites_failed",
            details={"required_failures": required_failures, "preflight": preflight, "log": log_lines[-12:]},
        )
    if required_failures:
        log(
            "preflight",
            "Required prerequisites are missing for full bootstrap; scaffold will continue without running Codex.",
            level="warning",
            data={"required_failures": required_failures},
        )

    log("state", "Writing target-local dashboard state.")
    state_path = write_dashboard_state_from_intake(target, intake, last_action="scaffold_bootstrap_started")
    intake_path = preferred_target_path(target, ".agentic/project_intake.json")
    intake_path.parent.mkdir(parents=True, exist_ok=True)
    scaffold_intake = project_intake_payload(intake)
    write_json_file(intake_path, scaffold_intake)
    log("state", f"Wrote {intake_path.relative_to(target)}.")

    scaffold_module = load_dashboard_module().load_scaffold_module()
    try:
        log("scaffold", "Rendering scaffold templates.")
        values = scaffold_module.placeholders(scaffold_intake)
        written = scaffold_module.scaffold(target, values, bool(args.force))
        log("scaffold", f"Scaffold wrote or updated {len(written)} file(s).")
        for path in written[:24]:
            log("scaffold", f"wrote {path.relative_to(target)}", data={"rel_path": str(path.relative_to(target))})
        if len(written) > 24:
            log("scaffold", f"... {len(written) - 24} more file(s).")
    except Exception as exc:
        log("scaffold", f"Scaffold generation failed: {exc}", level="error")
        raise BackendError(
            "Scaffold generation failed.",
            error_type="scaffold_failed",
            details={"target": str(target), "exception": str(exc), "log": log_lines[-20:]},
        ) from exc

    log("validation", "Running generated required-file validation.")
    required_files = run_required_file_check_for_intake(target, scaffold_intake)
    if required_files.get("stdout"):
        log("validation", str(required_files.get("stdout"))[:800], data={"exit_code": required_files.get("exit_code")})
    if required_files.get("stderr"):
        log("validation", str(required_files.get("stderr"))[:800], level="warning", data={"exit_code": required_files.get("exit_code")})
    if required_files["exit_code"] != 0:
        log("validation", "Required-file validation failed after scaffolding.", level="error")
        raise BackendError(
            "Required-file validation failed after scaffolding.",
            error_type="required_files_failed",
            details={**required_files, "log": log_lines[-20:]},
        )

    codex_result: dict[str, Any] = {
        "status": "skipped",
        "reason": "Codex bootstrap was not requested by this backend command.",
    }
    if bool(args.run_codex):
        log("bootstrap", "Starting Codex initial bootstrap run.")
        prompt_path = preferred_target_path(target, "docs/INITIAL_BOOTSTRAP_PROMPT.md")
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "Could not read the initial bootstrap prompt.",
                error_type="bootstrap_prompt_missing",
                details={"path": str(prompt_path), "exception": str(exc)},
            ) from exc
        codex_result = run_subprocess(
            ["codex", "exec", "--full-auto", "--skip-git-repo-check", prompt],
            cwd=target,
        )
        codex_result["status"] = "pass" if codex_result["exit_code"] == 0 else "fail"
        if codex_result.get("stdout"):
            log("bootstrap", str(codex_result.get("stdout"))[-1200:])
        if codex_result.get("stderr"):
            log("bootstrap", str(codex_result.get("stderr"))[-1200:], level="warning")
        if codex_result["exit_code"] != 0:
            log("bootstrap", "Codex bootstrap failed.", level="error", data={"exit_code": codex_result.get("exit_code")})
            raise BackendError(
                "Codex bootstrap failed.",
                error_type="codex_bootstrap_failed",
                details={**codex_result, "log": log_lines[-24:]},
            )
    else:
        log("bootstrap", "Skipped Codex initial bootstrap; Run controls can start automation after scaffold validation.")

    write_dashboard_state_from_intake(target, intake, last_action="bootstrap_completed")
    next_state = native_next_state_from_target(target)
    log("done", f"Scaffold pipeline completed: {next_state['state']}.", data=next_state)
    return {
        "target": target_metadata(target),
        "dashboard_state_path": str(state_path),
        "project_intake_path": str(intake_path),
        "written_files": [str(path.relative_to(target)) for path in written],
        "written_count": len(written),
        "required_files": required_files,
        "codex": codex_result,
        "preflight": preflight,
        "native_next_state": next_state,
        "log": log_lines,
        "log_excerpt": log_lines[-20:],
    }
