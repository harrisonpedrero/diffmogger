from agentic_notifier.discord_bot import should_capture_discord_message


def test_capture_discord_mentions_and_replies_in_messaging_channel() -> None:
    assert should_capture_discord_message(
        channel_id=222,
        messaging_channel_id=222,
        author_is_bot=False,
        mentioned_bot=True,
        replied_to_bot=False,
    )
    assert should_capture_discord_message(
        channel_id=222,
        messaging_channel_id=222,
        author_is_bot=False,
        mentioned_bot=False,
        replied_to_bot=True,
    )


def test_ignore_unrelated_discord_messages() -> None:
    assert not should_capture_discord_message(
        channel_id=222,
        messaging_channel_id=222,
        author_is_bot=False,
        mentioned_bot=False,
        replied_to_bot=False,
    )
    assert not should_capture_discord_message(
        channel_id=111,
        messaging_channel_id=222,
        author_is_bot=False,
        mentioned_bot=True,
        replied_to_bot=False,
    )
    assert not should_capture_discord_message(
        channel_id=222,
        messaging_channel_id=222,
        author_is_bot=True,
        mentioned_bot=True,
        replied_to_bot=False,
    )
