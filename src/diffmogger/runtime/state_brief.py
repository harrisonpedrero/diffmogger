#!/usr/bin/env python3
"""Render the bounded canonical state brief for a Diffmogger target."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from diffmogger.runtime.state_store import write_canonical_state_brief


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=".", help="Target project directory")
    parser.add_argument("--output", default="", help="Optional target-local output path")
    parser.add_argument("--json", action="store_true", help="Emit metadata as JSON")
    parser.add_argument("--print", dest="print_markdown", action="store_true", help="Print the Markdown brief")
    parser.add_argument("--quiet", action="store_true", help="Only write the brief")
    args = parser.parse_args(argv)

    target = Path(args.target).expanduser().resolve()
    output = Path(args.output) if args.output else None
    try:
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
