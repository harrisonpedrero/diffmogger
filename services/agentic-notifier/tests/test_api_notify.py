from fastapi.testclient import TestClient

import agentic_notifier.api_app as api_app
from agentic_notifier.api_app import create_app
from agentic_notifier.config import Settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.discord_bot import DiscordSendError, DiscordSendResult
from agentic_notifier.target_files import TargetFiles


class FakeDiscordSender:
    def __init__(self, *, enabled: bool = True, fail: bool = False) -> None:
        self.enabled = enabled
        self.fail = fail
        self.calls: list[tuple[str, str, bool]] = []

    def can_send(self, event_kind: str) -> bool:
        return self.enabled and event_kind in {"progress", "message"}

    async def send(self, event_kind: str, message: str, *, dry_run: bool) -> DiscordSendResult:
        self.calls.append((event_kind, message, dry_run))
        if self.fail:
            raise DiscordSendError("Discord rejected the message")
        return DiscordSendResult(sent=not dry_run, dry_run=dry_run, status="dry_run" if dry_run else "sent")


def _settings(tmp_path, **overrides) -> Settings:
    target = tmp_path / "target"
    values = {
        "discord_bot_token": "fake-token",
        "discord_progress_channel_id": 111,
        "discord_messaging_channel_id": 222,
        "local_notifications_enabled": True,
        "target_repo_dir": target,
        "target_human_inbox_path": target / "docs" / "HUMAN_INBOX.md",
        "target_human_requests_path": target / "docs" / "HUMAN_REQUESTS.md",
        "target_human_outbox_path": target / "docs" / "HUMAN_OUTBOX.md",
        "target_human_archive_path": target / "docs" / "HUMAN_RESPONSES_ARCHIVE.md",
        "runtime_dir": tmp_path / "runtime",
        "dry_run": False,
    }
    values.update(overrides)
    return Settings(**values)


def _payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": "HR-2026-04-29-001",
        "type": "api_key_setup",
        "priority": "unlocking",
        "summary": "Add Service X read-only API key",
        "event_kind": "message",
        "context": "Unlocks the next source adapter.",
        "agent_recommendation": "Use read-only/data-only access.",
        "minimum_user_action": "Add SERVICE_X_API_KEY locally and reply HR-001 DONE.",
        "reply_format": "HR-001 DONE or HR-001 SKIP",
        "unblocked_work_remaining": ["Continue fixture-based work"],
        "dedupe_key": "HR-2026-04-29-001:v1",
        "dry_run": False,
    }
    payload.update(overrides)
    return payload


def _client(
    tmp_path,
    settings: Settings | None = None,
    fake: FakeDiscordSender | None = None,
):
    settings = settings or _settings(tmp_path)
    fake = fake or FakeDiscordSender()
    files = TargetFiles.from_settings(settings)
    store = JsonlDedupeStore(tmp_path / "runtime" / "sent.jsonl", "dedupe_key")
    app = create_app(settings=settings, files=files, discord_sender=fake, sent_store=store)
    return TestClient(app), fake, files


def test_request_model_accepts_event_kind_and_rejects_invalid_value(tmp_path) -> None:
    client, _fake, _files = _client(tmp_path)

    accepted = client.post("/api/notify", json=_payload(event_kind="progress", local_notify=False))
    invalid = client.post("/api/notify", json=_payload(event_kind="other", dedupe_key="bad"))

    assert accepted.status_code == 200
    assert invalid.status_code == 422


