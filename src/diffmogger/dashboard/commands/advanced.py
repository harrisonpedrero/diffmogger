from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from diffmogger.runtime import ticket_run
from diffmogger.runtime.state_store import validate_state_database

from .diagnostics import command_diagnostics_run_checks, required_file_flags, run_subprocess
from .run_control import latest_run_log

def command_advanced_list_files(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    dashboard_app = load_dashboard_module()
    files = [
        describe_registered_file(target, record)
        for record in file_registry(dashboard_app).values()
    ]
    categories: dict[str, int] = {}
    for file in files:
        categories[str(file.get("category") or "Core state")] = categories.get(str(file.get("category") or "Core state"), 0) + 1
    return {"target": target_metadata(target), "files": files, "categories": categories}

def registered_file_description(target: Path, file_key: str) -> dict[str, Any]:
    dashboard_app = load_dashboard_module()
    registry = file_registry(dashboard_app)
    record = registry.get(file_key)
    if not record:
        raise BackendError(
            "Unknown file key.",
            exit_code=2,
            error_type="invalid_file_key",
            details={"file_key": file_key, "valid_keys": sorted(registry)},
        )
    return describe_registered_file(target, record)

def command_advanced_load_file(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    description = registered_file_description(target, args.file_key)
    if not description["exists"]:
        return {"target": target_metadata(target), "file": description, "content": "", "truncated": False}
    text, truncated = read_text_file(Path(description["path"]))
    return {"target": target_metadata(target), "file": description, "content": text, "truncated": truncated}

def command_advanced_save_file(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    if target == KIT_ROOT:
        raise BackendError(
            "Refusing to save managed files into the Diffmogger source checkout.",
            exit_code=2,
            error_type="invalid_target",
            details={"target": str(target)},
        )
    description = registered_file_description(target, args.file_key)
    if not bool(description.get("editable", True)):
        raise BackendError(
            "This managed file is read-only from Advanced.",
            exit_code=2,
            error_type="file_read_only",
            details={"file_key": args.file_key},
        )
    content = str(args.content or "")
    if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
        raise BackendError(
            "File content is too large for dashboard editing.",
            exit_code=2,
            error_type="content_too_large",
            details={"max_bytes": MAX_TEXT_BYTES},
        )
    path = Path(description["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    updated = registered_file_description(target, args.file_key)
    return {"target": target_metadata(target), "file": updated, "saved": True}

def command_advanced_validate_file(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    description = registered_file_description(target, args.file_key)
    validation = str(description.get("validation") or "")
    path = Path(description["path"])
    if not description["exists"]:
        return {"target": target_metadata(target), "file": description, "status": "missing", "items": [{"ok": False, "detail": "File does not exist yet."}]}
    if validation == "json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"target": target_metadata(target), "file": description, "status": "fail", "items": [{"ok": False, "detail": str(exc)}]}
        return {"target": target_metadata(target), "file": description, "status": "pass", "items": [{"ok": True, "detail": "JSON parses successfully."}]}
    if validation == "conveyor_projection":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"target": target_metadata(target), "file": description, "status": "fail", "items": [{"ok": False, "detail": str(exc)}]}
        result = validate_state_database(target)
        return {
            "target": target_metadata(target),
            "file": description,
            "status": result["status"],
            "items": result["items"],
            "result": result["snapshot"],
        }
    if validation == "required_files":
        flags = required_file_flags(target)
        result = run_subprocess([sys.executable, str(CHECK_REQUIRED_SCRIPT), *flags, str(target)])
        return {
            "target": target_metadata(target),
            "file": description,
            "status": "pass" if result["exit_code"] == 0 else "fail",
            "items": [{"ok": result["exit_code"] == 0, "detail": result["stdout"] or result["stderr"] or "Required-file check completed."}],
            "result": result,
        }
    if validation == "ticket_run":
        try:
            data, _ticket_path, _text = ticket_run.load_ticket_run(target, path)
        except SystemExit as exc:
            return {"target": target_metadata(target), "file": description, "status": "fail", "items": [{"ok": False, "detail": str(exc)}]}
        issues = ticket_run.ticket_validation_issues(data)
        return {
            "target": target_metadata(target),
            "file": description,
            "status": "fail" if any(issue.get("level") == "error" for issue in issues) else "pass",
            "items": [{"ok": issue.get("level") != "error", "detail": str(issue.get("detail") or issue)} for issue in issues] or [{"ok": True, "detail": "Ticket-run JSON parses and validates."}],
            "result": ticket_run.ticket_run_payload(data, target),
        }
    return {"target": target_metadata(target), "file": description, "status": "not_available", "items": [{"ok": True, "detail": "No validator is registered for this managed file."}]}

SECRET_KEY_RE = re.compile(r"(secret|token|password|api[_-]?key|credential|private[_-]?key|discord|webhook)", re.I)

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API[_-]?KEY|CREDENTIAL|PRIVATE[_-]?KEY|WEBHOOK)[A-Z0-9_]*)\b\s*[:=]\s*([^\s]+)"
)

SECRET_VALUE_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|xox[baprs]-[A-Za-z0-9-]{16,})\b")

def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str) and SECRET_KEY_RE.search(value):
        return "[REDACTED]"
    return value

