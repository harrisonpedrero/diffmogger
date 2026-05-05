from __future__ import annotations

import asyncio

import uvicorn

from agentic_notifier.api_app import create_app
from agentic_notifier.config import load_settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.discord_bot import DiscordBotBridge, DryRunDiscordNotifier
from agentic_notifier.target_files import TargetFiles


async def _serve() -> None:
    settings = load_settings()
    files = TargetFiles.from_settings(settings) if settings.target_repo_configured else None
    inbound_store = JsonlDedupeStore(settings.inbound_message_ids_path, "discord_message_id")
    discord_sender = (
        DiscordBotBridge(settings, files=files, inbound_store=inbound_store)
        if settings.discord_enabled and not settings.dry_run and files is not None
        else DryRunDiscordNotifier(settings)
    )
    app = create_app(
        settings=settings,
        files=files,
        discord_sender=discord_sender,
        sent_store=JsonlDedupeStore(settings.sent_notifications_path, "dedupe_key"),
    )
    api_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.notifier_api_host,
            port=settings.notifier_api_port,
            log_level="info",
        )
    )

    print(
        f"Starting local API at http://{settings.notifier_api_host}:{settings.notifier_api_port}"
    )
    print(
        "Discord configured: "
        f"{settings.discord_enabled}; local notifications enabled: {settings.local_notifications_enabled}; "
        f"dry_run: {settings.dry_run}"
    )

    tasks = [asyncio.create_task(api_server.serve())]
    if isinstance(discord_sender, DiscordBotBridge):
        tasks.append(asyncio.create_task(discord_sender.start()))
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        if isinstance(discord_sender, DiscordBotBridge):
            await discord_sender.close()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
