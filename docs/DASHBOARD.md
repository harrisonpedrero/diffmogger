# Dashboard

Diffmogger's dashboard is the native Tauri app in `services/agentic-dashboard/native/`. It is a compact control surface over target-local SQLite runtime state.

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

Backend smoke:

```bash
python3 scripts/dashboard_backend_cli.py diagnostics.environment
python3 scripts/dashboard_backend_cli.py state.snapshot --target /path/to/target
```

## Information Architecture

The native dashboard has two screens:

- **Setup**: choose a project, inspect whether Diffmogger is installed/configured, edit the project intake, import context files, manage seed tickets, scaffold, and run setup checks.
- **Automation**: show scheduler next action, queued/running/done work, tickets, generated unblocker work, human input counts, command output, and Start/Stop/Safety commands.

There is no separate Home, Activity, Review, Inbox, or Advanced page. Human input is a small panel and badge. Runtime activity is folded into Automation. Setup/diagnostics controls live in Setup.

## Backend Contract

The dashboard frontend calls backend commands instead of reading arbitrary files or recreating scaffold logic in TypeScript. The Rust shell allowlists only the native dashboard command surface:

- Project: `project.load_snapshot`, `project.list_recent`.
- Brief/setup: `brief.load`, `brief.generate_intake`, `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold`.
- Context: `context.import`.
- Run and automation: `project.load_snapshot`, `run.once`, `automation.start`, `automation.stop`, `blocker.recheck_baseline`.
- State: `state.snapshot`, `state.brief`, `state.validate`, `state.watch`.
- Tickets: `ticket.load`, `ticket.add`, `ticket.update`, `ticket.delete`, `ticket.import`, `ticket.draft_from_intake`, `ticket.accept_draft`, `ticket.split_preview`, `ticket.accept_split`.
- Safety: `diagnostics.environment`, `diagnostics.run_checks`, `safety.run_check`.
- Workers and parallel execution: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`, `worker.launch_read_only_group`, `worker.launch_write_group`, `execution_group.load`, `execution_group.start`, `execution_group.cancel`, `execution_group.retry_failed`, `execution_group.export_debug_bundle`, `validation_jobs.load`, `lease.release_stale`.

Removed native pages no longer have backend commands in the native shell. Inbox/review/advanced/observatory page commands are not normal dashboard controls.

## Setup Flow

Setup collects the same intake fields supported by `schemas/project_intake.schema.json`:

- fresh-project or existing-project mode
- product goal, target user, and desired runnable milestone
- tech preferences, constraints, safety rules, and "must never" rules
- verification commands
- human input mode
- optional context files
- worker settings
- bounded or ongoing campaign mode with seed-ticket entry, import, split, and draft candidates
- continuous execution DAG scheduler automation
- DAG scheduler config: `parallel_execution_mode`, `symbol_graph_languages`, `parallel_write_min_confidence`, `parallel_write_direct_confidence`, `max_parallel_write_workers`, and `max_parallel_scope_workers`
- optional Context7 and Playwright MCP setup
- deliverable definition and long-run direction

For existing repos, Diffmogger writes sidecar state under `.diffmogger/` and only manages its marked block in root `AGENTS.md`.

## Automation Flow

After scaffold and required-file validation, Automation can start or stop a detached target-scoped DAG scheduler runner.

- **Start** launches `.diffmogger/scripts/run_temporal_worker.sh` in a detached local process. The runtime model is Temporal plus the execution DAG read model.
- **Stop** terminates the recorded runner process group.
- **Run Safety Check** runs `scripts/check_integration_safety.py` and records target safety evidence.

Automation writes runner logs under `.diffmogger/runtime/automation_logs/`. Execution DAG state is canonical in `.diffmogger/runtime/orchestration.sqlite3`. The dashboard derives state from scheduler-selected action, tickets, DAG nodes, execution groups, conflict telemetry, validation receipts, integration queue state, repair/unblocker work, next actions, and ticket completion, not from raw validation failure counts alone.

Human input records are planning inputs in the current model. They should not hide independent work, setup, repair, mock, fixture, defer, split, reframe, documentation, review, or alternate-ticket work that can continue.

Validation failures are shown as validation/repair work rather than a generic frozen state. Required failures create repair nodes; missing tools create setup/harness nodes; external service failures create mock, local-fixture, or defer nodes; browser/MCP failures create alternate validation or deferred QA nodes; repeated failures create planner split/reframe/defer work. Current dashboards may surface unsafe, destructive, or corrupt state as `CRITICAL_STOP`; that label is compatibility vocabulary, not a reason to freeze the vocabulary forever.

## Review Artifacts

The native dashboard does not have a Review page or review-bundle command. When a target needs a local observatory artifact, run the target helper directly:

```bash
python3 .diffmogger/scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review
```

That writes:

```text
/tmp/Diffmogger-review/Diffmogger-observatory.html
/tmp/Diffmogger-review/Diffmogger-self-review.md
```

## Validation

```bash
cd services/agentic-dashboard/native
npm test
npm run build
cd src-tauri && cargo test
```
