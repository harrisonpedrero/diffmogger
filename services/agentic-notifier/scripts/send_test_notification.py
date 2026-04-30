#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

from agentic_notifier.config import load_settings


def main() -> None:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Send a local dry-run notification request.")
    parser.add_argument(
        "--url",
        default=f"http://{settings.notifier_api_host}:{settings.notifier_api_port}/api/notify",
    )
    parser.add_argument("--real-send", action="store_true", help="Do not force dry_run in payload.")
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Send a direct status/update payload instead of a human-unlock request.",
    )
    args = parser.parse_args()

    if args.direct:
        payload = {
            "request_id": "MSG-2026-04-29-001",
            "type": "human_requested_summary",
            "priority": "normal",
            "summary": "Progress summary requested by human",
            "message_body": "Project update: Built the notifier dry-run path and verified direct outbound formatting. Current blocker: none.",
            "agent_recommendation": "No action needed unless you want to review the generated artifacts.",
            "minimum_user_action": "None.",
            "reply_format": "Optional follow-up request.",
            "unblocked_work_remaining": ["Continue current automation sprint"],
            "dedupe_key": "MSG-2026-04-29-001:v1",
            "expects_reply": False,
            "dry_run": not args.real_send,
        }
    else:
        payload = {
            "request_id": "HR-2026-04-29-001",
            "type": "api_key_setup",
            "priority": "unlocking",
            "summary": "Add Service X read-only API key",
            "context": "This unlocks the next source adapter while offline fixtures remain available.",
            "agent_recommendation": "Use read-only/data-only access. Do not grant write, billing, admin, or production permissions.",
            "minimum_user_action": "Add SERVICE_X_API_KEY to your local secret store and reply HR-001 DONE.",
            "reply_format": "HR-001 DONE or HR-001 SKIP",
            "unblocked_work_remaining": [
                "Continue fixture-based dashboard work",
                "Continue report polish",
            ],
            "dedupe_key": "HR-2026-04-29-001:v1",
            "dry_run": not args.real_send,
        }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if settings.local_notify_api_token:
        request.add_header("Authorization", f"Bearer {settings.local_notify_api_token}")

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"))
        raise


if __name__ == "__main__":
    main()
