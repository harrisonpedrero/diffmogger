# Dashboard

Diffmogger's dashboard is the native Tauri app in `services/agentic-dashboard/native/`. It is the only user-facing dashboard.

The frontend calls `scripts/dashboard_backend_cli.py`, which delegates to package code under `src/diffmogger/dashboard/` and source-kit/runtime modules under `src/diffmogger/`. Backend commands return JSON and are allowlisted by the native Rust layer.

## Run The App

```bash
bash scripts/build_native_dashboard_app.sh
open Diffmogger.app
```

Development mode:

```bash
cd services/agentic-dashboard/native
npm install
npm run tauri dev
```

Manual packaged build:

```bash
npm run build
npm run tauri build
open src-tauri/target/release/bundle/macos/Diffmogger.app
```

The root build helper creates `Diffmogger.app` at the checkout root as a macOS Finder alias when possible, with a symlink fallback.

Backend smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
python3 scripts/dashboard_backend_cli.py state.snapshot --target /path/to/target
```

The packaged app is source-checkout-backed. Set `DIFFMOGGER_KIT_ROOT=/path/to/Diffmogger` to test another checkout.

## Backend Contract

The dashboard frontend should call backend commands instead of reading arbitrary files or recreating scaffold logic in TypeScript. Important command groups:

- Project: `project.load_snapshot`, `project.list_recent`.
- Brief: `brief.load`, `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold_bootstrap`, `brief.run_bootstrap`.
- Context: `context.import`.
- Run and automation: `run.load`, `run.load_log`, `automation.start`, `automation.stop`.
- State: `state.snapshot`, `state.validate`; these expose SQLite-backed execution DAG progress, capability manifest, graph summaries, context-pack previews, leases, scheduler candidates, next actions, validation receipts, event history, and narrow compatibility projections for older helpers.
- Tickets: `ticket.load`, `ticket.add`, `ticket.update`, `ticket.delete`, `ticket.import`, `ticket.draft_from_intake`, `ticket.accept_draft`.
- Safety: `safety.run_check`.
- Workers and parallel execution: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`, `execution_group.load`, `execution_group.start`, `execution_group.cancel`, `execution_group.retry_failed`, `execution_group.export_debug_bundle`, `validation_jobs.load`, `lease.release_stale`.
- Observatory and review: `observatory.snapshot`, `observatory.generate_html`, `observatory.load_html`, `review.load`, `review.export_bundle`, `review.mark_reviewed`.
- Inbox: `inbox.load`, `inbox.send_note`, `inbox.reply_request`.
- Advanced: `diagnostics.environment`, `diagnostics.run_checks`, `advanced.list_files`, `advanced.load_file`, `advanced.save_file`, `advanced.validate_file`, `advanced.export_debug_bundle`.

All commands validate target paths before reading or writing. Advanced file access uses managed file keys. Debug bundles redact `.env` and secret-like values.

## Setup Flow

The dashboard wizard collects the same intake fields supported by `schemas/project_intake.schema.json`:

- fresh-project or existing-project mode
- product goal, target user, and desired runnable milestone
- tech preferences, constraints, safety rules, and "must never" rules
- verification commands
- human bridge mode
- optional context files
- optional worker settings
- bounded or ongoing campaign mode with seed-ticket entry, bulk import, and review-only Codex follow-up candidates
- continuous execution DAG scheduler automation
- DAG scheduler config: `parallel_execution_mode`, `symbol_graph_languages`, `parallel_write_min_confidence`, `parallel_write_direct_confidence`, `max_parallel_write_workers`, and `max_parallel_scope_workers`
- optional Context7 and Playwright MCP setup
- deliverable definition and long-run direction

For existing repos, Diffmogger writes sidecar state under `.diffmogger/` and only manages its marked block in root `AGENTS.md`.

When a bounded campaign is selected, the wizard shows a **Ticket Queue** panel before review. Low-cortisol generation should decompose the full described scope into reviewable local patches with no fixed ticket-count ceiling. Seed tickets are saved in the intake as `ticket_run_seed_tickets`; scaffold seeds them into the target-local SQLite ticket queue. If no seed tickets are provided, scaffold keeps a placeholder ticket in SQLite.

## Scaffold And First Run

Manual setup writes target files; the first Run prepares the target if needed. **Scaffold** runs this source-kit pipeline:

1. write `.diffmogger/agentic/project_intake.json`
2. copy context files into `.diffmogger/context/`
3. scaffold target docs, shell scripts, Python wrappers, `.diffmogger/lib/diffmogger/`, and the exported state schema
4. update the target `.git/info/exclude`
5. run `scripts/check_required_files.py`
6. leaves first-run preparation for the Run page

