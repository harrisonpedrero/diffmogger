from __future__ import annotations

import re
from dataclasses import dataclass

from agentic_notifier.formatter import derive_short_request_id


REQUEST_ID_RE = re.compile(
    r"\b([A-Za-z]{2,}-(?:\d{4}-\d{2}-\d{2}-)?\d{3,})\b",
    re.IGNORECASE,
)

INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("skip", re.compile(r"\b(skip|skipped|defer|deferred|hold)\b", re.IGNORECASE)),
    ("done", re.compile(r"\b(done|complete|completed|finished|added|fixed|ready)\b", re.IGNORECASE)),
    ("approve", re.compile(r"\b(approve|approved|yes|ok|okay|proceed|go ahead)\b", re.IGNORECASE)),
    ("reject", re.compile(r"\b(reject|rejected|deny|denied|no|stop|blocked)\b", re.IGNORECASE)),
    ("info", re.compile(r"\b(info|note|details?|update)\b", re.IGNORECASE)),
]


@dataclass(frozen=True)
class ParsedReply:
    request_id: str | None
    short_request_id: str | None
    parsed_intent: str
    body: str


def parse_request_id(body: str) -> str | None:
    match = REQUEST_ID_RE.search(body or "")
    if not match:
        return None
    return match.group(1).upper()


def infer_intent(body: str, request_id: str | None = None) -> str:
    text = body or ""
    for intent, pattern in INTENT_PATTERNS:
        if pattern.search(text):
            return intent
    if request_id and text.strip():
        return "info"
    return "unknown"


def parse_reply(body: str) -> ParsedReply:
    request_id = parse_request_id(body)
    return ParsedReply(
        request_id=request_id,
        short_request_id=derive_short_request_id(request_id) if request_id else None,
        parsed_intent=infer_intent(body, request_id),
        body=body or "",
    )

