#!/usr/bin/env python3
"""Render the bounded canonical state brief for a Diffmogger target."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from diffmogger.runtime.state_store import write_automation_control_state, write_canonical_state_brief


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=".", help="Target project directory")
    parser.add_argument("--output", default="", help="Optional target-local output path")
    parser.add_argument("--json", action="store_true", help="Emit metadata as JSON")
    parser.add_argument("--print", dest="print_markdown", action="store_true", help="Print the Markdown brief")
    parser.add_argument("--quiet", action="store_true", help="Only write the brief")
    parser.add_argument("--set-status", choices=["ACTIVE", "ACTIVE_WITH_PENDING_USER_INPUT", "BLOCKED_ON_USER", "BLOCKED_ON_ENVIRONMENT", "CRITICAL_STOP"], default="", help="Update typed automation status before rendering")
    parser.add_argument("--horizon", default="", help="Update typed current horizon before rendering")
    parser.add_argument("--horizon-decision", default="", help="Update typed horizon decision before rendering")
    parser.add_argument("--current-assessment", default="", help="Update typed current assessment before rendering")
    parser.add_argument("--best-next-milestone", default="", help="Update typed best next milestone before rendering")
    parser.add_argument("--suggested-next-task", default="", help="Update typed suggested next sprint-sized task before rendering")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()
    output = Path(args.output) if args.output else None
    try:
        updates = {
            key: value
            for key, value in {
                "status": args.set_status,
                "horizon": args.horizon,
                "horizon_decision": args.horizon_decision,
                "current_assessment": args.current_assessment,
                "best_next_milestone": args.best_next_milestone,
                "suggested_next_task": args.suggested_next_task,
            }.items()
            if value
        }
        if updates:
            write_automation_control_state(
                target,
                updates,
                actor_role="state_brief",
                event_type="automation.control_updated_from_state_brief_cli",
            )
        result = write_canonical_state_brief(target, output_path=output)
    except Exception as exc:
        print(f"STATE_BRIEF_FAILED target={target} error={exc}", file=sys.stderr)
        return 1

    if args.print_markdown:
        print(str(result["markdown"]), end="")
    elif args.json:
        payload: dict[str, Any] = {key: value for key, value in result.items() if key not in {"markdown", "snapshot"}}
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not args.quiet:
        print(f"STATE_BRIEF_WRITTEN path={result['relative_path']} sha256={result['payload_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
