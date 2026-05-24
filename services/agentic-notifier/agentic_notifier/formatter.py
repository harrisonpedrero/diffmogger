from __future__ import annotations

import re
import textwrap

from agentic_notifier.models import NotifyRequest


FULL_REQUEST_ID_RE = re.compile(r"^([A-Za-z]+)-\d{4}-\d{2}-\d{2}-(\d+)$")
REQUEST_ID_RE = re.compile(r"\b([A-Za-z]+-(?:\d{4}-\d{2}-\d{2}-)?\d{1,})\b")


def derive_short_request_id(request_id: str) -> str:
    normalized = request_id.strip()
    match = FULL_REQUEST_ID_RE.match(normalized)
    if match:
        return f"{match.group(1).upper()}-{match.group(2)}"
    return normalized.upper()


def extract_request_id(text: str) -> str | None:
    match = REQUEST_ID_RE.search(text or "")
    return match.group(1).upper() if match else None


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clip(value: str, limit: int) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    shortened = textwrap.shorten(text, width=limit, placeholder="...")
    return shortened if shortened else text[: max(0, limit - 3)].rstrip() + "..."


def _clip_preserve_lines(value: str, limit: int) -> str:
    text = re.sub(r"[ \t]+", " ", value or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _why_text(request: NotifyRequest) -> str:
    if request.context:
        return request.context
    return request.summary


def _is_direct_message(request: NotifyRequest) -> bool:
    return (
        bool(request.message_body)
        or not request.expects_reply
        or request.request_id.upper().startswith("MSG-")
        or request.type.startswith("human_requested_")
    )


def format_notify_message(request: NotifyRequest, max_chars: int = 1900) -> str:
    if _is_direct_message(request):
        body = request.message_body or request.context or request.summary
        return _clip_preserve_lines(body, max_chars)

    short_id = derive_short_request_id(request.request_id)
    lines = [
        f"Need input: {short_id}",
        "",
        f"Type: {_clip(request.type, 64)}",
        f"Why: {_clip(_why_text(request), 220)}",
    ]

    if request.agent_recommendation:
        lines.append(f"Recommendation: {_clip(request.agent_recommendation, 220)}")
    if request.minimum_user_action:
        lines.append(f"Action: {_clip(request.minimum_user_action, 220)}")
    if request.reply_format:
        lines.append(f"Reply: {_clip(request.reply_format, 120)}")

    lines.extend(["", "I will keep working on unblocked local tasks meanwhile."])
    return _clip("\n".join(lines).strip(), max_chars)


def preview_message(message: str, limit: int = 160) -> str:
    return _clip(message.replace("\n", " "), limit)
