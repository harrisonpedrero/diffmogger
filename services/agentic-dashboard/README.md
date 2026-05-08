# Diffmogger Dashboard

The Diffmogger Dashboard is a local configuration wizard and automation monitor. The active UI is the native Tauri app in `services/agentic-dashboard/native`; the Python/Tkinter launcher remains for compatibility and backend helper reuse.

Launch the native app from the starter repo during development:

```bash
cd services/agentic-dashboard/native
npm install
npm run tauri dev
```

Legacy compatibility launcher:

```bash
python3 scripts/run_dashboard.py
```

The launcher and backend CLI load optional dashboard/runtime environment variables from the Diffmogger starter repo's root `.env` file before importing backend helpers. Missing `.env` is fine, existing shell variables win, and loaded values are not printed or copied into target projects or role worktrees. This lets advisory checks and dashboard-launched automation inherit optional values such as `CONTEXT7_API_KEY`.

## Native Build

```bash
cd services/agentic-dashboard/native
npm install
npm run build
npm run tauri build
```

Open the built app from:

```bash
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The packaged app is source-checkout-backed: the built app invokes the cloned Diffmogger kit's
`scripts/dashboard_backend_cli.py` instead of bundling a standalone backend distribution. The Tauri
shell uses a native folder picker, stores recent targets in app-local config, and does not grant
frontend shell or broad filesystem permissions.

Native backend commands use the automation PATH (`CODEX_AUTOMATION_PATH` if set, otherwise the
Homebrew/system default path plus the GUI PATH), load the starter repo `.env` without overriding
existing environment variables, and expose a targetless setup doctor through
`diagnostics.environment`.

## What It Does

- collects a project intake
- splits intake into Basics, Product, Rules, Run Config, Progression, and Context steps instead of a long scroll
- supports fresh-project and existing-project integration modes
- covers constraints, safety rules, automation prohibitions, human bridge choices, worker settings, optional bounded write-worker acceleration settings, optional automation signals, optional ticket-campaign mode, optional multi-role automation, optional Context7/Playwright MCP integrations, deliverable definition, and long-run direction
- copies optional context files into `.diffmogger/context/`
- writes `.diffmogger/state/PROJECT_CONTEXT.md`
- scaffolds Diffmogger target-project files
- runs the required-file check
- starts the first `codex exec --full-auto --skip-git-repo-check` bootstrap run through one `Scaffold & Bootstrap` action
- persists dashboard state in the selected target at `.diffmogger/agentic/dashboard_state.json`
- reopens Diffmogger-managed targets through `Open Diffmogger Project`
- enables `Start Scheduled Automation` only after the target appears bootstrapped
- installs and loads macOS launchd jobs for periodic sprint, fixed multi-role cadence, or continuous conveyor scheduling
- pauses scheduled automation by unloading and disabling dashboard-managed LaunchAgent jobs
- removes dashboard-managed schedules by deleting the target LaunchAgent plist(s)
- renders selected automation Markdown files
- launches an optional local browser observatory for active signal nudges, conveyor health, active roles, queued/deferred patches, the latest recorded integration-safety result, recent outcomes, and timeline events
- runs `scripts/check_integration_safety.py` through **Run Safety Check** and shows the output in the bounded dashboard log
- shows **Worker Strategy Controls** from the observatory's next-run recommendation and can launch one bounded read-only worker, one explicitly owned write worker, or one local integrator lane when that strategy recommends it; dashboard-launched workers are summarized into `.diffmogger/runtime/agent_runs/<run_id>/summary.md` and the latest summary can be loaded from the Run page
- lets a human send file-only messages to the next automation run when notifier delivery is disabled or unavailable
- displays prerequisites as readiness checks instead of raw command output

In existing-project mode, Diffmogger keeps generated state under `.diffmogger/` and only adds or updates a managed Diffmogger automation block in root `AGENTS.md` when needed.

## First Review Checklist

Use the native dashboard to tie the local review together:

1. Run `bash scripts/validate_starter_kit.sh` from the Diffmogger starter-kit source.
2. Open the target with **Open Diffmogger Project**.
3. Click **Run Safety Check** and review the dashboard log.
4. Click **Export Review Bundle** or export `python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
5. Open `/tmp/Diffmogger-review/Diffmogger-observatory.html` and inspect `/tmp/Diffmogger-review/Diffmogger-self-review.md`.

**Run Safety Check** also writes `.diffmogger/runtime/integration_safety_check.json` under the selected target.
The review bundle reads that runtime marker so the exported HTML and Markdown show the latest
dashboard safety result.
6. Check first-review readiness, safety status, validation state, active role or queue, known issues, the next-lane action plan, and the next-run worker strategy in the observatory, Markdown export, or **Worker Strategy Controls** panel.

## Prerequisites

Before starting automation, the dashboard checks for:

- Python 3.10+
- Codex CLI installed and signed in
- `bash`
- `git`
- writable target parent directory
- Codex home availability for nested workers
- macOS Full Disk Access advisory when the target lives under `~/Documents`
- optional local notifier health when `local_notifier` or `discord_notifier` mode is selected
- optional macOS desktop notification command when local notifications are enabled
- initialized git repo with an initial commit before starting multi-role or conveyor scheduling
- explicit local-only remote opt-in before multi-role or conveyor scheduling in repos with configured git remotes
- optional Context7 API key visibility when Context7 MCP is selected
- optional Node/npx, Codex MCP visibility, and managed browser advisories when Context7 or Playwright MCP is selected

The dashboard keeps notifier credentials out of target projects. In notifier modes, use `services/agentic-notifier/` for Discord and local desktop notification configuration.
Ticket campaign setup lives in Run Config, but tickets themselves are populated in the generated Markdown file, usually `.diffmogger/state/TICKET_RUN.md`. Ticket-campaign bootstrap is readiness-only; scheduled runs use dependency-aware `next --json` selection and act on one ticket per run.
Optional MCP setup is project-scoped and advisory. The dashboard never runs MCP install/login commands or edits user/global Codex config. When Context7 is selected, the generated config inherits `CONTEXT7_API_KEY` if it is present in the shell or loaded from the starter repo's root `.env`, but never stores the key.
