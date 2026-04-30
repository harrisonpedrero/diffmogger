from __future__ import annotations

import asyncio

import uvicorn

from agentic_notifier.api_app import create_app as create_api_app
from agentic_notifier.config import load_settings
from agentic_notifier.webhook_app import create_app as create_webhook_app


async def _serve() -> None:
    settings = load_settings()
    api_server = uvicorn.Server(
        uvicorn.Config(
            create_api_app(settings=settings),
            host=settings.notifier_api_host,
            port=settings.notifier_api_port,
            log_level="info",
        )
    )
    webhook_server = uvicorn.Server(
        uvicorn.Config(
            create_webhook_app(settings=settings),
            host=settings.webhook_host,
            port=settings.webhook_port,
            log_level="info",
        )
    )

    print(
        f"Starting local API at http://{settings.notifier_api_host}:{settings.notifier_api_port}"
    )
    print(
        f"Starting Twilio webhook receiver at http://{settings.webhook_host}:{settings.webhook_port}"
    )
    await asyncio.gather(api_server.serve(), webhook_server.serve())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()

