# DAG Symbol Scheduler Architecture Audit

Status: internal audit after the DAG scheduler, symbol graph, impact model, and dashboard migration.

## Runtime Contract

The trusted scheduler state is SQLite:

- `execution_dag_nodes` and `execution_dag_edges` are the canonical runtime graph. Hard edges block scheduling; advisory edges are context only.
- `execution_groups` and `execution_group_items` hold proposed and launched ready waves derived from DAG nodes.
- `resource_leases` are the concurrency guard for write ownership.
- `worker_agents`, `worker_contracts`, and `worker_patches` describe launched workers and serialized integration backlog.
- `validation_jobs` and `validation_receipts` record validation evidence; DAG validation nodes store receipt references.
- `scheduler_candidates` records the selected action and skipped/runnable alternatives for audit and dashboard display.

Graph facts are advisory until normalized into scheduler inputs by policy:

- Raw `graph_nodes`, `graph_edges`, `graph_node_facts`, and `graph_edge_facts` are discovery/debug facts.
- Impact graph edges and context packs are advisory read models.
- Direct path mentions and exact symbol-owner matches become trusted write candidates only after the confidence policy creates `likely_touches`.
- Keyword-only, import-adjacency, and test-proximity signals are scoping/read-only context unless reinforced by a direct path or exact symbol signal.
- When a ready ticket is blocked from write fanout by missing or insufficient direct write confidence, a bounded read-only scope evidence group is preferred before serial builder fallback when the read-only budget is available.
- Read-only scope/review reports can add structured `scope_evidence_records`, but worker prose is never write authority. Records must normalize against the current codebase graph, clear the promotion threshold, and avoid stale or ambiguous ownership before they can influence `likely_touches`.
- Dashboard snapshots, Markdown briefs, JSON projections, and old conveyor-shaped projections are read-only observability surfaces.

## Symbol Graph Flow

`src/diffmogger/runtime/codebase_graph.py` builds the codebase graph. File, directory, command, module, and symbol nodes use stable hashed IDs. Symbol nodes store owner file path, language, kind, qualified name, export status, line number, parser source, and confidence. File-to-symbol ownership is represented by `owns_symbol` edges.

Python extraction uses `ast.parse` for imports, top-level functions/classes, and class methods. Syntax failures keep file-level graphing alive by recording parser status with reduced confidence instead of dropping the file.

TypeScript and JavaScript extraction strips comments and uses bounded regex extraction for imports, re-exports, functions, classes, methods, arrow functions, and component-like declarations. Relative JS/TS imports resolve back to file nodes when possible. Parser confidence is lower than Python AST confidence, so the symbol layer improves impact without replacing file fallback.

SQLite persistence happens through `state_store.create_codebase_graph_tables`, `_insert_codebase_graph_conn`, and partial reindexing in `refresh_codebase_graph_changed_file_conn`. Graph snapshots retain file nodes even when symbol parsing fails.

## Impact Model

The impact layer joins task/DAG text, authored metadata, codebase graph nodes, symbol ownership, import edges, likely-test edges, commands, and artifacts.

Signal policy:

- Authored paths and exact path mentions are direct write signals.
- Exact symbol owner matches are direct write signals.
- Import adjacency and test proximity inherit reduced confidence and remain scoping/read-only by default.
- Keyword-only matches are advisory and capped below write confidence.
- Validation commands are context for validation, not write ownership.

For DAG planning, `_parallel_context_pack_for_dag_node_conn` builds a bounded context pack from the latest codebase graph. `_parallel_touch_items` promotes only direct write candidates at or above the write threshold (`0.75`) into `likely_touches`. `_parallel_scoping_items` allows read-only context at the lower threshold (`0.55`). If a ready `scope` node exists because write confidence is missing, insufficient scoping confidence now creates a read-only scope evidence group instead of immediately forcing serial builder fallback. That group stores ownership evidence, likely paths, likely symbols, validation hints, and risk notes in `execution_group_items.payload_json`.

Completed read-only reports are scanned only for structured JSON evidence blocks. Normalized `scope_evidence_records` rows capture candidate paths, candidate symbols, confidence, stale-context warnings, likely tests, reasons, source worker/report IDs, and accepted/advisory/rejected status. Accepted exact-owner or exact-path records feed later impact scoring and DAG materialization, allowing a future cycle to drop the scope gate and launch write workers. Rejected or advisory records stay visible for audit and do not create write candidates or leases.

## Scheduler Inputs

`choose_next_graph_aware` refreshes capability, codebase graph, execution DAG, task graph, impact graph, leases, worker patches, and validation jobs, then plans a DAG-native action. The selected action is one of:

- `launch_scope_group`
- `launch_write_group`
- `launch_validation_group`
- `launch_review_group`
- `run_serial_integration`
- `reconcile_worker_results`
- `create_repair_nodes`

