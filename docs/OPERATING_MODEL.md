# Operating Model

This document describes the active architecture, not a permanent contract. Durable principles are: reusable sidecar scaffolding, local-first safety, typed runtime/read-model state, generated projections, reviewable automation, clear validation evidence, and clean migrations for existing targets.

## Architecture

- Temporal owns workflow lifecycle, retries, timers, heartbeats, long-running execution, worker restarts, and crash recovery.
- launchd supervises the macOS runner when available. The portable fallback is a detached local process with the same runner state projection.
- SQLite is a local control-plane/read-model store for tickets, DAG nodes and edges, scheduler decisions, execution groups, validation groups, integration queue state, conflict telemetry, repair/unblocker work, code facts, human input, notification audit, ownership leases, projections, and runtime events.
- Alembic owns schema migration for the SQLite read model.
- Pydantic owns runtime contracts, scheduler records, notification payloads, ticket records, validation receipts, DAG records, DTOs, and JSON-schema-facing shapes.
- Apprise owns outbound delivery. Diffmogger keeps only a small loopback API adapter and local audit records.
- Tree-sitter owns deterministic code facts when parsers are available; fallback facts are explicit and non-authoritative.

## Runner Loop

1. Dashboard **Start** calls the supervision adapter.
2. On macOS, the adapter installs/starts a per-target launchd job for `.diffmogger/scripts/run_temporal_worker.sh`; other platforms use the portable fallback.
3. The Temporal worker runs campaign and scheduler-cycle workflows.
4. Scheduler policy stays pure and testable outside Temporal.
5. Activities persist Pydantic-validated records into Alembic-managed SQLite.
6. Generated Markdown/JSON projections are refreshed from typed state for humans and agents.
7. Dashboard **Stop** stops the launchd job or fallback runner and updates runner state.

## Work Generation

Diffmogger is a work generator, not a blocker detector. Required check failures create repair work. Missing tools create setup or harness work. External services create local fixture, mock, or defer work. Browser/MCP failures create alternate validation or deferred QA work. Repeated failures create split, reframe, planner, or review work. Human input creates pending input records while independent work continues.

The compatibility status names `ACTIVE`, `ACTIVE_WITH_PENDING_USER_INPUT`, `BLOCKED_ON_USER`, `BLOCKED_ON_ENVIRONMENT`, and `CRITICAL_STOP` may still appear in migrated targets. Treat them as annotations for current dashboards and prompts, not as scheduler doctrine.

## Swarm Readiness

Temporal workflows are designed for bounded fanout, scoped work waves, validation gates, and serialized integration when ownership overlaps. The current scheduler prefers non-overlapping scopes backed by paths, Tree-sitter symbol/import facts, validation state, active leases, confidence, or explicit scope evidence. Low confidence, stale facts, stale leases, optional validation failures, missing parser support, and ambiguous ownership reduce fanout or generate scope/setup work; they are not terminal blocker states.

## State And Projections

Canonical live state is `.diffmogger/runtime/orchestration.sqlite3`. Human-facing files such as `.diffmogger/runtime/canonical_state_brief.md` and `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` are projections. If a projection disagrees with SQLite, rebuild or inspect the read model rather than hand-editing the projection as authority.

Generated targets are decoupled from the Diffmogger source checkout at runtime by bundling `.diffmogger/lib/diffmogger/` and target-local `.diffmogger/scripts/` wrappers.

## Validation

Source-kit changes should pass:

```bash
bash scripts/validate_starter_kit.sh
```

When scaffolding behavior changes, also run:

```bash
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target /tmp/Diffmogger-smoke --force
python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```
