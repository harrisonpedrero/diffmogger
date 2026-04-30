from __future__ import annotations

import re
import textwrap

from agentic_notifier.models import NotifyRequest


FULL_REQUEST_ID_RE = re.compile(r"^([A-Za-z]+)-\d{4}-\d{2}-\d{2}-(\d+)$")


def derive_short_request_id(request_id: str) -> str:
    normalized = request_id.strip()
    match = FULL_REQUEST_ID_RE.match(normalized)
    if match:
        return f"{match.group(1).upper()}-{match.group(2)}"
    return normalized.upper()


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clip(value: str, limit: int) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    shortened = textwrap.shorten(text, width=limit, placeholder="...")
    return shortened if shortened else text[: max(0, limit - 3)].rstrip() + "..."


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


def format_notify_message(request: NotifyRequest, max_chars: int = 900) -> str:
    if _is_direct_message(request):
        body = request.message_body or request.context or request.summary
        return _clip(body, max_chars)

    short_id = derive_short_request_id(request.request_id)
    lines = [
        f"Need input: {short_id}",
        "",
        f"Type: {_clip(request.type, 48)}",
        f"Why: {_clip(_why_text(request), 150)}",
    ]

    if request.agent_recommendation:
        lines.append(f"Recommendation: {_clip(request.agent_recommendation, 145)}")
    if request.minimum_user_action:
        lines.append(f"Action: {_clip(request.minimum_user_action, 150)}")
    if request.reply_format:
        lines.append(f"Reply: {_clip(request.reply_format, 90)}")

    lines.extend(["", "I'll keep working on offline/demo tasks meanwhile."])
    message = "\n".join(lines).strip()

    if len(message) <= max_chars:
        return message

    essential = [
        f"Need input: {short_id}",
        "",
        f"Type: {_clip(request.type, 40)}",
        f"Why: {_clip(_why_text(request), 100)}",
    ]
    if request.minimum_user_action:
        essential.append(f"Action: {_clip(request.minimum_user_action, 120)}")
    if request.reply_format:
        essential.append(f"Reply: {_clip(request.reply_format, 80)}")
    essential.extend(["", "I'll keep working on offline/demo tasks meanwhile."])
    return _clip("\n".join(essential), max_chars)


def preview_message(message: str, limit: int = 160) -> str:
    return _clip(message.replace("\n", " "), limit)
