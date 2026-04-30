import pytest

from agentic_notifier.parser import parse_reply, parse_request_id


@pytest.mark.parametrize(
    ("body", "request_id"),
    [
        ("HR-001 DONE", "HR-001"),
        ("HR-2026-04-29-001 DONE", "HR-2026-04-29-001"),
        ("DONE HR-001", "HR-001"),
        ("skip HR-001", "HR-001"),
        ("I added the key for hr-2026-04-29-001", "HR-2026-04-29-001"),
    ],
)
def test_parse_request_id_formats(body: str, request_id: str) -> None:
    assert parse_request_id(body) == request_id


@pytest.mark.parametrize(
    ("body", "intent"),
    [
        ("HR-001 DONE", "done"),
        ("skip HR-001", "skip"),
        ("approve HR-001", "approve"),
        ("reject HR-001", "reject"),
        ("HR-001 here are details", "info"),
        ("hello there", "unknown"),
    ],
)
def test_parse_intents(body: str, intent: str) -> None:
    assert parse_reply(body).parsed_intent == intent

