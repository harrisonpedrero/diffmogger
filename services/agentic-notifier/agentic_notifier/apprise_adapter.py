from __future__ import annotations

import apprise

from agentic_notifier.models import DeliveryStatus, NotifyRequest


def apprise_urls_from_env(raw: str) -> list[str]:
    return [line.strip() for line in raw.replace(",", "\n").splitlines() if line.strip()]


def send_with_apprise(
    request: NotifyRequest,
    *,
    urls: list[str],
    message: str,
    dry_run: bool,
) -> DeliveryStatus:
    if dry_run:
        return DeliveryStatus(
            enabled=True,
            ok=True,
            sent=False,
            dry_run=True,
            status="dry_run",
            detail="Apprise delivery skipped by dry-run mode.",
        )
    if not urls:
        return DeliveryStatus(
            enabled=False,
            ok=True,
            sent=False,
            dry_run=False,
            status="no_routes",
            detail="No APPRISE_URLS configured.",
        )
    app = apprise.Apprise()
    for url in urls:
        app.add(url)
    sent = bool(app.notify(body=message, title=request.summary))
    return DeliveryStatus(
        enabled=True,
        ok=sent,
        sent=sent,
        dry_run=False,
        status="sent" if sent else "APPRISE_SEND_FAILED",
        detail="Delivered through Apprise." if sent else "Apprise returned false.",
    )
