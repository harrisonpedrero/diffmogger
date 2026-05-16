from __future__ import annotations

from ..errors import *
from ..jsonio import emit_jsonl
from ..target import *

from diffmogger.runtime.state_store import (
    connect_readonly,
    database_path_for_target,
    state_snapshot,
    utc_now,
    validate_state_database,
    write_canonical_state_brief,
)

import sqlite3
import time
from contextlib import closing


def command_state_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return {
        "target": target_metadata(target),
        "state": state_snapshot(target),
    }


def command_state_validate(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return {
        "target": target_metadata(target),
        "validation": validate_state_database(target),
    }


def command_state_brief(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    result = write_canonical_state_brief(target)
    return {
        "target": target_metadata(target),
        "brief": {
            "path": result["path"],
            "relative_path": result["relative_path"],
            "payload_sha256": result["payload_sha256"],
            "markdown": result["markdown"],
        },
    }


def _runtime_events_after(conn: sqlite3.Connection, after_event_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, stream_id, sequence, occurred_at, event_type, actor_role, actor_id,
               phase, status, task_id, run_id, correlation_id, payload_sha256, prev_hash, event_hash
        FROM events
        WHERE event_id > ?
        ORDER BY event_id ASC
        LIMIT ?
        """,
        (max(0, int(after_event_id)), max(1, min(500, int(limit or 100)))),
    ).fetchall()
    return [dict(row) for row in rows]


def command_state_watch(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    db_path = database_path_for_target(target)
    after_event_id = max(0, int(getattr(args, "after_event_id", 0) or 0))
    max_events = max(0, int(getattr(args, "max_events", 0) or 0))
    max_heartbeats = max(0, int(getattr(args, "max_heartbeats", 0) or 0))
    poll_interval = max(0.05, float(getattr(args, "poll_interval", 0.75) or 0.75))
    heartbeat_seconds = max(0.0, float(getattr(args, "heartbeat_seconds", 5.0) or 5.0))
    streamed = bool(getattr(args, "stream_jsonl", False))
    emitted_events = 0
    emitted_heartbeats = 0
    last_heartbeat = 0.0

    while True:
        events: list[dict[str, Any]] = []
        if db_path.exists():
            try:
                with closing(connect_readonly(db_path)) as conn:
                    events = _runtime_events_after(conn, after_event_id, limit=100)
            except sqlite3.Error:
                events = []
        for event in events:
            after_event_id = int(event.get("event_id") or after_event_id)
            emitted_events += 1
            if streamed:
                emit_jsonl(
                    {
                        "schema_version": 1,
                        "event": "runtime_state",
                        "target": str(target),
                        "runtime_event": event,
                        "after_event_id": after_event_id,
                    }
                )
            if max_events and emitted_events >= max_events:
                return {
                    "target": target_metadata(target),
                    "last_event_id": after_event_id,
                    "emitted_event_count": emitted_events,
                    "heartbeat_count": emitted_heartbeats,
                }

        now = time.monotonic()
        if streamed and (heartbeat_seconds == 0 or now - last_heartbeat >= heartbeat_seconds):
            last_heartbeat = now
            emitted_heartbeats += 1
            emit_jsonl(
                {
                    "schema_version": 1,
                    "event": "runtime_state_heartbeat",
                    "target": str(target),
                    "after_event_id": after_event_id,
                    "emitted_at": utc_now(),
                }
            )
            if max_heartbeats and emitted_heartbeats >= max_heartbeats:
                return {
                    "target": target_metadata(target),
                    "last_event_id": after_event_id,
                    "emitted_event_count": emitted_events,
                    "heartbeat_count": emitted_heartbeats,
                }

        if not streamed:
            return {
                "target": target_metadata(target),
                "last_event_id": after_event_id,
                "events": events,
                "emitted_event_count": emitted_events,
                "heartbeat_count": emitted_heartbeats,
            }
        time.sleep(poll_interval)
