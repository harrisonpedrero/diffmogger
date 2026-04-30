#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import datetime

from agentic_notifier.config import load_settings
from agentic_notifier.dedupe import JsonlDedupeStore
from agentic_notifier.parser import parse_reply
from agentic_notifier.target_files import TargetFiles


def main() -> None:
    parser = argparse.ArgumentParser(description="Append a fake inbound reply to HUMAN_INBOX.md.")
    parser.add_argument("body", nargs="?", default="HR-001 DONE. Key added locally.")
    parser.add_argument("--from", dest="from_value", default="+15555555555")
    parser.add_argument("--to", dest="to_value", default="+15555555555")
    parser.add_argument("--message-sid", default="")
    args = parser.parse_args()

    settings = load_settings()
    files = TargetFiles.from_settings(settings)
    parsed = parse_reply(args.body)
    message_sid = args.message_sid or "DRYRUN-" + datetime.now().strftime("%Y%m%d%H%M%S")
    store = JsonlDedupeStore(settings.inbound_message_sids_path, "message_sid")
    if store.contains(message_sid):
        print(f"Duplicate inbound message ignored: {message_sid}")
        return
    inbox_id = files.append_inbound_message(
        from_value=args.from_value,
        to_value=args.to_value,
        body=args.body,
        message_sid=message_sid,
        wa_id=None,
        request_id=parsed.request_id,
        parsed_intent=parsed.parsed_intent,
        channel="sms",
    )
    store.record(
        message_sid,
        {"request_id": parsed.request_id, "parsed_intent": parsed.parsed_intent, "channel": "sms"},
    )
    print(f"Appended {inbox_id} to {files.paths.inbox}")


if __name__ == "__main__":
    main()

