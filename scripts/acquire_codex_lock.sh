#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/acquire_codex_lock.sh [context...]

Acquire a local Codex automation lock.

Environment:
  CODEX_LOCK_PATH             Lock file path. Default: target/codex_automation.lock
  CODEX_LOCK_STALE_SECONDS    Stale threshold in seconds. Default: 14400
  CODEX_RUN_ID or RUN_ID      Run id to record in the lock. Generated if absent.
  CODEX_LOCK_CONTEXT          Context string to record. Positional args are used if set.
  CODEX_LOCK_OWNER_PID        Owner PID to record. Default: parent shell PID.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

lock_path="${CODEX_LOCK_PATH:-target/codex_automation.lock}"
stale_seconds="${CODEX_LOCK_STALE_SECONDS:-14400}"
run_id="${CODEX_RUN_ID:-${RUN_ID:-}}"
context="${CODEX_LOCK_CONTEXT:-$*}"
owner_pid="${CODEX_LOCK_OWNER_PID:-${PPID:-$$}}"

if [[ -z "$run_id" ]]; then
  run_id="$(date -u +%Y%m%dT%H%M%SZ)-$owner_pid"
fi

if ! [[ "$stale_seconds" =~ ^[0-9]+$ ]] || [[ "$stale_seconds" -lt 60 ]]; then
  echo "Invalid CODEX_LOCK_STALE_SECONDS: $stale_seconds" >&2
  exit 2
fi

lock_dir="$(dirname "$lock_path")"
mkdir -p "$lock_dir"

now_epoch="$(date +%s)"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
host="$(hostname 2>/dev/null || printf 'unknown')"
command_name="$(basename "${SHELL:-bash}")"
context_one_line="$(printf '%s' "$context" | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g')"

stat_mtime() {
  local path="$1"
  if stat -f %m "$path" >/dev/null 2>&1; then
    stat -f %m "$path"
  else
    stat -c %Y "$path"
  fi
}

read_field() {
  local key="$1"
  local path="$2"
  sed -n "s/^${key}=//p" "$path" 2>/dev/null | head -n 1
}

process_alive() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1
}

write_lock_once() {
  local tmp
  tmp="$(mktemp "${lock_dir}/.codex-lock.XXXXXX")"
  {
    printf 'pid=%s\n' "$owner_pid"
    printf 'run_id=%s\n' "$run_id"
    printf 'created_at=%s\n' "$created_at"
    printf 'created_at_epoch=%s\n' "$now_epoch"
    printf 'stale_after_seconds=%s\n' "$stale_seconds"
    printf 'host=%s\n' "$host"
    printf 'command=%s\n' "$command_name"
    printf 'context=%s\n' "$context_one_line"
  } >"$tmp"

  if (set -o noclobber; cat "$tmp" >"$lock_path") 2>/dev/null; then
    rm -f "$tmp"
    return 0
  fi

  rm -f "$tmp"
  return 1
}

describe_existing_lock() {
  local path="$1"
  local lock_pid lock_run_id lock_epoch age
  lock_pid="$(read_field pid "$path")"
  lock_run_id="$(read_field run_id "$path")"
  lock_epoch="$(read_field created_at_epoch "$path")"
  if ! [[ "$lock_epoch" =~ ^[0-9]+$ ]]; then
    lock_epoch="$(stat_mtime "$path")"
  fi
  age=$((now_epoch - lock_epoch))
  printf 'existing lock path=%s run_id=%s pid=%s age_seconds=%s\n' \
    "$path" "${lock_run_id:-unknown}" "${lock_pid:-unknown}" "$age"
}

if write_lock_once; then
  printf 'LOCK_ACQUIRED path=%s run_id=%s pid=%s\n' "$lock_path" "$run_id" "$owner_pid"
  exit 0
fi

lock_pid="$(read_field pid "$lock_path")"
lock_epoch="$(read_field created_at_epoch "$lock_path")"
if ! [[ "$lock_epoch" =~ ^[0-9]+$ ]]; then
  lock_epoch="$(stat_mtime "$lock_path")"
fi
age=$((now_epoch - lock_epoch))

if [[ "$age" -ge "$stale_seconds" ]]; then
  describe_existing_lock "$lock_path" >&2
  echo "Removing stale Codex lock after ${age}s >= ${stale_seconds}s" >&2
  rm -f "$lock_path"
elif [[ -n "${lock_pid:-}" ]] && ! process_alive "$lock_pid"; then
  describe_existing_lock "$lock_path" >&2
  echo "Removing stale Codex lock because owner PID is no longer running" >&2
  rm -f "$lock_path"
else
  describe_existing_lock "$lock_path" >&2
  echo "Active Codex automation lock exists; refusing to acquire." >&2
  exit 1
fi

if write_lock_once; then
  printf 'LOCK_ACQUIRED path=%s run_id=%s pid=%s\n' "$lock_path" "$run_id" "$owner_pid"
  exit 0
fi

describe_existing_lock "$lock_path" >&2
echo "Could not acquire Codex lock after stale-lock cleanup; another run won the race." >&2
exit 1
