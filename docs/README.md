# Diffmogger Docs

This directory is for source-kit documentation. Generated target-state docs live in `templates/docs/` and render into `.diffmogger/state/` as human/prompt projections, authored surfaces, or exports. Canonical live orchestration state is typed SQLite under `.diffmogger/runtime/orchestration.sqlite3`; agents read the generated `.diffmogger/runtime/canonical_state_brief.md` view.

Docs should distinguish durable kit principles from current implementation choices. Project-agnostic behavior, local-first safety, secret hygiene, typed runtime state, and reviewable automation are durable. Status names, scheduler internals, runner supervision, notifier implementation, and code-indexing details are current defaults that can change when a migration makes Diffmogger simpler or more reliable.

## Active Docs

- [Fresh Project Setup](FRESH_PROJECT_SETUP.md): dashboard and CLI setup flow for fresh or existing target repos.
- [Dashboard](DASHBOARD.md): native dashboard, backend CLI, run controls, safety, review, and worker controls.
- [Operating Model](OPERATING_MODEL.md): current run loop, compatibility statuses, sidecar layout, execution DAG state, and generated runtime views.
- [Human Bridge](HUMAN_BRIDGE.md): file-only handoff and optional notifier modes.
- [Worker Agents](WORKER_AGENTS.md): read-only workers, write-worker opt-in, and multi-role conventions.
- [Troubleshooting](TROUBLESHOOTING.md): local failure modes and recovery steps.
- [Examples](EXAMPLES.md): fictional reusable intake examples.
- [Native Dashboard Architecture](architecture/native-dashboard.md): source layout, backend command contract, and build notes.
- [DAG Symbol Scheduler Audit](architecture/dag-symbol-scheduler-audit.md): internal map of DAG scheduler, graph facts, leases, validation, dashboard projections, and conveyor-era residue.
- [Symbol Identity Contract](architecture/symbol-identity-contract.md): normalized cross-language symbol shape and scheduler resolution policy.
- [Concurrency Readiness Audit](architecture/concurrency-readiness-audit.md): end-to-end scheduler readiness findings and small follow-up tickets for safer parallel throughput.

## Root Docs

- [README](../README.md): short project orientation and quickstart.
- [Development](../DEVELOPMENT.md): contributor workflow, source ownership, validation, and docs policy.

## Service Docs

- [Dashboard service](../services/agentic-dashboard/README.md): native dashboard service layout.
- [Native dashboard app](../services/agentic-dashboard/native/README.md): Tauri app development commands.
- [Notifier service](../services/agentic-notifier/README.md): optional local/Discord notifier service.

## Archive Policy

`docs/archive/` is not a dumping ground. Keep only records that explain current architectural decisions or carry a compact maintenance checklist. Delete stale setup guides, migration plans, and obsolete product notes.
