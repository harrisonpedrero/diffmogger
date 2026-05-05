from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agentic_notifier.config import Settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.formatter import extract_request_id
from agentic_notifier.target_files import TargetFiles


class DiscordSendError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscordSendResult:
    sent: bool
    dry_run: bool
    status: str
    detail: str = ""


def should_capture_discord_message(
    *,
    channel_id: int,
    messaging_channel_id: int | None,
    author_is_bot: bool,
    mentioned_bot: bool,
    replied_to_bot: bool,
) -> bool:
    return bool(
        messaging_channel_id
        and channel_id == messaging_channel_id
        and not author_is_bot
        and (mentioned_bot or replied_to_bot)
    )


class DryRunDiscordNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sent: list[tuple[str, str]] = []

    def can_send(self, event_kind: str) -> bool:
        if not self.settings.discord_enabled:
            return False
        return event_kind in {"progress", "message"}

    async def send(self, event_kind: str, message: str, *, dry_run: bool) -> DiscordSendResult:
        if not self.can_send(event_kind):
            raise DiscordSendError(f"Discord is not configured for {event_kind} notifications")
        self.sent.append((event_kind, message))
        return DiscordSendResult(sent=not dry_run, dry_run=dry_run, status="dry_run" if dry_run else "sent")


class DiscordBotBridge:
    def __init__(
        self,
        settings: Settings,
        *,
        files: TargetFiles,
        inbound_store: JsonlDedupeStore,
    ) -> None:
        self.settings = settings
        self.files = files
        self.inbound_store = inbound_store
        self._discord: Any | None = None
        self.client: Any | None = None

    def can_send(self, event_kind: str) -> bool:
        if not self.settings.discord_enabled:
            return False
        if event_kind == "progress":
            return bool(self.settings.discord_progress_channel_id)
        if event_kind == "message":
            return bool(self.settings.discord_messaging_channel_id)
        return False

    def configured(self) -> bool:
        return self.settings.discord_enabled

    def build_client(self) -> Any:
        if self.client is not None:
            return self.client
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError(
                "discord.py is not installed. Run `python -m pip install -r requirements.txt` "
                "inside services/agentic-notifier."
            ) from exc

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._discord = discord
        self.client = client

        @client.event
        async def on_ready() -> None:
            user = getattr(client, "user", None)
            print(f"Discord notifier connected as {user}")

        @client.event
        async def on_message(message: Any) -> None:
            await self._handle_message(message)

        return client

    async def start(self) -> None:
        if not self.settings.discord_bot_token:
            return
        client = self.build_client()
        await client.start(self.settings.discord_bot_token)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()

    async def send(self, event_kind: str, message: str, *, dry_run: bool) -> DiscordSendResult:
        if not self.can_send(event_kind):
            raise DiscordSendError(f"Discord is not configured for {event_kind} notifications")
        if dry_run:
            return DiscordSendResult(sent=False, dry_run=True, status="dry_run")
        client = self.build_client()
        try:
            await asyncio.wait_for(client.wait_until_ready(), timeout=10)
            channel_id = (
                self.settings.discord_progress_channel_id
                if event_kind == "progress"
                else self.settings.discord_messaging_channel_id
            )
            channel = client.get_channel(channel_id)
            if channel is None:
                channel = await client.fetch_channel(channel_id)
            await channel.send(message)
        except Exception as exc:
            raise DiscordSendError(str(exc)) from exc
        return DiscordSendResult(sent=True, dry_run=False, status="sent")

    async def _handle_message(self, message: Any) -> None:
        client = self.client
        bot_user = getattr(client, "user", None) if client is not None else None
        bot_id = getattr(bot_user, "id", None)
        if bot_id is None:
            return

        replied_to_bot = await self._message_replies_to_bot(message, bot_id)
        mentioned_bot = any(getattr(user, "id", None) == bot_id for user in getattr(message, "mentions", []))
        if not should_capture_discord_message(
            channel_id=int(getattr(getattr(message, "channel", None), "id", 0) or 0),
            messaging_channel_id=self.settings.discord_messaging_channel_id,
            author_is_bot=bool(getattr(getattr(message, "author", None), "bot", False)),
            mentioned_bot=mentioned_bot,
            replied_to_bot=replied_to_bot,
        ):
            return

        message_id = str(getattr(message, "id", ""))
        if not message_id:
            return
        if not self.inbound_store.record(
            message_id,
            {
                "channel_id": str(getattr(message.channel, "id", "")),
                "author_id": str(getattr(message.author, "id", "")),
            },
        ):
            return

        body = str(getattr(message, "content", "") or "").strip()
        self.files.append_discord_inbound_message(
            author_name=str(getattr(message.author, "display_name", None) or getattr(message.author, "name", "unknown")),
            author_id=str(getattr(message.author, "id", "unknown")),
            channel_id=str(getattr(message.channel, "id", "unknown")),
            message_id=message_id,
            body=body,
            request_id=extract_request_id(body),
            capture_reason="mention" if mentioned_bot else "reply",
            received_at=datetime.now(timezone.utc),
        )

    async def _message_replies_to_bot(self, message: Any, bot_id: int) -> bool:
        reference = getattr(message, "reference", None)
        if reference is None or not getattr(reference, "message_id", None):
            return False
        resolved = getattr(reference, "resolved", None)
        if resolved is not None:
            return getattr(getattr(resolved, "author", None), "id", None) == bot_id
        try:
            fetched = await message.channel.fetch_message(reference.message_id)
        except Exception:
            return False
        return getattr(getattr(fetched, "author", None), "id", None) == bot_id
