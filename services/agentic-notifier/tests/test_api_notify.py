from fastapi.testclient import TestClient

from agentic_notifier.api_app import create_app
from agentic_notifier.config import Settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.target_files import TargetFiles
from agentic_notifier.twilio_client import ProviderSendError, TwilioSendResult


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def send_message(self, body: str, *, dry_run: bool = False) -> TwilioSendResult:
        self.calls.append((body, dry_run))
        return TwilioSendResult(sent=not dry_run, dry_run=dry_run, sid="SMFAKE")


class ProviderFailingNotifier:
    def send_message(self, body: str, *, dry_run: bool = False) -> TwilioSendResult:
        raise ProviderSendError(
            provider="twilio",
            code="30034",
            status=400,
            message="Twilio rejected the message because the A2P 10DLC campaign is not ready or the sender is not registered for this route.",
        )


class ConfigFailingNotifier:
    def send_message(self, body: str, *, dry_run: bool = False) -> TwilioSendResult:
        raise RuntimeError("Missing Twilio configuration: TWILIO_ACCOUNT_SID")


def _settings(tmp_path, **overrides) -> Settings:
    target = tmp_path / "target"
    values = {
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
        "context": "Unlocks the next source adapter.",
        "agent_recommendation": "Use read-only/data-only access. Do not add trading or write permissions.",
        "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
        "reply_format": "HR-001 DONE or HR-001 SKIP",
        "unblocked_work_remaining": ["Continue fixture-based work"],
        "dedupe_key": "HR-2026-04-29-001:v1",
        "dry_run": True,
    }
    payload.update(overrides)
    return payload


def _client(tmp_path, settings: Settings | None = None, fake: FakeNotifier | None = None):
    settings = settings or _settings(tmp_path)
    fake = fake or FakeNotifier()
    files = TargetFiles.from_settings(settings)
    store = JsonlDedupeStore(tmp_path / "runtime" / "sent.jsonl", "dedupe_key")
    app = create_app(settings=settings, files=files, notifier=fake, sent_store=store)
    return TestClient(app), fake, files


def test_api_notify_dry_run_writes_markdown_and_dedupes(tmp_path) -> None:
    client, fake, files = _client(tmp_path)

    first = client.post("/api/notify", json=_payload())
    second = client.post("/api/notify", json=_payload())

    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json()["sent"] is False
    assert first.json()["dry_run"] is True
    assert first.json()["deduped"] is False
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert len(fake.calls) == 1
    assert files.paths.outbox.read_text(encoding="utf-8").count("## OUTBOX-") == 1
    assert "## HR-2026-04-29-001" in files.paths.requests.read_text(encoding="utf-8")


def test_api_notify_fake_twilio_send_when_not_dry_run(tmp_path) -> None:
    settings = _settings(tmp_path, dry_run=False)
    client, fake, _files = _client(tmp_path, settings=settings)

    response = client.post("/api/notify", json=_payload(dry_run=False, dedupe_key="HR:v2"))

    assert response.status_code == 200
    assert response.json()["sent"] is True
    assert fake.calls[0][1] is False


def test_api_notify_direct_message_does_not_create_active_request(tmp_path) -> None:
    client, fake, files = _client(tmp_path)

    response = client.post(
        "/api/notify",
        json=_payload(
            request_id="MSG-2026-04-29-001",
            type="human_requested_summary",
            priority="normal",
            summary="Progress summary requested by human",
            message_body="Project update: Built the report view and added tests. Current blocker: none.",
            minimum_user_action="None.",
            reply_format="Optional follow-up request.",
            expects_reply=False,
            dedupe_key="MSG-2026-04-29-001:v1",
        ),
    )

    assert response.status_code == 200
    assert response.json()["message_preview"].startswith("Project update:")
    assert fake.calls[0][0].startswith("Project update:")
    assert "## MSG-2026-04-29-001" not in files.paths.requests.read_text(
        encoding="utf-8"
    )
    assert "## OUTBOX-" in files.paths.outbox.read_text(encoding="utf-8")


def test_api_notify_requires_token_when_configured(tmp_path) -> None:
    settings = _settings(tmp_path, local_notify_api_token="secret")
    client, _fake, _files = _client(tmp_path, settings=settings)

    missing = client.post("/api/notify", json=_payload())
    present = client.post(
        "/api/notify",
        json=_payload(dedupe_key="HR:v3"),
        headers={"Authorization": "Bearer secret"},
    )

    assert missing.status_code == 401
    assert present.status_code == 200


def test_api_notify_validates_payload(tmp_path) -> None:
    client, _fake, _files = _client(tmp_path)
    payload = _payload()
    payload.pop("request_id")

    response = client.post("/api/notify", json=payload)

    assert response.status_code == 422


def test_api_notify_provider_failure_returns_structured_json_and_outbox(tmp_path) -> None:
    settings = _settings(tmp_path, dry_run=False)
    files = TargetFiles.from_settings(settings)
    store = JsonlDedupeStore(tmp_path / "runtime" / "sent.jsonl", "dedupe_key")
    app = create_app(
        settings=settings,
        files=files,
        notifier=ProviderFailingNotifier(),
        sent_store=store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/notify",
        json=_payload(dry_run=False, dedupe_key="HR:provider-failure"),
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["ok"] is False
    assert detail["error_type"] == "provider_send_failed"
    assert detail["provider_error_code"] == "30034"
    assert "A2P 10DLC" in detail["hint"]

    outbox = files.paths.outbox.read_text(encoding="utf-8")
    assert "- status: PROVIDER_SEND_FAILED" in outbox
    assert "- provider_error_code: 30034" in outbox
    assert "TWILIO_AUTH_TOKEN" not in outbox


def test_api_notify_config_failure_returns_structured_json_and_outbox(tmp_path) -> None:
    settings = _settings(tmp_path, dry_run=False)
    files = TargetFiles.from_settings(settings)
    store = JsonlDedupeStore(tmp_path / "runtime" / "sent.jsonl", "dedupe_key")
    app = create_app(
        settings=settings,
        files=files,
        notifier=ConfigFailingNotifier(),
        sent_store=store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/notify",
        json=_payload(dry_run=False, dedupe_key="HR:config-failure"),
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["ok"] is False
    assert detail["error_type"] == "provider_config_error"

    outbox = files.paths.outbox.read_text(encoding="utf-8")
    assert "- status: PROVIDER_SEND_FAILED" in outbox
    assert "Missing Twilio configuration: TWILIO_ACCOUNT_SID" in outbox
