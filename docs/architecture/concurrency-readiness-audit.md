# Concurrency Readiness Audit

Audit date: 2026-05-16

Scope: DAG scheduler, symbol graph, impact scoring, leases, worker launchers, validation fanout, integration handoff, and dashboard observability. This audit uses `docs/architecture/dag-symbol-scheduler-audit.md` and `docs/architecture/symbol-identity-contract.md` as baseline context.

Authority rule: SQLite runtime state is the control plane. Markdown, briefs, worker reports, and dashboard JSON are projections or inputs; they do not directly authorize writes.

## Current Concurrency Flow

1. `choose_next_graph_aware` refreshes the runtime view before each decision: capability manifest, codebase graph, automation control, execution DAG, task graph, impact graph, leases, parallel dry-run groups, queued worker patches, integration preflight, and failed validation jobs.
2. `plan_parallel_execution_groups_conn` derives ready candidates from execution DAG nodes when available, falling back to compatibility task graph inputs only when the DAG is not populated.
3. Impact scoring separates trusted write evidence from advisory context. Direct path mentions, exact fresh symbol owners, and accepted normalized scope evidence can produce `likely_touches`; keyword matches, import adjacency, stale symbols, and ambiguous ownership stay advisory.
4. Read-only scope and review groups can fan out without write leases. They produce structured scope evidence, validation hints, risk notes, likely paths, and likely symbols for later normalization.
5. Write groups remain opt-in and conservative. Candidates need confident `likely_touches` plus compatible lease shapes. Overlap by file, directory, symbol/module/package-style ownership, or active lease blocks same-wave writes.
6. Validation fanout classifies commands into unit, lint, typecheck, smoke, docs, generated-helper, browser, resource-heavy, environment-repair, and exclusive lanes. Safe read-only checks run concurrently; exclusive or resource-heavy work stays serialized.
7. Worker patches are queued and reconciled into review, validation, and integration DAG nodes. Integration itself remains serialized.
8. `worker_patch_integration_preflight_conn` predicts safe patch order, overlap conflicts, stale bases, missing metadata, and validation dependency readiness before the integrator applies queued patches.
9. Runtime snapshots and dashboard models expose proposed groups, active groups, leases, validation jobs, integration backlog, integration preflight, and the "Why Not Parallel?" read model.

## Top Serial Fallback Causes

| Cause | Typical signal | Concrete unlock |
| --- | --- | --- |
| `missing_direct_write_signal` | A ready write node has no direct path, exact symbol owner, or accepted scope evidence. | Add explicit path/symbol ownership evidence or launch read-only scope fanout. |
| `insufficient_scoping_confidence` | Context is keyword-only, adjacency-only, ambiguous, or below the write threshold. | Collect structured scope evidence with candidate paths, symbols, tests, and reasons. |
| `stale_symbol` | Symbol or file graph evidence is stale or parse status is not trustworthy. | Refresh the affected index slice before attempting write grouping. |
| `write_surface_overlap` | Candidate `likely_touches` or lease shapes overlap another write candidate. | Split ownership, narrow scope, or serialize the overlapping work. |
| `lease_conflict` | Active resource leases cover the same path, directory, symbol, module, package, docs, or tests surface. | Wait, release stale leases, or change ownership boundaries. |
| `budget_blocked` | Read-only, write-worker, validation, or global worker budget is exhausted. | Raise budget deliberately or wait for active jobs to finish. |
| validation backpressure | Failed validation jobs require repair nodes or validation DAG dependencies are pending. | Create targeted repair nodes and rerun only the needed gates. |
| integration preflight block | Patch metadata is missing, base commit is stale, patches overlap, or integration DAG nodes are not ready. | Reconcile metadata, refresh/rebase patch context, or serialize conflict resolution. |
| compatibility fallback | Scheduler has no useful DAG-ready node and falls back to legacy task compatibility. | Materialize precise DAG nodes with action capabilities and dependencies. |

## Missing Evidence Loops

- Stale symbol handling mostly appears as a blocking reason or warning. It should produce a small index-refresh or scope-repair action for only the affected files before serial fallback.
- The scope evidence loop normalizes worker reports and can promote accepted evidence, but operators need clearer telemetry for accepted, advisory, and rejected evidence by DAG node and reason.
- "Why Not Parallel?" aggregates blocked reasons, but the next improvement is still mostly reason-level. The next step should be candidate-level evidence hints, such as exact paths to confirm, stale symbols to refresh, or leases to split.
- Validation job receipts record command classification and outcomes, but repeated validation failures do not yet strongly feed back into scoping confidence, repair-node priority, or write readiness.
- Integration preflight is typed and visible, but the serialized integrator should keep proving it only acts on the safe preflight subset selected for that run.
- Lease grouping is richer, but confidence thresholds for docs-only, tests-only, module, symbol, directory, and package ownership need a compact fixture suite to prevent accidental broadening.
- Dashboard observability is good for current state; it can be better at showing "next unlock" rows per blocked candidate and per budget.

