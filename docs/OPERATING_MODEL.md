# Operating Model

This document describes the current implementation, not a permanent contract. Keep the durable principles: target-project agnostic setup, local-first safety, typed runtime state, generated projections, and reviewable automation. Treat status names, runner details, scheduler internals, notifier mechanics, and code-indexing strategies as replaceable defaults when a migration makes the kit smaller or more reliable.

## Loop

1. The continuous execution DAG scheduler chooses the next runnable node or wave.
2. The target repo's automation wrapper reads `.diffmogger/manifest.json`, acquires the manifest-declared lock path, and grants `$HOME/.codex` access for nested Codex CLI startup.
3. Codex reads `AGENTS.md`, `.diffmogger/runtime/canonical_state_brief.md`, `.diffmogger/agentic/automation_prompt.md`, `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`, `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`, and any relevant files listed in intake/dashboard context records.
4. Codex reads queued human-message summaries from the canonical state brief and records replies/resolutions through typed dashboard/SQLite state. In notifier modes it sends direct notifier responses when the human asked to be messaged.
5. Codex marks handled human messages resolved only after the requested action is complete or intentionally deferred.
6. Codex reads `## Product Horizon State`, chooses the highest-value sprint-sized milestone inside the current horizon, and gathers advancement evidence.
7. Codex records a `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` decision plus a worker strategy: `READ_ONLY_REPORTS`, `WRITE_WORKERS`, `INTEGRATION_ONLY`, or `NO_WORKERS`.
8. Codex may spawn bounded read-only workers if useful, optionally through `.diffmogger/scripts/spawn_worker_agent.sh`.
9. Codex may spawn up to the capped write-worker count as bounded acceleration for work that can split into reviewable lanes. The main agent must choose a parallelism budget, define enough ownership/contracts to keep work coherent, review diffs, integrate, verify, and update canonical SQLite state plus generated handoff projections.
10. Codex implements, verifies, and updates artifacts.
11. Codex updates typed automation control state, regenerates the canonical brief, and refreshes the task file only as a prompt/handoff projection. The runtime records typed events, execution DAG transitions, capability manifests, checkpoints, next actions, blockers, runs, and validations in SQLite.
12. The automation wrapper releases the lock through local `.diffmogger/scripts/release_codex_lock.sh` when possible and Codex returns a concise summary.

## DAG Scheduler Campaign Loop

Generated targets currently use the continuous DAG action scheduler with planner, builder, hardener/reviewer, and integrator prompt bases. The dashboard **Start** button launches one detached local runner for `.diffmogger/scripts/run_conveyor_automation.sh`; that wrapper enters the DAG runtime. **Stop** terminates the recorded runner process group. The runner records canonical execution DAG state in `.diffmogger/runtime/orchestration.sqlite3`, regenerates `.diffmogger/runtime/canonical_state_brief.md` before Codex runs, and generates `.diffmogger/runtime/automation_runner.json` and `.diffmogger/runtime/automation_conveyor_state.json` only as read-model projections. The scheduler chooses ready nodes and waves by DAG readiness, confidence, leases, and risk. Diffmogger should generate useful work rather than merely detect blockers: blockers are planning inputs that can create repair, setup, mock, fixture, defer, split, reframe, review, documentation, or alternate-ticket work while tickets remain. Typed state includes an append-only event ledger, execution DAG nodes for `orchestrate`, `decompose`, `scope`, `build`, `review`, `validate`, `repair`, `integrate`, `audit`, `calibrate`, blockers, and completion, plus hard/advisory DAG edges, repository capability manifests, checkpoints, current task/run projections, open blockers, validation receipts, active role runs, and bounded future decision projections for local observability. Those tables and action names are current interfaces, not sacred architecture.

