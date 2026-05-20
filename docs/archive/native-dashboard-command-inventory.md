# Native Dashboard Command Inventory

This compact inventory exists because `scripts/validation/check_native_rebuild_guardrails.py` verifies that the native dashboard still exposes the command groups Diffmogger depends on. Active dashboard guidance lives in `docs/DASHBOARD.md`; active architecture guidance lives in `docs/architecture/native-dashboard.md`.

The current app is `services/agentic-dashboard/native`. It calls `scripts/dashboard_backend_cli.py` and exposes two user surfaces: **Setup** and **Automation**.

## Backend Command Groups

- Prerequisite checks: `diagnostics.environment`, `diagnostics.run_checks`.
- Fresh-project setup: `brief.load`, `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold`.
- Existing-project setup: `brief.scaffold_preview`, `brief.scaffold`.
- Project intake fields: `brief.load`, `brief.generate_intake`, `brief.save_draft`, `brief.scaffold`.
- Context-file import: `context.import`.
- Project-context generation: `context.import`.
- Scaffold/start: `brief.scaffold_preview`, `brief.scaffold`, `automation.start`.
- Continuous automation start/stop: `project.load_snapshot`, `automation.start`, `automation.stop`.
- Run safety check: `safety.run_check`.
- Ticket queue: `ticket.load`, `ticket.add`, `ticket.update`, `ticket.delete`, `ticket.import`, `ticket.draft_from_intake`, `ticket.accept_draft`, `ticket.split_preview`, `ticket.accept_split`.
- Runtime state: `state.snapshot`, `state.brief`, `state.validate`, `state.watch`.
- Worker and parallel controls: `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`, `worker.launch_read_only_group`, `worker.launch_write_group`, `execution_group.load`, `execution_group.start`, `execution_group.cancel`, `execution_group.retry_failed`, `execution_group.export_debug_bundle`, `validation_jobs.load`, `lease.release_stale`.
- Human input records: `project.load_snapshot`, `state.snapshot`.
- Multi-role and DAG scheduler intake settings: `brief.save_draft`, `brief.scaffold`, `project.load_snapshot`, `state.snapshot`.
- Context7 and Playwright MCP options: `brief.load`, `brief.save_draft`, `brief.scaffold`.
- Dashboard state persistence: `project.load_snapshot`, `brief.load`, `brief.save_draft`.
- Parallel debug bundle: `execution_group.export_debug_bundle`.

## Current Source Ownership

- Native UI: `services/agentic-dashboard/native/`.
- Backend CLI: command registry and implementation groups under `src/diffmogger/dashboard/cli.py` and `src/diffmogger/dashboard/commands/`, exposed through `scripts/dashboard_backend_cli.py`.
- Compatibility facade: `src/diffmogger/dashboard/backend_cli.py`.
- Shared dashboard helpers: `src/diffmogger/dashboard/shared/`.
- Scaffold and source-kit validators: `src/diffmogger/kit/`.
- Target runtime modules: `src/diffmogger/runtime/`, bundled into generated targets under `.diffmogger/lib/diffmogger/`.
- Generated target shell helpers: physical templates under `templates/scripts/`.

## Guardrail Intent

The native app should remain a thin client over backend commands. The frontend may render state, collect setup input, and call allowlisted commands, but scaffold, safety, automation runner, worker, ticket, human-input, and target-file semantics belong in Python backend modules and SQLite runtime state.

Removed page command groups for Inbox, Review, Activity/Observatory, and Advanced should not be reintroduced as normal native scheduler gates.
