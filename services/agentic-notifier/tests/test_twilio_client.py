import pytest

from agentic_notifier.config import Settings
from agentic_notifier.twilio_client import ProviderSendError, TwilioNotifier


class FakeMessages:
    def __init__(self, exc: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.exc = exc

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return type("Message", (), {"sid": "SMFAKE"})()


class FakeClient:
    def __init__(self, messages: FakeMessages) -> None:
        self.messages = messages


def test_twilio_notifier_uses_messaging_service_sid_without_from() -> None:
    messages = FakeMessages()
    settings = Settings(
        twilio_account_sid="ACfake",
        twilio_auth_token="auth",
        twilio_messaging_service_sid="MGfake",
        twilio_from="+15550001111",
        human_to="+15550002222",
    )

    result = TwilioNotifier(settings, client=FakeClient(messages)).send_message("hello")

    assert result.sent is True
    assert messages.calls == [
        {
            "body": "hello",
            "to": "+15550002222",
            "messaging_service_sid": "MGfake",
        }
    ]


def test_twilio_notifier_falls_back_to_from_when_no_messaging_service() -> None:
    messages = FakeMessages()
    settings = Settings(
        twilio_account_sid="ACfake",
        twilio_auth_token="auth",
        twilio_from="+15550001111",
        human_to="+15550002222",
    )

    TwilioNotifier(settings, client=FakeClient(messages)).send_message("hello")

    assert messages.calls == [
        {
            "body": "hello",
            "to": "+15550002222",
            "from_": "+15550001111",
        }
    ]


def test_twilio_notifier_converts_30034_to_provider_error() -> None:
    twilio = pytest.importorskip("twilio.base.exceptions")
    exc = twilio.TwilioRestException(
        status=400,
        uri="/Messages",
        msg="Sender not registered",
        code=30034,
        method="POST",
    )
    settings = Settings(
        twilio_account_sid="ACfake",
        twilio_auth_token="auth",
        twilio_from="+15550001111",
        human_to="+15550002222",
    )

    with pytest.raises(ProviderSendError) as raised:
        TwilioNotifier(settings, client=FakeClient(FakeMessages(exc))).send_message("hello")

    assert raised.value.code == "30034"
    assert raised.value.status == 400
    assert "A2P 10DLC" in raised.value.message
