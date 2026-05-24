# Diffmogger Docs

This directory is for active source-kit documentation. Generated target docs live in `templates/docs/` and render into `.diffmogger/state/` as projections or authored setup surfaces.

Canonical live orchestration state is typed SQLite under `.diffmogger/runtime/orchestration.sqlite3`. Markdown and JSON files are generated views, audit projections, or migration aids.

## Active Docs

- [Fresh Project Setup](FRESH_PROJECT_SETUP.md): dashboard and CLI scaffold flow.
- [Dashboard](DASHBOARD.md): native dashboard, backend CLI, run controls, safety, and worker controls.
- [Operating Model](OPERATING_MODEL.md): Temporal, launchd, Alembic, Pydantic, Apprise, Tree-sitter, and SQLite roles.
- [Human Bridge](HUMAN_BRIDGE.md): typed human-message state and Apprise notifier mode.
- [Worker Agents](WORKER_AGENTS.md): bounded read/write worker conventions and integration safeguards.
- [Troubleshooting](TROUBLESHOOTING.md): local failure modes and recovery steps.
- [Examples](EXAMPLES.md): fictional reusable intake examples.

## Root Docs

- [README](../README.md): project orientation and quickstart.
- [Development](../DEVELOPMENT.md): contributor workflow, validation, and docs policy.

## Service Docs

- [Dashboard service](../services/agentic-dashboard/README.md)
- [Native dashboard app](../services/agentic-dashboard/native/README.md)
- [Notifier service](../services/agentic-notifier/README.md)

## Docs Policy

Keep docs command-oriented and current. Delete stale architecture notes instead of preserving parallel old/new explanations. Compatibility surfaces should be described as migration aids, not permanent rules.