When `campaign_mode` is `bounded`, generated targets use the dashboard-backed SQLite ticket queue and `.diffmogger/scripts/ticket_run.py` as the fixed campaign scope. Scaffold initializes ticket readiness, and Start launches actual automation directly. Normal campaign runs use `python3 .diffmogger/scripts/ticket_run.py . next --json` to select dependency-ready ticket context, keep queue order as the human priority order, and avoid inventing new scope after the bounded set is done. Planner, builder, and hardener worktrees stage ticket updates as typed runtime actions; the integrator applies those ticket changes to canonical SQLite only after the related patch is accepted. The DAG scheduler stops launching new work only after all tickets are done with evidence, then writes `.diffmogger/runtime/ticket_run_completion.json`, a Markdown completion report, and a native desktop notification or durable fallback record in typed human-message state. Blocked tickets remain live planning inputs that create unblocker DAG work. When `campaign_mode` is `ongoing`, the scheduler drafts/enqueues safe project-agnostic follow-up tickets from typed runtime context when no dependency-ready ticket remains, without pausing for approval just because tickets were drafted. Remote push/PR creation remains manual.

DAG scheduling config is stored from intake and surfaced in snapshots. Current fields include `parallel_execution_mode`, `symbol_graph_languages`, `parallel_write_min_confidence`, `parallel_write_direct_confidence`, `max_parallel_write_workers`, and `max_parallel_scope_workers`. These fields may be renamed or replaced during future orchestration work. The important behavior is bounded fanout, evidence-backed write confidence, explicit ownership, validation gates, and serialized integration when work overlaps.

Before a first long DAG run, use the target-local preflight report to check symbol freshness, extractor health, semantic coverage, scheduler config, lease conflicts, validation commands, dashboard DAG data, and telemetry. It returns `ready`, `warn`, or `block`, lists expected parallel and serialized tasks with reasons, and highlights risk areas before the 24h run begins:

```bash
python3 .diffmogger/scripts/preflight_parallelization_readiness.py --target . --json
```

Planner, builder, and hardener start from the current main `HEAD` in isolated worktrees under `.diffmogger/runtime/automation_worktrees/<role>/<run_id>/` and queue patches under `.diffmogger/runtime/automation_queue/<role>/<run_id>/`. Seeing partially integrated state from earlier patches in the same cycle is accepted behavior.

The integrator owns the main checkout. It acquires `.diffmogger/runtime/codex_automation.lock`, checkpoints dirty main changes as automation-authored local commits, runs `git apply --check` FIFO, batch-verifies clean patches, falls back to individual verification on failure, commits accepted patches locally, records deferred patches with machine-readable root causes, updates typed SQLite state, regenerates `.diffmogger/runtime/canonical_state_brief.md`, and refreshes `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` as the generated handoff projection.

Full-suite verification is explicit config in `.diffmogger/agentic/verification_commands.txt`. Builder and planner patches use manifest-declared checks or `.diffmogger/agentic/smoke_commands.txt` patch-scoped checks unless a manifest requires full verification. Hardener and finalization work can require the full suite.

Before applying full-suite-required patches, the current integrator records clean-HEAD baseline verification in `.diffmogger/runtime/baseline_verification.json`. A failing baseline creates repair/setup/defer DAG work for normal hardener/finalization patches, but does not reject unrelated builder patches whose focused checks pass. Required check failures create repair work; missing tools create setup/harness work; missing project-local services become local harness/setup/mock/fixture work; external service failures become mock/local-fixture/defer work; browser or MCP failures become alternate validation or deferred QA work. If the compatibility status vocabulary is still in use, `BLOCKED_ON_ENVIRONMENT` is only an annotation after that follow-up work exists. Patches that intentionally repair the baseline should declare `Verification scope: baseline_repair`.

Hardener may add tests, rewrite brittle or stale tests, broaden meaningful coverage, update fixtures/mocks, and remove obsolete tests when that improves verification quality. It must not remove or weaken tests merely to make checks pass, and summaries should include `Test change rationale:` whenever hardener touches tests.

Deferred duplicate builder patches are triaged before launching more equivalent builder work. The integrator can mark older equivalent patches `superseded` and keep the freshest deferred patch as `retryable`, `retryable-after-environment-repair`, or `replace-from-current-HEAD` so planner/integrator triage happens before another builder retry.

