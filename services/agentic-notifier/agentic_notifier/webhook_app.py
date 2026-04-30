from __future__ import annotations

import hashlib
import logging
import os
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from agentic_notifier.config import Settings, load_settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.parser import parse_reply
from agentic_notifier.target_files import TargetConfigError, TargetFiles
from agentic_notifier.twilio_client import validate_twilio_signature


TWIML_EMPTY_RESPONSE = "<Response></Response>"
logger = logging.getLogger(__name__)


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def _test_bypass_allowed(settings: Settings) -> bool:
    return settings.test_mode or _running_under_pytest()


def _channel(from_value: str, to_value: str, wa_id: str | None) -> str:
    if wa_id or from_value.startswith("whatsapp:") or to_value.startswith("whatsapp:"):
        return "whatsapp"
    return "sms"


def _validation_url(settings: Settings, request: Request) -> str:
    suffix = request.url.path
    if request.url.query:
        suffix += f"?{request.url.query}"
    if settings.webhook_public_base_url:
        return settings.webhook_public_base_url.rstrip("/") + suffix

    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_proto and forwarded_host:
        return f"{forwarded_proto}://{forwarded_host}{suffix}"
    return str(request.url)


async def _read_form_params(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: str(value) for key, value in form.items()}


def _fallback_message_sid(params: dict[str, str]) -> str:
    body = "|".join([params.get("From", ""), params.get("To", ""), params.get("Body", "")])
    return "NO-SID-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def create_app(
    *,
    settings: Settings | None = None,
    files: TargetFiles | None = None,
    inbound_store: JsonlDedupeStore | None = None,
) -> FastAPI:
    app_settings = settings or load_settings()
    app_files = files
    app_inbound_store = inbound_store or JsonlDedupeStore(
        app_settings.inbound_message_sids_path, "message_sid"
    )
    app = FastAPI(title="agentic-notifier-webhook")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "service": "agentic-notifier",
            "api_port": app_settings.notifier_api_port,
            "webhook_port": app_settings.webhook_port,
            "target_repo_configured": app_settings.target_repo_configured,
        }

    @app.post("/twilio/inbound")
    async def twilio_inbound(request: Request) -> Response:
        params = await _read_form_params(request)
        bypass_requested = request.headers.get("X-Agentic-Notifier-Test-Bypass", "")
        if bypass_requested.strip().lower() in {"1", "true", "yes"}:
            if not _test_bypass_allowed(app_settings):
                raise HTTPException(status_code=403, detail="Test bypass is not enabled")
        else:
            signature = request.headers.get("X-Twilio-Signature")
            validation_url = _validation_url(app_settings, request)
            logger.debug(
                "Twilio inbound signature validation: validation_url=%s request_path=%s "
                "form_keys=%s signature_present=%s",
                validation_url,
                request.url.path,
                sorted(params.keys()),
                bool(signature),
            )
            if not validate_twilio_signature(
                auth_token=app_settings.twilio_auth_token,
                url=validation_url,
                params=params,
                signature=signature,
            ):
                raise HTTPException(status_code=403, detail="Invalid Twilio signature")

        message_sid = params.get("MessageSid") or _fallback_message_sid(params)
        if app_inbound_store.contains(message_sid):
            return Response(TWIML_EMPTY_RESPONSE, media_type="application/xml")

        body = params.get("Body", "")
        parsed = parse_reply(body)
        from_value = params.get("From", "")
        to_value = params.get("To", "")
        wa_id = params.get("WaId") or None
        channel = _channel(from_value, to_value, wa_id)

        try:
            target_files = app_files or TargetFiles.from_settings(app_settings)
            target_files.append_inbound_message(
                from_value=from_value,
                to_value=to_value,
                body=body,
                message_sid=message_sid,
                wa_id=wa_id,
                request_id=parsed.request_id,
                parsed_intent=parsed.parsed_intent,
                channel=channel,
            )
        except TargetConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        app_inbound_store.record(
            message_sid,
            {
                "request_id": parsed.request_id,
                "parsed_intent": parsed.parsed_intent,
                "channel": channel,
            },
        )
        return Response(TWIML_EMPTY_RESPONSE, media_type="application/xml")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.webhook_host,
        port=settings.webhook_port,
    )


if __name__ == "__main__":
    main()
