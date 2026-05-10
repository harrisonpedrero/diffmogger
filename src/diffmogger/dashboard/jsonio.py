from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import BackendError


SCHEMA_VERSION = 1
MAX_TEXT_BYTES = 1_000_000
MAX_HTML_BYTES = 5_000_000

def json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)

def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))

def emit_jsonl(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, default=json_default), flush=True)

def success(command: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": command,
        "data": data,
    }

def failure(command: str, error: BackendError) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "command": command,
        "message": error.message,
        "error": {
            "type": error.error_type,
            "details": error.details,
        },
    }

def stream_event(
    args: argparse.Namespace,
    stage: str,
    message: str,
    *,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    if not bool(getattr(args, "stream_jsonl", False)):
        return
    emit_jsonl(
        {
            "schema_version": SCHEMA_VERSION,
            "event": "log",
            "stage": stage,
            "level": level,
            "message": message,
            "data": data or {},
        }
    )

def read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}

def read_text_file(path: Path, *, max_bytes: int = MAX_TEXT_BYTES) -> tuple[str, bool]:
    with path.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    truncated = len(payload) > max_bytes
    if truncated:
        payload = payload[:max_bytes]
    return payload.decode("utf-8", errors="replace"), truncated

def parse_json_arg(raw: str, *, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackendError(
            f"{label} must be valid JSON.",
            exit_code=2,
            error_type="invalid_json",
            details={"label": label, "exception": str(exc)},
        ) from exc

def mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return None

def compact_text(value: Any, *, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", "" if value is None else str(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."

def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
