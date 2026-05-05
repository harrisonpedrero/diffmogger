#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/spawn_worker_agent.sh [options]

Spawn one bounded Codex CLI worker report. The default mode is read-only review:
the worker may only write its assigned report under target/agent_runs/<run_id>/.

Options:
  --target PATH              Target project directory. Default: current directory
  --run-id RUN_ID            Run id. Default: CODEX_RUN_ID, RUN_ID, or UTC timestamp
  --role ROLE                Worker role slug. Default: review
  --mode MODE                read-only or write. Default: read-only
  --read-only                Shortcut for --mode read-only
  --write                    Shortcut for --mode write
  --ownership TEXT           Required ownership scope for --mode write
  --prompt TEXT              Worker assignment
  --prompt-file PATH         Read worker assignment from a file
  --max-prompt-chars N       Bound assignment text. Default: 12000
  -h, --help                 Show this help

The script uses `codex exec --disable plugins --ephemeral
--dangerously-bypass-approvals-and-sandbox` for the nested child worker. The
scheduled parent run remains the outer sandbox boundary. The parent should grant
write access to ~/.codex with --add-dir so the nested CLI can authenticate and
start. If codex is unavailable or the worker fails, it still writes a report
explaining what happened.
EOF
}

target_dir="."
run_id="${CODEX_RUN_ID:-${RUN_ID:-}}"
role="review"
mode="${CODEX_WORKER_MODE:-read-only}"
ownership_scope=""
prompt_text=""
prompt_file=""
max_prompt_chars="${CODEX_WORKER_MAX_PROMPT_CHARS:-12000}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      target_dir="${2:?--target requires a path}"
      shift 2
      ;;
    --run-id)
      run_id="${2:?--run-id requires a value}"
      shift 2
      ;;
    --role)
      role="${2:?--role requires a value}"
      shift 2
      ;;
    --mode)
      mode="${2:?--mode requires read-only or write}"
      shift 2
      ;;
    --read-only)
      mode="read-only"
      shift
      ;;
    --write)
      mode="write"
      shift
      ;;
    --ownership)
      ownership_scope="${2:?--ownership requires a scope description}"
      shift 2
      ;;
    --prompt)
      prompt_text="${2:?--prompt requires text}"
      shift 2
      ;;
    --prompt-file)
      prompt_file="${2:?--prompt-file requires a path}"
      shift 2
      ;;
    --max-prompt-chars)
      max_prompt_chars="${2:?--max-prompt-chars requires a number}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! [[ "$max_prompt_chars" =~ ^[0-9]+$ ]] || [[ "$max_prompt_chars" -lt 200 ]]; then
  echo "Invalid --max-prompt-chars value: $max_prompt_chars" >&2
  exit 2
fi

case "$mode" in
  read-only|readonly|read_only|report)
    mode="read-only"
    ;;
  write|write-worker|write_worker|implementation)
    mode="write"
    ;;
  *)
    echo "Invalid --mode value: $mode" >&2
    usage >&2
    exit 2
    ;;
esac

ownership_scope="$(printf '%s' "$ownership_scope" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"

if [[ "$mode" == "write" && -z "$ownership_scope" ]]; then
  echo "--mode write requires --ownership with disjoint file/module scope" >&2
  exit 2
fi

if [[ -z "$run_id" ]]; then
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

role_slug="$(printf '%s' "$role" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9][^a-z0-9]*/_/g; s/^_//; s/_$//')"
if [[ -z "$role_slug" ]]; then
  role_slug="review"
fi

target_abs="$(cd "$target_dir" && pwd)"
run_dir="$target_abs/target/agent_runs/$run_id"
output_path="$run_dir/worker_${role_slug}.md"
raw_log="$run_dir/worker_${role_slug}.raw.log"
mkdir -p "$run_dir"

if [[ -n "$prompt_file" ]]; then
  if [[ ! -f "$prompt_file" ]]; then
    echo "Prompt file not found: $prompt_file" >&2
    exit 2
  fi
  prompt_text="$(cat "$prompt_file")"
fi

if [[ -z "$prompt_text" ]]; then
  if [[ "$mode" == "write" ]]; then
    prompt_text="Implement the bounded assignment inside the ownership scope, run relevant checks you can, and write a concise integration report."
  else
    prompt_text="Inspect the target project for the current automation sprint. Produce a concise read-only report with findings, risks, recommended next steps, and verification suggestions."
  fi
fi