def redact_secret_text(text: str) -> str:
    redacted_lines: list[str] = []
    for line in text.splitlines():
        sanitized = SECRET_VALUE_RE.sub("[REDACTED]", line)
        if SECRET_ASSIGNMENT_RE.search(sanitized):
            redacted_lines.append(SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", sanitized))
        elif SECRET_KEY_RE.search(line):
            redacted_lines.append("[REDACTED LINE]")
        else:
            redacted_lines.append(sanitized)
    return "\n".join(redacted_lines)

def resolve_output_dir(raw: str) -> Path:
    if not raw or not str(raw).strip():
        raise BackendError("An output directory is required.", exit_code=2, error_type="invalid_output_dir")
    path = Path(raw).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise BackendError(
            "Output path exists but is not a directory.",
            exit_code=2,
            error_type="invalid_output_dir",
            details={"output_dir": str(path)},
        )
    path.mkdir(parents=True, exist_ok=True)
    return path

def command_advanced_export_debug_bundle(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    output_dir = resolve_output_dir(args.output_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    bundle_path = output_dir / f"Diffmogger-debug-{target.name or 'target'}-{timestamp}.zip"
    diagnostics = command_diagnostics_run_checks(args)
    files = command_advanced_list_files(args)
    latest_log = latest_run_log(target, load_dashboard_module())
    debug_summary = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target_metadata(target),
        "diagnostics": diagnostics,
        "files": files,
        "latest_log": latest_log,
        "omitted": [
            ".env and .env.* files",
            "secret-like keys and values",
            "arbitrary project source files outside the managed file allowlist",
        ],
    }
    dashboard_state = load_dashboard_state(target)
    backend_command_log = {
        "last_action": dashboard_state.get("last_action", ""),
        "updated_at": dashboard_state.get("updated_at", ""),
        "last_run_once_started_at": dashboard_state.get("last_run_once_started_at", ""),
        "last_run_once_finished_at": dashboard_state.get("last_run_once_finished_at", ""),
        "last_run_once_exit_code": dashboard_state.get("last_run_once_exit_code", ""),
        "last_safety_check_exit_code": dashboard_state.get("last_safety_check_exit_code", ""),
        "last_worker_run_id": dashboard_state.get("last_worker_run_id", ""),
        "last_reviewed_at": dashboard_state.get("last_reviewed_at", ""),
    }
    safe_records = [
        ("debug-summary.json", json.dumps(redact_secrets(debug_summary), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("dashboard-state.json", json.dumps(redact_secrets(dashboard_state), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("project-intake.json", json.dumps(redact_secrets(load_intake(target)), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("backend-command-log.json", json.dumps(redact_secrets(backend_command_log), indent=2, sort_keys=True, default=json_default) + "\n"),
        ("native-app-log-note.txt", "No native app log file is configured yet; backend command metadata and the latest target run log are included when present.\n"),
    ]
    safety_path = target_path(target, "target/integration_safety_check.json")
    if safety_path.exists():
        text, _truncated = read_text_file(safety_path)
        try:
            safety_payload = json.loads(text or "{}")
            safety_body = json.dumps(redact_secrets(safety_payload), indent=2, sort_keys=True, default=json_default) + "\n"
        except json.JSONDecodeError:
            safety_body = redact_secret_text(text)
        safe_records.append(("integration-safety-check.json", safety_body))
    if latest_log.get("content"):
        safe_records.append(("latest-run-log.txt", redact_secret_text(str(latest_log.get("content") or ""))))
    try:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in safe_records:
                archive.writestr(name, body)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackendError(
            "Could not write debug bundle.",
            error_type="debug_bundle_failed",
            details={"output_dir": str(output_dir), "exception": str(exc)},
        ) from exc
    return {
        "target": target_metadata(target),
        "bundle_path": str(bundle_path),
        "included": [name for name, _body in safe_records],
        "omitted": debug_summary["omitted"],
    }
