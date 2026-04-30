from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


class JsonlDedupeStore:
    def __init__(self, path: Path, key_field: str):
        self.path = Path(path)
        self.key_field = key_field
        self._lock = Lock()

    def contains(self, key: str) -> bool:
        if not key or not self.path.exists():
            return False
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get(self.key_field) == key:
                    return True
        return False

    def record(self, key: str, metadata: dict[str, Any] | None = None) -> bool:
        if not key:
            return False
        with self._lock:
            if self.contains(key):
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                self.key_field: key,
                "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            if metadata:
                record.update(metadata)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            return True

    def check_and_record(self, key: str, metadata: dict[str, Any] | None = None) -> bool:
        return self.record(key, metadata=metadata)

