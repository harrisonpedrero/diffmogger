"""Canonical typed SQLite state for Diffmogger orchestration.

The runtime keeps SQLite as the authoritative control-plane store. JSON files
under ``.diffmogger/runtime`` are generated projections for compatibility and
human/debug tooling; they are never the source of truth once this module has
initialized a target.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from diffmogger.runtime.paths import existing_or_target_path, target_path


STATE_SCHEMA_VERSION = 2
STATE_APPLICATION_ID = 0x444D4752  # DMGR
CANONICAL_DB_RELATIVE = "target/orchestration.sqlite3"
CONVEYOR_PROJECTION_RELATIVE = "target/automation_conveyor_state.json"
CONVEYOR_STREAM_ID = "stream:conveyor"
CONVEYOR_TASK_ID = "task:conveyor"
CONVEYOR_PROJECTION_NAME = "conveyor.state"
RUNNER_PROJECTION_RELATIVE = "target/automation_runner.json"
RUNNER_STREAM_ID = "stream:automation-runner"
RUNNER_TASK_ID = "task:automation-runner"
RUNNER_PROJECTION_NAME = "automation.runner"
CANONICAL_STATE_BRIEF_RELATIVE = "target/canonical_state_brief.md"
CANONICAL_STATE_BRIEF_PROJECTION_NAME = "canonical.state_brief"
HUMAN_STREAM_ID = "stream:human-messages"
HUMAN_TASK_ID = "task:human-messages"
HUMAN_PROJECTION_NAME = "human.messages"
TICKET_STREAM_ID = "stream:ticket-run"
TICKET_TASK_ID = "task:ticket-run"
TICKET_RUN_PROJECTION_NAME = "ticket.run"
DEFAULT_EVENT_LIMIT = 20
BRIEF_ITEM_LIMIT = 8
BRIEF_TEXT_LIMIT = 240

STATUS_MODEL = (
    "ACTIVE",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
    "BLOCKED_ON_ENVIRONMENT",
    "CRITICAL_STOP",
)

ORCHESTRATION_TABLES = (
    "meta",
    "streams",
    "events",
    "checkpoints",
    "tasks",
    "runs",
    "worktrees",
    "validations",
    "assumptions",
    "decisions",
    "blockers",
    "artifacts",
    "next_actions",
    "projections",
    "human_messages",
    "ticket_runs",
    "ticket_items",
    "compatibility_migrations",
)

HUMAN_REQUEST_ACTIVE_STATUSES = {"active", "awaiting_user", "awaiting_human", "pending", "open", "unresolved"}
HUMAN_ARCHIVE_STATUSES = {"resolved", "handled", "consumed", "archived", "done", "closed", "skipped"}
HUMAN_NOTE_ACTIVE_STATUSES = {"unhandled", "queued", "failed", "pending", "open"}
TICKET_ITEM_STATUSES = {"pending", "in_progress", "candidate_done", "done", "blocked"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json_projection(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(pretty_json(payload), encoding="utf-8")
    tmp.replace(path)


def default_conveyor_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cycles": 0,
        "role_counts": {},
        "history": [],
    }


def normalize_conveyor_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(state or {})
    normalized.setdefault("schema_version", 1)
    normalized.setdefault("cycles", 0)
    normalized.setdefault("role_counts", {})
    normalized.setdefault("history", [])
    if not isinstance(normalized.get("role_counts"), dict):
        normalized["role_counts"] = {}
    if not isinstance(normalized.get("history"), list):
        normalized["history"] = []
    return normalized


def normalize_runner_state(state: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(state or {})
    if not normalized:
        return {}
    normalized.setdefault("schema_version", 1)
    return normalized


def database_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), CANONICAL_DB_RELATIVE)


def conveyor_projection_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), CONVEYOR_PROJECTION_RELATIVE)


def runner_projection_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), RUNNER_PROJECTION_RELATIVE)


def canonical_state_brief_path_for_target(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), CANONICAL_STATE_BRIEF_RELATIVE)


def database_path_for_projection(projection_path: Path) -> Path:
    path = projection_path.expanduser()
    if path.name in {Path(CONVEYOR_PROJECTION_RELATIVE).name, Path(RUNNER_PROJECTION_RELATIVE).name}:
        return path.with_name("orchestration.sqlite3")
    return path.with_suffix(".sqlite3")


@dataclass(frozen=True)
class StateEvent:
    stream_id: str
    event_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    actor_role: str = "runtime"
    actor_id: str = ""
    phase: str = ""
    status: str = ""
    task_id: str = ""
    run_id: str = ""
    causation_id: int | None = None
    correlation_id: str = ""
    occurred_at: str = ""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA application_id = {STATE_APPLICATION_ID}")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS streams (
            stream_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            current_sequence INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_id TEXT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            phase TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            task_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            causation_id INTEGER,
            correlation_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            prev_hash TEXT NOT NULL DEFAULT '',
            event_hash TEXT NOT NULL,
            UNIQUE(stream_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, occurred_at);
        CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, occurred_at);

        CREATE TABLE IF NOT EXISTS checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL REFERENCES streams(stream_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state_json TEXT NOT NULL,
            state_sha256 TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_checkpoints_stream ON checkpoints(stream_id, sequence);

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            parent_task_id TEXT,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            risk_tier TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            status TEXT NOT NULL,
            phase TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            base_commit TEXT NOT NULL DEFAULT '',
            head_commit TEXT NOT NULL DEFAULT '',
            worktree_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, status);

        CREATE TABLE IF NOT EXISTS worktrees (
            worktree_id TEXT PRIMARY KEY,
            repo_root TEXT NOT NULL,
            path TEXT NOT NULL,
            branch TEXT NOT NULL DEFAULT '',
            base_commit TEXT NOT NULL DEFAULT '',
            head_commit TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS validations (
            validation_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            command TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT '',
            finished_at TEXT NOT NULL DEFAULT '',
            environment_digest TEXT NOT NULL DEFAULT '',
            log_artifact_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_validations_task ON validations(task_id, status);

        CREATE TABLE IF NOT EXISTS assumptions (
            assumption_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0,
            evidence_event_id INTEGER,
            introduced_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            invalidation_rule TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            owner_role TEXT NOT NULL DEFAULT '',
            decided_at TEXT NOT NULL,
            superseded_by TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS blockers (
            blocker_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            summary TEXT NOT NULL,
            resume_token TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_blockers_status ON blockers(status, kind);

        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            digest TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS next_actions (
            action_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            owner_role TEXT NOT NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_projection TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_next_actions_status ON next_actions(status, owner_role, priority);

        CREATE TABLE IF NOT EXISTS projections (
            name TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id)
        );

        CREATE TABLE IF NOT EXISTS human_messages (
            message_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT '',
            request_id TEXT NOT NULL DEFAULT '',
            source_inbox_id TEXT NOT NULL DEFAULT '',
            channel TEXT NOT NULL DEFAULT '',
            sender TEXT NOT NULL DEFAULT '',
            recipient TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_human_messages_kind_status ON human_messages(kind, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_human_messages_request ON human_messages(request_id, updated_at);

        CREATE TABLE IF NOT EXISTS ticket_runs (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'active',
            halt_when_complete INTEGER NOT NULL DEFAULT 1,
            notify_on_complete INTEGER NOT NULL DEFAULT 1,
            ticket_file TEXT NOT NULL DEFAULT '',
            report_path TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS ticket_items (
            ticket_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            summary TEXT NOT NULL,
            status TEXT NOT NULL,
            blocker TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_ticket_items_run_status ON ticket_items(run_id, status, position);

        CREATE TABLE IF NOT EXISTS compatibility_migrations (
            source_path TEXT PRIMARY KEY,
            source_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            event_id INTEGER REFERENCES events(event_id)
        );
        """
    )
    now = utc_now()
    conn.execute(f"PRAGMA user_version = {STATE_SCHEMA_VERSION}")
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("schema_version", str(STATE_SCHEMA_VERSION), now),
    )
    conn.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        ("state_authority", "sqlite", now),
    )
    conn.commit()


