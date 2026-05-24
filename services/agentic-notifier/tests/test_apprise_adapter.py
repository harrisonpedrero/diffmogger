from agentic_notifier.apprise_adapter import send_with_apprise
from agentic_notifier.models import NotifyRequest


def test_apprise_adapter_dry_run() -> None:
    request = NotifyRequest(
        request_id="REQ-1",
        type="progress",
        priority="normal",
        summary="Dry-run",
        message_body="Body",
        expects_reply=False,
    )

    result = send_with_apprise(request, urls=["json://127.0.0.1:9"], message="Body", dry_run=True)

    assert result.ok is True
    assert result.sent is False
    assert result.status == "dry_run"
