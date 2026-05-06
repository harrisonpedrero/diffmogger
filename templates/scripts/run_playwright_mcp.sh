#!/usr/bin/env bash
set -euo pipefail

run_id="${CODEX_RUN_ID:-manual}"
output_dir="${PLAYWRIGHT_MCP_OUTPUT_DIR:-docs/backlog/ui_artifacts/$run_id}"
mkdir -p "$output_dir"

args=(
  -y
  @playwright/mcp@latest
  --headless
  --isolated
  --codegen
  none
  --output-dir
  "$output_dir"
)

if [[ -n "${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-}" ]]; then
  args+=(--executable-path "$PLAYWRIGHT_MCP_EXECUTABLE_PATH")
fi

exec npx "${args[@]}"
