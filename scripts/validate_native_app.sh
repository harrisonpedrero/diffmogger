#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

native_dir="services/agentic-dashboard/native"

python3 scripts/check_native_rebuild_guardrails.py

(
  cd "$native_dir"
  npm test
  npm run build
  (
    cd src-tauri
    cargo test
  )
  npm run tauri build
)

echo "OK: native app validation passed"