## Highest-Leverage Implementation Tickets

### CONC-AUDIT-001: Create stale-index refresh repair nodes

Add a typed scheduler follow-up when blocked candidates include `stale_symbol` or stale file graph context. The node should refresh only the affected files or symbols, then allow the next scheduling cycle to recompute impact.

Acceptance: stale symbol fixtures create a refresh or scope-repair DAG node; no source files are mutated; refreshed exact owners can later promote write readiness.

### CONC-AUDIT-002: Persist candidate-level next-evidence hints

Store normalized missing evidence hints for blocked candidates, including candidate paths, symbols, confidence gaps, stale context, and recommended evidence source.

Acceptance: snapshots and canonical briefs show per-candidate next evidence without treating Markdown as authority.

### CONC-AUDIT-003: Add scope evidence promotion telemetry

Track whether accepted scope evidence actually raised `likely_touches` or write confidence on a later impact refresh.

Acceptance: tests cover accepted exact-owner evidence, ambiguous evidence, stale evidence, and rejected evidence counts by reason.

### CONC-AUDIT-004: Enforce integration preflight selected-patch allowlist

Pass the selected safe patch IDs into the integrator handoff and ensure the integrator ignores queued patches outside that typed allowlist.

Acceptance: an integration run with one safe patch and one conflict applies only the safe patch and records the deferred conflict reason.

### CONC-AUDIT-005: Feed validation failures into DAG repair priority

Use validation job receipts to prioritize targeted repair nodes and block repeat write readiness for the same ownership surface until required validation is repaired.

Acceptance: failed required validation creates a repair node with command family and affected ownership evidence; unrelated write candidates remain schedulable.

### CONC-AUDIT-006: Add lease confidence fixture matrix

Create data-driven tests for file, directory, docs-only, tests-only, symbol, module, and package lease shapes.

Acceptance: independent docs, tests, and module writes can group; overlapping source ownership stays blocked; stale or ambiguous symbol evidence never grants a write lease.

### CONC-AUDIT-007: Distinguish solo-safe from blocked-parallel

Separate "only one safe candidate is ready" from unsafe serial fallback reasons in the read model.

Acceptance: a single safe candidate reports low parallel opportunity, not a blocked parallel failure.

### CONC-AUDIT-008: Add sidecar worker launcher contract matrix

Keep regression coverage for explicit report paths, legacy reported paths, role slug normalization, raw logs, and sidecar-aware canonical run directories.

Acceptance: read-only and write worker launchers record a real reported path instead of creating synthetic failure reports when the helper succeeds.

### CONC-AUDIT-009: Add validation setup-cache evidence

Record when target-local setup caches or reusable virtual environments are detected and why they are safe to reuse.

Acceptance: validation snapshots show cache hit, cache miss, and unsafe-cache reasons without reinstalling tooling unnecessarily.

### CONC-AUDIT-010: Warn on unexpected compatibility scheduling

Emit a typed warning when the scheduler falls back to task-graph compatibility after execution DAG materialization should have produced ready nodes.

Acceptance: fallback is visible in snapshots and briefs with the missing DAG capability or dependency reason.

## Suggested Validation Strategy

- Unit-test impact scoring with path mention, exact fresh symbol, stale symbol, ambiguous symbol, keyword-only, accepted scope evidence, and rejected scope evidence fixtures.
- Unit-test lease overlap for file, directory, docs-only, tests-only, symbol, module, and package lease shapes.
- Integration-test scheduler order: validation repair, safe serial integration, worker reconciliation, parallel groups, ready single action, then serial fallback.
- Test read-only scope fanout as the preferred path before serial fallback when write confidence is missing or insufficient.
- Test validation planning with parallel-safe commands, exclusive commands, resource-heavy commands, and validation receipt recording.
- Test integration preflight for independent patches, overlapping patches, stale bases, missing metadata, and validation-pending patches.
- Snapshot-test runtime briefs and dashboard state for proposed groups, blocked candidates, why-not-parallel groups, validation jobs, and integration preflight.
- Run `bash scripts/validate_starter_kit.sh` after source, docs, schema, or template changes. Run scaffold smoke checks when template output or required generated files change.

## Risks and Guardrails

- Worker prose must never directly authorize writes. Only normalized, thresholded, auditable SQLite evidence can affect `likely_touches`, leases, or write readiness.
- Read-only workers must not acquire write leases, mutate source, spawn more workers, use credentials, or depend on network access.
- Write workers stay opt-in, bounded by budgets, and blocked by any overlapping ownership unless an explicit coordination protocol exists.
- Integration remains serialized even when preflight predicts independent patches.
- Stale, ambiguous, unresolved, or low-confidence symbols remain advisory until refreshed and normalized.
- Budget increases should be explicit operator choices, not automatic reactions to blocked work.
- Keep all behavior target-project agnostic. Examples, docs, prompts, schemas, and templates should not assume a particular product stack.
- Sidecar paths must be canonical and launcher report paths must be explicit whenever possible.
