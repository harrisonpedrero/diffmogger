from __future__ import annotations

from ..errors import *
from ..jsonio import *
from ..target import *

from diffmogger.runtime.state_store import human_messages_snapshot, record_human_message

HUMAN_INTENTS = {"info", "done", "skip", "approve", "reject", "unknown"}

HUMAN_REQUEST_STATUSES = {"active", "awaiting_user", "awaiting_human", "pending", "open", "unresolved"}

HUMAN_ARCHIVE_STATUSES = {"resolved", "handled", "consumed", "archived", "done", "closed", "skipped"}

def human_file(target: Path, name: str) -> Path:
    return target_path(target, f"docs/{name}")

def parse_metadata_block(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*-\s+([A-Za-z0-9_-]+):\s*(.*)\s*$", line)
        if match:
            metadata[match.group(1).strip()] = match.group(2).strip()
    return metadata

def extract_markdown_body(section: str) -> str:
    body_match = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
    if body_match:
        body_start = body_match.end()
        next_heading = re.search(r"^#{3,5}\s+", section[body_start:], flags=re.MULTILINE)
        body_end = body_start + next_heading.start() if next_heading else len(section)
        return section[body_start:body_end].strip()
    stripped_lines = [
        line
        for line in section.splitlines()
        if not re.match(r"^\s*-\s+[A-Za-z0-9_-]+:\s*", line)
        and not re.match(r"^#{1,6}\s+", line)
        and not line.strip().startswith("```")
    ]
    return "\n".join(stripped_lines).strip()

def markdown_record_summary(section: str, metadata: dict[str, str], body: str) -> str:
    for key in ("summary", "action_taken", "remaining_followup", "blocker", "reason"):
        if metadata.get(key):
            return compact_text(metadata[key], limit=180)
    if body:
        return compact_text(body, limit=180)
    return "No message body recorded."

def parse_markdown_records(path: Path, prefixes: tuple[str, ...]) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    text, truncated = read_text_file(path)
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    heading_pattern = re.compile(
        rf"^(?P<level>##+)\s+(?P<record_id>(?:{prefix_pattern})-[A-Za-z0-9_.:-]+)(?P<title>[^\n]*)$",
        flags=re.MULTILINE,
    )
    matches = list(heading_pattern.finditer(text))
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        record_id = match.group("record_id").strip()
        if "YYYY" in record_id or record_id.endswith("-001`"):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        metadata_boundary = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
        metadata_text = section[: metadata_boundary.start()] if metadata_boundary else section
        metadata = parse_metadata_block(metadata_text)
        body = extract_markdown_body(section)
        raw_status = metadata.get("status", "").strip().lower()
        title = match.group("title").strip(" -:\t")
        records.append(
            {
                "id": record_id,
                "title": title or record_id,
                "status": raw_status or "unknown",
                "status_label": (raw_status or "unknown").replace("_", " ").title(),
                "timestamp": metadata.get("received_at")
                or metadata.get("created_at")
                or metadata.get("requested_at")
                or metadata.get("resolved_at")
                or metadata.get("timestamp")
                or "",
                "request_id": metadata.get("request_id", ""),
                "source_inbox_id": metadata.get("source_inbox_id", ""),
                "intent": metadata.get("parsed_intent") or metadata.get("intent") or "",
                "channel": metadata.get("channel", ""),
                "from": metadata.get("from", ""),
                "to": metadata.get("to", ""),
                "related": {
                    "request": metadata.get("request_id", ""),
                    "ticket": metadata.get("ticket_id") or metadata.get("related_ticket") or metadata.get("ticket") or "",
                    "run": metadata.get("run_id") or metadata.get("related_run") or "",
                    "file": metadata.get("file") or metadata.get("related_file") or metadata.get("path") or "",
                },
                "metadata": metadata,
                "body": body,
                "summary": markdown_record_summary(section, metadata, body),
                "source_file_key": "",
                "truncated": truncated,
            }
        )
    return records

def classify_request(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "").lower()
    if status in HUMAN_ARCHIVE_STATUSES:
        return "handled"
    if status in HUMAN_REQUEST_STATUSES:
        return "pending"
    return "unknown"

def classify_note(record: dict[str, Any], archived_inbox_ids: set[str]) -> str:
    status = str(record.get("status") or "").lower()
    record_id = str(record.get("id") or "")
    if record_id in archived_inbox_ids:
        return "archived"
    if status in {"handled", "consumed", "archived", "done", "closed"}:
        return "consumed"
    if status in {"failed", "error"}:
        return "failed"
    return "queued"

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
