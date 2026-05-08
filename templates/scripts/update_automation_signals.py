#!/usr/bin/env python3
"""Refresh and complete optional Diffmogger automation signals.

Signals are local nudges for recurring automation roles. Definitions live in
`docs/AUTOMATION_SIGNALS.md`; runtime state lives in
`target/automation_signals.json`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diffmogger_paths import target_path


DEFAULT_STATE = {"schema_version": 1, "signals": []}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def cadence_delta(value: Any) -> timedelta:
    text = str(value or "weekly").strip().lower()
    presets = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "monthly": timedelta(days=30),
    }
    if text in presets:
        return presets[text]
    match = re.search(r"(\d+)\s*(minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)", text)
    if not match:
        return timedelta(days=7)
    count = max(1, int(match.group(1)))
    unit = match.group(2)
    if unit.startswith(("minute", "min")) or unit == "m":
        return timedelta(minutes=count)
    if unit.startswith(("hour", "hr")) or unit == "h":
        return timedelta(hours=count)
    if unit.startswith("week") or unit == "w":
        return timedelta(weeks=count)
    return timedelta(days=count)


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def signal_docs_path(target: Path) -> Path:
    return target_path(target, "docs/AUTOMATION_SIGNALS.md")


def state_path(target: Path) -> Path:
    return target_path(target, "target/automation_signals.json")


def load_definitions(target: Path) -> list[dict[str, Any]]:
    path = signal_docs_path(target)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return []
    data = json.loads(match.group(1))
    signals = data.get("signals", [])
    if not isinstance(signals, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw in signals:
        if not isinstance(raw, dict):
            continue
        signal_id = str(raw.get("id") or "").strip()
        owner = str(raw.get("owner_role") or "").strip()
        if not signal_id or not owner:
            continue
        normalized.append(
            {
                "id": signal_id,
                "owner_role": owner,
                "cadence": str(raw.get("cadence") or "weekly"),
                "priority": str(raw.get("priority") or "medium"),
                "instructions": str(raw.get("instructions") or "").strip(),
            }
        )
    return normalized


def load_state(target: Path) -> dict[str, Any]:
    data = read_json(state_path(target), DEFAULT_STATE.copy())
    if not isinstance(data, dict):
        return DEFAULT_STATE.copy()
    data.setdefault("schema_version", 1)
    data.setdefault("signals", [])
    if not isinstance(data["signals"], list):
        data["signals"] = []
    return data


def write_state(target: Path, state: dict[str, Any]) -> None:
    path = state_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = iso(now_utc())
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def state_by_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in state.get("signals", []):
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
    return by_id


def refresh(target: Path) -> dict[str, Any]:
    definitions = load_definitions(target)
    state = load_state(target)
    existing = state_by_id(state)
    refreshed: list[dict[str, Any]] = []
    current = now_utc()
    for definition in definitions:
        old = existing.get(definition["id"], {})
        last_completed = parse_time(old.get("last_completed_at"))
        due_at = (last_completed + cadence_delta(definition["cadence"])) if last_completed else current
        active = current >= due_at or bool(old.get("active", False))
        item = {
            **definition,
            "active": active,
            "last_activated_at": old.get("last_activated_at") or (iso(current) if active else None),
            "last_completed_at": old.get("last_completed_at"),
            "last_completed_by": old.get("last_completed_by"),
            "last_completion_note": old.get("last_completion_note"),
            "next_due_at": iso(due_at),
        }
        if active and not old.get("last_activated_at"):
            item["last_activated_at"] = iso(current)
        refreshed.append(item)
    state["signals"] = refreshed
    write_state(target, state)
    return state


def complete(target: Path, signal_id: str, role: str, note: str) -> dict[str, Any]:
    state = refresh(target)
    current = iso(now_utc())
    found = False
    for signal in state.get("signals", []):
        if signal.get("id") == signal_id:
            signal["active"] = False
            signal["last_completed_at"] = current
            signal["last_completed_by"] = role
            signal["last_completion_note"] = note
            signal["last_activated_at"] = None
            signal["next_due_at"] = iso(now_utc() + cadence_delta(signal.get("cadence")))
            found = True
    if not found:
        raise SystemExit(f"Unknown signal id: {signal_id}")
    write_state(target, state)
    return state


def merge_state(target: Path, incoming_path: Path) -> dict[str, Any]:
    base = refresh(target)
    incoming = read_json(incoming_path, {})
    if not isinstance(incoming, dict):
        return base
    base_items = state_by_id(base)
    for incoming_signal in incoming.get("signals", []):
        if not isinstance(incoming_signal, dict):
            continue
        signal_id = str(incoming_signal.get("id") or "")
        if not signal_id or signal_id not in base_items:
            continue
        incoming_completed = parse_time(incoming_signal.get("last_completed_at"))
        base_completed = parse_time(base_items[signal_id].get("last_completed_at"))
        if incoming_completed and (base_completed is None or incoming_completed > base_completed):
            for key in [
                "active",
                "last_completed_at",
                "last_completed_by",
                "last_completion_note",
                "last_activated_at",
                "next_due_at",
            ]:
                base_items[signal_id][key] = incoming_signal.get(key)
    write_state(target, base)
    return base


def print_summary(state: dict[str, Any], role: str | None) -> None:
    active = [
        item
        for item in state.get("signals", [])
        if item.get("active") and (not role or item.get("owner_role") in {role, "any"})
    ]
    if not active:
        print("AUTOMATION_SIGNALS active=0")
        return
    print(f"AUTOMATION_SIGNALS active={len(active)}")
    for item in active:
        print(
            f"- {item.get('id')} owner={item.get('owner_role')} "
            f"priority={item.get('priority')} cadence={item.get('cadence')}: "
            f"{item.get('instructions')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--refresh", action="store_true", help="Refresh runtime signal state from docs")
    parser.add_argument("--summary", action="store_true", help="Print active signal summary")
    parser.add_argument("--role", default=None, help="Filter summary or record completion role")
    parser.add_argument("--complete", metavar="ID", help="Mark one signal handled")
    parser.add_argument("--note", default="", help="Completion note")
    parser.add_argument("--merge-state", help="Merge completions from another automation_signals.json")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not signal_docs_path(target).exists():
        if args.summary:
            print("AUTOMATION_SIGNALS disabled")
        return 0

    if args.merge_state:
        state = merge_state(target, Path(args.merge_state).expanduser().resolve())
    elif args.complete:
        state = complete(target, args.complete, args.role or "automation", args.note)
    else:
        state = refresh(target)

    if args.summary:
        print_summary(state, args.role)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
