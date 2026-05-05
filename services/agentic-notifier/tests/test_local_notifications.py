from agentic_notifier.local_notifications import send_local_notification


def test_local_notification_disabled() -> None:
    result = send_local_notification(
        subtitle="message",
        body="hello",
        enabled=False,
        dry_run=False,
    )

    assert result["enabled"] is False
    assert result["ok"] is True
    assert result["status"] == "disabled"


def test_local_notification_dry_run() -> None:
    result = send_local_notification(
        subtitle="message",
        body="hello",
        enabled=True,
        dry_run=True,
    )

    assert result["enabled"] is True
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["status"] == "dry_run"