def append_event(conn: sqlite3.Connection, event: StateEvent) -> int:
    occurred_at = event.occurred_at or utc_now()
    payload_json = stable_json(dict(event.payload))
    payload_sha = sha256_text(payload_json)
    with conn:
        row = conn.execute(
            "SELECT current_sequence FROM streams WHERE stream_id = ?",
            (event.stream_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO streams(stream_id, kind, subject_id, status, current_sequence, created_at, updated_at, payload_json) "
                "VALUES(?, ?, ?, ?, 0, ?, ?, ?)",
                (
                    event.stream_id,
                    "conveyor"
                    if event.stream_id == CONVEYOR_STREAM_ID
                    else (
                        "runner"
                        if event.stream_id == RUNNER_STREAM_ID
                        else (
                            "human"
                            if event.stream_id == HUMAN_STREAM_ID
                            else ("ticket_run" if event.stream_id == TICKET_STREAM_ID else "task")
                        )
                    ),
                    event.task_id or event.stream_id,
                    event.status or "ACTIVE",
                    occurred_at,
                    occurred_at,
                    "{}",
                ),
            )
            sequence = 1
            prev_hash = ""
        else:
            sequence = int(row["current_sequence"]) + 1
            last = conn.execute(
                "SELECT event_hash FROM events WHERE stream_id = ? ORDER BY sequence DESC LIMIT 1",
                (event.stream_id,),
            ).fetchone()
            prev_hash = str(last["event_hash"]) if last else ""
        material = stable_json(
            {
                "stream_id": event.stream_id,
                "sequence": sequence,
                "occurred_at": occurred_at,
                "event_type": event.event_type,
                "actor_role": event.actor_role,
                "actor_id": event.actor_id,
                "phase": event.phase,
                "status": event.status,
                "task_id": event.task_id,
                "run_id": event.run_id,
                "causation_id": event.causation_id,
                "correlation_id": event.correlation_id,
                "payload_sha256": payload_sha,
                "prev_hash": prev_hash,
            }
        )
        event_hash = sha256_text(material)
        cursor = conn.execute(
            """
            INSERT INTO events(
                stream_id, sequence, occurred_at, event_type, actor_role, actor_id,
                phase, status, task_id, run_id, causation_id, correlation_id,
                payload_json, payload_sha256, prev_hash, event_hash
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.stream_id,
                sequence,
                occurred_at,
                event.event_type,
                event.actor_role,
                event.actor_id,
                event.phase,
                event.status,
                event.task_id,
                event.run_id,
                event.causation_id,
                event.correlation_id,
                payload_json,
                payload_sha,
                prev_hash,
                event_hash,
            ),
        )
        conn.execute(
            "UPDATE streams SET current_sequence = ?, status = ?, updated_at = ? WHERE stream_id = ?",
            (sequence, event.status or "ACTIVE", occurred_at, event.stream_id),
        )
        return int(cursor.lastrowid)


def replace_projection(
    conn: sqlite3.Connection,
    *,
    name: str,
    payload: Mapping[str, Any],
    event_id: int | None,
) -> None:
    payload_json = stable_json(dict(payload))
    now = utc_now()
    with conn:
        conn.execute(
            "INSERT INTO projections(name, updated_at, payload_json, payload_sha256, event_id) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET "
            "updated_at=excluded.updated_at, payload_json=excluded.payload_json, "
            "payload_sha256=excluded.payload_sha256, event_id=excluded.event_id",
            (name, now, payload_json, sha256_text(payload_json), event_id),
        )


def load_projection(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    row = conn.execute("SELECT payload_json FROM projections WHERE name = ?", (name,)).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def checkpoint_stream(
    conn: sqlite3.Connection,
    *,
    stream_id: str,
    kind: str,
    state: Mapping[str, Any],
    event_id: int | None,
) -> str:
    row = conn.execute(
        "SELECT current_sequence FROM streams WHERE stream_id = ?",
        (stream_id,),
    ).fetchone()
    sequence = int(row["current_sequence"]) if row else 0
    state_json = stable_json(dict(state))
    checkpoint_id = f"ckpt:{stream_id}:{sequence}"
    with conn:
        conn.execute(
            "INSERT INTO checkpoints(checkpoint_id, stream_id, sequence, kind, created_at, state_json, state_sha256, event_id) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(checkpoint_id) DO UPDATE SET "
            "created_at=excluded.created_at, state_json=excluded.state_json, "
            "state_sha256=excluded.state_sha256, event_id=excluded.event_id",
            (
                checkpoint_id,
                stream_id,
                sequence,
                kind,
                utc_now(),
                state_json,
                sha256_text(state_json),
                event_id,
            ),
        )
    return checkpoint_id


def apply_conveyor_read_models(conn: sqlite3.Connection, state: Mapping[str, Any], *, event_id: int | None) -> None:
    now = utc_now()
    active = state.get("active_role_run") if isinstance(state.get("active_role_run"), dict) else {}
    last_decision = state.get("last_decision") if isinstance(state.get("last_decision"), dict) else {}
    phase = str(last_decision.get("role") or active.get("role") or "idle")
    with conn:
        conn.execute(
            """
            INSERT INTO tasks(task_id, parent_task_id, title, status, phase, owner_role, risk_tier, created_at, updated_at, payload_json)
            VALUES(?, '', ?, ?, ?, ?, '', ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                phase=excluded.phase,
                owner_role=excluded.owner_role,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                CONVEYOR_TASK_ID,
                "Automation conveyor",
                "ACTIVE",
                phase,
                str(active.get("role") or ""),
                now,
                now,
                stable_json({"projection": CONVEYOR_PROJECTION_NAME, "last_event_id": event_id}),
            ),
        )
        for run_key in ("active_role_run", "last_active_role_run"):
            run = state.get(run_key)
            if not isinstance(run, dict) or not run.get("run_id"):
                continue
            run_id = str(run.get("run_id"))
            status = str(run.get("status") or ("running" if run_key == "active_role_run" else "finished"))
            conn.execute(
                """
                INSERT INTO runs(run_id, task_id, stream_id, status, phase, owner_role, started_at, finished_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    phase=excluded.phase,
                    owner_role=excluded.owner_role,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    payload_json=excluded.payload_json
                """,
                (
                    run_id,
                    CONVEYOR_TASK_ID,
                    CONVEYOR_STREAM_ID,
                    status,
                    str(run.get("role") or ""),
                    str(run.get("role") or ""),
                    str(run.get("started_at") or ""),
                    str(run.get("finished_at") or ""),
                    stable_json(run),
                ),
            )
        conn.execute(
            "DELETE FROM next_actions WHERE source_projection = ?",
            (CONVEYOR_PROJECTION_NAME,),
        )
        decision_queue = state.get("decision_queue") if isinstance(state.get("decision_queue"), list) else []
        for index, item in enumerate(decision_queue[:12]):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "idle")
            state_name = str(item.get("state") or "planned")
            reason = str(item.get("reason") or "")
            action_id = f"next:conveyor:{index}:{sha256_text(role + state_name + reason)[:12]}"
            conn.execute(
                """
                INSERT INTO next_actions(action_id, task_id, owner_role, kind, status, reason, priority, created_at, updated_at, source_projection, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    CONVEYOR_TASK_ID,
                    role,
                    "conveyor_lane",
                    state_name,
                    reason,
                    index,
                    now,
                    now,
                    CONVEYOR_PROJECTION_NAME,
                    stable_json(item),
                ),
            )


def annotate_projection_state(state: dict[str, Any], db_path: Path, event_id: int | None) -> dict[str, Any]:
    annotated = normalize_conveyor_state(state)
    annotated["canonical_state"] = {
        "authority": "sqlite",
        "database_path": str(db_path),
        "projection": CONVEYOR_PROJECTION_NAME,
        "projected_at": utc_now(),
        "event_id": event_id,
        "note": "This JSON file is a generated projection. Do not edit it as authoritative state.",
    }
    return annotated


def write_conveyor_state(
    projection_path: Path,
    state: Mapping[str, Any],
    *,
    event_type: str = "conveyor.state_projection_updated",
    actor_role: str = "conveyor",
    phase: str = "",
    status: str = "ACTIVE",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base_state = normalize_conveyor_state(state)
    base_state["updated_at"] = utc_now()
    db_path = database_path_for_projection(projection_path)
    active_run = base_state.get("active_role_run") if isinstance(base_state.get("active_role_run"), dict) else {}
    with closing(connect(db_path)) as conn:
        event_payload = {
            "projection": CONVEYOR_PROJECTION_NAME,
            "state": base_state,
        }
        if payload:
            event_payload["metadata"] = dict(payload)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=CONVEYOR_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase=phase,
                status=status,
                task_id=CONVEYOR_TASK_ID,
                run_id=str(active_run.get("run_id") or ""),
                payload=event_payload,
            ),
        )
        annotated = annotate_projection_state(base_state, db_path, event_id)
        replace_projection(conn, name=CONVEYOR_PROJECTION_NAME, payload=annotated, event_id=event_id)
        apply_conveyor_read_models(conn, annotated, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=CONVEYOR_STREAM_ID,
            kind="conveyor_projection",
            state=annotated,
            event_id=event_id,
        )
    write_json_projection(projection_path, annotated)
    return annotated


def import_legacy_conveyor_json(projection_path: Path, db_path: Path) -> dict[str, Any]:
    legacy = normalize_conveyor_state(read_json_file(projection_path))
    source_hash = sha256_text(stable_json(legacy))
    with closing(connect(db_path)) as conn:
        existing = conn.execute(
            "SELECT event_id FROM compatibility_migrations WHERE source_path = ? AND source_sha256 = ?",
            (str(projection_path), source_hash),
        ).fetchone()
        if existing is not None:
            projected = load_projection(conn, CONVEYOR_PROJECTION_NAME)
            if projected:
                return normalize_conveyor_state(projected)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=CONVEYOR_STREAM_ID,
                event_type="compatibility.legacy_conveyor_json_imported",
                actor_role="migration",
                phase="migration",
                status="ACTIVE",
                task_id=CONVEYOR_TASK_ID,
                payload={"source_path": str(projection_path), "source_sha256": source_hash, "state": legacy},
            ),
        )
        annotated = annotate_projection_state(legacy, db_path, event_id)
        replace_projection(conn, name=CONVEYOR_PROJECTION_NAME, payload=annotated, event_id=event_id)
        apply_conveyor_read_models(conn, annotated, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=CONVEYOR_STREAM_ID,
            kind="legacy_import",
            state=annotated,
            event_id=event_id,
        )
        with conn:
            conn.execute(
                "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(source_path) DO UPDATE SET source_sha256=excluded.source_sha256, "
                "imported_at=excluded.imported_at, event_id=excluded.event_id",
                (str(projection_path), source_hash, utc_now(), event_id),
            )
    write_json_projection(projection_path, annotated)
    return annotated


def initialize_conveyor_state(projection_path: Path, db_path: Path) -> dict[str, Any]:
    state = default_conveyor_state()
    return write_conveyor_state(
        projection_path,
        state,
        event_type="conveyor.state_initialized",
        actor_role="runtime",
        phase="initialization",
        payload={"reason": "canonical SQLite store initialized"},
    )


def load_conveyor_state(projection_path: Path) -> dict[str, Any]:
    db_path = database_path_for_projection(projection_path)
    if db_path.exists():
        with closing(connect(db_path)) as conn:
            projected = load_projection(conn, CONVEYOR_PROJECTION_NAME)
            if projected:
                return normalize_conveyor_state(projected)
    if projection_path.exists():
        return import_legacy_conveyor_json(projection_path, db_path)
    return initialize_conveyor_state(projection_path, db_path)


def annotate_runner_state(state: Mapping[str, Any], db_path: Path, event_id: int | None) -> dict[str, Any]:
    annotated = normalize_runner_state(state)
    if not annotated:
        return {}
    annotated["canonical_state"] = {
        "authority": "sqlite",
        "database_path": str(db_path),
        "projection": RUNNER_PROJECTION_NAME,
        "projected_at": utc_now(),
        "event_id": event_id,
        "note": "This JSON file is a generated projection. Do not edit it as authoritative state.",
    }
    return annotated


def write_runner_state(
    projection_path: Path,
    state: Mapping[str, Any],
    *,
    event_type: str = "runner.state_projection_updated",
    actor_role: str = "dashboard",
    phase: str = "run_control",
    status: str = "",
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base_state = normalize_runner_state(state)
    if not base_state:
        base_state = {"schema_version": 1, "state": "stopped"}
    base_state["updated_at"] = utc_now()
    db_path = database_path_for_projection(projection_path)
    with closing(connect(db_path)) as conn:
        event_payload = {
            "projection": RUNNER_PROJECTION_NAME,
            "state": base_state,
        }
        if payload:
            event_payload["metadata"] = dict(payload)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=RUNNER_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase=phase,
                status=status or str(base_state.get("state") or ""),
                task_id=RUNNER_TASK_ID,
                run_id=str(base_state.get("run_id") or ""),
                payload=event_payload,
            ),
        )
        annotated = annotate_runner_state(base_state, db_path, event_id)
        replace_projection(conn, name=RUNNER_PROJECTION_NAME, payload=annotated, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=RUNNER_STREAM_ID,
            kind="runner_projection",
            state=annotated,
            event_id=event_id,
        )
    write_json_projection(projection_path, annotated)
    return annotated


def import_legacy_runner_json(projection_path: Path, db_path: Path) -> dict[str, Any]:
    legacy = normalize_runner_state(read_json_file(projection_path))
    if not legacy:
        return {}
    source_hash = sha256_text(stable_json(legacy))
    with closing(connect(db_path)) as conn:
        existing = conn.execute(
            "SELECT event_id FROM compatibility_migrations WHERE source_path = ? AND source_sha256 = ?",
            (str(projection_path), source_hash),
        ).fetchone()
        if existing is not None:
            projected = load_projection(conn, RUNNER_PROJECTION_NAME)
            if projected:
                return normalize_runner_state(projected)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=RUNNER_STREAM_ID,
                event_type="compatibility.legacy_runner_json_imported",
                actor_role="migration",
                phase="migration",
                status=str(legacy.get("state") or ""),
                task_id=RUNNER_TASK_ID,
                payload={"source_path": str(projection_path), "source_sha256": source_hash, "state": legacy},
            ),
        )
        annotated = annotate_runner_state(legacy, db_path, event_id)
        replace_projection(conn, name=RUNNER_PROJECTION_NAME, payload=annotated, event_id=event_id)
        checkpoint_stream(
            conn,
            stream_id=RUNNER_STREAM_ID,
            kind="legacy_import",
            state=annotated,
            event_id=event_id,
        )
        with conn:
            conn.execute(
                "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                "VALUES(?, ?, ?, ?) "
                "ON CONFLICT(source_path) DO UPDATE SET source_sha256=excluded.source_sha256, "
                "imported_at=excluded.imported_at, event_id=excluded.event_id",
                (str(projection_path), source_hash, utc_now(), event_id),
            )
    write_json_projection(projection_path, annotated)
    return annotated


def load_runner_state(projection_path: Path) -> dict[str, Any]:
    db_path = database_path_for_projection(projection_path)
    if db_path.exists():
        with closing(connect(db_path)) as conn:
            projected = load_projection(conn, RUNNER_PROJECTION_NAME)
            if projected:
                return normalize_runner_state(projected)
    if projection_path.exists():
        return import_legacy_runner_json(projection_path, db_path)
    return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse_metadata_block(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*-\s+([A-Za-z0-9_-]+):\s*(.*)\s*$", line)
        if match:
            metadata[match.group(1).strip()] = match.group(2).strip()
    return metadata


def _extract_markdown_body(section: str) -> str:
    body_match = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
    if body_match:
        body_start = body_match.end()
        next_heading = re.search(r"^#{3,5}\s+", section[body_start:], flags=re.MULTILINE)
        body_end = body_start + next_heading.start() if next_heading else len(section)
        return section[body_start:body_end].strip()
    stripped_lines = [
        line
        for line in section.splitlines()
        if not re.match(r"^\s*-\s+[A-Za-z0-9_-]+:\s*", line)
        and not re.match(r"^#{1,6}\s+", line)
        and not line.strip().startswith("```")
    ]
    return "\n".join(stripped_lines).strip()


def _human_summary(metadata: Mapping[str, str], body: str) -> str:
    for key in ("summary", "action_taken", "remaining_followup", "blocker", "reason"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return _brief_text(value, limit=180)
    return _brief_text(body, limit=180) if body else "No message body recorded."


def _parse_human_markdown_records(path: Path, prefixes: tuple[str, ...], kind: str) -> list[dict[str, Any]]:
    text = _read_text(path)
    if not text:
        return []
    prefix_pattern = "|".join(re.escape(prefix) for prefix in prefixes)
    heading_pattern = re.compile(
        rf"^(?P<level>##+)\s+(?P<record_id>(?:{prefix_pattern})-[A-Za-z0-9_.:-]+)(?P<title>[^\n]*)$",
        flags=re.MULTILINE,
    )
    matches = list(heading_pattern.finditer(text))
    records: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        record_id = match.group("record_id").strip()
        if "YYYY" in record_id or record_id.endswith("-001`"):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        metadata_boundary = re.search(r"^#{3,5}\s+Body\s*$", section, flags=re.IGNORECASE | re.MULTILINE)
        metadata_text = section[: metadata_boundary.start()] if metadata_boundary else section
        metadata = _parse_metadata_block(metadata_text)
        body = _extract_markdown_body(section)
        raw_status = str(metadata.get("status") or "").strip().lower()
        title = match.group("title").strip(" -:\t")
        records.append(
            {
                "id": record_id,
                "kind": kind,
                "title": title or record_id,
                "status": raw_status or ("unhandled" if kind == "note" else "unknown"),
                "intent": metadata.get("parsed_intent") or metadata.get("intent") or "",
                "request_id": metadata.get("request_id", ""),
                "source_inbox_id": metadata.get("source_inbox_id", ""),
                "channel": metadata.get("channel", ""),
                "from": metadata.get("from", ""),
                "to": metadata.get("to", ""),
                "related": {
                    "request": metadata.get("request_id", ""),
                    "ticket": metadata.get("ticket_id") or metadata.get("related_ticket") or metadata.get("ticket") or "",
                    "run": metadata.get("run_id") or metadata.get("related_run") or "",
                    "file": metadata.get("file") or metadata.get("related_file") or metadata.get("path") or "",
                },
                "timestamp": metadata.get("received_at")
                or metadata.get("created_at")
                or metadata.get("requested_at")
                or metadata.get("resolved_at")
                or metadata.get("timestamp")
                or "",
                "body": body,
                "summary": _human_summary(metadata, body),
                "metadata": metadata,
            }
        )
    return records


def _upsert_human_message_conn(conn: sqlite3.Connection, record: Mapping[str, Any], *, now: str) -> None:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    payload = {
        "title": record.get("title") or record.get("id") or "",
        "timestamp": record.get("timestamp") or "",
        "related": record.get("related") if isinstance(record.get("related"), dict) else {},
        "metadata": metadata,
        "source_file_key": record.get("source_file_key") or "",
    }
    created_at = str(record.get("timestamp") or "") or now
    conn.execute(
        """
        INSERT INTO human_messages(
            message_id, kind, status, intent, request_id, source_inbox_id, channel,
            sender, recipient, summary, body, created_at, updated_at, payload_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            kind=excluded.kind,
            status=excluded.status,
            intent=excluded.intent,
            request_id=excluded.request_id,
            source_inbox_id=excluded.source_inbox_id,
            channel=excluded.channel,
            sender=excluded.sender,
            recipient=excluded.recipient,
            summary=excluded.summary,
            body=excluded.body,
            updated_at=excluded.updated_at,
            payload_json=excluded.payload_json
        """,
        (
            str(record.get("id") or ""),
            str(record.get("kind") or "note"),
            str(record.get("status") or "unknown"),
            str(record.get("intent") or ""),
            str(record.get("request_id") or ""),
            str(record.get("source_inbox_id") or ""),
            str(record.get("channel") or ""),
            str(record.get("from") or record.get("sender") or ""),
            str(record.get("to") or record.get("recipient") or ""),
            str(record.get("summary") or ""),
            str(record.get("body") or ""),
            created_at,
            now,
            stable_json(payload),
        ),
    )


def import_legacy_human_markdown(target: Path) -> int:
    """Import old human bridge Markdown once so it stops being a live channel."""

    target = target.expanduser().resolve()
    specs = [
        ("docs/HUMAN_REQUESTS.md", ("HR",), "request"),
        ("docs/HUMAN_INBOX.md", ("INBOX",), "note"),
        ("docs/HUMAN_RESPONSES_ARCHIVE.md", ("HR", "INBOX", "ARCHIVE"), "archive"),
        ("docs/HUMAN_OUTBOX.md", ("OUTBOX",), "outbound"),
    ]
    db_path = database_path_for_target(target)
    imported = 0
    with closing(connect(db_path)) as conn:
        for rel, prefixes, kind in specs:
            path = existing_or_target_path(target, rel)
            if not path.exists():
                continue
            source_key = f"legacy-human-markdown:{rel}"
            if conn.execute(
                "SELECT event_id FROM compatibility_migrations WHERE source_path = ?",
                (source_key,),
            ).fetchone():
                continue
            text = _read_text(path)
            source_hash = sha256_text(text)
            records = _parse_human_markdown_records(path, prefixes, kind)
            now = utc_now()
            with conn:
                for record in records:
                    _upsert_human_message_conn(conn, record, now=now)
            event_id = append_event(
                conn,
                StateEvent(
                    stream_id=HUMAN_STREAM_ID,
                    event_type="compatibility.legacy_human_markdown_imported",
                    actor_role="migration",
                    phase="migration",
                    status="ACTIVE",
                    task_id=HUMAN_TASK_ID,
                    payload={"source_path": str(path), "source_rel": rel, "record_count": len(records)},
                ),
            )
            replace_projection(conn, name=HUMAN_PROJECTION_NAME, payload=human_messages_payload(conn), event_id=event_id)
            with conn:
                conn.execute(
                    "INSERT INTO compatibility_migrations(source_path, source_sha256, imported_at, event_id) "
                    "VALUES(?, ?, ?, ?)",
                    (source_key, source_hash, utc_now(), event_id),
                )
            imported += len(records)
    return imported


def _next_human_message_id(conn: sqlite3.Connection, prefix: str, now: str) -> str:
    date_prefix = now[:10]
    pattern = f"{prefix}-{date_prefix}-%"
    rows = conn.execute(
        "SELECT message_id FROM human_messages WHERE message_id LIKE ?",
        (pattern,),
    ).fetchall()
    highest = 0
    for row in rows:
        match = re.search(r"-(\d{3,})$", str(row["message_id"]))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{date_prefix}-{highest + 1:03d}"


def record_human_message(
    target: Path,
    *,
    kind: str,
    body: str,
    request_id: str = "",
    intent: str = "",
    status: str = "",
    channel: str = "dashboard",
    sender: str = "dashboard",
    recipient: str = "automation",
    summary: str = "",
    message_id: str = "",
    actor_role: str = "dashboard",
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    normalized_kind = str(kind or "note").strip().lower()
    prefix = {"request": "HR", "note": "INBOX", "archive": "ARCHIVE", "outbound": "OUTBOX"}.get(normalized_kind, "INBOX")
    now = utc_now()
    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        resolved_id = message_id or _next_human_message_id(conn, prefix, now)
        resolved_status = status or ("unhandled" if normalized_kind == "note" else "active" if normalized_kind == "request" else "sent")
        record = {
            "id": resolved_id,
            "kind": normalized_kind,
            "status": resolved_status,
            "intent": intent,
            "request_id": request_id,
            "channel": channel,
            "from": sender,
            "to": recipient,
            "timestamp": now,
            "body": body,
            "summary": summary or _brief_text(body, limit=180),
            "metadata": {"created_by": actor_role},
        }
        with conn:
            _upsert_human_message_conn(conn, record, now=now)
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=HUMAN_STREAM_ID,
                event_type="human.message_recorded",
                actor_role=actor_role,
                phase="human_bridge",
                status="ACTIVE",
                task_id=HUMAN_TASK_ID,
                payload={"message_id": resolved_id, "kind": normalized_kind, "status": resolved_status},
            ),
        )
        replace_projection(conn, name=HUMAN_PROJECTION_NAME, payload=human_messages_payload(conn), event_id=event_id)
        return human_message_row(conn, resolved_id) or record


def human_message_row(conn: sqlite3.Connection, message_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM human_messages WHERE message_id = ?", (message_id,)).fetchone()
    if row is None:
        return None
    return _human_row_to_record(row)


def _human_ui_state(kind: str, status: str, archived_inbox_ids: set[str]) -> str:
    normalized = status.lower()
    if kind == "request":
        return "handled" if normalized in HUMAN_ARCHIVE_STATUSES else "pending" if normalized in HUMAN_REQUEST_ACTIVE_STATUSES else "unknown"
    if kind == "note":
        if normalized in HUMAN_ARCHIVE_STATUSES or normalized in {"consumed"}:
            return "consumed"
        return "queued" if normalized in HUMAN_NOTE_ACTIVE_STATUSES else "unknown"
    if kind == "outbound":
        return "sent"
    return "archived"


def _human_row_to_record(row: sqlite3.Row, *, archived_inbox_ids: set[str] | None = None) -> dict[str, Any]:
    archived = archived_inbox_ids or set()
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except json.JSONDecodeError:
        payload = {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    kind = str(row["kind"] or "")
    status = str(row["status"] or "unknown")
    return {
        "id": str(row["message_id"]),
        "title": str(payload.get("title") or row["message_id"]),
        "kind": kind,
        "status": status,
        "status_label": status.replace("_", " ").title(),
        "timestamp": str(row["created_at"] or ""),
        "request_id": str(row["request_id"] or ""),
        "source_inbox_id": str(row["source_inbox_id"] or ""),
        "intent": str(row["intent"] or ""),
        "channel": str(row["channel"] or ""),
        "from": str(row["sender"] or ""),
        "to": str(row["recipient"] or ""),
        "related": payload.get("related") if isinstance(payload.get("related"), dict) else {},
        "metadata": metadata,
        "body": str(row["body"] or ""),
        "summary": str(row["summary"] or ""),
        "source_file_key": str(payload.get("source_file_key") or ""),
        "truncated": False,
        "ui_state": "archived" if str(row["message_id"]) in archived else _human_ui_state(kind, status, archived),
    }


def human_messages_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM human_messages ORDER BY updated_at DESC, message_id DESC LIMIT 200").fetchall()
    records = [_human_row_to_record(row) for row in rows]
    return {"schema_version": 1, "records": records, "updated_at": utc_now()}


def human_messages_snapshot(target: Path, *, import_legacy: bool = True) -> dict[str, Any]:
    target = target.expanduser().resolve()
    if import_legacy:
        import_legacy_human_markdown(target)
    with closing(connect(database_path_for_target(target))) as conn:
        rows = conn.execute("SELECT * FROM human_messages ORDER BY created_at ASC, message_id ASC").fetchall()
    raw_records = [_human_row_to_record(row) for row in rows]
    archived_inbox_ids = {
        str(record.get("source_inbox_id") or "")
        for record in raw_records
        if record.get("kind") == "archive" and str(record.get("source_inbox_id") or "")
    }
    records = []
    for record in raw_records:
        record = dict(record)
        record["ui_state"] = "archived" if record["id"] in archived_inbox_ids else _human_ui_state(record["kind"], record["status"], archived_inbox_ids)
        records.append(record)
    requests = [record for record in records if record["kind"] == "request"]
    notes = [record for record in records if record["kind"] == "note"]
    archive = [record for record in records if record["kind"] == "archive"]
    outbox = [record for record in records if record["kind"] == "outbound"]
    active_requests = [record for record in requests if record.get("ui_state") == "pending"]
    active_notes = [record for record in notes if record.get("ui_state") in {"queued", "failed", "unknown"}]
    archive_items = [*archive, *[record for record in requests if record.get("ui_state") == "handled"], *[record for record in notes if record.get("ui_state") in {"archived", "consumed"}]]
    return {
        "requests": requests,
        "active_requests": active_requests,
        "notes": notes,
        "active_notes": active_notes,
        "archive": archive_items,
        "outbox": outbox,
        "counts": {
            "pending_requests": len(active_requests),
            "queued_notes": len([record for record in active_notes if record.get("ui_state") == "queued"]),
            "failed_notes": len([record for record in active_notes if record.get("ui_state") == "failed"]),
            "archived_items": len(archive_items),
            "outbound_records": len(outbox),
        },
        "raw_file_keys": [],
    }


def unhandled_human_message_count(target: Path) -> int:
    snapshot = human_messages_snapshot(target)
    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    return int(counts.get("queued_notes") or 0) + int(counts.get("failed_notes") or 0)


def normalize_ticket_run_data(data: Mapping[str, Any] | None) -> dict[str, Any]:
    normalized = dict(data or {})
    normalized.setdefault("run_id", "ticket-run")
    normalized.setdefault("halt_when_complete", True)
    normalized.setdefault("notify_on_complete", True)
    raw = normalized.get("tickets")
    normalized["tickets"] = [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    return normalized


def load_ticket_run_state(target: Path) -> dict[str, Any] | None:
    target = target.expanduser().resolve()
    with closing(connect(database_path_for_target(target))) as conn:
        projected = load_projection(conn, TICKET_RUN_PROJECTION_NAME)
        if projected:
            return normalize_ticket_run_data(projected)
        run = conn.execute("SELECT * FROM ticket_runs ORDER BY updated_at DESC LIMIT 1").fetchone()
        if run is None:
            return None
        items = conn.execute(
            "SELECT * FROM ticket_items WHERE run_id = ? ORDER BY position ASC, ticket_id ASC",
            (run["run_id"],),
        ).fetchall()
    tickets: list[dict[str, Any]] = []
    for item in items:
        try:
            payload = json.loads(str(item["payload_json"] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        ticket = dict(payload)
        ticket.update(
            {
                "id": str(item["ticket_id"]),
                "summary": str(item["summary"] or ""),
                "status": str(item["status"] or "pending"),
                "blocker": str(item["blocker"] or ""),
            }
        )
        tickets.append(ticket)
    try:
        run_payload = json.loads(str(run["payload_json"] or "{}"))
    except json.JSONDecodeError:
        run_payload = {}
    data = dict(run_payload)
    data.update(
        {
            "run_id": str(run["run_id"]),
            "halt_when_complete": bool(run["halt_when_complete"]),
            "notify_on_complete": bool(run["notify_on_complete"]),
            "tickets": tickets,
        }
    )
    if str(run["report_path"] or ""):
        data["report_path"] = str(run["report_path"])
    return normalize_ticket_run_data(data)


def write_ticket_run_state(
    target: Path,
    data: Mapping[str, Any],
    *,
    actor_role: str = "dashboard",
    event_type: str = "ticket.run_updated",
    source_path: str = "",
) -> dict[str, Any]:
    target = target.expanduser().resolve()
    normalized = normalize_ticket_run_data(data)
    run_id = str(normalized.get("run_id") or "ticket-run")
    tickets = normalized["tickets"]
    now = utc_now()
    status_counts: dict[str, int] = {}
    for item in tickets:
        status = str(item.get("status") or "pending").strip().lower()
        status = status if status in TICKET_ITEM_STATUSES else "pending"
        status_counts[status] = status_counts.get(status, 0) + 1
    run_status = "active"
    if tickets and status_counts.get("done", 0) == len(tickets):
        run_status = "complete"
    elif tickets and status_counts.get("done", 0) + status_counts.get("blocked", 0) == len(tickets):
        run_status = "blocked"

    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        event_id = append_event(
            conn,
            StateEvent(
                stream_id=TICKET_STREAM_ID,
                event_type=event_type,
                actor_role=actor_role,
                phase="ticket_run",
                status="ACTIVE" if run_status == "active" else "ACTIVE_WITH_PENDING_USER_INPUT",
                task_id=TICKET_TASK_ID,
                run_id=run_id,
                payload={"run_id": run_id, "ticket_count": len(tickets), "status": run_status, "source_path": source_path},
            ),
        )
        with conn:
            conn.execute(
                """
                INSERT INTO ticket_runs(run_id, status, halt_when_complete, notify_on_complete, ticket_file, report_path, updated_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    halt_when_complete=excluded.halt_when_complete,
                    notify_on_complete=excluded.notify_on_complete,
                    ticket_file=excluded.ticket_file,
                    report_path=excluded.report_path,
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (
                    run_id,
                    run_status,
                    1 if bool(normalized.get("halt_when_complete", True)) else 0,
                    1 if bool(normalized.get("notify_on_complete", True)) else 0,
                    source_path,
                    str(normalized.get("report_path") or ""),
                    now,
                    stable_json({key: value for key, value in normalized.items() if key != "tickets"}),
                ),
            )
            conn.execute("DELETE FROM ticket_items WHERE run_id = ?", (run_id,))
            for index, item in enumerate(tickets):
                ticket_id = str(item.get("id") or f"ticket-{index + 1:03d}").strip()
                status = str(item.get("status") or "pending").strip().lower()
                status = status if status in TICKET_ITEM_STATUSES else "pending"
                conn.execute(
                    """
                    INSERT INTO ticket_items(ticket_id, run_id, position, summary, status, blocker, updated_at, payload_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticket_id) DO UPDATE SET
                        run_id=excluded.run_id,
                        position=excluded.position,
                        summary=excluded.summary,
                        status=excluded.status,
                        blocker=excluded.blocker,
                        updated_at=excluded.updated_at,
                        payload_json=excluded.payload_json
                    """,
                    (
                        ticket_id,
                        run_id,
                        index,
                        str(item.get("summary") or ""),
                        status,
                        str(item.get("blocker") or ""),
                        now,
                        stable_json(dict(item)),
                    ),
                )
            replace_projection(conn, name=TICKET_RUN_PROJECTION_NAME, payload=normalized, event_id=event_id)
        return normalized


def ticket_run_state_summary(target: Path) -> dict[str, Any]:
    data = load_ticket_run_state(target)
    if not data:
        return {"active": False, "status": "inactive", "total": 0, "counts": {}}
    counts: dict[str, int] = {}
    tickets = data.get("tickets") if isinstance(data.get("tickets"), list) else []
    for item in tickets:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "pending").strip().lower()
        status = status if status in TICKET_ITEM_STATUSES else "pending"
        counts[status] = counts.get(status, 0) + 1
    total = sum(counts.values())
    status = "active"
    if total and counts.get("done", 0) == total:
        status = "complete"
    elif total and counts.get("done", 0) + counts.get("blocked", 0) == total and counts.get("blocked", 0):
        status = "blocked"
    return {"active": True, "run_id": str(data.get("run_id") or "ticket-run"), "status": status, "total": total, "counts": counts}


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ORCHESTRATION_TABLES:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        except sqlite3.Error:
            counts[table] = -1
        else:
            counts[table] = int(row["count"] if row else 0)
    return counts


def recent_events(conn: sqlite3.Connection, *, limit: int = DEFAULT_EVENT_LIMIT) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_id, stream_id, sequence, occurred_at, event_type, actor_role, phase,
               status, task_id, run_id, payload_sha256, prev_hash, event_hash
        FROM events
        ORDER BY event_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def open_blockers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT blocker_id, task_id, kind, status, summary, resume_token, updated_at "
        "FROM blockers WHERE status NOT IN ('closed', 'resolved', 'superseded') "
        "ORDER BY updated_at DESC LIMIT 20"
    ).fetchall()
    return [dict(row) for row in rows]


