#!/usr/bin/env python3
"""List deferred multi-role automation patches as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROLES = ("planner", "builder", "hardener")
DEFERRAL_REASON_FIELD = "deferral_reason"


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def deferred_manifests(target: Path) -> list[dict[str, Any]]:
    queue = target / "target" / "automation_queue"
    records: list[dict[str, Any]] = []
    for role in ROLES:
        role_dir = queue / role
        if not role_dir.exists():
            continue
        for manifest_path in sorted(role_dir.glob("*/manifest.json")):
            manifest = load_json(manifest_path)
            if not manifest or manifest.get("status") != "deferred":
                continue
            manifest = dict(manifest)
            manifest.setdefault(DEFERRAL_REASON_FIELD, "other")
            manifest["manifest_path"] = manifest_path.relative_to(target).as_posix()
            records.append(manifest)
    records.sort(key=lambda item: str(item.get("created_at") or ""))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    indent = 2 if args.pretty else None
    print(json.dumps(deferred_manifests(target), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
