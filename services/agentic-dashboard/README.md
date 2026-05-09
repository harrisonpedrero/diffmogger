# Diffmogger Dashboard Service

The user-facing dashboard is the native Tauri app in `services/agentic-dashboard/native/`. Backend commands live behind `scripts/dashboard_backend_cli.py` and package modules under `src/diffmogger/dashboard/`.

## Development

```bash
cd services/agentic-dashboard/native
npm install
npm test
npm run build
npm run tauri dev
```

Packaged build:

```bash
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The packaged app is source-checkout-backed. Keep the cloned Diffmogger checkout in place, or launch with:

```bash
DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger npm run tauri dev
```

## Backend

The native app invokes `scripts/dashboard_backend_cli.py` through an allowlisted Rust subprocess boundary. The backend loads the starter repo `.env` without overriding existing environment variables and never prints loaded values.

Useful smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```

Backend commands cover setup doctor, project snapshots, intake draft/scaffold, context import, ticket queue load/add/update/delete/import/draft/accept, run controls, launchd schedule controls, safety checks, Observatory snapshots, review bundles, inbox messages, worker controls, managed file editing, and redacted debug bundles.

The app supports **Scaffold & Bootstrap**, **Open Diffmogger Project**, **Ticket Queue**, **Run Safety Check**, **Export Review Bundle**, and **Worker Strategy Controls**. Target-local dashboard state lives at `.diffmogger/agentic/dashboard_state.json`; context imports go to `.diffmogger/context/` and update `.diffmogger/state/PROJECT_CONTEXT.md`. Ticket-campaign targets use `.diffmogger/state/TICKET_RUN.md` as the canonical queue; draft candidates live in `.diffmogger/runtime/ticket_drafts/` until accepted. Setup checks include whether the Codex CLI installed and signed in state is usable.

## First Review Checklist

1. Run `bash scripts/validate_starter_kit.sh` in the Diffmogger source checkout.
2. Open the target with **Open Diffmogger Project**.
3. Run **Run Safety Check**.
4. Use **Export Review Bundle** or run `python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
5. Inspect `/tmp/Diffmogger-review/Diffmogger-observatory.html` and `/tmp/Diffmogger-review/Diffmogger-self-review.md`.

## Validation

```bash
bash scripts/validate_native_app.sh
```

That script checks the archived command inventory, frontend tests/build, Rust tests, and packaged Tauri build.