def test_progress_event_routes_to_discord_progress_without_local_by_default(tmp_path) -> None:
    client, fake, files = _client(tmp_path)

    response = client.post(
        "/api/notify",
        json=_payload(
            request_id="PROG-2026-04-29-001",
            type="automation_progress",
            event_kind="progress",
            summary="Builder integrated one patch",
            message_body="Builder integrated one patch and verification passed.",
            expects_reply=False,
            local_notify=None,
            dedupe_key="progress:v1",
        ),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["sent"] is True
    assert body["deliveries"]["discord"]["sent"] is True
    assert body["deliveries"]["local"]["enabled"] is False
    assert fake.calls[0][0] == "progress"
    assert "Builder integrated" in files.paths.outbox.read_text(encoding="utf-8")


def test_message_event_sends_discord_and_local_notification(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        api_app,
        "send_local_notification",
        lambda **_kwargs: {
            "enabled": True,
            "ok": True,
            "sent": True,
            "dry_run": False,
            "status": "sent",
            "detail": "delivered",
        },
    )
    client, fake, _files = _client(tmp_path)

    response = client.post(
        "/api/notify",
        json=_payload(
            request_id="MSG-2026-04-29-001",
            type="human_requested_summary",
            event_kind="message",
            summary="Progress summary requested",
            message_body="Project update: checks passed; no blocker.",
            expects_reply=False,
            dedupe_key="message:v1",
        ),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["deliveries"]["discord"]["sent"] is True
    assert body["deliveries"]["local"]["sent"] is True
    assert fake.calls[0][0] == "message"


def test_completion_progress_event_sends_discord_and_local_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        api_app,
        "send_local_notification",
        lambda **_kwargs: {
            "enabled": True,
            "ok": True,
            "sent": True,
            "dry_run": False,
            "status": "sent",
            "detail": "delivered",
        },
    )
    client, fake, _files = _client(tmp_path)

    response = client.post(
        "/api/notify",
        json=_payload(
            request_id="TICKET-run-1",
            type="ticket_campaign_complete",
            event_kind="progress",
            summary="Ticket campaign complete",
            message_body="Ticket campaign run-1 complete. Report written.",
            expects_reply=False,
            dedupe_key="ticket:v1",
        ),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["deliveries"]["discord"]["sent"] is True
    assert body["deliveries"]["local"]["sent"] is True
    assert fake.calls[0][0] == "progress"


def test_local_only_mode_skips_discord_and_sends_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        api_app,
        "send_local_notification",
        lambda **_kwargs: {
            "enabled": True,
            "ok": True,
            "sent": True,
            "dry_run": False,
            "status": "sent",
            "detail": "delivered",
        },
    )
    settings = _settings(
        tmp_path,
        discord_bot_token="",
        discord_progress_channel_id=None,
        discord_messaging_channel_id=None,
    )
    client, fake, _files = _client(tmp_path, settings=settings, fake=FakeDiscordSender(enabled=False))

    response = client.post("/api/notify", json=_payload(dedupe_key="local-only:v1"))

    body = response.json()
    assert response.status_code == 200
    assert body["deliveries"]["discord"]["enabled"] is False
    assert body["deliveries"]["local"]["sent"] is True
    assert fake.calls == []


def test_discord_failure_records_generic_status(tmp_path) -> None:
    client, _fake, files = _client(tmp_path, fake=FakeDiscordSender(fail=True))

    response = client.post("/api/notify", json=_payload(dedupe_key="discord-fails:v1"))

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["deliveries"]["discord"]["status"] == "DISCORD_SEND_FAILED"
    outbox = files.paths.outbox.read_text(encoding="utf-8")
    assert "- status: DISCORD_SEND_FAILED" in outbox
    assert "Discord rejected the message" in outbox


def test_local_notification_failure_records_generic_status(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        api_app,
        "send_local_notification",
        lambda **_kwargs: {
            "enabled": True,
            "ok": False,
            "sent": False,
            "dry_run": False,
            "status": "LOCAL_NOTIFICATION_FAILED",
            "detail": "osascript unavailable",
        },
    )
    client, _fake, files = _client(tmp_path, fake=FakeDiscordSender(enabled=False))

    response = client.post("/api/notify", json=_payload(dedupe_key="local-fails:v1"))

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["deliveries"]["local"]["status"] == "LOCAL_NOTIFICATION_FAILED"
    outbox = files.paths.outbox.read_text(encoding="utf-8")
    assert "- status: LOCAL_NOTIFICATION_FAILED" in outbox
    assert "osascript unavailable" in outbox


def test_api_notify_dedupes_after_first_delivery(tmp_path) -> None:
    client, fake, files = _client(tmp_path)

    first = client.post("/api/notify", json=_payload(dedupe_key="dedupe:v1"))
    second = client.post("/api/notify", json=_payload(dedupe_key="dedupe:v1"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert len(fake.calls) == 1
    assert files.paths.outbox.read_text(encoding="utf-8").count("## OUTBOX-") == 1
    assert "## HR-2026-04-29-001" in files.paths.requests.read_text(encoding="utf-8")


def test_api_notify_requires_token_when_configured(tmp_path) -> None:
    settings = _settings(tmp_path, local_notify_api_token="secret")
    client, _fake, _files = _client(tmp_path, settings=settings)

    missing = client.post("/api/notify", json=_payload(dedupe_key="auth:v1"))
    present = client.post(
        "/api/notify",
        json=_payload(dedupe_key="auth:v2"),
        headers={"Authorization": "Bearer secret"},
    )

    assert missing.status_code == 401
    assert present.status_code == 200
