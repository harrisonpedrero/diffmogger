# Diffmogger Docs

This directory is for source-kit documentation. Generated target-state docs live in `templates/docs/` and render into `.diffmogger/state/` as human/prompt projections, authored surfaces, or exports. Canonical live orchestration state is SQLite under `.diffmogger/runtime/orchestration.sqlite3`; agents read the generated `.diffmogger/runtime/canonical_state_brief.md` view.

## Active Docs

- [Fresh Project Setup](FRESH_PROJECT_SETUP.md): dashboard and CLI setup flow for fresh or existing target repos.
- [Dashboard](DASHBOARD.md): native dashboard, backend CLI, run controls, safety, review, and worker controls.
- [Operating Model](OPERATING_MODEL.md): recurring run loop, statuses, sidecar layout, conveyor state, and generated runtime state.
- [Human Bridge](HUMAN_BRIDGE.md): file-only handoff and optional notifier modes.
- [Worker Agents](WORKER_AGENTS.md): read-only workers, write-worker opt-in, and multi-role conventions.
- [Troubleshooting](TROUBLESHOOTING.md): local failure modes and recovery steps.
- [Examples](EXAMPLES.md): fictional reusable intake examples.
- [Native Dashboard Architecture](architecture/native-dashboard.md): source layout, backend command contract, and build notes.

## Root Docs

- [README](../README.md): short project orientation and quickstart.
- [Development](../DEVELOPMENT.md): contributor workflow, source ownership, validation, and docs policy.

## Service Docs

- [Dashboard service](../services/agentic-dashboard/README.md): native dashboard service layout.
- [Native dashboard app](../services/agentic-dashboard/native/README.md): Tauri app development commands.
- [Notifier service](../services/agentic-notifier/README.md): optional local/Discord notifier service.

## Archive Policy

`docs/archive/` is not a dumping ground. Keep only records that explain current architectural decisions or preserve a compact maintenance checklist. Delete stale setup guides, migration plans, and obsolete product notes.
