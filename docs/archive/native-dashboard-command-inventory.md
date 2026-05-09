# Native Dashboard Command Inventory

This compact archive exists because `scripts/validation/check_native_rebuild_guardrails.py` verifies that the native dashboard still exposes the command groups Diffmogger depends on. Active dashboard guidance lives in `docs/DASHBOARD.md`; active architecture guidance lives in `docs/architecture/native-dashboard.md`.

The current app is `services/agentic-dashboard/native`. It calls `scripts/dashboard_backend_cli.py`, and the Observatory export keeps the `Diffmogger Autonomous Build Log` review artifact available for local inspection.

## Backend Command Groups

- Prerequisite checks: `diagnostics.environment`, `diagnostics.run_checks`.
- Fresh-project setup: `brief.load`, `brief.save_draft`, `brief.scaffold_preview`, `brief.scaffold_bootstrap`.
- Existing-project setup: `brief.scaffold_preview`, `brief.scaffold_bootstrap`.
- Project intake fields: `brief.load`, `brief.save_draft`, `brief.scaffold_bootstrap`.
- Context-file import: `context.import`.
- Project-context generation: `context.import`.
- Scaffold/bootstrap: `brief.scaffold_preview`, `brief.scaffold_bootstrap`.
- Continuous automation start/stop: `run.load`, `automation.start`, `automation.stop`.
- Run safety check: `safety.run_check`.
- Review export: `review.load`, `review.export_bundle`, `review.mark_reviewed`.
- Observatory launch: `observatory.snapshot`, `observatory.generate_html`, `observatory.load_html`.
- Worker strategy controls: `run.load`, `worker.run_read_only`, `worker.run_write`, `worker.run_integrator`.
- Human bridge and file-only messaging: `inbox.load`, `inbox.send_note`, `inbox.reply_request`.
- Markdown file monitor/editor: `advanced.list_files`, `advanced.load_file`, `advanced.save_file`, `advanced.validate_file`.
- Multi-role and conveyor intake settings: `brief.save_draft`, `brief.scaffold_bootstrap`, `run.load`.
- Context7 and Playwright MCP options: `brief.load`, `brief.save_draft`, `brief.scaffold_bootstrap`.
- Dashboard state persistence: `project.load_snapshot`, `brief.load`, `brief.save_draft`.
- Debug bundle: `advanced.export_debug_bundle`.

## Current Source Ownership

- Native UI: `services/agentic-dashboard/native/`.
- Backend CLI: command registry and implementation groups under `src/diffmogger/dashboard/cli.py` and `src/diffmogger/dashboard/commands/`, exposed through `scripts/dashboard_backend_cli.py`.
- Compatibility facade: `src/diffmogger/dashboard/backend_cli.py`.
- Shared dashboard helpers: `src/diffmogger/dashboard/shared/`.
- Scaffold and source-kit validators: `src/diffmogger/kit/`.
- Target runtime modules: `src/diffmogger/runtime/`, bundled into generated targets under `.diffmogger/lib/diffmogger/`.
- Generated target shell helpers: physical templates under `templates/scripts/`.

## Guardrail Intent

The native app should remain a thin client over backend commands. The frontend may render state, collect input, and call allowlisted commands, but scaffold, safety, automation runner, review, worker, inbox, and target-file semantics belong in Python backend modules.

Mutating commands should return machine-readable results, include touched paths where useful, avoid secret values, and keep generated target repos decoupled from the Diffmogger source checkout at runtime.
