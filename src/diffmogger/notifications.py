"""Apprise notification adapter for local Diffmogger messages."""

from __future__ import annotations

from typing import Any

import apprise

from diffmogger.contracts import NotificationDelivery, NotificationPayload


def send_notification(payload: NotificationPayload) -> NotificationDelivery:
    if payload.dry_run:
        return NotificationDelivery(
            ok=True,
            sent=False,
            dry_run=True,
            status="dry_run",
            detail="Apprise delivery skipped by dry_run.",
            message_id=payload.message_id,
        )

    app = apprise.Apprise()
    for url in payload.apprise_urls:
        app.add(url)
    if not payload.apprise_urls:
        return NotificationDelivery(
            ok=True,
            sent=False,
            dry_run=False,
            status="no_routes",
            detail="No Apprise URLs configured.",
            message_id=payload.message_id,
        )
    sent = bool(app.notify(body=payload.body, title=payload.title))
    return NotificationDelivery(
        ok=sent,
        sent=sent,
        dry_run=False,
        status="sent" if sent else "apprise_send_failed",
        detail="Delivered through Apprise." if sent else "Apprise returned false.",
        message_id=payload.message_id,
    )


def payload_from_mapping(data: dict[str, Any]) -> NotificationPayload:
    return NotificationPayload.model_validate(data)
