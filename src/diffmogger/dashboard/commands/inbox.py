from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from diffmogger.runtime.state_store import human_messages_snapshot, record_human_message

HUMAN_INTENTS = {"info", "done", "skip", "approve", "reject", "unknown"}

def inbox_snapshot(target: Path) -> dict[str, Any]:
    snapshot = human_messages_snapshot(target)
    return {
        "target": target_metadata(target),
        "bridge_mode": human_bridge_mode_from_state(target),
        **snapshot,
    }

def command_inbox_load(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return inbox_snapshot(target)

def normalize_human_intent(raw: str) -> str:
    intent = str(raw or "info").strip().lower()
    if intent not in HUMAN_INTENTS:
        raise BackendError(
            "Intent is not supported by the file-only human bridge.",
            exit_code=2,
            error_type="invalid_human_intent",
            details={"intent": raw, "allowed": sorted(HUMAN_INTENTS)},
        )
    return intent

def command_inbox_send_note(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    body = str(args.body or "").strip()
    if not body:
        raise BackendError(
            "A message body is required.",
            exit_code=2,
            error_type="missing_body",
        )
    request_id = str(args.related or "").strip() or "general"
    note = record_human_message(
        target,
        kind="note",
        request_id=request_id,
        body=body,
        intent=normalize_human_intent(args.intent),
        status="unhandled",
        channel="manual-dashboard",
    )
    inbox_id = str(note.get("id") or "")
    snapshot = inbox_snapshot(target)
    note = next((record for record in snapshot["notes"] if record.get("id") == inbox_id), note)
    return {
        "target": target_metadata(target),
        "inbox_id": inbox_id,
        "status": "queued",
        "note": note,
        "state": "sqlite",
        "snapshot": snapshot,
    }

def command_inbox_reply_request(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    request_id = str(args.request_id or "").strip()
    if not request_id:
        raise BackendError(
            "A request id is required when replying to an automation request.",
            exit_code=2,
            error_type="missing_request_id",
        )
    body = str(args.body or "").strip()
    if not body:
        raise BackendError(
            "A reply body is required.",
            exit_code=2,
            error_type="missing_body",
        )
    note = record_human_message(
        target,
        kind="note",
        request_id=request_id,
        body=body,
        intent=normalize_human_intent(args.intent),
        status="unhandled",
        channel="manual-dashboard",
    )
    inbox_id = str(note.get("id") or "")
    snapshot = inbox_snapshot(target)
    note = next((record for record in snapshot["notes"] if record.get("id") == inbox_id), note)
    return {
        "target": target_metadata(target),
        "request_id": request_id,
        "inbox_id": inbox_id,
        "status": "queued",
        "note": note,
        "state": "sqlite",
        "snapshot": snapshot,
    }
