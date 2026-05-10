from __future__ import annotations

from .common import *

def signals_snapshot(target: Path) -> dict[str, Any]:
    return {
        "active_count": 0,
        "active": [],
        "recent_completed": [],
        "updated_at": "retired",
    }
