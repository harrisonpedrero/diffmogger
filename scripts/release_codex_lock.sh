#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/release_codex_lock.sh

Release the local Codex automation lock when it appears to belong to this run.

Environment:
  CODEX_LOCK_PATH          Lock file path. Default: target/codex_automation.lock
  CODEX_RUN_ID or RUN_ID   Current run id. Preferred release identity.
  CODEX_LOCK_OWNER_PID     Owner PID. Default: parent shell PID.
  CODEX_LOCK_FORCE_RELEASE Set true to remove without identity match.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

lock_path="${CODEX_LOCK_PATH:-target/codex_automation.lock}"
current_run_id="${CODEX_RUN_ID:-${RUN_ID:-}}"
current_owner_pid="${CODEX_LOCK_OWNER_PID:-${PPID:-$$}}"
force="${CODEX_LOCK_FORCE_RELEASE:-false}"

if [[ ! -e "$lock_path" ]]; then
  printf 'LOCK_NOT_FOUND path=%s\n' "$lock_path"
  exit 0
fi

read_field() {
  local key="$1"
  local path="$2"
  sed -n "s/^${key}=//p" "$path" 2>/dev/null | head -n 1
}

process_alive() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1
}

lock_run_id="$(read_field run_id "$lock_path")"
lock_pid="$(read_field pid "$lock_path")"

if [[ "$force" =~ ^(1|true|yes|on)$ ]]; then
  rm -f "$lock_path"
  printf 'LOCK_RELEASED path=%s reason=forced\n' "$lock_path"
  exit 0
fi

if [[ -n "$current_run_id" && "$current_run_id" == "$lock_run_id" ]]; then
  rm -f "$lock_path"
  printf 'LOCK_RELEASED path=%s run_id=%s\n' "$lock_path" "$current_run_id"
  exit 0
fi

if [[ -z "$current_run_id" && -n "$lock_pid" && "$lock_pid" == "$current_owner_pid" ]]; then
  rm -f "$lock_path"
  printf 'LOCK_RELEASED path=%s pid=%s\n' "$lock_path" "$current_owner_pid"
  exit 0
fi

if [[ -z "$current_run_id" && -n "$lock_pid" ]] && ! process_alive "$lock_pid"; then
  rm -f "$lock_path"
  printf 'LOCK_RELEASED path=%s reason=dead-owner-pid pid=%s\n' "$lock_path" "$lock_pid"
  exit 0
fi

echo "Refusing to release Codex lock that does not match this run." >&2
echo "lock_path=$lock_path lock_run_id=${lock_run_id:-unknown} lock_pid=${lock_pid:-unknown}" >&2
echo "current_run_id=${current_run_id:-unset} current_owner_pid=$current_owner_pid" >&2
exit 1