When the user clicks **Start** for a scaffolded target whose first-run preparation is still pending, the Run page runs the guarded `brief.run_bootstrap` phase first, records completion in target-local state, refuses a second successful bootstrap, and starts automation only if preparation succeeds.

The legacy **Scaffold & Bootstrap** wording refers to this guarded scaffold plus first-run preparation flow.

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
- initialized git repo and initial commit before continuous automation; scaffold creates them automatically when `HEAD` is missing
- local-only remote opt-in before continuous automation in repos with configured remotes

## Continuous Automation

After scaffold/bootstrap and required-file validation, the Run page can start or stop a detached target-scoped DAG scheduler runner.

- **Start** launches `.diffmogger/scripts/run_conveyor_automation.sh` in a detached local process. On the first start, it runs guarded target preparation first and launches automation only after that phase passes. The script keeps its historical filename, but the runtime model is the execution DAG.
- **Stop** terminates the recorded runner process group.

Automation writes runner logs under `.diffmogger/runtime/automation_logs/`. Execution DAG state is canonical in `.diffmogger/runtime/orchestration.sqlite3`; the Run page surfaces DAG Progress, owner role, validation receipts, blockers, capability manifest, and queued next actions as the primary progress model. It also shows the graph-derived Codebase Graph summary, Task Graph summary, Impact View, context-pack reasons, active leases, lease conflicts, stale graph warnings, scheduler candidates, proposed execution groups, validation jobs, worker contracts, and integration backlog from allowlisted backend commands over typed state. `.diffmogger/runtime/canonical_state_brief.md` is the generated agent-facing view, and `.diffmogger/runtime/automation_runner.json` plus `.diffmogger/runtime/automation_conveyor_state.json` are generated compatibility projections.

For scaffolded ticket-campaign targets, the Run page exposes the ticket authoring file through a structured **Ticket Queue** panel. It shows status counts, the next selected ticket, placeholder/dependency validation, and lets users inspect, edit, delete, add, preview/apply Markdown/CSV/JSON imports, draft from intake with Codex, and accept candidates. Draft candidates are stored under `.diffmogger/runtime/ticket_drafts/` and are not applied until accepted.

## Review And Safety

**Run Safety Check** runs `scripts/check_integration_safety.py` against the kit source and records the selected target result at `.diffmogger/runtime/integration_safety_check.json`.

**Launch Observatory** and **Export Review Bundle** use `.diffmogger/scripts/run_observatory.py`. Review bundles write:

```text
/tmp/Diffmogger-review/Diffmogger-observatory.html
/tmp/Diffmogger-review/Diffmogger-self-review.md
```

The native Observatory view and exported HTML show run state, DAG progress, queue/deferred patches, canonical state health, validation, safety, recent outcomes, and next-run worker strategy.

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

Worker artifacts live under `.diffmogger/runtime/agent_runs/<run_id>/`. The main agent remains responsible for reviewing, integrating, verifying, and updating canonical state plus generated handoff projections.

## Parallel Execution Controls

The Run page includes a **Parallel Execution** panel backed by `execution_group.load` and `validation_jobs.load`. It shows proposed and active execution groups, why work was grouped, skipped candidates, worker contracts, active and conflicting leases, validation jobs, queued worker patches, and warnings for stale graph context, unknown impact, exhausted budgets, disabled write workers, stale leases, report disposition, and integration backlog pressure.

Dashboard controls stay narrow and typed:

- **Start Read-Only Group** starts a proposed read-only execution group within the configured parallelism budget.
- **Start Validation Group** runs independent validation jobs through the validation budget.
- **Cancel** marks a proposed, running, or failed execution group cancelled and releases leases tied to that group.
- **Release** releases an explicit stale lease by lease id.
- **Export Debug Bundle** writes a compact parallel-state bundle without source contents, environment values, credentials, or arbitrary file reads.

Write-worker fanout remains gated by target worker settings, DAG scheduler confidence, lease ownership, and serialized integrator handoff. Dashboard controls observe and route typed runtime state; they do not bypass the DAG scheduler or apply worker patches directly.

## Inbox And Advanced Files

The Inbox page writes structured notes and replies into typed human-message state in SQLite. Notifier credentials stay in `services/agentic-notifier/.env`; target projects only use the dashboard-backed queue or the loopback notifier API.

The Advanced page can read, write, validate, open, or reveal only allowlisted managed files. Ticket and human-message state are edited through structured dashboard commands, while the **Canonical state** tab reads SQLite health, event counts, execution DAG state, capability manifests, checkpoints, next actions, and recent event hashes through the backend API. It is for inspection and careful repair, not broad filesystem access.
