# Diffmogger Native Dashboard

This is the active Tauri v2 dashboard for Diffmogger.

Quickstart from the repository root:

```bash
bash scripts/build_native_dashboard_app.sh
open Diffmogger.app
```

The root helper builds the packaged macOS app and creates `Diffmogger.app` at the checkout root as a Finder alias when possible, with a symlink fallback.

Development commands from this directory:

```bash
npm install
npm test
npm run build
npm run tauri dev
```

Packaged app:

```bash
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The Rust layer exposes native folder selection, recent target storage, safe open/reveal helpers, and an allowlisted subprocess wrapper around `scripts/dashboard_backend_cli.py`.

The Advanced page includes a **Canonical state** tab backed by `state.snapshot`. It reads `.diffmogger/runtime/orchestration.sqlite3` through the backend and shows event/checkpoint counts, next actions, database health, and recent event hashes. The backend also exposes `state.brief`, which regenerates `.diffmogger/runtime/canonical_state_brief.md` for agents. JSON and Markdown files are projections or authoring surfaces, not live runtime authority.

Ticket-campaign setup and operations use the Ticket Queue panels in the Brief wizard and Run page. They call structured backend commands backed by SQLite, support Markdown/CSV/JSON import preview/apply, and keep Codex draft candidates review-only until accepted.

The app is source-checkout-backed. Use `DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger` to point the backend at another checkout.
