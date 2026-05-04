from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules or any("pytest" in arg for arg in sys.argv)


def _maybe_load_dotenv(load_dotenv_file: bool | None) -> None:
    if load_dotenv_file is None:
        load_dotenv_file = not _running_under_pytest() and not _truthy(
            os.getenv("AGENTIC_NOTIFIER_SKIP_DOTENV")
        )
    if not load_dotenv_file:
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def _optional_path(value: str | None) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser()


@dataclass(frozen=True)
class Settings:
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_messaging_service_sid: str = ""
    twilio_from: str = ""
    human_to: str = ""
    human_channel: str = "sms"
    target_repo_dir: Path | None = None
    target_human_inbox_path: Path | None = None
    target_human_requests_path: Path | None = None
    target_human_outbox_path: Path | None = None
    target_human_archive_path: Path | None = None
    target_queue_dir: Path | None = None
    notifier_api_host: str = "127.0.0.1"
    notifier_api_port: int = 8765
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8787
    local_notify_api_token: str = ""
    webhook_public_base_url: str = ""
    dry_run: bool = True
    runtime_dir: Path = Path("runtime")
    test_mode: bool = False

    @property
    def target_repo_configured(self) -> bool:
        return all(
            [
                self.target_human_inbox_path,
                self.target_human_requests_path,
                self.target_human_outbox_path,
                self.target_human_archive_path,
            ]
        )

    @property
    def sent_notifications_path(self) -> Path:
        return self.runtime_dir / "sent_notifications.jsonl"

    @property
    def inbound_message_sids_path(self) -> Path:
        return self.runtime_dir / "inbound_message_sids.jsonl"


def load_settings(load_dotenv_file: bool | None = None) -> Settings:
    _maybe_load_dotenv(load_dotenv_file)

    repo_dir = _optional_path(os.getenv("TARGET_REPO_DIR"))

    def target_path(env_name: str, default_name: str) -> Path | None:
        explicit = _optional_path(os.getenv(env_name))
        if explicit:
            return explicit
        if repo_dir:
            return repo_dir / "docs" / default_name
        return None

    repo_root = Path(__file__).resolve().parents[1]
    runtime_dir = _optional_path(os.getenv("NOTIFIER_RUNTIME_DIR")) or repo_root / "runtime"

    return Settings(
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_messaging_service_sid=os.getenv("TWILIO_MESSAGING_SERVICE_SID", ""),
        twilio_from=os.getenv("TWILIO_FROM", ""),
        human_to=os.getenv("HUMAN_TO", ""),
        human_channel=os.getenv("HUMAN_CHANNEL", "sms"),
        target_repo_dir=repo_dir,
        target_human_inbox_path=target_path(
            "TARGET_HUMAN_INBOX_PATH", "HUMAN_INBOX.md"
        ),
        target_human_requests_path=target_path(
            "TARGET_HUMAN_REQUESTS_PATH", "HUMAN_REQUESTS.md"
        ),
        target_human_outbox_path=target_path(
            "TARGET_HUMAN_OUTBOX_PATH", "HUMAN_OUTBOX.md"
        ),
        target_human_archive_path=target_path(
            "TARGET_HUMAN_ARCHIVE_PATH", "HUMAN_RESPONSES_ARCHIVE.md"
        ),
        target_queue_dir=_optional_path(os.getenv("TARGET_QUEUE_DIR")),
        notifier_api_host=os.getenv("NOTIFIER_API_HOST", "127.0.0.1"),
        notifier_api_port=int(os.getenv("NOTIFIER_API_PORT", "8765")),
        webhook_host=os.getenv("WEBHOOK_HOST", "127.0.0.1"),
        webhook_port=int(os.getenv("WEBHOOK_PORT", "8787")),
        local_notify_api_token=os.getenv("LOCAL_NOTIFY_API_TOKEN", ""),
        webhook_public_base_url=os.getenv("WEBHOOK_PUBLIC_BASE_URL", "").rstrip("/"),
        dry_run=_truthy(os.getenv("DRY_RUN", "true")),
        runtime_dir=runtime_dir,
        test_mode=_truthy(os.getenv("AGENTIC_NOTIFIER_TEST_MODE")),
    )