def pending_next_actions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT action_id, task_id, owner_role, kind, status, reason, priority, updated_at "
        "FROM next_actions ORDER BY priority ASC, updated_at DESC LIMIT 20"
    ).fetchall()
    return [dict(row) for row in rows]


def validation_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM validations GROUP BY status ORDER BY status"
    ).fetchall()
    latest = conn.execute(
        "SELECT validation_id, task_id, run_id, kind, command, status, finished_at "
        "FROM validations ORDER BY COALESCE(NULLIF(finished_at, ''), started_at) DESC LIMIT 10"
    ).fetchall()
    return {
        "counts": {str(row["status"]): int(row["count"]) for row in rows},
        "latest": [dict(row) for row in latest],
    }


def sqlite_integrity(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        return f"error: {exc}"
    return str(row[0]) if row else "unknown"


def journal_mode(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.Error:
        return "unknown"
    return str(row[0]) if row else "unknown"


def state_snapshot(target: Path, *, event_limit: int = DEFAULT_EVENT_LIMIT) -> dict[str, Any]:
    target = target.expanduser().resolve()
    projection_path = conveyor_projection_path_for_target(target)
    state = load_conveyor_state(projection_path)
    runner_projection_path = runner_projection_path_for_target(target)
    runner_state = load_runner_state(runner_projection_path)
    human_state = human_messages_snapshot(target, import_legacy=True)
    ticket_state = ticket_run_state_summary(target)
    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        last_event = conn.execute(
            """
            SELECT event_id, stream_id, sequence, occurred_at, event_type, actor_role,
                   phase, status, task_id, run_id, event_hash
            FROM events
            ORDER BY event_id DESC
            LIMIT 1
            """
        ).fetchone()
        checkpoint = conn.execute(
            "SELECT checkpoint_id, stream_id, sequence, kind, created_at, state_sha256 "
            "FROM checkpoints ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (CONVEYOR_PROJECTION_NAME,),
        ).fetchone()
        runner_projection_row = conn.execute(
            "SELECT name, updated_at, payload_sha256, event_id FROM projections WHERE name = ?",
            (RUNNER_PROJECTION_NAME,),
        ).fetchone()
        counts = table_counts(conn)
        projection_payload = {
            "name": CONVEYOR_PROJECTION_NAME,
            "path": str(projection_path),
            "exists": projection_path.exists(),
            "updated_at": projection_row["updated_at"] if projection_row else "",
            "payload_sha256": projection_row["payload_sha256"] if projection_row else "",
            "event_id": projection_row["event_id"] if projection_row else None,
        }
        runner_projection_payload = {
            "name": RUNNER_PROJECTION_NAME,
            "path": str(runner_projection_path),
            "exists": runner_projection_path.exists(),
            "updated_at": runner_projection_row["updated_at"] if runner_projection_row else "",
            "payload_sha256": runner_projection_row["payload_sha256"] if runner_projection_row else "",
            "event_id": runner_projection_row["event_id"] if runner_projection_row else None,
        }
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "authority": "sqlite",
            "status": "ok" if counts.get("events", 0) >= 1 and projection_row else "initializing",
            "database": {
                "path": str(db_path),
                "exists": db_path.exists(),
                "sqlite_version": sqlite3.sqlite_version,
                "journal_mode": journal_mode(conn),
                "integrity_check": sqlite_integrity(conn),
                "application_id": STATE_APPLICATION_ID,
            },
            "projection": projection_payload,
            "projections": {
                "conveyor": projection_payload,
                "runner": runner_projection_payload,
            },
            "contract": {
                "tables": list(ORCHESTRATION_TABLES),
                "status_model": list(STATUS_MODEL),
                "canonical_runtime_state": "SQLite append-only events + typed current-state projections",
                "compatibility_surfaces": [
                    "canonical Markdown state brief",
                    "conveyor/runner JSON projections",
                    "Markdown handoffs",
                    "JSON Schema exports",
                ],
            },
            "counts": counts,
            "last_event": dict(last_event) if last_event else {},
            "last_checkpoint": dict(checkpoint) if checkpoint else {},
            "recent_events": recent_events(conn, limit=event_limit),
            "open_blockers": open_blockers(conn),
            "next_actions": pending_next_actions(conn),
            "validations": validation_summary(conn),
            "conveyor_state": state,
            "runner_state": runner_state,
            "human_messages": human_state,
            "ticket_run": ticket_state,
        }


def _brief_text(value: Any, *, limit: int = BRIEF_TEXT_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def _display_path(target: Path, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if path.is_absolute():
        try:
            return path.resolve().relative_to(target).as_posix()
        except (OSError, ValueError):
            return f"<redacted:absolute>/{path.name}"
    return normalize_path_for_brief(text)


def normalize_path_for_brief(value: str) -> str:
    rel = str(value).strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")


def _brief_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _brief_sha(value: Any) -> str:
    text = str(value or "")
    return text[:12] if text else ""


def _format_key_values(values: Mapping[str, Any]) -> str:
    rendered = []
    for key, value in values.items():
        if value is None or value == "":
            continue
        rendered.append(f"{key}={_brief_text(value)}")
    return ", ".join(rendered) if rendered else "none"


def render_canonical_state_brief(snapshot: Mapping[str, Any], *, target: Path) -> str:
    """Render a bounded Markdown brief from ``state_snapshot`` for Codex agents."""

    target = target.expanduser().resolve()
    generated_at = utc_now()
    database = snapshot.get("database") if isinstance(snapshot.get("database"), dict) else {}
    conveyor_state = snapshot.get("conveyor_state") if isinstance(snapshot.get("conveyor_state"), dict) else {}
    runner_state = snapshot.get("runner_state") if isinstance(snapshot.get("runner_state"), dict) else {}
    human_state = snapshot.get("human_messages") if isinstance(snapshot.get("human_messages"), dict) else {}
    human_counts = human_state.get("counts") if isinstance(human_state.get("counts"), dict) else {}
    ticket_state = snapshot.get("ticket_run") if isinstance(snapshot.get("ticket_run"), dict) else {}
    last_event = snapshot.get("last_event") if isinstance(snapshot.get("last_event"), dict) else {}
    last_checkpoint = snapshot.get("last_checkpoint") if isinstance(snapshot.get("last_checkpoint"), dict) else {}
    validations = snapshot.get("validations") if isinstance(snapshot.get("validations"), dict) else {}
    validation_counts = validations.get("counts") if isinstance(validations.get("counts"), dict) else {}
    validation_latest = validations.get("latest") if isinstance(validations.get("latest"), list) else []
    active_role = conveyor_state.get("active_role_run") if isinstance(conveyor_state.get("active_role_run"), dict) else {}
    last_role = conveyor_state.get("last_active_role_run") if isinstance(conveyor_state.get("last_active_role_run"), dict) else {}
    last_decision = conveyor_state.get("last_decision") if isinstance(conveyor_state.get("last_decision"), dict) else {}
    decision_queue = conveyor_state.get("decision_queue") if isinstance(conveyor_state.get("decision_queue"), list) else []
    projections = snapshot.get("projections") if isinstance(snapshot.get("projections"), dict) else {}
    projection_items = [
        ("conveyor", projections.get("conveyor") if isinstance(projections.get("conveyor"), dict) else snapshot.get("projection")),
        ("runner", projections.get("runner") if isinstance(projections.get("runner"), dict) else {}),
    ]

    status = str(last_event.get("status") or conveyor_state.get("status") or "ACTIVE")
    if status not in STATUS_MODEL:
        status = "ACTIVE" if str(snapshot.get("status") or "") == "ok" else "ACTIVE_WITH_PENDING_USER_INPUT"

    lines = [
        "# Canonical State Brief",
        "",
        f"- generated_at: {generated_at}",
        "- authority: SQLite orchestration state is canonical; this file is a generated view for agents.",
        f"- database: `{_display_path(target, database.get('path'))}`",
        f"- database_exists: {_brief_bool(database.get('exists'))}",
        f"- sqlite_integrity: {_brief_text(database.get('integrity_check') or 'unknown')}",
        f"- runtime_status: `{status}`",
        "- agent_rule: read this brief at run start; do not inspect or edit the SQLite database manually.",
        "- reconciliation_rule: if Markdown or JSON projections disagree with this brief, regenerate/reconcile through Diffmogger typed state APIs.",
        "",
        "## Last State Change",
        "",
        f"- event: {_format_key_values({'id': last_event.get('event_id'), 'type': last_event.get('event_type'), 'role': last_event.get('actor_role'), 'phase': last_event.get('phase'), 'status': last_event.get('status'), 'at': last_event.get('occurred_at'), 'hash': _brief_sha(last_event.get('event_hash'))})}",
        f"- checkpoint: {_format_key_values({'id': last_checkpoint.get('checkpoint_id'), 'kind': last_checkpoint.get('kind'), 'sequence': last_checkpoint.get('sequence'), 'at': last_checkpoint.get('created_at'), 'sha': _brief_sha(last_checkpoint.get('state_sha256'))})}",
        "",
        "## Runner And Conveyor",
        "",
        f"- conveyor_cycles: {int(conveyor_state.get('cycles') or 0)}",
        f"- last_decision: {_format_key_values({'role': last_decision.get('role') or 'idle', 'reason': last_decision.get('reason'), 'decided_at': last_decision.get('decided_at')})}",
        f"- active_role: {_format_key_values({'role': active_role.get('role'), 'run_id': active_role.get('run_id'), 'status': active_role.get('status'), 'started_at': active_role.get('started_at'), 'reason': active_role.get('reason')})}",
        f"- last_role_run: {_format_key_values({'role': last_role.get('role'), 'run_id': last_role.get('run_id'), 'status': last_role.get('status'), 'exit_code': last_role.get('exit_code'), 'finished_at': last_role.get('finished_at')})}",
        f"- runner: {_format_key_values({'state': runner_state.get('state'), 'pid': runner_state.get('pid'), 'run_id': runner_state.get('run_id'), 'started_at': runner_state.get('started_at'), 'updated_at': runner_state.get('updated_at')})}",
        f"- human_messages: {_format_key_values({'pending_requests': human_counts.get('pending_requests'), 'queued_notes': human_counts.get('queued_notes'), 'failed_notes': human_counts.get('failed_notes'), 'outbound_records': human_counts.get('outbound_records')})}",
        f"- ticket_run: {_format_key_values({'status': ticket_state.get('status'), 'run_id': ticket_state.get('run_id'), 'total': ticket_state.get('total'), 'counts': stable_json(ticket_state.get('counts')) if isinstance(ticket_state.get('counts'), dict) else ''})}",
        "",
        "## Queued Decisions",
        "",
    ]
    if decision_queue:
        for item in decision_queue[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('role') or 'idle')}: {str(item.get('state') or 'planned')} - {_brief_text(item.get('reason'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Pending Next Actions", ""])
    next_actions = snapshot.get("next_actions") if isinstance(snapshot.get("next_actions"), list) else []
    if next_actions:
        for item in next_actions[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('owner_role') or 'idle')}: {str(item.get('status') or 'planned')} - {_brief_text(item.get('reason'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Open Blockers", ""])
    blockers = snapshot.get("open_blockers") if isinstance(snapshot.get("open_blockers"), list) else []
    if blockers:
        for item in blockers[:BRIEF_ITEM_LIMIT]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('kind') or 'blocker')}: {str(item.get('status') or 'open')} - {_brief_text(item.get('summary'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Validation Summary", ""])
    lines.append(f"- counts: {_format_key_values(validation_counts)}")
    if validation_latest:
        for item in validation_latest[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- latest: {str(item.get('kind') or 'validation')} {str(item.get('status') or 'unknown')} - {_brief_text(item.get('command'), limit=160)}"
            )
    else:
        lines.append("- latest: none")

    lines.extend(["", "## Projection Freshness", ""])
    for name, projection in projection_items:
        projection = projection if isinstance(projection, dict) else {}
        lines.append(
            f"- {name}: path=`{_display_path(target, projection.get('path'))}`, exists={_brief_bool(projection.get('exists'))}, updated_at={_brief_text(projection.get('updated_at') or 'never')}, event_id={projection.get('event_id') or 'none'}, sha={_brief_sha(projection.get('payload_sha256')) or 'none'}"
        )

    return "\n".join(lines).rstrip() + "\n"


def write_canonical_state_brief(target: Path, *, output_path: Path | None = None) -> dict[str, Any]:
    target = target.expanduser().resolve()
    snapshot = state_snapshot(target, event_limit=8)
    if output_path:
        raw_output = output_path.expanduser()
        brief_path = raw_output.resolve() if raw_output.is_absolute() else (target / raw_output).resolve()
    else:
        brief_path = canonical_state_brief_path_for_target(target)
    if target not in brief_path.parents and brief_path != target:
        raise ValueError(f"canonical state brief output must stay inside target: {brief_path}")
    markdown = render_canonical_state_brief(snapshot, target=target)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = brief_path.with_name(f".{brief_path.name}.tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(brief_path)
    digest = sha256_text(markdown)
    db_path = database_path_for_target(target)
    with closing(connect(db_path)) as conn:
        replace_projection(
            conn,
            name=CANONICAL_STATE_BRIEF_PROJECTION_NAME,
            payload={
                "format": "markdown",
                "path": str(brief_path),
                "payload_sha256": digest,
                "generated_at": utc_now(),
                "note": "Generated agent-readable view of canonical SQLite state.",
            },
            event_id=None,
        )
    return {
        "path": str(brief_path),
        "relative_path": _display_path(target, brief_path),
        "payload_sha256": digest,
        "markdown": markdown,
        "snapshot": snapshot,
    }


def validate_state_database(target: Path) -> dict[str, Any]:
    snapshot = state_snapshot(target)
    counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    missing_tables = [table for table in ORCHESTRATION_TABLES if int(counts.get(table, -1)) < 0]
    items = [
        {
            "ok": snapshot["database"]["exists"],
            "detail": f"Canonical SQLite database exists at {snapshot['database']['path']}.",
        },
        {
            "ok": snapshot["database"]["integrity_check"] == "ok",
            "detail": f"SQLite integrity_check: {snapshot['database']['integrity_check']}.",
        },
        {
            "ok": not missing_tables,
            "detail": "Required typed state tables present."
            if not missing_tables
            else "Missing typed state tables: " + ", ".join(missing_tables),
        },
        {
            "ok": bool(snapshot["projection"]["exists"]),
            "detail": "Compatibility conveyor JSON projection is generated from SQLite."
            if snapshot["projection"]["exists"]
            else "Compatibility conveyor JSON projection is missing.",
        },
    ]
    return {
        "status": "pass" if all(item["ok"] for item in items) else "fail",
        "items": items,
        "snapshot": snapshot,
    }
