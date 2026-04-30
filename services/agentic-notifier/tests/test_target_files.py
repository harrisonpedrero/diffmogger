from datetime import datetime, timezone

from agentic_notifier.config import Settings
from agentic_notifier.models import NotifyRequest
from agentic_notifier.target_files import TargetFiles


def _settings(tmp_path) -> Settings:
    target = tmp_path / "target"
    return Settings(
        target_repo_dir=target,
        target_human_inbox_path=target / "docs" / "HUMAN_INBOX.md",
        target_human_requests_path=target / "docs" / "HUMAN_REQUESTS.md",
        target_human_outbox_path=target / "docs" / "HUMAN_OUTBOX.md",
        target_human_archive_path=target / "docs" / "HUMAN_RESPONSES_ARCHIVE.md",
        target_queue_dir=target / "queue",
        runtime_dir=tmp_path / "runtime",
        dry_run=True,
    )


def _notify(summary: str = "Add Service X read-only API key") -> NotifyRequest:
    return NotifyRequest(
        request_id="HR-2026-04-29-001",
        type="api_key_setup",
        priority="unlocking",
        summary=summary,
        context="Unlocks the next source adapter.",
        agent_recommendation="Use read-only data access.",
        minimum_user_action="Add SERVICE_X_API_KEY locally.",
        reply_format="HR-001 DONE or HR-001 SKIP",
        dedupe_key="HR-2026-04-29-001:v1",
    )


def test_append_inbound_message_creates_markdown_entry(tmp_path) -> None:
    files = TargetFiles.from_settings(_settings(tmp_path))
    received_at = datetime(2026, 4, 29, 1, 23, 45, tzinfo=timezone.utc)

    inbox_id = files.append_inbound_message(
        from_value="+15555555555",
        to_value="+15555550000",
        body="HR-001 DONE. Key added locally.",
        message_sid="SM123",
        wa_id=None,
        request_id="HR-001",
        parsed_intent="done",
        channel="sms",
        received_at=received_at,
    )

    assert inbox_id == "INBOX-2026-04-29-001"
    inbox = files.paths.inbox.read_text(encoding="utf-8")
    assert "## INBOX-2026-04-29-001" in inbox
    assert "- parsed_intent: done" in inbox
    assert "HR-001 DONE. Key added locally." in inbox


def test_upsert_active_request_replaces_existing_entry(tmp_path) -> None:
    files = TargetFiles.from_settings(_settings(tmp_path))

    files.upsert_active_request(_notify("First summary"), "Message one", dedupe_key="HR:v1")
    files.upsert_active_request(_notify("Updated summary"), "Message two", dedupe_key="HR:v1")

    requests = files.paths.requests.read_text(encoding="utf-8")
    assert requests.count("## HR-2026-04-29-001") == 1
    assert "Updated summary" in requests
    assert "First summary" not in requests


def test_append_outbound_request_records_dry_run(tmp_path) -> None:
    files = TargetFiles.from_settings(_settings(tmp_path))

    files.append_outbound_request(
        _notify(),
        "Need input: HR-001",
        sent=False,
        dry_run=True,
        dedupe_key="HR-2026-04-29-001:v1",
    )

    outbox = files.paths.outbox.read_text(encoding="utf-8")
    assert "- dry_run: true" in outbox
    assert "- sent: false" in outbox
    assert "Need input: HR-001" in outbox


def test_optional_jsonl_queues_are_written(tmp_path) -> None:
    files = TargetFiles.from_settings(_settings(tmp_path))

    files.upsert_active_request(_notify(), "Need input: HR-001", dedupe_key="HR:v1")
    files.append_outbound_request(
        _notify(),
        "Need input: HR-001",
        sent=False,
        dry_run=True,
        dedupe_key="HR:v1",
    )
    files.append_inbound_message(
        from_value="+15555555555",
        to_value="+15555550000",
        body="DONE HR-001",
        message_sid="SMJSONL",
        wa_id=None,
        request_id="HR-001",
        parsed_intent="done",
        channel="sms",
    )

    assert (files.paths.queue_dir / "human_requests.jsonl").exists()
    assert (files.paths.queue_dir / "human_outbox.jsonl").exists()
    responses = (files.paths.queue_dir / "human_responses.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"message_sid": "SMJSONL"' in responses