prompt_chars="$(printf '%s' "$prompt_text" | wc -c | tr -d ' ')"
truncated_notice=""
if [[ "$prompt_chars" -gt "$max_prompt_chars" ]]; then
  prompt_text="$(printf '%s' "$prompt_text" | head -c "$max_prompt_chars")"
  truncated_notice="The assignment was truncated to ${max_prompt_chars} characters by spawn_worker_agent.sh."
fi

if [[ "$mode" == "write" ]]; then
  worker_prompt=$(cat <<EOF
You are a bounded write-capable worker for a recurring Codex automation run.

Target project: $target_abs
Run id: $run_id
Worker role: $role_slug
Mode: write
Owned scope: $ownership_scope
Output report: $output_path

Rules:
- You are not alone in the codebase.
- Modify only the owned files/modules/scratch area described above, plus the output report path.
- Do not touch unrelated files.
- Do not revert unrelated edits or changes made by other agents or humans.
- Adjust your implementation to documented contracts and outputs from other workers when visible.
- Follow the target project's environment-access policy. Never print, copy, store, or commit secret values.
- Do not use network.
- Do not send Discord, notifier, email, or other external messages.
- Do not spawn subagents, do not call codex exec, and do not call spawn_worker_agent.sh.
- Do not run destructive cleanup, history rewrites, mass deletion, or broad formatting outside your owned scope.
- Stop after the bounded assignment and report.

Report format:
- assignment
- ownership scope
- files changed
- checks run
- integration notes
- risks
- follow-up needed

Assignment:
$prompt_text

$truncated_notice
EOF
)
else
  worker_prompt=$(cat <<EOF
You are a bounded read-only worker for a recurring Codex automation run.

Target project: $target_abs
Run id: $run_id
Worker role: $role_slug
Mode: read-only
Output report: $output_path

Rules:
- Read the target project and produce the assigned report.
- Do not modify source files or docs except for the output report path above.
- Follow the target project's environment-access policy. Never print, copy, store, or commit secret values.
- Do not use network.
- Do not send Discord, notifier, email, or other external messages.
- Do not spawn subagents, do not call codex exec, and do not call spawn_worker_agent.sh.
- Stop after writing the report.

Report format:
- assignment
- files inspected
- findings
- risks
- recommendations
- suggested verification
- confidence

Assignment:
$prompt_text

$truncated_notice
EOF
)
fi

write_unavailable_report() {
  local reason="$1"
  cat >"$output_path" <<EOF
# Worker Report: $role_slug

- run_id: $run_id
- role: $role_slug
- mode: $mode
- status: UNAVAILABLE
- output_path: $output_path
$(if [[ "$mode" == "write" ]]; then printf '%s\n' "- ownership_scope: $ownership_scope"; fi)

## Assignment

$prompt_text

## Result

$reason

## Recommendations

- Continue the sprint without blocking on this worker.
- Record \`Codex CLI worker decision: UNAVAILABLE\` if no workers could run.
EOF
}

if ! command -v codex >/dev/null 2>&1; then
  write_unavailable_report "\`codex\` command not found in this environment."
  echo "Codex CLI unavailable; wrote $output_path" >&2
  exit 127
fi

set +e
codex exec \
  --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C "$target_abs" \
  "$worker_prompt" >"$raw_log" 2>&1
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
  cat >"$output_path" <<EOF
# Worker Report: $role_slug

- run_id: $run_id
- role: $role_slug
- mode: $mode
- status: FAILED
- exit_code: $status
- raw_log: $raw_log
$(if [[ "$mode" == "write" ]]; then printf '%s\n' "- ownership_scope: $ownership_scope"; fi)

## Assignment

$prompt_text

## Result

The Codex CLI worker failed. Review the raw log if needed; do not treat this as a completed worker review.
EOF
  echo "Codex worker failed with exit code $status; wrote $output_path" >&2
  exit "$status"
fi

if [[ ! -s "$output_path" ]]; then
  cat >"$output_path" <<EOF
# Worker Report: $role_slug

- run_id: $run_id
- role: $role_slug
- mode: $mode
- status: COMPLETED_WITHOUT_REPORT
- raw_log: $raw_log
$(if [[ "$mode" == "write" ]]; then printf '%s\n' "- ownership_scope: $ownership_scope"; fi)

## Assignment

$prompt_text

## Result

The Codex CLI worker exited successfully but did not write the assigned report file. The raw log may contain useful output.
EOF
fi

printf 'WORKER_REPORT path=%s run_id=%s role=%s mode=%s\n' "$output_path" "$run_id" "$role_slug" "$mode"
