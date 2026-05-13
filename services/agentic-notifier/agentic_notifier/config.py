from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _truthy(value: str | bool | None, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = value.strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


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


def _optional_int(value: str | int | None) -> int | None:
    if isinstance(value, int):
        return value
    if value is None or not str(value).strip():
        return None
    return int(str(value).strip())


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str = ""
    discord_progress_channel_id: int | None = None
    discord_messaging_channel_id: int | None = None
    local_notifications_enabled: bool = True
    target_repo_dir: Path | None = None
    target_human_inbox_path: Path | None = None
    target_human_requests_path: Path | None = None
    target_human_outbox_path: Path | None = None
    target_human_archive_path: Path | None = None
    target_queue_dir: Path | None = None
    notifier_api_host: str = "127.0.0.1"
    notifier_api_port: int = 8765
    local_notify_api_token: str = ""
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
    def discord_enabled(self) -> bool:
        return bool(
            self.discord_bot_token
            and self.discord_progress_channel_id
            and self.discord_messaging_channel_id
        )

    @property
    def sent_notifications_path(self) -> Path:
        return self.runtime_dir / "sent_notifications.jsonl"

    @property
    def inbound_message_ids_path(self) -> Path:
        return self.runtime_dir / "discord_inbound_message_ids.jsonl"


def load_settings(load_dotenv_file: bool | None = None) -> Settings:
    _maybe_load_dotenv(load_dotenv_file)

    repo_dir = _optional_path(os.getenv("TARGET_REPO_DIR"))

    def target_path(env_name: str, default_name: str) -> Path | None:
        explicit = _optional_path(os.getenv(env_name))
        if explicit:
            return explicit
        if repo_dir:
            if (repo_dir / ".diffmogger" / "manifest.json").exists():
                return repo_dir / ".diffmogger" / "state" / default_name
            return repo_dir / "docs" / default_name
        return None

    repo_root = Path(__file__).resolve().parents[1]
    runtime_dir = _optional_path(os.getenv("NOTIFIER_RUNTIME_DIR")) or repo_root / "runtime"

    return Settings(
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
        discord_progress_channel_id=_optional_int(os.getenv("DISCORD_PROGRESS_CHANNEL_ID")),
        discord_messaging_channel_id=_optional_int(os.getenv("DISCORD_MESSAGING_CHANNEL_ID")),
        local_notifications_enabled=_truthy(os.getenv("LOCAL_NOTIFICATIONS_ENABLED", "true"), default=True),
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
        local_notify_api_token=os.getenv("LOCAL_NOTIFY_API_TOKEN", ""),
        dry_run=_truthy(os.getenv("DRY_RUN", "true"), default=True),
        runtime_dir=runtime_dir,
        test_mode=_truthy(os.getenv("AGENTIC_NOTIFIER_TEST_MODE")),
    )