`execution_dag_read_model` is the scheduler gate: terminal hard dependencies unblock target nodes, unresolved hard dependencies or hard blocker edges block them, and advisory edges do not block. Action capability metadata defines permissions, inputs, outputs, lease behavior, prompt base, and optional/required policy for `orchestrate`, `decompose`, `scope`, `build`, `review`, `validate`, `repair`, `integrate`, `audit`, and `calibrate`. The scheduler prioritizes failed-validation repair creation, ready serialized integration, worker-result reconciliation, ready execution waves, and single ready scope/review/validation nodes. It does not rotate through conveyor stages.

`plan_parallel_execution_groups_conn` builds ready waves from `execution_dag.ready_nodes` when DAG nodes exist. It excludes compatibility default nodes, ticket roots, blocker nodes, completion, integration, and human/environment-blocked nodes. High-confidence build nodes can skip a separate scope node; low-confidence work receives scope/review/audit/repair specialization through typed dependencies. Scope nodes with weak or missing context can still launch read-only evidence fanout so workers gather ownership signals before the scheduler falls back to `run_serial_role`. Write candidates conflict when their `likely_touches` overlap by graph node or path containment. Integration remains serialized. Planner telemetry records fast-path build count, specialization count, and whether specialization is expected to increase wall-clock time, reduce failures, or both.

## Leases And Workers

Write groups require confident ownership. DAG write candidates generate typed resource leases from `likely_touches`: file fallback, directory, tests-only, docs-only, exact symbol, module, and package scopes are allowed only when the graph can detect conflicts safely. `launch_write_execution_group_conn` rechecks ownership, acquires leases, writes worker contracts, runs isolated write workers, stores patch manifests, and queues patches for integrator review. Workers do not mutate the main checkout directly.

Read-only scope/review groups do not acquire write leases. Scope evidence groups also keep `required_leases` empty and use worker contracts that forbid source, projection, and runtime-state mutation. Validation groups use the validation budget and command classification instead of file ownership leases.

## Validation And Repair

`run_parallel_validation_conn` records validation jobs, logs, artifacts, and typed validation receipts. `record_validation_group_result_on_execution_dag_conn` updates DAG validation nodes, increments attempts, records failed receipt refs, and marks failed validation nodes blocked.

`reconcile_worker_results_into_execution_dag_conn` converts queued worker patches into review, validation, and integration DAG nodes. Compatible worker patches can converge into one review and validation node. Each integration node remains patch-specific and waits on validation.

`create_repair_nodes_for_failed_validation_conn` creates targeted repair nodes connected to failed work/review/validation evidence. Once retry limits are exhausted, it creates explicit blocker nodes instead.

## Dashboard And Snapshots

`state_snapshot` exposes `execution_dag` and aliases it as `progress_model`; fresh snapshots therefore show DAG state as the primary progress model. It also exposes graph summaries, context-pack previews, stale graph warnings, leases, proposed execution groups, scheduler candidates, validation jobs, worker contracts, and integration backlog.

The Run page reads `run.state.execution_dag` first, falls back only to `progress_model` when it is already an execution DAG, and renders a native SVG DAG with phase columns, hard/advisory edges, status counts, blocker details, patch metadata, ownership scope, and receipt references. Empty DAG snapshots show "No DAG data for this run" rather than reconstructing conveyor behavior.

Telemetry is recorded in the event ledger, `scheduler_candidates.graph_signals_used`, execution-group rows, validation job rows, worker patch rows, lease rows, and dashboard/observatory snapshots.

## Conveyor-Era Assumptions To Remove Later

- The dispatcher package, CLI, script names, lock file, logs, tests, and some event labels still use `conveyor` naming for compatibility (`run_conveyor_automation`, `automation_conveyor_state.json`, `automation_conveyor.lock`, `CONVEYOR_*`). These names are process-shell compatibility, not scheduler authority.
- `materialize_execution_dag_conn` still creates a default `task:conveyor` linear path from compatibility state for non-ticket runs. Parallel planning explicitly skips these default compatibility nodes, but this path should be renamed or replaced with a neutral default task model.
- `plan_parallel_execution_groups_conn` still has a `task_graph_compatibility` fallback if called before any DAG nodes exist. New scheduler and snapshot paths materialize DAG first, but the fallback should be removed once all callers require DAG materialization.
- `state_snapshot` still materializes conveyor machine projections and exposes `conveyor_state`/`conveyor_machine` for older helpers and observability. These should shrink to migration/debug surfaces after downstream consumers stop reading them.
- Validation receipt projection still maps some legacy validation evidence through `CONVEYOR_WORK_ITEM_ID`. DAG validation nodes store explicit receipt refs, but receipt ownership should be migrated to DAG node/task ids.
- Home and Observatory dashboard models still contain role-lane/conveyor compatibility sections. The Run page is DAG-primary, but secondary views should eventually rename those surfaces around DAG execution lanes.

## Verdict

The canonical scheduler loop is DAG-native: new decisions come from SQLite execution DAG readiness, worker/validation/integration tables, leases, and configured budgets. Symbol and file graph facts improve confidence and ownership selection, but they remain advisory until converted into direct, thresholded `likely_touches` or validation context. The remaining conveyor influence is mostly compatibility naming and projection support, with the `task_graph_compatibility` fallback and default `task:conveyor` path as the main removal candidates.
