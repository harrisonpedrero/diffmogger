#!/usr/bin/env python3
"""Validate local-first safety defaults for optional integrations."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DISCORD_BOT_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{24,}\b")
PHONE_NUMBER = re.compile(r"(?<![\w+])\+1\d{10}(?!\w)")
PLACEHOLDER_PHONES = {"+15555555555", "+14155238886"}


@dataclass(frozen=True)
class Problem:
    path: str
    detail: str


def read_text(root: Path, rel_path: str, problems: list[Problem]) -> str:
    path = root / rel_path
    if not path.exists() or not path.is_file():
        problems.append(Problem(rel_path, "missing required integration-safety file"))
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        problems.append(Problem(rel_path, "not valid UTF-8 text"))
        return ""


def require_marker(
    root: Path,
    rel_path: str,
    marker: str,
    problems: list[Problem],
    *,
    detail: str,
) -> None:
    text = read_text(root, rel_path, problems)
    if text and marker not in text:
        problems.append(Problem(rel_path, detail))


def iter_scanned_text_files(root: Path) -> list[Path]:
    scan_paths = [
        root / "README.md",
        root / "docs",
        root / "prompts",
        root / "examples",
        root / "templates",
        root / "services" / "agentic-notifier" / "README.md",
        root / "services" / "agentic-notifier" / ".env.example",
    ]
    files: list[Path] = []
    for path in scan_paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in {".md", ".json", ".txt", ".example"}:
                    files.append(child)
    return files


def scan_for_live_secrets_or_urls(root: Path, problems: list[Problem]) -> None:
    for path in iter_scanned_text_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for match in DISCORD_BOT_TOKEN.findall(text):
            problems.append(Problem(rel, f"contains a concrete-looking Discord bot token: {match}"))

        for match in PHONE_NUMBER.findall(text):
            if match not in PLACEHOLDER_PHONES:
                problems.append(Problem(rel, f"contains a non-placeholder +1 phone number: {match}"))


def check_integration_safety(root: Path) -> list[Problem]:
    problems: list[Problem] = []

    markers = [
        (
            "services/agentic-notifier/agentic_notifier/config.py",
            'notifier_api_host: str = "127.0.0.1"',
            "notifier API must default to loopback",
        ),
        (
            "services/agentic-notifier/agentic_notifier/config.py",
            "discord_bot_token: str = \"\"",
            "Discord token must default to empty configuration",
        ),
        (
            "services/agentic-notifier/agentic_notifier/config.py",
            "dry_run: bool = True",
            "notifier settings must default to dry-run",
        ),
        (
            "services/agentic-notifier/agentic_notifier/config.py",
            'os.getenv("DRY_RUN", "true")',
            "no-env notifier configuration must load dry-run by default",
        ),
        (
            "services/agentic-notifier/.env.example",
            "DRY_RUN=true",
            "example notifier config must start in dry-run mode",
        ),
        (
            "services/agentic-notifier/.env.example",
            "NOTIFIER_API_HOST=127.0.0.1",
            "example notifier API host must be loopback",
        ),
        (
            "services/agentic-notifier/.env.example",
            "DISCORD_BOT_TOKEN=replace-with-your-discord-bot-token",
            "example notifier config must use a placeholder Discord token",
        ),
        (
            "services/agentic-notifier/agentic_notifier/api_app.py",
            'LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}',
            "notify API must define loopback-only unauthenticated hosts",
        ),
        (
            "services/agentic-notifier/agentic_notifier/api_app.py",
            "LOCAL_NOTIFY_API_TOKEN is required when API host is not loopback",
            "notify API must require a token when bound off loopback",
        ),
        (
            "services/agentic-notifier/scripts/send_test_notification.py",
            '"dry_run": not args.real_send',
            "notifier test script must force dry-run unless --real-send is explicit",
        ),
        (
            "services/agentic-notifier/README.md",
            "The example config starts with `DRY_RUN=true`",
            "notifier docs must document dry-run default",
        ),
        (
            "services/agentic-notifier/README.md",
            "Bind the API to `127.0.0.1` unless `LOCAL_NOTIFY_API_TOKEN` is configured.",
            "notifier docs must document local API binding and token safety",
        ),
        (
            "src/diffmogger/kit/scaffold_project_docs.py",
            'return "file_only"',
            "generated targets must keep file-only human bridge as the safe default",
        ),
        (
            "docs/HUMAN_BRIDGE.md",
            "No Discord, webhook, notifier API, or messaging credentials are used in this mode.",
            "current file-only bridge docs must forbid notifier and messaging side effects",
        ),
        (
            "src/diffmogger/dashboard/shared/__init__.py",
            "File-only handoff remains available if notifier setup is incomplete.",
            "dashboard should treat notifier as optional readiness, not a credential store",
        ),
        (
            "src/diffmogger/dashboard/shared/__init__.py",
            "allow_remotes: bool = False",
            "dashboard run-control helpers must default remote opt-in to false",
        ),
    ]

    for rel_path, marker, detail in markers:
        require_marker(root, rel_path, marker, problems, detail=detail)

    scan_for_live_secrets_or_urls(root, problems)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Diffmogger starter-kit directory")
    args = parser.parse_args()

    root = Path(args.target).resolve()
    problems = check_integration_safety(root)
    if problems:
        print("Integration safety check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem.path}: {problem.detail}", file=sys.stderr)
        return 1

    print(f"OK: integration safety defaults verified under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
