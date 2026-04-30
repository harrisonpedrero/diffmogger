from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentic_notifier.config import Settings


@dataclass(frozen=True)
class TwilioSendResult:
    sent: bool
    dry_run: bool
    sid: str | None = None


@dataclass(frozen=True)
class ProviderSendError(RuntimeError):
    provider: str
    message: str
    code: str | None = None
    status: int | None = None

    def __str__(self) -> str:
        parts = [f"{self.provider} send failed"]
        if self.code:
            parts.append(f"code={self.code}")
        if self.status:
            parts.append(f"status={self.status}")
        parts.append(self.message)
        return ": ".join(parts)


def _friendly_twilio_message(code: str | None, fallback: str) -> str:
    if code == "30034":
        return (
            "Twilio rejected the message because the A2P 10DLC campaign is not ready "
            "or the sender is not registered for this route."
        )
    return fallback or "Twilio rejected the outbound message."


class TwilioNotifier:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self._client = client

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError("twilio package is required to send messages") from exc
        return Client(self.settings.twilio_account_sid, self.settings.twilio_auth_token)

    def send_message(self, body: str, *, dry_run: bool = False) -> TwilioSendResult:
        if dry_run:
            return TwilioSendResult(sent=False, dry_run=True)

        missing = [
            name
            for name, value in [
                ("TWILIO_ACCOUNT_SID", self.settings.twilio_account_sid),
                ("TWILIO_AUTH_TOKEN", self.settings.twilio_auth_token),
                ("HUMAN_TO", self.settings.human_to),
            ]
            if not value
        ]
        if not self.settings.twilio_messaging_service_sid and not self.settings.twilio_from:
            missing.append("TWILIO_MESSAGING_SERVICE_SID or TWILIO_FROM")
        if missing:
            raise RuntimeError(f"Missing Twilio configuration: {', '.join(missing)}")

        create_kwargs = {
            "body": body,
            "to": self.settings.human_to,
        }
        if self.settings.twilio_messaging_service_sid:
            create_kwargs["messaging_service_sid"] = self.settings.twilio_messaging_service_sid
        else:
            create_kwargs["from_"] = self.settings.twilio_from

        try:
            message = self._client_or_create().messages.create(**create_kwargs)
        except Exception as exc:
            try:
                from twilio.base.exceptions import TwilioRestException
            except ImportError:
                TwilioRestException = ()  # type: ignore[assignment]

            if TwilioRestException and isinstance(exc, TwilioRestException):
                code = str(getattr(exc, "code", "") or "") or None
                status = getattr(exc, "status", None)
                raise ProviderSendError(
                    provider="twilio",
                    code=code,
                    status=status if isinstance(status, int) else None,
                    message=_friendly_twilio_message(code, getattr(exc, "msg", "")),
                ) from exc
            raise
        return TwilioSendResult(sent=True, dry_run=False, sid=getattr(message, "sid", None))


def validate_twilio_signature(
    *,
    auth_token: str,
    url: str,
    params: dict[str, str],
    signature: str | None,
) -> bool:
    if not auth_token or not signature:
        return False
    try:
        from twilio.request_validator import RequestValidator
    except ImportError as exc:
        raise RuntimeError("twilio package is required to validate webhook signatures") from exc
    return bool(RequestValidator(auth_token).validate(url, params, signature))
