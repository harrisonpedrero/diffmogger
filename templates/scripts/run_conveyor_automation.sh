#!/usr/bin/env bash
set -euo pipefail

export TARGET="${TARGET:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

cd "$TARGET"
exec python3 scripts/run_conveyor_automation.py --target "$TARGET" "$@"
