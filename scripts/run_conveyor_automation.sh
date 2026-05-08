#!/usr/bin/env bash
set -euo pipefail

runner_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
script_parent="$(cd "$runner_script_dir/.." && pwd)"
if [ "$(basename "$script_parent")" = ".diffmogger" ]; then
  default_target="$(cd "$script_parent/.." && pwd)"
else
  default_target="$script_parent"
fi
export TARGET="${TARGET:-$default_target}"
export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

cd "$TARGET"

load_codex_automation_env() {
  if [ "${CODEX_AUTOMATION_ENV_LOADED:-}" = "1" ]; then
    return 0
  fi
  if [ -f "$runner_script_dir/load_automation_env.py" ]; then
    exec python3 "$runner_script_dir/load_automation_env.py" --target "$TARGET" -- "${BASH:-bash}" "$0" "$@"
  fi
  export CODEX_AUTOMATION_ENV_LOADED="1"
}

load_codex_automation_env "$@"

if [ -n "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ]; then
  export CHROME_PATH="$DIFFMOGGER_BROWSER_PATH"
elif [ -z "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ] && [ -f "$runner_script_dir/diffmogger_browser.py" ]; then
  browser_env="$(python3 "$runner_script_dir/diffmogger_browser.py" env 2>/dev/null || true)"
  if [ -n "$browser_env" ]; then
    eval "$browser_env"
  fi
fi
if [ -n "${DIFFMOGGER_BROWSER_PATH:-}" ]; then
  export PLAYWRIGHT_MCP_EXECUTABLE_PATH="${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-$DIFFMOGGER_BROWSER_PATH}"
elif [ -n "${CHROME_PATH:-}" ]; then
  export PLAYWRIGHT_MCP_EXECUTABLE_PATH="${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-$CHROME_PATH}"
fi

exec python3 "$runner_script_dir/run_conveyor_automation.py" --target "$TARGET" "$@"
