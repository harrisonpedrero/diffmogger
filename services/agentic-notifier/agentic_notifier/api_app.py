from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from agentic_notifier.apprise_adapter import send_with_apprise
from agentic_notifier.config import Settings, load_settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.formatter import (
    format_notify_message,
    preview_message,
)
from agentic_notifier.models import DeliveryStatus, NotifyRequest, NotifyResponse
from agentic_notifier.target_files import TargetConfigError, TargetFiles


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _dedupe_key(request: NotifyRequest) -> str:
    return request.dedupe_key or f"{request.request_id}:{request.type}:{request.event_kind}:{request.summary}"


def _authorize(settings: Settings, authorization: str | None) -> None:
    token = settings.local_notify_api_token
    if token:
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
        return

    if settings.notifier_api_host not in LOOPBACK_HOSTS:
        raise HTTPException(
            status_code=401,
            detail="LOCAL_NOTIFY_API_TOKEN is required when API host is not loopback",
        )


def _failure_status(deliveries: dict[str, DeliveryStatus]) -> str:
    if any(result.status == "APPRISE_SEND_FAILED" for result in deliveries.values()):
        return "APPRISE_SEND_FAILED"
    return "outbound_recorded"


def _delivery_json(deliveries: dict[str, DeliveryStatus]) -> dict[str, object]:
    return {name: result.model_dump() for name, result in deliveries.items()}


def create_app(
    *,
    settings: Settings | None = None,
    files: TargetFiles | None = None,
    sent_store: JsonlDedupeStore | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    app_files = files
    app_sent_store = sent_store or JsonlDedupeStore(
        app_settings.sent_notifications_path, "dedupe_key"
    )
    app = FastAPI(title="agentic-notifier-api")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "service": "agentic-notifier",
            "api_port": app_settings.notifier_api_port,
            "target_repo_configured": app_settings.target_repo_configured,
            "apprise_configured": app_settings.apprise_enabled,
            "apprise_route_count": len(app_settings.apprise_urls),
            "dry_run": app_settings.dry_run,
        }

    @app.post("/api/notify", response_model=NotifyResponse)
    async def notify(
        request: NotifyRequest,
        authorization: str | None = Header(default=None),
    ) -> NotifyResponse:
        _authorize(app_settings, authorization)
        message = format_notify_message(request)
        key = _dedupe_key(request)
        effective_dry_run = app_settings.dry_run or request.dry_run

        target_files: TargetFiles
        try:
            target_files = app_files or TargetFiles.from_settings(app_settings)
            if request.expects_reply:
                target_files.upsert_active_request(request, message, dedupe_key=key)
        except TargetConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if app_sent_store.contains(key):
            return NotifyResponse(
                ok=True,
                request_id=request.request_id,
                sent=False,
                dry_run=effective_dry_run,
                deduped=True,
                message_preview=preview_message(message),
                deliveries={},
            )

        deliveries: dict[str, DeliveryStatus] = {}
        deliveries["apprise"] = send_with_apprise(
            request,
            urls=list(app_settings.apprise_urls),
            message=message,
            dry_run=effective_dry_run,
        )

        sent = any(result.sent for result in deliveries.values())
        ok = all(result.ok for result in deliveries.values())
        status = _failure_status(deliveries) if not ok else "sent" if sent else "dry_run" if effective_dry_run else "outbound_recorded"
        target_files.append_outbound_request(
            request,
            message,
            sent=sent,
            dry_run=effective_dry_run,
            dedupe_key=key,
            status=status,
            delivery_error_code=status if not ok else None,
            delivery_error_message="; ".join(
                result.detail for result in deliveries.values() if not result.ok and result.detail
            ) or None,
            delivery_results=_delivery_json(deliveries),
        )
        app_sent_store.record(
            key,
            {
                "request_id": request.request_id,
                "dry_run": effective_dry_run,
                "sent": sent,
                "event_kind": request.event_kind,
            },
        )

        return NotifyResponse(
            ok=ok,
            request_id=request.request_id,
            sent=sent,
            dry_run=effective_dry_run,
            deduped=False,
            message_preview=preview_message(message),
            deliveries=deliveries,
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.notifier_api_host,
        port=settings.notifier_api_port,
    )


if __name__ == "__main__":
    main()
