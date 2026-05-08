# Diffmogger Native Dashboard

This is the active Tauri v2 shell for the Diffmogger dashboard. It keeps the Python backend command
layer as the source of truth so scaffold, schedule, human bridge, observatory, and review behavior
stay shared with the rest of the kit.

## Development

```bash
npm install
npm run build
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The Rust command layer only exposes app-local recent-target storage, native folder selection, safe
open/reveal helpers, and an allowlisted wrapper around `scripts/dashboard_backend_cli.py`.

For now the packaged app is source-checkout-backed: keep the cloned Diffmogger repo in place because
the native shell invokes `scripts/dashboard_backend_cli.py` from that checkout. To debug another
checkout, launch with `DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger`.

The backend wrapper resolves `python3` and tools from the automation PATH first
(`CODEX_AUTOMATION_PATH`, or the Homebrew/system default path), then appends the GUI PATH inherited
by macOS. If setup checks fail, run:

```bash
cd ../../..
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```
