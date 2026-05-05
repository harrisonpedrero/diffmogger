from agentic_notifier.dedupe import JsonlDedupeStore


def test_jsonl_dedupe_records_once(tmp_path) -> None:
    store = JsonlDedupeStore(tmp_path / "runtime" / "sent.jsonl", "dedupe_key")

    assert not store.contains("HR-001:v1")
    assert store.record("HR-001:v1", {"request_id": "HR-001"})
    assert store.contains("HR-001:v1")
    assert not store.record("HR-001:v1", {"request_id": "HR-001"})


def test_jsonl_dedupe_ignores_malformed_lines(tmp_path) -> None:
    path = tmp_path / "runtime" / "inbound.jsonl"
    path.parent.mkdir()
    path.write_text("not-json\n{\"discord_message_id\":\"DM1\"}\n", encoding="utf-8")
    store = JsonlDedupeStore(path, "discord_message_id")

    assert store.contains("DM1")
    assert not store.contains("DM2")
