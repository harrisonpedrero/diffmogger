from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from agentic_notifier.config import Settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.target_files import TargetFiles
from agentic_notifier.webhook_app import create_app


def _settings(tmp_path, **overrides) -> Settings:
    target = tmp_path / "target"
    values = {
        "twilio_auth_token": "test-token",
        "target_repo_dir": target,
        "target_human_inbox_path": target / "docs" / "HUMAN_INBOX.md",
        "target_human_requests_path": target / "docs" / "HUMAN_REQUESTS.md",
        "target_human_outbox_path": target / "docs" / "HUMAN_OUTBOX.md",
        "target_human_archive_path": target / "docs" / "HUMAN_RESPONSES_ARCHIVE.md",
        "runtime_dir": tmp_path / "runtime",
    }
    values.update(overrides)
    return Settings(**values)


def _client(tmp_path, settings: Settings | None = None):
    settings = settings or _settings(tmp_path)
    files = TargetFiles.from_settings(settings)
    store = JsonlDedupeStore(tmp_path / "runtime" / "inbound.jsonl", "message_sid")
    app = create_app(settings=settings, files=files, inbound_store=store)
    return TestClient(app), files


def _form(message_sid: str = "SM123") -> dict[str, str]:
    return {
        "From": "+15555555555",
        "To": "+15555550000",
        "Body": "HR-001 DONE. Key added locally.",
        "MessageSid": message_sid,
    }


def test_webhook_inbound_bypass_appends_and_dedupes(tmp_path) -> None:
    client, files = _client(tmp_path)

    first = client.post(
        "/twilio/inbound",
        data=_form(),
        headers={"X-Agentic-Notifier-Test-Bypass": "true"},
    )
    second = client.post(
        "/twilio/inbound",
        data=_form(),
        headers={"X-Agentic-Notifier-Test-Bypass": "true"},
    )

    assert first.status_code == 200
    assert first.text == "<Response></Response>"
    assert second.status_code == 200
    inbox = files.paths.inbox.read_text(encoding="utf-8")
    assert inbox.count("## INBOX-") == 1
    assert "- parsed_intent: done" in inbox
    assert "- message_sid: SM123" in inbox


def test_webhook_inbound_accepts_signed_request(tmp_path) -> None:
    client, files = _client(tmp_path)
    params = _form("SM-SIGNED")
    signature = RequestValidator("test-token").compute_signature(
        "http://testserver/twilio/inbound",
        params,
    )

    response = client.post(
        "/twilio/inbound",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )

    assert response.status_code == 200
    assert "SM-SIGNED" in files.paths.inbox.read_text(encoding="utf-8")


def test_webhook_inbound_accepts_public_base_url_signature(tmp_path) -> None:
    settings = _settings(
        tmp_path,
        webhook_public_base_url="https://notifier.ngrok-free.app/",
    )
    client, files = _client(tmp_path, settings)
    params = _form("SM-PUBLIC")
    signature = RequestValidator("test-token").compute_signature(
        "https://notifier.ngrok-free.app/twilio/inbound",
        params,
    )

    response = client.post(
        "/twilio/inbound",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )

    assert response.status_code == 200
    assert "SM-PUBLIC" in files.paths.inbox.read_text(encoding="utf-8")


def test_webhook_inbound_public_base_url_rejects_local_request_url_signature(
    tmp_path,
) -> None:
    settings = _settings(
        tmp_path,
        webhook_public_base_url="https://notifier.ngrok-free.app",
    )
    client, _files = _client(tmp_path, settings)
    params = _form("SM-LOCAL-URL")
    signature = RequestValidator("test-token").compute_signature(
        "http://testserver/twilio/inbound",
        params,
    )

    response = client.post(
        "/twilio/inbound",
        data=params,
        headers={"X-Twilio-Signature": signature},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid Twilio signature"


def test_webhook_inbound_preserves_query_string_in_validation_url(tmp_path) -> None:
    settings = _settings(
        tmp_path,
        webhook_public_base_url="https://notifier.ngrok-free.app",
    )
    client, files = _client(tmp_path, settings)
    params = _form("SM-QUERY")
    path = "/twilio/inbound?foo=bar&empty=&encoded=a%20b"
    signature = RequestValidator("test-token").compute_signature(
        f"https://notifier.ngrok-free.app{path}",
        params,
    )

    response = client.post(
        path,
        data=params,
        headers={"X-Twilio-Signature": signature},
    )

    assert response.status_code == 200
    assert "SM-QUERY" in files.paths.inbox.read_text(encoding="utf-8")


def test_webhook_inbound_passes_form_params_to_signature_validator(
    tmp_path,
    monkeypatch,
) -> None:
    captured = {}

    def fake_validate_twilio_signature(*, auth_token, url, params, signature):
        captured["auth_token"] = auth_token
        captured["url"] = url
        captured["params"] = params
        captured["signature"] = signature
        return True

    monkeypatch.setattr(
        "agentic_notifier.webhook_app.validate_twilio_signature",
        fake_validate_twilio_signature,
    )
    client, files = _client(tmp_path)
    params = _form("SM-FORM")
    params["Body"] = "HR-001 DONE. Key=alpha+beta & verified."
    params["NumMedia"] = "0"

    response = client.post(
        "/twilio/inbound",
        data=params,
        headers={"X-Twilio-Signature": "present"},
    )

    assert response.status_code == 200
    assert captured == {
        "auth_token": "test-token",
        "url": "http://testserver/twilio/inbound",
        "params": params,
        "signature": "present",
    }
    assert "SM-FORM" in files.paths.inbox.read_text(encoding="utf-8")


def test_webhook_inbound_rejects_bad_signature(tmp_path) -> None:
    client, _files = _client(tmp_path)

    response = client.post(
        "/twilio/inbound",
        data=_form("SM-BAD"),
        headers={"X-Twilio-Signature": "bad"},
    )

    assert response.status_code == 403
