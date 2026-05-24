#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from agentic_notifier.config import load_settings
from agentic_notifier.formatter import extract_request_id
from agentic_notifier.target_files import TargetFiles


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a simulated inbound human reply into the target inbox.")
    parser.add_argument("body", help="Message body to write.")
    parser.add_argument("--author-name", default="local-test-user")
    parser.add_argument("--author-id", default="local-test-author")
    parser.add_argument("--channel", default="manual")
    parser.add_argument("--route", default="local-test")
    parser.add_argument("--message-id", default=None)
    parser.add_argument("--capture-reason", choices=["mention", "reply"], default="mention")
    args = parser.parse_args()

    settings = load_settings()
    files = TargetFiles.from_settings(settings)
    message_id = args.message_id or "local-test-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    inbox_id = files.append_inbound_message(
        author_name=args.author_name,
        author_id=args.author_id,
        channel=args.channel,
        route=args.route,
        message_id=message_id,
        body=args.body,
        request_id=extract_request_id(args.body),
        capture_reason=args.capture_reason,
        received_at=datetime.now(timezone.utc),
    )
    print(inbox_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
