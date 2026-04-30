#!/usr/bin/env python3
"""Check that a target project has the required agentic automation files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BASE_REQUIRED = [
    "AGENTS.md",
    ".agentic/automation_prompt.md",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/run_codex_automation.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "scripts/compact_agent_state.py",
    "docs/INITIAL_BOOTSTRAP_PROMPT.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/CODEX_AUTOMATION_GUARDRAILS.md",
    "docs/AUTONOMY_EXPERIMENT_LOG.md",
    "docs/DAILY_AUTOMATION_REVIEW.md",
]

HUMAN_REQUIRED = [
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_BRIDGE_SETUP.md",
]

TASK_REQUIRED_STRINGS = [
    "AUTOMATION_STATUS:",
    "## Current Project State",
    "## Completed Last Run",
    "## Checks From Last Run",
    "## Worker-Agent Activity",
    "## Known Issues",
    "## Pending Human Requests",
    "## Human Messages Sent",
    "## Best Next Milestone",
    "## Suggested Next Sprint-Sized Task",
    "## Ambitious Ideas Backlog",
    "## Continue/Block/Critical-Stop Rationale",
]

AUTOMATION_REQUIRED_STRINGS = [
    "CODEX_LOCK_ALREADY_ACQUIRED=true",
    "scripts/run_codex_automation.sh",
    "scripts/acquire_codex_lock.sh",
    "scripts/release_codex_lock.sh",
    "scripts/spawn_worker_agent.sh",
    "scripts/summarize_worker_outputs.py",
    "Codex CLI worker decision: USE / SKIP / UNAVAILABLE",
    "command -v codex",
    "codex exec --ephemeral",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
]

FILE_ONLY_AUTOMATION_REQUIRED_STRINGS = [
    "Human bridge mode: `file_only`",
    "docs/HUMAN_INBOX.md",
    "Remove handled",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_REQUESTS.md",
    "Do not attempt to send a text message",
]

LOCAL_NOTIFIER_AUTOMATION_REQUIRED_STRINGS = [
    "Human bridge mode: `local_notifier`",
    "POST http://127.0.0.1:8765/api/notify",
    "docs/HUMAN_INBOX.md",
    "Remove handled",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_OUTBOX.md",
    "NOTIFIER_UNREACHABLE",
    "message_body",
    "send me",
    "text me",
]


def check_file(path: Path) -> str | None:
    if not path.exists():
        return "missing"
    if not path.is_file():
        return "not a file"
    if not path.read_text(encoding="utf-8").strip():
        return "empty"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument(
        "--no-human-bridge",
        action="store_true",
        help="Do not require HUMAN_* bridge files",
    )
    parser.add_argument(
        "--human-bridge-mode",
        choices=["file_only", "local_notifier", "disabled"],
        default=None,
        help="Validate mode-specific human bridge markers.",
    )
    args = parser.parse_args()

    root = Path(args.target).resolve()
    mode = args.human_bridge_mode or ("disabled" if args.no_human_bridge else "file_only")
    required = list(BASE_REQUIRED)
    if mode != "disabled":
        required.extend(HUMAN_REQUIRED)

    problems: list[str] = []
    for rel in required:
        problem = check_file(root / rel)
        if problem:
            problems.append(f"{rel}: {problem}")

    task_path = root / "docs/CODEX_AUTOMATION_TASKS.md"
    if task_path.exists() and task_path.is_file():
        task_text = task_path.read_text(encoding="utf-8")
        for marker in TASK_REQUIRED_STRINGS:
            if marker not in task_text:
                problems.append(f"docs/CODEX_AUTOMATION_TASKS.md: missing marker {marker!r}")

    automation_path = root / ".agentic/automation_prompt.md"
    if automation_path.exists() and automation_path.is_file():
        automation_text = automation_path.read_text(encoding="utf-8")
        mode_markers: list[str] = []
        if mode == "file_only":
            mode_markers = FILE_ONLY_AUTOMATION_REQUIRED_STRINGS
        elif mode == "local_notifier":
            mode_markers = LOCAL_NOTIFIER_AUTOMATION_REQUIRED_STRINGS
        for marker in AUTOMATION_REQUIRED_STRINGS + mode_markers:
            if marker not in automation_text:
                problems.append(f".agentic/automation_prompt.md: missing marker {marker!r}")

    if problems:
        print("Required automation file check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print(f"OK: required automation files exist under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
