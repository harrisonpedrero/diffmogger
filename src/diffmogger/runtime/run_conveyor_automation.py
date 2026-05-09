#!/usr/bin/env python3
"""Compatibility entrypoint for the Diffmogger automation conveyor."""

from __future__ import annotations

import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from diffmogger.conveyor import *  # noqa: F401,F403
from diffmogger.conveyor.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
