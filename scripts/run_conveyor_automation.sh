#!/usr/bin/env bash
set -euo pipefail

export TARGET="${TARGET:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

cd "$TARGET"

load_codex_automation_env() {
  if [ "${CODEX_AUTOMATION_ENV_LOADED:-}" = "1" ]; then
    return 0
  fi
  if [ -f "$TARGET/scripts/load_automation_env.py" ]; then
    exec python3 "$TARGET/scripts/load_automation_env.py" --target "$TARGET" -- "${BASH:-bash}" "$0" "$@"
  fi
  export CODEX_AUTOMATION_ENV_LOADED="1"
}

load_codex_automation_env "$@"

if [ -n "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ]; then
  export CHROME_PATH="$DIFFMOGGER_BROWSER_PATH"
elif [ -z "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ] && [ -f "scripts/diffmogger_browser.py" ]; then
  browser_env="$(python3 scripts/diffmogger_browser.py env 2>/dev/null || true)"
  if [ -n "$browser_env" ]; then
    eval "$browser_env"
  fi
fi
if [ -n "${DIFFMOGGER_BROWSER_PATH:-}" ]; then
  export PLAYWRIGHT_MCP_EXECUTABLE_PATH="${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-$DIFFMOGGER_BROWSER_PATH}"
elif [ -n "${CHROME_PATH:-}" ]; then
  export PLAYWRIGHT_MCP_EXECUTABLE_PATH="${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-$CHROME_PATH}"
fi

exec python3 scripts/run_conveyor_automation.py --target "$TARGET" "$@"
