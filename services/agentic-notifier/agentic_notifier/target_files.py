from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agentic_notifier.config import Settings
from agentic_notifier.formatter import derive_short_request_id
from agentic_notifier.models import NotifyRequest


class TargetConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class TargetPaths:
    inbox: Path
    requests: Path
    outbox: Path
    archive: Path
    queue_dir: Path | None = None

    @property
    def requests_jsonl(self) -> Path | None:
        return self.queue_dir / "human_requests.jsonl" if self.queue_dir else None

    @property
    def outbox_jsonl(self) -> Path | None:
        return self.queue_dir / "human_outbox.jsonl" if self.queue_dir else None

    @property
    def responses_jsonl(self) -> Path | None:
        return self.queue_dir / "human_responses.jsonl" if self.queue_dir else None


def _now() -> datetime:
    return datetime.now().astimezone()


def _one_line(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _ensure_file(path: Path, title: str, intro: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"# {title}\n\n{intro.strip()}\n\n", encoding="utf-8")


def _append_markdown(path: Path, title: str, intro: str, entry: str) -> None:
    _ensure_file(path, title, intro)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.rstrip() + "\n\n")


def _append_jsonl(path: Path | None, record: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


class TargetFiles:
    def __init__(self, paths: TargetPaths):
        self.paths = paths

    @classmethod
    def from_settings(cls, settings: Settings) -> "TargetFiles":
        if not settings.target_repo_configured:
            raise TargetConfigError(
                "Target project markdown paths are not configured. Set TARGET_REPO_DIR "
                "or all TARGET_HUMAN_*_PATH values."
            )
        return cls(
            TargetPaths(
                inbox=settings.target_human_inbox_path,
                requests=settings.target_human_requests_path,
                outbox=settings.target_human_outbox_path,
                archive=settings.target_human_archive_path,
                queue_dir=settings.target_queue_dir,
            )
        )

    def ensure_all(self) -> None:
        _ensure_file(
            self.paths.inbox,
            "Human Inbox",
            "Unhandled human replies for the next target project automation run.",
        )
        _ensure_file(
            self.paths.requests,
            "Human Requests",
            "Active human unlock requests created by automation.",
        )
        _ensure_file(
            self.paths.outbox,
            "Human Outbox",
            "Outbound human notification records sent by agentic-notifier.",
        )
        _ensure_file(
            self.paths.archive,
            "Human Responses Archive",
            "Concise resolution notes archived by target project automation.",
        )

    def append_outbound_request(
        self,
        request: NotifyRequest,
        message: str,
        *,
        sent: bool,
        dry_run: bool,
        dedupe_key: str,
        status: str = "outbound_recorded",
        provider_error_code: str | None = None,
        provider_error_message: str | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        self.ensure_all()
        timestamp = sent_at or _now()
        entry_id = f"OUTBOX-{timestamp.strftime('%Y-%m-%d-%H%M%S')}"
        unblocked = "\n".join(
            f"- {item}" for item in request.unblocked_work_remaining
        ) or "- None listed"
        entry = f"""## {entry_id}

- sent_at: {timestamp.isoformat(timespec="seconds")}
- request_id: {request.request_id}
- short_request_id: {derive_short_request_id(request.request_id)}
- type: {_one_line(request.type)}
- priority: {_one_line(request.priority)}
- dedupe_key: {_one_line(dedupe_key)}
- sent: {str(sent).lower()}
- dry_run: {str(dry_run).lower()}
- status: {_one_line(status)}
{f"- provider_error_code: {_one_line(provider_error_code)}" if provider_error_code else ""}
{f"- provider_error_message: {_one_line(provider_error_message)}" if provider_error_message else ""}

### Summary

{request.summary}

### Message

{message}

### Unblocked Work Remaining

{unblocked}
"""
        _append_markdown(
            self.paths.outbox,
            "Human Outbox",
            "Outbound human notification records sent by agentic-notifier.",
            entry,
        )
        _append_jsonl(
            self.paths.outbox_jsonl,
            {
                "event": "outbound_notification",
                "entry_id": entry_id,
                "sent_at": timestamp.isoformat(timespec="seconds"),
                "request_id": request.request_id,
                "short_request_id": derive_short_request_id(request.request_id),
                "type": request.type,
                "priority": request.priority,
                "dedupe_key": dedupe_key,
                "sent": sent,
                "dry_run": dry_run,
                "status": status,
                "provider_error_code": provider_error_code,
                "provider_error_message": provider_error_message,
                "summary": request.summary,
                "message": message,
                "unblocked_work_remaining": request.unblocked_work_remaining,
            },
        )

    def upsert_active_request(
        self,
        request: NotifyRequest,
        message: str,
        *,
        dedupe_key: str,
        updated_at: datetime | None = None,
    ) -> None:
        self.ensure_all()
        timestamp = updated_at or _now()
        unblocked = "\n".join(
            f"- {item}" for item in request.unblocked_work_remaining
        ) or "- None listed"
        entry = f"""## {request.request_id}

- updated_at: {timestamp.isoformat(timespec="seconds")}
- request_id: {request.request_id}
- short_request_id: {derive_short_request_id(request.request_id)}
- type: {_one_line(request.type)}
- priority: {_one_line(request.priority)}
- dedupe_key: {_one_line(dedupe_key)}
- status: active

### Summary

{request.summary}

### Context

{request.context or "None provided."}

### Recommendation

{request.agent_recommendation or "None provided."}

### Minimum User Action

{request.minimum_user_action or "None provided."}

### Reply Format

{request.reply_format or "None provided."}

### Outbound Message

{message}

### Unblocked Work Remaining

{unblocked}
"""
        path = self.paths.requests
        _ensure_file(
            path,
            "Human Requests",
            "Active human unlock requests created by automation.",
        )
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(
            rf"^## {re.escape(request.request_id)}\n.*?(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        replacement = entry.rstrip() + "\n\n"
        if pattern.search(text):
            text = pattern.sub(replacement, text)
        else:
            if not text.endswith("\n\n"):
                text = text.rstrip() + "\n\n"
            text += replacement
        path.write_text(text, encoding="utf-8")
        _append_jsonl(
            self.paths.requests_jsonl,
            {
                "event": "active_request_upserted",
                "updated_at": timestamp.isoformat(timespec="seconds"),
                "request_id": request.request_id,
                "short_request_id": derive_short_request_id(request.request_id),
                "type": request.type,
                "priority": request.priority,
                "dedupe_key": dedupe_key,
                "summary": request.summary,
                "context": request.context,
                "agent_recommendation": request.agent_recommendation,
                "minimum_user_action": request.minimum_user_action,
                "reply_format": request.reply_format,
                "unblocked_work_remaining": request.unblocked_work_remaining,
            },
        )

    def append_inbound_message(
        self,
        *,
        from_value: str,
        to_value: str,
        body: str,
        message_sid: str,
        wa_id: str | None,
        request_id: str | None,
        parsed_intent: str,
        channel: str,
        received_at: datetime | None = None,
    ) -> str:
        self.ensure_all()
        timestamp = received_at or _now()
        inbox_id = self._next_inbox_id(timestamp)
        entry = f"""## {inbox_id}

- received_at: {timestamp.isoformat(timespec="seconds")}
- channel: {_one_line(channel)}
- from: {_one_line(from_value)}
- to: {_one_line(to_value)}
- request_id: {_one_line(request_id) or "unknown"}
- parsed_intent: {_one_line(parsed_intent)}
- message_sid: {_one_line(message_sid)}
- wa_id: {_one_line(wa_id) or "none"}
- status: unhandled

### Body

{body}

### Expected automation behavior

The next target project automation run should handle this message, update any related request state, then remove this entry from `docs/HUMAN_INBOX.md` and archive a concise resolution note in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
"""
        _append_markdown(
            self.paths.inbox,
            "Human Inbox",
            "Unhandled human replies for the next target project automation run.",
            entry,
        )
        _append_jsonl(
            self.paths.responses_jsonl,
            {
                "event": "inbound_response",
                "inbox_id": inbox_id,
                "received_at": timestamp.isoformat(timespec="seconds"),
                "channel": channel,
                "from": from_value,
                "to": to_value,
                "request_id": request_id or "unknown",
                "parsed_intent": parsed_intent,
                "message_sid": message_sid,
                "wa_id": wa_id,
                "status": "unhandled",
                "body": body,
            },
        )
        return inbox_id

    def _next_inbox_id(self, timestamp: datetime) -> str:
        date_prefix = timestamp.strftime("%Y-%m-%d")
        path = self.paths.inbox
        _ensure_file(
            path,
            "Human Inbox",
            "Unhandled human replies for the next target project automation run.",
        )
        text = path.read_text(encoding="utf-8")
        pattern = re.compile(rf"^## INBOX-{re.escape(date_prefix)}-(\d{{3,}})", re.MULTILINE)
        existing = [int(match.group(1)) for match in pattern.finditer(text)]
        next_number = max(existing, default=0) + 1
        return f"INBOX-{date_prefix}-{next_number:03d}"
