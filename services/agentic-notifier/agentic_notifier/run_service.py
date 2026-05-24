from __future__ import annotations

import asyncio

import uvicorn

from agentic_notifier.api_app import create_app
from agentic_notifier.config import load_settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.target_files import TargetFiles


async def _serve() -> None:
    settings = load_settings()
    files = TargetFiles.from_settings(settings) if settings.target_repo_configured else None
    app = create_app(
        settings=settings,
        files=files,
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
        "Apprise configured: "
        f"{settings.apprise_enabled}; routes: {len(settings.apprise_urls)}; "
        f"dry_run: {settings.dry_run}"
    )

    await api_server.serve()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
