from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from diffmogger.runtime import ticket_run


def _ticket_file_arg(args: argparse.Namespace) -> Path | None:
    raw = str(getattr(args, "ticket_file", "") or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def _load_ticket_state(target: Path, args: argparse.Namespace) -> tuple[dict[str, Any], Path, str]:
    try:
        return ticket_run.load_ticket_run(target, _ticket_file_arg(args))
    except SystemExit as exc:
        raise BackendError(
            str(exc),
            exit_code=2,
            error_type="ticket_load_failed",
            details={"target": str(target)},
        ) from exc


def _payload(target: Path, data: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "target": target_metadata(target),
        "ticket_file": str(path),
        **ticket_run.ticket_run_payload(data, target),
    }


def _write_result(target: Path, path: Path, text: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = ticket_run.write_if_valid(target, path, text, data)
    if not payload.get("written"):
        raise BackendError(
            "Ticket changes were not written because validation failed.",
            exit_code=2,
            error_type="ticket_validation_failed",
            details=payload,
        )
    write_dashboard_action_state(target, last_action="ticket_queue_updated")
    return {"target": target_metadata(target), **payload}


def command_ticket_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data, path, _text = _load_ticket_state(target, args)
    return _payload(target, data, path)


def command_ticket_add(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data, path, text = _load_ticket_state(target, args)
    ticket = ticket_run.read_ticket_json_arg(args.ticket_json, data)
    next_data = dict(data)
    next_data["tickets"] = [*ticket_run.tickets(data), ticket]
    return _write_result(target, path, text, next_data)


def command_ticket_update(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data, path, text = _load_ticket_state(target, args)
    target_id = str(args.ticket_id or "").strip()
    replacement = ticket_run.read_ticket_json_arg(args.ticket_json)
    next_items: list[dict[str, Any]] = []
    found = False
    for item in ticket_run.tickets(data):
        if str(item.get("id") or "").strip() == target_id:
            next_items.append(ticket_run.normalize_ticket({**item, **replacement, "id": target_id}))
            found = True
        else:
            next_items.append(item)
    if not found:
        raise BackendError(
            "Ticket id not found.",
            exit_code=2,
            error_type="ticket_not_found",
            details={"ticket_id": target_id},
        )
    next_data = dict(data)
    next_data["tickets"] = next_items
    return _write_result(target, path, text, next_data)


def command_ticket_delete(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data, path, text = _load_ticket_state(target, args)
    target_id = str(args.ticket_id or "").strip()
    current = ticket_run.tickets(data)
    next_items = [item for item in current if str(item.get("id") or "").strip() != target_id]
    if len(next_items) == len(current):
        raise BackendError(
            "Ticket id not found.",
            exit_code=2,
            error_type="ticket_not_found",
            details={"ticket_id": target_id},
        )
    next_data = dict(data)
    next_data["tickets"] = next_items
    return _write_result(target, path, text, next_data)


def _import_text(args: argparse.Namespace) -> str:
    provided = [bool(args.input_file), bool(args.input_text), bool(args.input_json)]
    if sum(1 for item in provided if item) != 1:
        raise BackendError(
            "Provide exactly one ticket import source.",
            exit_code=2,
            error_type="ticket_import_source_invalid",
            details={"input_file": bool(args.input_file), "input_text": bool(args.input_text), "input_json": bool(args.input_json)},
        )
    if args.input_file:
        path = Path(args.input_file).expanduser()
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "Could not read ticket import file.",
                exit_code=2,
                error_type="ticket_import_read_failed",
                details={"input_file": str(path), "exception": str(exc)},
            ) from exc
    if args.input_json:
        return str(args.input_json)
    return str(args.input_text)


def command_ticket_import(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data, path, text = _load_ticket_state(target, args)
    try:
        imported = ticket_run.parse_import_tickets(_import_text(args), args.import_format)
    except SystemExit as exc:
        raise BackendError(
            str(exc),
            exit_code=2,
            error_type="ticket_import_parse_failed",
            details={"format": args.import_format},
        ) from exc
    mode = str(args.import_mode or "") or ticket_run.default_import_mode(data)
    next_data = ticket_run.data_with_imported_tickets(data, imported, mode)
    preview_payload = {
        "target": target_metadata(target),
        "ticket_file": str(path),
        "preview": bool(args.preview),
        "written": False,
        "mode": mode,
        "imported_count": len(imported),
        "imported_tickets": imported,
        **ticket_run.ticket_run_payload(next_data, target),
    }
    if args.preview:
        return preview_payload
    write_payload = _write_result(target, path, text, next_data)
    write_payload.update({"preview": False, "mode": mode, "imported_count": len(imported), "imported_tickets": imported})
    return write_payload


def _git_status(target: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=target,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _extract_json_payload(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", stripped)
    if not match:
        raise BackendError(
            "Codex did not return JSON ticket candidates.",
            error_type="ticket_draft_parse_failed",
            details={"stdout_excerpt": stripped[-1200:]},
        )
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise BackendError(
            "Codex returned malformed JSON ticket candidates.",
            error_type="ticket_draft_parse_failed",
            details={"exception": str(exc), "stdout_excerpt": stripped[-1200:]},
        ) from exc


def _draft_dir(target: Path) -> Path:
    path = target_path(target, "target/ticket_drafts")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _draft_path(target: Path, draft_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", draft_id).strip("-") or "ticket-draft"
    return _draft_dir(target) / f"{safe}.json"


def _summary_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _next_available_ticket_id(used_ids: set[str]) -> str:
    highest = 0
    for ticket_id in used_ids:
        match = re.search(r"(\d+)$", ticket_id)
        if match:
            highest = max(highest, int(match.group(1)))
    while True:
        highest += 1
        candidate = f"TICKET-{highest:03d}"
        if candidate not in used_ids:
            return candidate


def _append_only_draft_candidates(
    data: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    current = ticket_run.tickets(data)
    existing_ids = {str(item.get("id") or "").strip() for item in current if str(item.get("id") or "").strip()}
    existing_summaries = {
        key for key in (_summary_key(item.get("summary")) for item in current) if key
    }
    used_ids = set(existing_ids)
    filtered: list[dict[str, Any]] = []
    dropped_existing_count = 0
    renumbered_count = 0

    for candidate in candidates:
        ticket = ticket_run.normalize_ticket(candidate)
        summary_key = _summary_key(ticket.get("summary"))
        if summary_key and summary_key in existing_summaries:
            dropped_existing_count += 1
            continue

        original_id = str(ticket.get("id") or "").strip()
        next_id = original_id
        if not next_id or next_id in used_ids:
            next_id = _next_available_ticket_id(used_ids)
            renumbered_count += 1

        used_ids.add(next_id)
        ticket["id"] = next_id
        ticket["status"] = "pending"
        filtered.append(ticket)

    known_ids = existing_ids | {
        str(item.get("id") or "").strip()
        for item in filtered
        if str(item.get("id") or "").strip()
    }
    dropped_dependency_count = 0
    for ticket in filtered:
        next_dependencies: list[str] = []
        for dependency_id in ticket_run.ticket_dependency_ids(ticket):
            if (
                dependency_id in known_ids
                and dependency_id != str(ticket.get("id") or "")
                and dependency_id not in next_dependencies
            ):
                next_dependencies.append(dependency_id)
            else:
                dropped_dependency_count += 1
        ticket["depends_on"] = next_dependencies

    return filtered, {
        "dropped_existing_count": dropped_existing_count,
        "renumbered_count": renumbered_count,
        "dropped_dependency_count": dropped_dependency_count,
    }


def command_ticket_draft_from_intake(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    try:
        data, path, text = _load_ticket_state(target, args)
    except BackendError:
        path = ticket_run.ticket_file_path(target)
        data = {"run_id": "ticket-run", "tickets": []}
        text = ""
    intake = load_intake(target) or load_dashboard_state(target).get("brief_draft_intake") or {}
    current_tickets = ticket_run.tickets(data)
    current_ids = {str(item.get("id") or "").strip() for item in current_tickets if str(item.get("id") or "").strip()}
    next_ticket_id = _next_available_ticket_id(set(current_ids))
    prompt = "\n".join(
        [
            "Draft additional Diffmogger ticket-campaign tickets from this project intake.",
            "Return JSON only: an array of ticket objects.",
            "Each ticket must include id, summary, depends_on, status, acceptance_criteria, verification_commands, evidence, related_commits, and blocker.",
            "Use status pending. Do not modify files.",
            "Append-only rules:",
            "- Propose only genuinely new follow-up tickets.",
            "- Do not repeat, rewrite, replace, or reset any current ticket.",
            f"- Use fresh ticket IDs starting at {next_ticket_id} or later.",
            "- Dependencies may point to current tickets or to newly proposed tickets.",
            "",
            "Project intake JSON:",
            json.dumps(intake, indent=2, sort_keys=True, default=json_default),
            "",
            "Current ticket-run JSON:",
            json.dumps(data, indent=2, sort_keys=True, default=json_default),
        ]
    )
    before_status = _git_status(target)
    before_ticket = json.dumps(data, sort_keys=True, default=json_default)
    if path != ticket_run.ticket_state_path(target) and text:
        before_ticket = text
    stream_event(args, "ticket-draft", "Starting Codex ticket draft.")
    result = subprocess.run(
        ["codex", "exec", "--full-auto", "--skip-git-repo-check", prompt],
        cwd=target,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    after_status = _git_status(target)
    after_data = ticket_run.load_ticket_run(target)[0] if path == ticket_run.ticket_state_path(target) else data
    after_ticket = json.dumps(after_data, sort_keys=True, default=json_default)
    if path != ticket_run.ticket_state_path(target) and path.exists():
        after_ticket = path.read_text(encoding="utf-8")
    if after_status != before_status or after_ticket != before_ticket:
        raise BackendError(
            "Codex ticket drafting unexpectedly modified the target.",
            error_type="ticket_draft_mutated_target",
            details={"before_status": before_status, "after_status": after_status, "ticket_file": str(path)},
        )
    if result.returncode != 0:
        raise BackendError(
            "Codex ticket drafting failed.",
            error_type="ticket_draft_failed",
            details={"exit_code": result.returncode, "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]},
        )
    raw_candidates = _extract_json_payload(result.stdout)
    candidate_text = json.dumps(raw_candidates)
    raw_imported = ticket_run.parse_import_tickets(candidate_text, "json")
    candidates, draft_meta = _append_only_draft_candidates(data, raw_imported)
    stream_event(args, "ticket-draft", f"Prepared {len(candidates)} append-only draft ticket candidate(s).")
    draft_id = datetime.now(timezone.utc).strftime("ticket-draft-%Y%m%d-%H%M%S")
    message = (
        f"{len(candidates)} new draft ticket candidate{' is' if len(candidates) == 1 else 's are'} ready to add."
        if candidates
        else "No new draft tickets were found."
    )
    payload = {
        "schema_version": 1,
        "draft_id": draft_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ticket_file": str(path),
        "generation_mode": "append",
        "message": message,
        **draft_meta,
        "candidates": candidates,
    }
    draft_path = _draft_path(target, draft_id)
    write_json_file(draft_path, payload)
    write_dashboard_action_state(target, last_action="ticket_draft_created")
    return {
        "target": target_metadata(target),
        "draft_id": draft_id,
        "draft_path": str(draft_path),
        "candidate_count": len(candidates),
        "generation_mode": "append",
        "message": message,
        **draft_meta,
        "candidates": candidates,
    }


def command_ticket_accept_draft(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    data, path, text = _load_ticket_state(target, args)
    draft_id = str(args.draft_id or "").strip()
    draft_path = _draft_path(target, draft_id)
    draft = read_json_file(draft_path)
    candidates = [item for item in draft.get("candidates", []) if isinstance(item, dict)]
    selected_ids = {item.strip() for item in str(args.ticket_ids or "").split(",") if item.strip()}
    if selected_ids:
        candidates = [item for item in candidates if str(item.get("id") or "").strip() in selected_ids]
    if not candidates:
        raise BackendError(
            "No draft tickets were selected.",
            exit_code=2,
            error_type="ticket_draft_empty",
            details={"draft_id": draft_id},
        )
    mode = str(args.import_mode or "") or ticket_run.default_import_mode(data)
    next_data = ticket_run.data_with_imported_tickets(data, candidates, mode)
    result = _write_result(target, path, text, next_data)
    result.update({"draft_id": draft_id, "accepted_count": len(candidates), "mode": mode})
    return result