Multi-role mode is local-only. Role prompts prohibit pushes, fetches, pulls, remote configuration, upstream tracking, and remote-affecting git commands. Runtime scripts refuse configured remotes unless `MULTI_ROLE_ALLOW_REMOTES=1` is set, and the integrator refuses executable hooks containing `git push`.

## Continuous Runner

The dashboard no longer creates or manages fixed-time schedules. Start launches a detached local runner that survives closing the dashboard but does not auto-start after reboot. Stop sends `SIGTERM` to the runner process group and only escalates when the process does not exit after a short grace period.

Logs are written under `.diffmogger/runtime/automation_logs/`. Runner state and execution DAG state are recorded canonically in `.diffmogger/runtime/orchestration.sqlite3`. `.diffmogger/runtime/canonical_state_brief.md` is the bounded generated view for agents. `.diffmogger/runtime/automation_runner.json` and `.diffmogger/runtime/automation_conveyor_state.json` are generated read-model projections for dashboard debugging and quick inspection.

## Main State Files

Generated targets keep Diffmogger-owned state under `.diffmogger/` and ignore that namespace locally. Normal scheduler, dashboard, and runtime code read the canonical sidecar paths from `.diffmogger/manifest.json`; historical root layouts are handled only through the explicit `import_legacy_target_state()` migration seam.

- `AGENTS.md`: repository-wide instructions Codex loads automatically.
- `.diffmogger/manifest.json`: generated ownership manifest and path source of truth.
- `.diffmogger/runtime/orchestration.sqlite3`: canonical typed SQLite state for automation control, streams, events, execution DAG nodes/edges, capability manifests, checkpoints, tasks, runs, worktrees, validations, assumptions, decisions, blockers, artifacts, next actions, and projections.
- `.diffmogger/runtime/canonical_state_brief.md`: generated, redacted, bounded Markdown view for Codex agents; regenerated before role `codex exec` calls.
- `.diffmogger/runtime/automation_conveyor_state.json` and `.diffmogger/runtime/automation_runner.json`: generated JSON read-model projections for dashboard debugging; do not edit them as authoritative state.
- `.diffmogger/lib/diffmogger/`: bundled runtime package copied from `src/diffmogger/` so generated targets do not depend on the source checkout.
- `.diffmogger/agentic/automation_prompt.md`: recurring automation behavior.
- `.diffmogger/agentic/roles/*.md`: optional static role prompts for multi-role mode.
- `.diffmogger/scripts/run_conveyor_automation.py`: continuous local DAG scheduler wrapper.
- `.diffmogger/scripts/run_observatory.py`: optional local browser observatory for runner, execution DAG, queue, log, and progress state.
- `.diffmogger/scripts/ticket_run.py`: bounded ticket-campaign status, dependency-aware next-ticket selection, halt, report, and local desktop notification helper.
- `.diffmogger/scripts/repair_environment.py`: local environment diagnosis and safe repair helper.
- `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`: static boundaries.
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`: dynamic prompt and human handoff projection.
- dashboard Ticket Queue: bounded ticket-campaign authoring surface backed by SQLite.
- `.diffmogger/context/`: optional copied context files tracked through intake/dashboard state.
- dashboard human-input panel: human requests, replies, outbound delivery records, and handled-resolution notes backed by SQLite.

## Canonical State Model

SQLite is the authority for live orchestration. The runner writes an ordered event stream before replacing current-state projections, then materializes the typed execution DAG action capabilities: `orchestrate`, `decompose`, `scope`, `build`, `review`, `validate`, `repair`, `integrate`, `audit`, and `calibrate`, plus blockers, completion, dependency modes, repository capability manifest, validation receipts, and next actions. Conveyor stage rows are generated read models. It checkpoints the active stream at semantic boundaries such as initialization, decisions, role starts, role recovery, and role completion. Dashboard commands query the database directly through `state.snapshot` and `state.validate`.

Schema evolution is explicit in the current SQLite implementation: `PRAGMA user_version` matches the Diffmogger state schema version, applied migrations are recorded in `schema_migrations`, and `state.validate` reports checks for event sequencing/hash links, projection event references, execution DAG contracts, generated conveyor read models, actionable blockers/escalations, and terminal validation receipt evidence. Migration tooling may change; docs should follow the active mechanism rather than preserving this implementation by habit.

Generated Markdown and JSON remain useful, but they are views: prompt inputs, authored import/export surfaces, migration artifacts, handoff packets, or read-model projections. If a projection disagrees with `.diffmogger/runtime/canonical_state_brief.md` or `.diffmogger/runtime/orchestration.sqlite3`, rebuild or inspect through the dashboard/API instead of treating the projection as truth.

Historical target imports are deliberately narrow: use the explicit `import_legacy_target_state()` migration seam to import old root task Markdown, conveyor/runner JSON, human bridge Markdown, or `TICKET_RUN.md` into SQLite once. New generated targets do not read those files as live runtime state.

## Human Bridge Modes

Mode `file_only` uses dashboard human-input records backed by SQLite. Codex records requests there; the human replies through the dashboard; Codex handles replies on a later run and records concise resolution notes. Summary and status requests are answered through the dashboard or requested local artifacts.

Mode `local_notifier` adds the optional notifier service for native local desktop notifications. Mode `discord_notifier` routes progress updates and direct messages through Discord, with optional local desktop notifications. In multi-role automation, local commits created by the integrator send brief progress-channel updates with the commit subject and work summary.

## Optional Notifier Service

Diffmogger includes `services/agentic-notifier/`. Target projects remain decoupled from it: they call `POST http://127.0.0.1:8765/api/notify` if it is running, and otherwise record pending outbound messages in typed human-message state.

