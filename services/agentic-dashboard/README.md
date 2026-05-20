# Diffmogger Dashboard Service

The user-facing dashboard is the native Tauri app in `services/agentic-dashboard/native/`. Backend commands live behind `scripts/dashboard_backend_cli.py` and package modules under `src/diffmogger/dashboard/`.

## Quickstart

```bash
bash scripts/build_native_dashboard_app.sh
open Diffmogger.app
```

## Development

```bash
cd services/agentic-dashboard/native
npm install
npm test
npm run build
npm run tauri dev
```

Manual packaged build:

```bash
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The root helper creates `Diffmogger.app` at the checkout root as a macOS Finder alias when possible, with a symlink fallback.

The packaged app is source-checkout-backed. Keep the cloned Diffmogger checkout in place, or launch with:

```bash
DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger npm run tauri dev
```

## Backend

The native app invokes `scripts/dashboard_backend_cli.py` through an allowlisted Rust subprocess boundary. The backend loads the starter repo `.env` without overriding existing environment variables and never prints loaded values.

Useful smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
python3 scripts/dashboard_backend_cli.py state.snapshot --target /path/to/target
```

Backend commands cover setup doctor, project snapshots, canonical SQLite state snapshots, intake draft/scaffold, context import, ticket queue load/add/update/delete/import/draft/accept, run controls, safety checks, worker controls, execution groups, validation jobs, lease cleanup, and the task projection opener.

The app has two surfaces: **Setup** for choosing/configuring a project and **Automation** for scheduler next action, queued/running/done work, generated unblocker work, human input records, and Start/Stop/Safety commands. Target-local dashboard preferences live at `.diffmogger/agentic/dashboard_state.json`; canonical orchestration state lives at `.diffmogger/runtime/orchestration.sqlite3`; the generated agent state view lives at `.diffmogger/runtime/canonical_state_brief.md`; context imports are copied to `.diffmogger/context/` and tracked in the intake/dashboard state. Ticket-campaign targets use the dashboard-backed SQLite ticket queue; draft candidates live in `.diffmogger/runtime/ticket_drafts/` until accepted. Setup checks include whether the Codex CLI installed and signed in state is usable.

## Smoke Checklist

1. Run `bash scripts/validate_starter_kit.sh` in the Diffmogger source checkout.
2. Open the target with **Choose project** on Setup.
3. Confirm Diffmogger is configured or run **Scaffold**.
4. Open **Automation** and run **Run Safety Check**.
5. Start or stop automation from the Automation command row.

## Validation

```bash
bash scripts/validate_native_app.sh
```

That script checks the archived command inventory, frontend tests/build, Rust tests, and packaged Tauri build.
