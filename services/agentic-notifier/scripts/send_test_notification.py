#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request

from agentic_notifier.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test agentic-notifier payload.")
    parser.add_argument("--progress", action="store_true", help="Send to the progress channel instead of the messaging channel.")
    parser.add_argument("--real-send", action="store_true", help="Do not force dry_run on the request payload.")
    parser.add_argument(
        "--url",
        default=None,
        help="Notify API URL. Defaults to settings NOTIFIER_API_HOST/PORT.",
    )
    args = parser.parse_args()

    settings = load_settings()
    url = args.url or f"http://{settings.notifier_api_host}:{settings.notifier_api_port}/api/notify"
    payload = {
        "request_id": "PROG-TEST-001" if args.progress else "MSG-TEST-001",
        "type": "manual_progress_test" if args.progress else "human_requested_summary",
        "priority": "normal",
        "summary": "Agentic notifier test",
        "event_kind": "progress" if args.progress else "message",
        "message_body": (
            "Progress test: Diffmogger can post to the progress channel."
            if args.progress
            else "Message test: Diffmogger can post to the messaging channel and local notifications."
        ),
        "minimum_user_action": "None.",
        "reply_format": "Optional follow-up request.",
        "unblocked_work_remaining": ["Continue current automation sprint"],
        "dedupe_key": "agentic-notifier-test:progress" if args.progress else "agentic-notifier-test:message",
        "expects_reply": False,
        "local_notify": not args.progress,
        "dry_run": not args.real_send,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if settings.local_notify_api_token:
        headers["Authorization"] = f"Bearer {settings.local_notify_api_token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.read().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
