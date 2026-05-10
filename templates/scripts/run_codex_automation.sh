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

def normalize_rel(value: str) -> str:
    rel = str(value).strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")

def rel(path: str) -> str:
    if not sidecar:
        return path
    if path in aliases:
        return normalize_rel(str(aliases[path]))
    for old, new in sorted(aliases.items(), key=lambda item: len(str(item[0])), reverse=True):
        old = normalize_rel(str(old)).rstrip("/")
        new = normalize_rel(str(new)).rstrip("/")
        if old and path.startswith(old + "/"):
            return new + path[len(old):]
    return normalize_rel(path)

values = {
    "automation_prompt_path": target / rel(".agentic/automation_prompt.md"),
    "project_intake_path": target / rel(".agentic/project_intake.json"),
    "task_file_path": target / rel("docs/CODEX_AUTOMATION_TASKS.md"),
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

normalize_task_state_headings() {
  if [ ! -f "$task_file_path" ]; then
    return 0
  fi
  python3 - "$task_file_path" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
replacements = {
    "## Completed This Run": "## Completed Last Run",
    "## Checks Run And Results": "## Checks From Last Run",
}
try:
    text = path.read_text(encoding="utf-8")
except OSError:
    raise SystemExit(0)
updated = text
for old, new in replacements.items():
    updated = updated.replace(old, new)
if updated != text:
    path.write_text(updated, encoding="utf-8")
    print(f"TASK_HEADINGS_NORMALIZED path={path}")
PY
}

single_lane_commit_enabled() {
  if [ "${DIFFMOGGER_SINGLE_LANE_COMMITS:-}" = "0" ] || [ "${DIFFMOGGER_SINGLE_LANE_COMMITS:-}" = "false" ]; then
    return 1
  fi
  python3 - "$project_intake_path" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
value = data.get("automation_checkpoint_commits", True)
if isinstance(value, bool):
    raise SystemExit(0 if value else 1)
text = str(value).strip().lower()
raise SystemExit(1 if text in {"0", "false", "no", "off"} else 0)
PY
}

single_lane_commit_pathspecs() {
  python3 - "$TARGET" <<'PY'
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1])
result = subprocess.run(
    ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
    cwd=target,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    check=False,
)
if result.returncode != 0:
    raise SystemExit(0)

blocked_exact = {"AGENTS.md"}
blocked_dirs = {".git", ".diffmogger"}
skipped_secret_count = 0
paths: list[str] = []
records = result.stdout.split(b"\0")
index = 0
while index < len(records):
    record = records[index]
    index += 1
    if not record:
        continue
    status = record[:2].decode("utf-8", errors="replace")
    raw_path = record[3:]
    path = raw_path.decode("utf-8", errors="surrogateescape")
    if status[0] in {"R", "C"} and index < len(records):
        index += 1
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    parts = [part for part in normalized.split("/") if part]
    name = parts[-1] if parts else ""
    if not normalized or normalized in blocked_exact or any(part in blocked_dirs for part in parts):
        continue
    if normalized.startswith("target/"):
        continue
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        skipped_secret_count += 1
        continue
    paths.append(normalized)

for path in sorted(set(paths)):
    sys.stdout.buffer.write(path.encode("utf-8", errors="surrogateescape") + b"\0")
if skipped_secret_count:
    print(
        f"SINGLE_LANE_COMMIT_SKIPPED_SECRET_PATHS count={skipped_secret_count}",
        file=sys.stderr,
    )
PY
}

staged_single_lane_unsafe_paths() {
  python3 - <<'PY'
import subprocess
import sys

result = subprocess.run(
    ["git", "diff", "--cached", "--name-only", "-z"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    check=False,
)
if result.returncode != 0:
    raise SystemExit(0)

unsafe: list[str] = []
for item in result.stdout.split(b"\0"):
    if not item:
        continue
    path = item.decode("utf-8", errors="surrogateescape").replace("\\", "/")
    parts = [part for part in path.split("/") if part]
    name = parts[-1] if parts else ""
    if any(part in {".git", ".diffmogger"} for part in parts):
        unsafe.append(path)
    elif path == "AGENTS.md" or path.startswith("target/"):
        unsafe.append(path)
    elif name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        unsafe.append(path)
for path in unsafe[:20]:
    print(path)
if len(unsafe) > 20:
    print(f"... {len(unsafe) - 20} more")
PY
}

commit_single_lane_changes() {
  if ! single_lane_commit_enabled; then
    printf 'SINGLE_LANE_COMMIT_DISABLED automation_checkpoint_commits=false\n'
    return 0
  fi
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'WARN: single-lane checkpoint commit skipped; target is not a git worktree.\n' >&2
    return 0
  fi
  if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    printf 'WARN: single-lane checkpoint commit skipped; target has no HEAD commit.\n' >&2
    return 0
  fi

  mkdir -p "$logs_dir"
  pathspec_file="$logs_dir/single_lane_commit_paths.${CODEX_RUN_ID}.nul"
  single_lane_commit_pathspecs >"$pathspec_file"
  if [ ! -s "$pathspec_file" ]; then
    rm -f "$pathspec_file"
    printf 'SINGLE_LANE_COMMIT_SKIPPED reason=no_changes\n'
    return 0
  fi

  if ! git add -A --pathspec-from-file="$pathspec_file" --pathspec-file-nul; then
    rm -f "$pathspec_file"
    printf 'ERROR: single-lane checkpoint git add failed.\n' >&2
    return 1
  fi
  rm -f "$pathspec_file"

  if git diff --cached --quiet --exit-code; then
    printf 'SINGLE_LANE_COMMIT_SKIPPED reason=no_committable_changes\n'
    return 0
  fi
  unsafe_paths="$(staged_single_lane_unsafe_paths)"
  if [ -n "$unsafe_paths" ]; then
    printf 'ERROR: refusing single-lane checkpoint commit with unsafe staged path(s):\n%s\n' "$unsafe_paths" >&2
    return 1
  fi

  commit_env=(
    "GIT_AUTHOR_NAME=Diffmogger Single Lane"
    "GIT_AUTHOR_EMAIL=diffmogger-single-lane@example.invalid"
    "GIT_COMMITTER_NAME=Diffmogger Single Lane"
    "GIT_COMMITTER_EMAIL=diffmogger-single-lane@example.invalid"
  )
  if ! env "${commit_env[@]}" git commit --no-verify \
    -m "chore(single-lane): checkpoint automation run ${CODEX_RUN_ID}" \
    -m "Run: ${CODEX_RUN_ID}"; then
    printf 'ERROR: single-lane checkpoint git commit failed.\n' >&2
    return 1
  fi
  commit_hash="$(git rev-parse --short HEAD 2>/dev/null || true)"
  printf 'SINGLE_LANE_COMMIT_CREATED hash=%s run_id=%s\n' "$commit_hash" "$CODEX_RUN_ID"
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
lock_context="${CODEX_LOCK_CONTEXT:-${target_name} automation sprint}"
bash "$runner_script_dir/acquire_codex_lock.sh" "$lock_context" || exit 0
export CODEX_LOCK_ALREADY_ACQUIRED="true"

if maybe_finalize_ticket_campaign; then
  exit 0
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

if [ "$exit_code" = "0" ]; then
  finalizer_exit=1
  maybe_finalize_ticket_campaign
  finalizer_exit="$?"
  normalize_task_state_headings
  commit_single_lane_changes || exit "$?"
  if [ "$finalizer_exit" = "0" ]; then
    exit 0
  fi
fi

exit "$exit_code"
