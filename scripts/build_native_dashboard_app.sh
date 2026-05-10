#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

kit_root="$(pwd)"
native_dir="$kit_root/services/agentic-dashboard/native"
app_path="$native_dir/src-tauri/target/release/bundle/macos/Diffmogger.app"
alias_name="Diffmogger.app"
alias_path="$kit_root/$alias_name"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper builds the macOS Diffmogger.app bundle and root alias." >&2
  echo "Run it on macOS, or use npm run tauri build from $native_dir for other platforms." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Missing required command: npm" >&2
  exit 1
fi

if ! command -v osascript >/dev/null 2>&1; then
  echo "Warning: osascript is unavailable; the root app entry will be a symlink." >&2
fi

if [[ -d "$alias_path" && ! -L "$alias_path" ]]; then
  echo "Refusing to overwrite existing directory: $alias_path" >&2
  exit 1
fi

echo "Installing native dashboard dependencies..."
(
  cd "$native_dir"
  npm ci
)

echo "Building native dashboard..."
(
  cd "$native_dir"
  npm run tauri build
)

if [[ ! -d "$app_path" ]]; then
  echo "Expected built app was not found: $app_path" >&2
  exit 1
fi

rm -f "$alias_path"

create_finder_alias() {
  command -v osascript >/dev/null 2>&1 || return 1
  osascript \
    -e 'on run argv' \
    -e 'set appPath to POSIX file (item 1 of argv) as alias' \
    -e 'set repoFolder to POSIX file (item 2 of argv) as alias' \
    -e 'set aliasName to item 3 of argv' \
    -e 'tell application "Finder"' \
    -e 'set createdAlias to make new alias file to appPath at repoFolder' \
    -e 'set name of createdAlias to aliasName' \
    -e 'end tell' \
    -e 'end run' \
    "$app_path" "$kit_root" "$alias_name" >/dev/null
}

if create_finder_alias; then
  echo "Created Finder alias: $alias_path"
else
  rm -f "$alias_path"
  ln -s "$app_path" "$alias_path"
  echo "Created symlink: $alias_path"
fi

echo "Open the dashboard with: open $alias_name"
