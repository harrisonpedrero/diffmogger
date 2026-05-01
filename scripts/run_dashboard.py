#!/usr/bin/env python3
"""Launch the standalone Diffmogger dashboard."""

from __future__ import annotations

import sys
from pathlib import Path


KIT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = KIT_ROOT / "services" / "agentic-dashboard"
sys.path.insert(0, str(DASHBOARD_ROOT))

from agentic_dashboard.app import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
