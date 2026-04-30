from agentic_notifier.formatter import derive_short_request_id, format_notify_message
from agentic_notifier.models import NotifyRequest


def test_derive_short_request_id_from_dated_id() -> None:
    assert derive_short_request_id("HR-2026-04-29-001") == "HR-001"


def test_format_notify_message_is_concise() -> None:
    request = NotifyRequest(
        request_id="HR-2026-04-29-001",
        type="api_key_setup",
        priority="unlocking",
        summary="Add Service X read-only API key",
        context="This unlocks the next source adapter while offline fixtures remain available.",
        agent_recommendation="Use read-only/data-only access. Do not grant write, billing, admin, or production permissions.",
        minimum_user_action="Add SERVICE_X_API_KEY to your local secret store.",
        reply_format="HR-001 DONE or HR-001 SKIP",
        dedupe_key="HR-2026-04-29-001:v1",
    )

    message = format_notify_message(request)

    assert "Need input: HR-001" in message
    assert "Type: api_key_setup" in message
    assert "Reply: HR-001 DONE or HR-001 SKIP" in message
    assert len(message) < 900


def test_format_notify_message_supports_direct_status_message() -> None:
    request = NotifyRequest(
        request_id="MSG-2026-04-29-001",
        type="human_requested_summary",
        priority="normal",
        summary="Progress summary requested by human",
        context="Built the report view, added tests, and kept the next sprint focused.",
        message_body="Project update: Built the report view, added tests, and kept the next sprint focused. Current blocker: none.",
        minimum_user_action="None.",
        reply_format="Optional follow-up request.",
        dedupe_key="MSG-2026-04-29-001:v1",
        expects_reply=False,
    )

    message = format_notify_message(request)

    assert message.startswith("Project update:")
    assert "Need input" not in message
    assert len(message) < 900
