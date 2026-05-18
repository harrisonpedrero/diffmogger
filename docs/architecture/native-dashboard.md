# Native Dashboard Architecture

Diffmogger's primary dashboard is the native Tauri v2 app. The Python backend command layer remains
the source of truth for scaffold, automation runner lifecycle, human bridge, Observatory, review, and validation
behavior.

Generated sidecar targets resolve managed paths through `.diffmogger/manifest.json` and store
Diffmogger-owned files under `.diffmogger/`. Runtime helpers still tolerate earlier generated
target layouts where required for compatibility.

The goal is better UX without losing the dashboard's automation controls, Observatory export,
file-only human bridge, scaffold flow, and Markdown-first operating model.

## Entry Points

Native app:

```bash
cd services/agentic-dashboard/native
npm install
npm run tauri dev
```

Backend command smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```

Observatory export/server:

```bash
python3 scripts/runtime/run_observatory.py --target /path/to/target --review-dir /path/to/target/.diffmogger/runtime/first-review
```

Source-checkout packaged app:

```bash
git clone <diffmogger-repo-url>
cd Diffmogger/services/agentic-dashboard/native
npm install
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The packaged app is source-checkout-backed, not a standalone binary distribution yet. The built app uses
the cloned Diffmogger kit as its backend/script root. For debugging alternate checkouts, launch the
app with `DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger`.

Native validation:

```bash
bash scripts/validate_native_app.sh
```

Full starter-kit validation:

```bash
bash scripts/validate_starter_kit.sh
```

## Architecture

The native app is intentionally thin:

- React/TypeScript renders the shell and pages in `services/agentic-dashboard/native/src/`.
- Tauri/Rust owns native folder selection, recent-project config, path validation, safe open/reveal
  actions, and the allowlisted subprocess boundary.
- Python remains the backend source of truth through `scripts/dashboard_backend_cli.py`.
- Existing scaffold, dashboard helper, automation runner, human bridge, Observatory, review export, and
  validation functions are reused rather than duplicated in TypeScript.

The frontend must not scrape Markdown files for core state. It calls backend commands and receives
JSON snapshots. Raw Markdown editing remains available in Advanced through allowlisted file keys.

## Backend Command Contract

All backend CLI commands return JSON on stdout:

```json
{
  "schema_version": 1,
  "ok": true,
  "command": "project.load_snapshot",
  "data": {}
}
```

Errors also return JSON and use non-zero exit codes:

```json
{
  "schema_version": 1,
  "ok": false,
  "command": "project.load_snapshot",
  "message": "Target path does not exist.",
  "error": {
    "type": "invalid_target",
    "details": {}
  }
}
```

Current command groups:

- Project and Brief: `project.load_snapshot`, `project.list_recent`, `brief.load`,
  `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold`.
- Context: `context.import`.
- Run and automation: `run.load`, `run.load_log`, `automation.start`,
  `automation.stop`, `safety.run_check`.
