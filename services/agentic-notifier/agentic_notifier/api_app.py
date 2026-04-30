from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException

from agentic_notifier.config import Settings, load_settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.formatter import format_notify_message, preview_message
from agentic_notifier.models import NotifyRequest, NotifyResponse
from agentic_notifier.target_files import TargetConfigError, TargetFiles
from agentic_notifier.twilio_client import ProviderSendError, TwilioNotifier


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _dedupe_key(request: NotifyRequest) -> str:
    return request.dedupe_key or f"{request.request_id}:{request.type}:{request.summary}"


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


def _provider_failure_detail(
    *,
    error_type: str,
    message: str,
    provider: str = "twilio",
    provider_error_code: str | None = None,
    provider_status: int | None = None,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "ok": False,
        "error_type": error_type,
        "provider": provider,
        "message": message,
    }
    if provider_error_code:
        detail["provider_error_code"] = provider_error_code
    if provider_status:
        detail["provider_status"] = provider_status
    if provider_error_code == "30034":
        detail["hint"] = (
            "Twilio error 30034 usually means the A2P 10DLC campaign is not ready "
            "or the sender is not registered for this route."
        )
    return detail


def create_app(
    *,
    settings: Settings | None = None,
    files: TargetFiles | None = None,
    notifier: TwilioNotifier | None = None,
    sent_store: JsonlDedupeStore | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    app_files = files
    app_notifier = notifier or TwilioNotifier(app_settings)
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
            "webhook_port": app_settings.webhook_port,
            "target_repo_configured": app_settings.target_repo_configured,
        }

    @app.post("/api/notify", response_model=NotifyResponse)
    def notify(
        request: NotifyRequest,
        authorization: str | None = Header(default=None),
    ) -> NotifyResponse:
        _authorize(app_settings, authorization)
        message = format_notify_message(request)
        key = _dedupe_key(request)

        target_files: TargetFiles
        try:
            target_files = app_files or TargetFiles.from_settings(app_settings)
            if request.expects_reply:
                target_files.upsert_active_request(request, message, dedupe_key=key)
        except TargetConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        effective_dry_run = app_settings.dry_run or request.dry_run
        if app_sent_store.contains(key):
            return NotifyResponse(
                ok=True,
                request_id=request.request_id,
                sent=False,
                dry_run=effective_dry_run,
                deduped=True,
                message_preview=preview_message(message),
            )

        try:
            result = app_notifier.send_message(message, dry_run=effective_dry_run)
            target_files.append_outbound_request(
                request,
                message,
                sent=result.sent,
                dry_run=result.dry_run,
                dedupe_key=key,
            )
            app_sent_store.record(
                key,
                {
                    "request_id": request.request_id,
                    "dry_run": result.dry_run,
                    "sent": result.sent,
                },
            )
        except ProviderSendError as exc:
            target_files.append_outbound_request(
                request,
                message,
                sent=False,
                dry_run=effective_dry_run,
                dedupe_key=key,
                status="PROVIDER_SEND_FAILED",
                provider_error_code=exc.code,
                provider_error_message=exc.message,
            )
            raise HTTPException(
                status_code=502,
                detail=_provider_failure_detail(
                    error_type="provider_send_failed",
                    message=exc.message,
                    provider=exc.provider,
                    provider_error_code=exc.code,
                    provider_status=exc.status,
                ),
            ) from exc
        except RuntimeError as exc:
            safe_message = str(exc)
            target_files.append_outbound_request(
                request,
                message,
                sent=False,
                dry_run=effective_dry_run,
                dedupe_key=key,
                status="PROVIDER_SEND_FAILED",
                provider_error_message=safe_message,
            )
            raise HTTPException(
                status_code=502,
                detail=_provider_failure_detail(
                    error_type="provider_config_error",
                    message=safe_message,
                ),
            ) from exc

        return NotifyResponse(
            ok=True,
            request_id=request.request_id,
            sent=result.sent,
            dry_run=result.dry_run,
            deduped=False,
            message_preview=preview_message(message),
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
