# Dashboard

Diffmogger's dashboard is the native Tauri app in `services/agentic-dashboard/native/`. It is the only user-facing dashboard.

The frontend calls `scripts/dashboard_backend_cli.py`, which delegates to package code under `src/diffmogger/dashboard/` and source-kit/runtime modules under `src/diffmogger/`. Backend commands return JSON and are allowlisted by the native Rust layer.

## Run The App

```bash
cd services/agentic-dashboard/native
npm install
npm run tauri dev
```

Packaged build:

```bash
npm run build
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

Backend smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
```

The packaged app is source-checkout-backed. Set `DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger` to test another checkout.

## Backend Contract

The dashboard frontend should call backend commands instead of reading arbitrary files or recreating scaffold logic in TypeScript. Important command groups:

- Project: `project.load_snapshot`, `project.list_recent`.
- Brief: `brief.load`, `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold_bootstrap`.
- Context: `context.import`.
- Run and automation: `run.load`, `run.load_log`, `automation.start`, `automation.stop`.
- Tickets: `ticket.load`, `ticket.add`, `ticket.update`, `ticket.delete`, `ticket.import`, `ticket.draft_from_intake`, `ticket.accept_draft`.
- Safety: `safety.run_check`.
- Workers: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`.
- Observatory and review: `observatory.snapshot`, `observatory.generate_html`, `observatory.load_html`, `review.load`, `review.export_bundle`, `review.mark_reviewed`.
- Inbox: `inbox.load`, `inbox.send_note`, `inbox.reply_request`.
- Advanced: `diagnostics.environment`, `diagnostics.run_checks`, `advanced.list_files`, `advanced.load_file`, `advanced.save_file`, `advanced.validate_file`, `advanced.export_debug_bundle`.

All commands validate target paths before reading or writing. Advanced file access uses managed file keys. Debug bundles redact `.env` and secret-like values.

## Setup Flow

The dashboard wizard collects the same intake fields supported by `schemas/project_intake.schema.json`:

- fresh-project or existing-project mode
- product goal, target user, and first demo
- tech preferences, constraints, safety rules, and "must never" rules
- verification commands
- human bridge mode
- optional context files
- optional worker settings
- optional ticket-campaign mode with seed-ticket entry, bulk import, and review-only Codex draft candidates
- continuous role conveyor automation
- optional Context7 and Playwright MCP setup
- deliverable definition and long-run direction

For existing repos, Diffmogger writes sidecar state under `.diffmogger/` and only manages its marked block in root `AGENTS.md`.

When Ticket Campaign is selected, the wizard shows a **Ticket Queue** panel before review. Seed tickets are saved in the intake as `ticket_run_seed_tickets`; scaffold renders them into `.diffmogger/state/TICKET_RUN.md`. If no seed tickets are provided, scaffold keeps the placeholder ticket.

## Scaffold And Bootstrap

**Scaffold & Bootstrap** runs this source-kit pipeline:

1. write `.diffmogger/agentic/project_intake.json`
2. copy context files into `.diffmogger/context/`
3. scaffold target docs, shell scripts, Python wrappers, and `.diffmogger/lib/diffmogger/`
4. update the target `.git/info/exclude`
5. run `scripts/check_required_files.py`
6. optionally start the first Codex bootstrap run

`diffmogger.kit.scaffold_project_docs` is the source of truth for generated files. The dashboard is a UI over that contract.

## Prerequisites

Before automation starts, the dashboard checks:

- Python 3.10+
- Codex CLI availability and Codex home access
- `bash` and `git`
- writable target parent directory
- macOS Full Disk Access advisory for targets under `~/Documents`
- optional notifier health for notifier modes
- optional desktop notification command for ticket completion notifications
- optional Context7/Playwright MCP advisories
- initialized git repo and initial commit before continuous automation
- local-only remote opt-in before continuous automation in repos with configured remotes

## Continuous Automation

After scaffold/bootstrap and required-file validation, the Run page can start or stop a detached target-scoped conveyor runner.

- **Start** launches `.diffmogger/scripts/run_conveyor_automation.sh` in a detached local process.
- **Stop** terminates the recorded runner process group.

Automation writes runner logs under `.diffmogger/runtime/automation_logs/`. Runner state lives in `.diffmogger/runtime/automation_runner.json`; conveyor state lives in `.diffmogger/runtime/automation_conveyor_state.json`.

For scaffolded ticket-campaign targets, the Run page exposes the canonical ticket file through a structured **Ticket Queue** panel. It shows status counts, the next selected ticket, placeholder/dependency validation, and lets users inspect, edit, delete, add, preview/apply Markdown/CSV/JSON imports, draft from intake with Codex, and accept candidates. Draft candidates are stored under `.diffmogger/runtime/ticket_drafts/` and are not applied until accepted.

## Review And Safety

**Run Safety Check** runs `scripts/check_integration_safety.py` against the kit source and records the selected target result at `.diffmogger/runtime/integration_safety_check.json`.

**Launch Observatory** and **Export Review Bundle** use `.diffmogger/scripts/run_observatory.py`. Review bundles write:

```text
/tmp/Diffmogger-review/Diffmogger-observatory.html
/tmp/Diffmogger-review/Diffmogger-self-review.md
```

The native Observatory view and exported HTML show run state, queue/deferred patches, conveyor state, validation, safety, recent outcomes, and next-run worker strategy.

## First Review Checklist

1. Run `bash scripts/validate_starter_kit.sh` in the Diffmogger source checkout.
2. Open the target with **Open Diffmogger Project**.
3. Run **Run Safety Check**.
4. Use **Export Review Bundle** or run `python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
5. Inspect `/tmp/Diffmogger-review/Diffmogger-observatory.html` and `/tmp/Diffmogger-review/Diffmogger-self-review.md`.

## Worker Controls

The Run page reads the Observatory worker recommendation and can launch:

- one bounded read-only worker report
- one write worker with explicit ownership scope when the target enables write workers
- one local integrator lane

Worker artifacts live under `.diffmogger/runtime/agent_runs/<run_id>/`. The main agent remains responsible for reviewing, integrating, verifying, and updating durable state.

## Inbox And Advanced Files

The Inbox page writes structured notes and replies into generated human bridge Markdown files under `.diffmogger/state/`. Notifier credentials stay in `services/agentic-notifier/.env`; target projects only use file handoff or the loopback notifier API.

The Advanced page can read, write, validate, open, or reveal only allowlisted managed files, including raw `.diffmogger/state/TICKET_RUN.md` inspection. It is for inspection and careful repair, not broad filesystem access.
