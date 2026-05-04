#!/usr/bin/env bash
set -euo pipefail

export TARGET="${TARGET:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

cd "$TARGET"

if [ -n "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ]; then
  export CHROME_PATH="$DIFFMOGGER_BROWSER_PATH"
elif [ -z "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ] && [ -f "scripts/diffmogger_browser.py" ]; then
  browser_env="$(python3 scripts/diffmogger_browser.py env 2>/dev/null || true)"
  if [ -n "$browser_env" ]; then
    eval "$browser_env"
  fi
fi

exec python3 scripts/run_conveyor_automation.py --target "$TARGET" "$@"