If a human message asks for a direct reply or status summary and notifier mode is enabled, the automation should send a concise `event_kind: "message"` notification through the notifier. Human-unlock requests and blockers that need user input also use `event_kind: "message"`. Writing a Markdown-only note is not sufficient for that request. If the notifier is unavailable, the automation records `NOTIFIER_UNREACHABLE` in typed human-message state and continues useful work.

## Horizon Progression

Typed automation control state communicates the current product horizon or ticket-run phase to the dashboard and DAG scheduler. The task file may mirror that state for agents and humans, but each run should update SQLite first, then regenerate the canonical state brief and task projection.

When the current horizon is satisfied, the run should update typed automation control to the next horizon and include a dated horizon-transition note with the previous horizon, new horizon, evidence, and checks in generated projections. If a later regression undermines an earlier horizon, do not reset the current horizon; make the regression the next sprint-sized task and document the risk.

Generated horizons are mode-aware. Continuous-improvement targets use intake-derived product horizons. Ticket-campaign targets use bounded phases around scaffolded ticket readiness, dependency-aware one-ticket implementation, verification, final reporting, and stopping new launches.

## State Compaction

Long-running Markdown state can become context bloat. Use `.diffmogger/scripts/compact_agent_state.py --dry-run <target-project>` to review a conservative compaction plan. The script keeps unresolved human requests and deferred multi-role manifests, keeps recent state, summarizes transient multi-role artifacts before cleanup, and archives concise rollups instead of silently deleting important entries.

## Status Compatibility

Current generated targets use these status names for compatibility with existing dashboard and prompt surfaces:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

Treat this as a default vocabulary, not an invariant. `ACTIVE` means useful work remains. `ACTIVE_WITH_PENDING_USER_INPUT` means input exists. `BLOCKED_ON_USER` and `BLOCKED_ON_ENVIRONMENT` annotate planning pressure; they are not scheduler gates while independent or unblocker work is available. `CRITICAL_STOP` means continuing would be unsafe, destructive, credential-exposing, or corrupting.

Future versions may replace these names with a more expressive state machine. Keep the behavioral intent: failed validation, missing tools, external services, browser/MCP failures, and human input should become typed planning inputs or follow-up work instead of hiding useful runnable work.

## Definition Of Done For A Run

A run is done when it has produced integrated deliverable work or unblocker work, run relevant checks where possible, updated typed state and generated projections, and left the next run with a clear next sprint. Create unblocker work unless all tickets are done with evidence.
