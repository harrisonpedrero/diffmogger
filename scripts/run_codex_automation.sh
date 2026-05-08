#!/usr/bin/env bash
set -u

runner_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
script_parent="$(cd "$runner_script_dir/.." && pwd)"
if [ "$(basename "$script_parent")" = ".diffmogger" ]; then
  default_target="$(cd "$script_parent/.." && pwd)"
else
  default_target="$script_parent"
fi
export TARGET="${TARGET:-$default_target}"
export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
default_codex_lock_path="$TARGET/target/codex_automation.lock"
export CODEX_LOCK_PATH="${CODEX_LOCK_PATH:-$default_codex_lock_path}"
export CODEX_LOCK_ALREADY_ACQUIRED="false"
child_pid=""

cd "$TARGET" || exit 1

eval "$(
  python3 - "$TARGET" "$CODEX_RUN_ID" <<'PY'
import json
import shlex
import sys
from pathlib import Path

target = Path(sys.argv[1])
run_id = sys.argv[2]
try:
    manifest = json.loads((target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8"))
except Exception:
    manifest = {}
sidecar = manifest.get("layout") == "sidecar_v1"
aliases = manifest.get("path_aliases") if isinstance(manifest.get("path_aliases"), dict) else {}

def rel(path: str) -> str:
    if not sidecar:
        return path
    if path in aliases:
        return str(aliases[path]).strip().lstrip("./")
    for old, new in sorted(aliases.items(), key=lambda item: len(str(item[0])), reverse=True):
        old = str(old).strip().lstrip("./").rstrip("/")
        new = str(new).strip().lstrip("./").rstrip("/")
        if old and path.startswith(old + "/"):
            return new + path[len(old):]
    return path

values = {
    "automation_prompt_path": target / rel(".agentic/automation_prompt.md"),
    "signal_docs_path": target / rel("docs/AUTOMATION_SIGNALS.md"),
    "logs_dir": target / rel("target/automation_logs"),
    "lock_path": target / rel("target/codex_automation.lock"),
    "mcp_config_path": target / rel(".codex/config.toml"),
    "playwright_mcp_rel": rel("scripts/run_playwright_mcp.sh"),
    "playwright_artifact_rel": rel(f"docs/backlog/ui_artifacts/{run_id}"),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

if [ "$CODEX_LOCK_PATH" = "$default_codex_lock_path" ]; then
  export CODEX_LOCK_PATH="$lock_path"
fi

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

configure_diffmogger_browser() {
  if [ -n "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ]; then
    export CHROME_PATH="$DIFFMOGGER_BROWSER_PATH"
  fi
  if [ -z "${DIFFMOGGER_BROWSER_PATH:-}" ] && [ -z "${CHROME_PATH:-}" ] && [ -f "$runner_script_dir/diffmogger_browser.py" ]; then
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
  export PLAYWRIGHT_MCP_OUTPUT_DIR="${PLAYWRIGHT_MCP_OUTPUT_DIR:-$playwright_artifact_rel}"
}

configure_diffmogger_browser

maybe_finalize_ticket_campaign() {
  if [ -f "$runner_script_dir/ticket_run.py" ]; then
    python3 "$runner_script_dir/ticket_run.py" . should-halt --finalize
    return "$?"
  fi
  return 1
}

CODEX_PARENT_ARGS=()
toml_quote() {
  value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

append_context7_mcp_args() {
  CODEX_PARENT_ARGS+=(
    -c 'mcp_servers.context7.command="npx"'
    -c 'mcp_servers.context7.args=["-y","@upstash/context7-mcp"]'
    -c 'mcp_servers.context7.enabled=true'
    -c 'mcp_servers.context7.required=false'
    -c 'mcp_servers.context7.startup_timeout_sec=20'
    -c 'mcp_servers.context7.tool_timeout_sec=60'
    -c 'mcp_servers.context7.env_vars=["CONTEXT7_API_KEY"]'
  )
}

append_playwright_mcp_args() {
  CODEX_PARENT_ARGS+=(
    -c 'mcp_servers.playwright.command="bash"'
    -c "mcp_servers.playwright.args=[$(toml_quote "$playwright_mcp_rel")]"
    -c 'mcp_servers.playwright.enabled=true'
    -c 'mcp_servers.playwright.required=false'
    -c 'mcp_servers.playwright.disabled_tools=["browser_run_code_unsafe","browser_file_upload"]'
    -c 'mcp_servers.playwright.startup_timeout_sec=20'
    -c 'mcp_servers.playwright.tool_timeout_sec=60'
    -c "mcp_servers.playwright.env.PLAYWRIGHT_MCP_OUTPUT_DIR=$(toml_quote "$PLAYWRIGHT_MCP_OUTPUT_DIR")"
  )
  if [ -n "${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-}" ]; then
    CODEX_PARENT_ARGS+=(
      -c "mcp_servers.playwright.env.PLAYWRIGHT_MCP_EXECUTABLE_PATH=$(toml_quote "$PLAYWRIGHT_MCP_EXECUTABLE_PATH")"
    )
  fi
}

if [ -f "$mcp_config_path" ]; then
  CODEX_PARENT_ARGS+=(
    -c 'mcp_servers.context7.enabled=false'
    -c 'mcp_servers.playwright.enabled=false'
  )
  if grep -q "mcp_servers.context7" "$mcp_config_path"; then
    append_context7_mcp_args
  fi
  if grep -q "mcp_servers.playwright" "$mcp_config_path"; then
    append_playwright_mcp_args
  fi
fi
if [ "${CODEX_ENABLE_NESTED_CLI_HOME:-true}" = "true" ] && [ -n "${HOME:-}" ]; then
  export CODEX_NESTED_CLI_HOME="${CODEX_NESTED_CLI_HOME:-$HOME/.codex}"
  if mkdir -p "$CODEX_NESTED_CLI_HOME"; then
    CODEX_PARENT_ARGS+=(--add-dir "$CODEX_NESTED_CLI_HOME")
  else
    printf 'WARN: could not create CODEX_NESTED_CLI_HOME=%s; nested Codex CLI workers may be unavailable.\n' "$CODEX_NESTED_CLI_HOME" >&2
  fi
fi

release_lock() {
  if [ "${CODEX_LOCK_ALREADY_ACQUIRED:-false}" = "true" ]; then
    bash "$runner_script_dir/release_codex_lock.sh" || true
  fi
}

forward_signal() {
  signal="$1"
  exit_code="$2"
  if [ -n "${child_pid:-}" ] && kill -0 "$child_pid" >/dev/null 2>&1; then
    kill "-$signal" "$child_pid" >/dev/null 2>&1 || true
    wait "$child_pid" >/dev/null 2>&1 || true
  fi
  exit "$exit_code"
}

trap release_lock EXIT
trap 'forward_signal TERM 143' TERM
trap 'forward_signal INT 130' INT

target_name="$(basename "$TARGET")"
lock_context="${CODEX_LOCK_CONTEXT:-${target_name} scheduled sprint}"
bash "$runner_script_dir/acquire_codex_lock.sh" "$lock_context" || exit 0
export CODEX_LOCK_ALREADY_ACQUIRED="true"

if maybe_finalize_ticket_campaign; then
  exit 0
fi

if [ -f "$runner_script_dir/update_automation_signals.py" ] && [ -f "$signal_docs_path" ]; then
  python3 "$runner_script_dir/update_automation_signals.py" . --refresh --summary || true
fi

mkdir -p "$logs_dir"
run_stdout="$logs_dir/codex.${CODEX_RUN_ID}.stdout.log"
run_stderr="$logs_dir/codex.${CODEX_RUN_ID}.stderr.log"
watchdog_status_path="$logs_dir/codex.${CODEX_RUN_ID}.watchdog.json"
env_repair_path="$logs_dir/codex.${CODEX_RUN_ID}.environment_repair.json"
rerun_stdout="$logs_dir/codex.${CODEX_RUN_ID}.rerun.stdout.log"
rerun_stderr="$logs_dir/codex.${CODEX_RUN_ID}.rerun.stderr.log"
rerun_watchdog_status_path="$logs_dir/codex.${CODEX_RUN_ID}.rerun.watchdog.json"

watchdog_helper="$runner_script_dir/run_process_watchdog.py"

run_with_watchdog() {
  stdout_file="$1"
  stderr_file="$2"
  status_file="$3"
  shift 3
  python3 "$watchdog_helper" \
    --stdout-file "$stdout_file" \
    --stderr-file "$stderr_file" \
    --status-file "$status_file" \
    -- "$@"
}

append_watchdog_status() {
  status_file="$1"
  log_file="$2"
  if [ -f "$status_file" ]; then
    {
      printf '\n=== process watchdog status ===\n'
      cat "$status_file"
    } >>"$log_file"
  fi
}

run_with_watchdog "$run_stdout" "$run_stderr" "$watchdog_status_path" \
  codex exec --full-auto --skip-git-repo-check "${CODEX_PARENT_ARGS[@]}" "$(cat "$automation_prompt_path")" &
child_pid="$!"
wait "$child_pid"
exit_code="$?"
child_pid=""
append_watchdog_status "$watchdog_status_path" "$run_stderr"
cat "$run_stdout"
cat "$run_stderr" >&2

if [ "$exit_code" != "0" ] && [ "$exit_code" != "124" ] && [ -f "$runner_script_dir/repair_environment.py" ]; then
  repair_status=0
  python3 "$runner_script_dir/repair_environment.py" . \
    --command "codex exec single-lane automation" \
    --exit-code "$exit_code" \
    --stdout-file "$run_stdout" \
    --stderr-file "$run_stderr" \
    --status-file "$env_repair_path" >/dev/null 2>&1 || repair_status=$?
  if python3 - "$env_repair_path" <<'PY'
import json
import sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if data.get("repair_performed") else 1)
PY
  then
    while IFS= read -r path_item; do
      if [ -n "$path_item" ]; then
        export PATH="$path_item:$PATH"
      fi
    done <<EOF
$(python3 - "$env_repair_path" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in data.get("path_prepend") or []:
    print(item)
PY
)
EOF
    printf 'Environment repair attempted; repair_status=%s\n' "$repair_status"
    cat "$env_repair_path"
    run_with_watchdog "$rerun_stdout" "$rerun_stderr" "$rerun_watchdog_status_path" \
      codex exec --full-auto --skip-git-repo-check "${CODEX_PARENT_ARGS[@]}" "$(cat "$automation_prompt_path")" &
    child_pid="$!"
    wait "$child_pid"
    exit_code="$?"
    child_pid=""
    append_watchdog_status "$rerun_watchdog_status_path" "$rerun_stderr"
    cat "$rerun_stdout"
    cat "$rerun_stderr" >&2
  fi
fi

if [ "$exit_code" = "0" ] && maybe_finalize_ticket_campaign; then
  exit 0
fi

exit "$exit_code"