- Workers: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`.
- Observatory and Review: `observatory.snapshot`, `observatory.generate_html`,
  `observatory.load_html`, `review.load`, `review.export_bundle`, `review.mark_reviewed`.
- Inbox: `inbox.load`, `inbox.send_note`, `inbox.reply_request`.
- Advanced and setup doctor: `diagnostics.environment`, `diagnostics.run_checks`,
  `advanced.list_files`, `advanced.load_file`, `advanced.save_file`, `advanced.validate_file`,
  `advanced.export_debug_bundle`.

Path rules:

- Commands validate target paths before reading or writing.
- The native Rust layer allowlists backend command names.
- Advanced file access uses file keys, not arbitrary paths.
- Generated artifacts opened or revealed by the native app are validated as Diffmogger review
  artifacts.
- Destructive operations must be explicit in the command name and should remain rare.

## UI State Model

The native app uses backend snapshots to derive page state:

- No target selected: Home offers native folder selection and recent projects.
- Unconfigured target: Home and Run point to Brief. Run controls remain disabled.
- Scaffolded target with no runs: Home routes to Run; Run presents **Start**. When initial
  preparation is pending, Start performs the guarded first-run preparation before launching
  continuous automation, while Observatory and Review show honest empty states.
- Running target: Home/Run show running status, sidebar running badge, and log controls.
- Human input pending: Home routes to Inbox and the sidebar shows an input badge.
- Environment blocked or critical stop: Home/Run/Observatory use warning or critical tones and route
  toward Review, Diagnostics, or Inbox based on backend state.

State derivation lives in small testable frontend model files:

- `homeModel.ts`: Home headline, primary CTA, safety/readiness, progress, and human bridge.
- `runModel.ts`: Run page readiness, control enablement, automation runner status, log state, worker strategy.
- `observatoryModel.ts`: Observatory headline/tone from snapshot mission, active role, queue, human
  input, and critical stop state.
- `commandPaletteModel.ts`: state-gated command palette commands and disabled reasons.
- `advancedModel.ts`: Advanced file editor dirty/save/open/reveal state.

## Native Backend Parity

Keep native behavior and test coverage aligned with the backend contracts for:

- prerequisite checks
- fresh and existing project setup
- project intake fields
- context-file import and `.diffmogger/state/PROJECT_CONTEXT.md` updates
- scaffold preview and execution
- continuous automation start/stop
- run safety checks
- review bundle export
- Observatory launch/export and native snapshot rendering
- worker strategy controls
- file-only human bridge messaging
- Markdown file monitor/editor
- multi-role DAG scheduler settings
- Context7 and Playwright MCP intake options
- dashboard state persistence in `.diffmogger/agentic/dashboard_state.json`

`docs/archive/native-dashboard-command-inventory.md` is the compact command inventory used by the guardrail script.
`scripts/validation/check_native_rebuild_guardrails.py` verifies preserved feature groups still have backend
commands and that those commands remain available through the native Rust allowlist.

## Regression Guardrails

Backend tests:

```bash
python3 -m unittest tests.dashboard.test_dashboard_backend_cli tests.kit.test_native_rebuild_guardrails
```

Frontend/native tests:

```bash
cd services/agentic-dashboard/native
npm test
npm run build
cd src-tauri && cargo test
```

Packaged native build:

```bash
cd services/agentic-dashboard/native
npm run tauri build
```

## Clone / Build / Run Troubleshooting

The native app launches backend commands with the same practical automation PATH used by generated
automation runs: `CODEX_AUTOMATION_PATH` when set, otherwise
`/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin`, followed by the app's original GUI
PATH. This avoids the common macOS GUI issue where a packaged app only sees `/usr/bin/python3`.

Use the targetless setup doctor before opening a project:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```

Use the target-scoped doctor after choosing a project:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.run_checks --target /path/to/project
```

Common fixes:

- Install a Homebrew Python 3.10+ if the backend resolves `/usr/bin/python3` 3.9.
- Install/sign in to Codex CLI, then run `codex` once in Terminal so `~/.codex` exists.
- Install Node with `brew install node` only when optional Context7/Playwright MCP integration needs
  `node`, `npm`, or `npx`.
- macOS targets under `~/Documents` may need Full Disk Access for `/bin/bash` and the Node
  executable used by continuous Codex runs. This is advisory unless automation jobs fail to access the
  target.

The setup doctor shows copyable commands and rerun checks. It does not auto-install tools or print
secret values loaded from `.env`.

Full validation:

```bash
bash scripts/validate_starter_kit.sh
```

When adding, renaming, or removing a backend command, update all of:

- `src/diffmogger/dashboard/cli.py` and the relevant module under `src/diffmogger/dashboard/commands/`
- `src/diffmogger/dashboard/backend_cli.py` only when the compatibility facade needs a new public re-export
- `scripts/dashboard_backend_cli.py`
- the Rust allowlist in `services/agentic-dashboard/native/src-tauri/src/lib.rs`
- `docs/archive/native-dashboard-command-inventory.md`
- `scripts/validation/check_native_rebuild_guardrails.py`
- backend and frontend regression tests
