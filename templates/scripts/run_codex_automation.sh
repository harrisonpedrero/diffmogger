#!/usr/bin/env bash
set -u

export TARGET="${TARGET:-$(cd "$(dirname "$0")/.." && pwd)}"
export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
export CODEX_LOCK_PATH="${CODEX_LOCK_PATH:-$TARGET/target/codex_automation.lock}"
export CODEX_LOCK_ALREADY_ACQUIRED="false"
child_pid=""

cd "$TARGET" || exit 1

CODEX_PARENT_ARGS=()
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
    bash scripts/release_codex_lock.sh || true
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

bash scripts/acquire_codex_lock.sh "{{PROJECT_NAME}} scheduled sprint" || exit 0
export CODEX_LOCK_ALREADY_ACQUIRED="true"

codex exec --full-auto --skip-git-repo-check "${CODEX_PARENT_ARGS[@]}" "$(cat .agentic/automation_prompt.md)" &
child_pid="$!"
wait "$child_pid"
exit_code="$?"
child_pid=""
exit "$exit_code"
