# Native Dashboard Architecture

Diffmogger's primary dashboard is the native Tauri v2 app. It is a thin operational shell over the Python backend and the target-local SQLite runtime control plane.

Generated sidecar targets resolve canonical files under `.diffmogger/`. Historical layouts are handled through explicit import/migration paths, not scattered dashboard reads.

## Information Architecture

The dashboard has only two screens:

- **Setup**: choose project, inspect setup status, edit intake, import context, manage seed tickets, scaffold, and run setup checks.
- **Automation**: show scheduler next action, queued/running/done DAG work, tickets, generated unblocker work, human input records, command output, and Start/Stop/Safety controls.

Removed surfaces:

- Home is folded into Setup.
- Run and Activity are folded into Automation.
- Review is removed from the native app.
- Inbox is a compact human-input panel/badge.
- Advanced/Sidecar controls are folded into Setup or Automation when still necessary.

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
python3 scripts/dashboard_backend_cli.py state.snapshot --target /path/to/target
```

Native validation:

```bash
cd services/agentic-dashboard/native
npm test
npm run build
cd src-tauri && cargo test
```

Full starter-kit validation:

```bash
bash scripts/validate_starter_kit.sh
```

## Architecture

The native app stays intentionally thin:

- React/TypeScript renders Setup, Automation, the command palette, and dense operational panels.
- Tauri/Rust owns native folder selection, recent-project config, path validation, safe open/reveal actions, and the allowlisted subprocess boundary.
- Python remains the backend source of truth through `scripts/dashboard_backend_cli.py`.
- SQLite runtime state is canonical. Markdown and JSON are projections or authored inputs.

The frontend must not scrape Markdown files for scheduler state. It calls backend commands and receives JSON snapshots. The only managed file opener retained by the shell is the canonical generated task projection, `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`.

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

Current native command groups:

- Project/setup: `project.load_snapshot`, `project.list_recent`, `brief.load`, `brief.generate_intake`, `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold`, `context.import`.
- Automation: `project.load_snapshot`, `run.once`, `automation.start`, `automation.stop`, `blocker.recheck_baseline`, `safety.run_check`.
- Runtime state: `state.snapshot`, `state.brief`, `state.validate`, `state.watch`.
- Tickets: `ticket.load`, `ticket.add`, `ticket.update`, `ticket.delete`, `ticket.import`, `ticket.draft_from_intake`, `ticket.accept_draft`, `ticket.split_preview`, `ticket.accept_split`.
- Worker/parallel controls: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`, `worker.launch_read_only_group`, `worker.launch_write_group`, `execution_group.load`, `execution_group.start`, `execution_group.cancel`, `execution_group.retry_failed`, `execution_group.export_debug_bundle`, `validation_jobs.load`, `lease.release_stale`.
- Diagnostics: `diagnostics.environment`, `diagnostics.run_checks`.

Native page-only commands for Inbox, Review, Activity/Observatory, and Advanced are not allowlisted.

## UI State Model

The dashboard answers six questions:

1. What project is selected?
2. Is Diffmogger installed/configured?
3. What is the scheduler doing next?
4. What tickets/actions are queued, running, done, or needing generated unblocker work?
5. What human input exists?
6. What command can the user run/start/stop?

State derivation lives in small testable frontend files:

- `BriefWizard.tsx`: project intake, scaffold preview/execution, context import, seed tickets, setup checks entry.
- `runModel.ts`: scheduler/automation read model, control enablement, DAG summaries, action rows, liveness copy.
- `AutomationPage.tsx`: dense operational rendering of scheduler next action, tickets/actions, human input, unblocker work, and command output.
- `commandPaletteModel.ts`: state-gated command palette commands and disabled reasons.

The dashboard currently remains compatible with `ACTIVE`, `ACTIVE_WITH_PENDING_USER_INPUT`, `BLOCKED_ON_USER`, `BLOCKED_ON_ENVIRONMENT`, and `CRITICAL_STOP`. Treat those names as compatibility vocabulary. User and environment states should annotate planning inputs rather than halt normal scheduling while unfinished work can continue, and future dashboard work may replace the vocabulary with a richer state model.

## Guardrails

Keep native behavior and test coverage aligned with:

- project selection and recent targets
- setup/scaffold preview and execution
- context import
- ticket import/add/update/delete/draft/split/accept
- automation start/stop
- safety checks
- scheduler-selected action and DAG state
- generated repair/setup/mock/fixture/defer/split/reframe/unblocker work
- human input records without a separate Inbox page

`scripts/validation/check_native_rebuild_guardrails.py` keeps broad feature groups honest. `scripts/validate_starter_kit.sh` checks the simplified native file set and command surface.
