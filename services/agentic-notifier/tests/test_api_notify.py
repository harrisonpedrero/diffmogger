from fastapi.testclient import TestClient

from agentic_notifier.api_app import create_app
from agentic_notifier.config import Settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.target_files import TargetFiles


def _settings(tmp_path, **overrides) -> Settings:
    target = tmp_path / "target"
    values = {
        "apprise_urls": ("json://127.0.0.1:9",),
        "target_repo_dir": target,
        "target_human_inbox_path": target / "docs" / "HUMAN_INBOX.md",
        "target_human_requests_path": target / "docs" / "HUMAN_REQUESTS.md",
        "target_human_outbox_path": target / "docs" / "HUMAN_OUTBOX.md",
        "target_human_archive_path": target / "docs" / "HUMAN_RESPONSES_ARCHIVE.md",
        "runtime_dir": tmp_path / "runtime",
        "dry_run": True,
    }
    values.update(overrides)
    return Settings(**values)


def _client(tmp_path, *, settings: Settings | None = None) -> tuple[TestClient, TargetFiles]:
    settings = settings or _settings(tmp_path)
    files = TargetFiles.from_settings(settings)
    store = JsonlDedupeStore(settings.sent_notifications_path, "dedupe_key")
    return TestClient(create_app(settings=settings, files=files, sent_store=store)), files


def _payload(**overrides):
    payload = {
        "request_id": "REQ-1",
        "type": "human_requested_summary",
        "priority": "normal",
        "summary": "Progress requested",
        "event_kind": "message",
        "message_body": "Here is the update.",
        "minimum_user_action": "None.",
        "reply_format": "Optional follow-up.",
        "expects_reply": False,
        "dedupe_key": "req-1:v1",
        "dry_run": True,
    }
    payload.update(overrides)
    return payload


def test_api_notify_records_apprise_dry_run(tmp_path) -> None:
    client, files = _client(tmp_path)

    response = client.post("/api/notify", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["dry_run"] is True
    assert body["deliveries"]["apprise"]["status"] == "dry_run"
    assert "Progress requested" in files.paths.outbox.read_text(encoding="utf-8")


def test_api_notify_dedupes_after_first_record(tmp_path) -> None:
    client, _files = _client(tmp_path)

    first = client.post("/api/notify", json=_payload())
    second = client.post("/api/notify", json=_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert second.json()["sent"] is False


def test_api_notify_requires_token_when_configured(tmp_path) -> None:
    settings = _settings(tmp_path, local_notify_api_token="secret")
    client, _files = _client(tmp_path, settings=settings)

    assert client.post("/api/notify", json=_payload(dedupe_key="token:v1")).status_code == 401
    ok = client.post(
        "/api/notify",
        json=_payload(dedupe_key="token:v2"),
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status_code == 200


def test_health_reports_apprise_routes(tmp_path) -> None:
    client, _files = _client(tmp_path)

    body = client.get("/health").json()

    assert body["apprise_configured"] is True
    assert body["apprise_route_count"] == 1
