# Operating Model

## Loop

1. The continuous conveyor chooses the next runnable lane.
2. The target repo's automation wrapper reads `.diffmogger/manifest.json`, acquires the manifest-declared lock path, and grants `$HOME/.codex` access for nested Codex CLI startup.
3. Codex reads `AGENTS.md`, `.diffmogger/runtime/canonical_state_brief.md`, `.diffmogger/agentic/automation_prompt.md`, `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`, `.diffmogger/state/PROJECT_CONTEXT.md`, and `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`.
4. Codex reads queued human-message summaries from the canonical state brief and records replies/resolutions through typed dashboard/SQLite state. In notifier modes it sends direct notifier responses when the human asked to be messaged.
5. Codex marks handled human messages resolved only after the requested action is complete or intentionally deferred.
6. Codex reads `## Product Horizon State`, chooses the highest-value sprint-sized milestone inside the current horizon, and gathers advancement evidence.
7. Codex records a `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` decision plus a worker strategy: `READ_ONLY_REPORTS`, `WRITE_WORKERS`, `INTEGRATION_ONLY`, or `NO_WORKERS`.
8. Codex may spawn bounded read-only workers if useful, optionally through `.diffmogger/scripts/spawn_worker_agent.sh`.
9. If the generated target intake explicitly enabled write-capable workers, Codex may spawn up to the capped write-worker count as bounded acceleration for work that can split into reviewable lanes. The main agent must choose a parallelism budget, define enough ownership/contracts to keep work coherent, review diffs, integrate, verify, and update canonical SQLite state plus generated handoff projections.
10. Codex implements, verifies, and updates artifacts.
11. Codex rewrites the task file as a prompt/handoff projection and lets the conveyor record typed runtime events, checkpoints, next actions, blockers, runs, and validations in SQLite.
12. The automation wrapper releases the lock through local `.diffmogger/scripts/release_codex_lock.sh` when possible and Codex returns a concise summary.

## Optional Multi-Role Loop

Generated targets use the continuous conveyor. The `single_lane` profile repeatedly dispatches the single automation wrapper for docs, research, cleanup, reports, small apps, bounded/simple work, and non-engineering workflows. The `planner_builder_hardener_integrator` profile adds separate planner, builder, hardener, and integrator lanes for larger software engineering work. The dashboard **Start** button launches one detached local runner for `.diffmogger/scripts/run_conveyor_automation.sh`; **Stop** terminates the recorded runner process group. The runner and conveyor record canonical state in `.diffmogger/runtime/orchestration.sqlite3`, regenerate `.diffmogger/runtime/canonical_state_brief.md` before Codex runs, and generate `.diffmogger/runtime/automation_runner.json` and `.diffmogger/runtime/automation_conveyor_state.json` only as compatibility projections. The conveyor chooses the next runnable lane from current profile, queue depth, terminal ticket state, active locks, ticket completion/blocking, queued patches, baseline repair, duplicate/deferred triage, no-progress recovery, typed human-message queue, post-builder hardening, candidate verification, and planner/builder/hardener transitions. Typed state includes an append-only event ledger, checkpoints, current task/run projections, open blockers, validation summaries, the active role run, and a bounded future decision queue for local observability.

When `automation_run_mode` is `ticket_campaign`, generated targets use the dashboard-backed SQLite ticket queue and `.diffmogger/scripts/ticket_run.py`. Bootstrap is readiness-only in this mode. Normal campaign runs use `python3 .diffmogger/scripts/ticket_run.py . next --json` to select one dependency-ready ticket, preserve queue order as the human priority order, and avoid continuing into the next ticket in the same run. The conveyor and single-lane wrapper stop launching new work after all tickets are done with evidence, or after all remaining tickets are blocked, then write `.diffmogger/runtime/ticket_run_completion.json`, a Markdown completion report, and a native desktop notification or durable fallback record in typed human-message state. Remote push/PR creation remains manual.

Planner, builder, and hardener start from the current main `HEAD` in isolated worktrees under `.diffmogger/runtime/automation_worktrees/<role>/<run_id>/` and queue patches under `.diffmogger/runtime/automation_queue/<role>/<run_id>/`. Seeing partially integrated state from earlier patches in the same cycle is accepted behavior.

The integrator owns the main checkout. It acquires `.diffmogger/runtime/codex_automation.lock`, checkpoints dirty main changes as automation-authored local commits, runs `git apply --check` FIFO, batch-verifies clean patches, falls back to individual verification on failure, commits accepted patches locally, records deferred patches with machine-readable root causes, updates `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`, and maintains `.diffmogger/state/MULTI_ROLE_PROGRESS.md`.

Full-suite verification is explicit config in `.diffmogger/agentic/verification_commands.txt`. Builder and planner patches use manifest-declared checks or `.diffmogger/agentic/smoke_commands.txt` patch-scoped checks unless a manifest requires full verification. Hardener and finalization work can require the full suite.

Before applying full-suite-required patches, the integrator records clean-HEAD baseline verification in `.diffmogger/runtime/baseline_verification.json`. A failing baseline becomes a `baseline_verification_blocker` for normal hardener/finalization patches, but does not reject unrelated builder patches whose focused checks pass. Missing project-local services, such as an unavailable local PostgreSQL test database in a repo with Prisma/Postgres test configuration, are classified as `repairable_local_service` and routed to baseline repair before `BLOCKED_ON_ENVIRONMENT`. Patches that intentionally repair the baseline should declare `Verification scope: baseline_repair`.

Hardener may add tests, rewrite brittle or stale tests, broaden meaningful coverage, update fixtures/mocks, and remove obsolete tests when that improves verification quality. It must not remove or weaken tests merely to make checks pass, and summaries should include `Test change rationale:` whenever hardener touches tests.

Deferred duplicate builder patches are triaged before launching more equivalent builder work. The integrator can mark older equivalent patches `superseded` and keep the freshest deferred patch as `retryable`, `retryable-after-environment-repair`, or `replace-from-current-HEAD` so planner/integrator triage happens before another builder retry.

Multi-role mode is local-only. Role prompts prohibit pushes, fetches, pulls, remote configuration, upstream tracking, and remote-affecting git commands. Runtime scripts refuse configured remotes unless `MULTI_ROLE_ALLOW_REMOTES=1` is set, and the integrator refuses executable hooks containing `git push`.

## Continuous Runner

The dashboard no longer creates or manages fixed-time schedules. Start launches a detached local runner that survives closing the dashboard but does not auto-start after reboot. Stop sends `SIGTERM` to the runner process group and only escalates when the process does not exit after a short grace period.

Logs are written under `.diffmogger/runtime/automation_logs/`. Runner and conveyor state are recorded canonically in `.diffmogger/runtime/orchestration.sqlite3`. `.diffmogger/runtime/canonical_state_brief.md` is the bounded generated view for agents. `.diffmogger/runtime/automation_runner.json` and `.diffmogger/runtime/automation_conveyor_state.json` remain generated projections for older helpers and quick inspection.

## Main State Files

New generated targets keep Diffmogger-owned state under `.diffmogger/` and ignore that namespace locally. Existing generated targets may still use the legacy `.agentic/`, `docs/`, and `target/` paths; generated helper scripts resolve both layouts through `.diffmogger/manifest.json` when present.

- `AGENTS.md`: repository-wide instructions Codex loads automatically.
- `.diffmogger/manifest.json`: generated ownership manifest and path source of truth.
- `.diffmogger/runtime/orchestration.sqlite3`: canonical typed SQLite state for streams, events, checkpoints, tasks, runs, worktrees, validations, assumptions, decisions, blockers, artifacts, next actions, and projections.
- `.diffmogger/runtime/canonical_state_brief.md`: generated, redacted, bounded Markdown view for Codex agents; regenerated before single-lane and role `codex exec` calls.
- `.diffmogger/runtime/automation_conveyor_state.json` and `.diffmogger/runtime/automation_runner.json`: generated JSON projections for compatibility and dashboard debugging; do not edit them as authoritative state.
- `.diffmogger/lib/diffmogger/`: bundled runtime package copied from `src/diffmogger/` so generated targets do not depend on the source checkout.
- `.diffmogger/agentic/automation_prompt.md`: recurring automation behavior.
- `.diffmogger/agentic/roles/*.md`: optional static role prompts for multi-role mode.
- `.diffmogger/scripts/run_conveyor_automation.py`: continuous local conveyor.
- `.diffmogger/scripts/run_observatory.py`: optional local browser observatory for runner, conveyor, queue, log, and progress state.
- `.diffmogger/scripts/ticket_run.py`: bounded ticket-campaign status, dependency-aware next-ticket selection, halt, report, and local desktop notification helper.
- `.diffmogger/scripts/repair_environment.py`: local environment diagnosis and safe repair helper.
- `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`: static boundaries.
- `.diffmogger/state/PROJECT_CONTEXT.md`: optional supplemental context index for PDFs, research notes, design docs, and other reusable references.
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`: dynamic prompt and human handoff projection.
- dashboard Ticket Queue: bounded ticket-campaign authoring surface backed by SQLite.
- `.diffmogger/state/MULTI_ROLE_PROGRESS.md`: human-readable progress, metrics, deferred backlog, architectural decisions, and role health projection for multi-role mode.
- `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md`: lessons about the workflow itself.
- `.diffmogger/state/DAILY_AUTOMATION_REVIEW.md`: review capsule for humans.
- dashboard Inbox: human requests, replies, outbound delivery records, and handled-resolution notes backed by SQLite.

## Canonical State Model

SQLite is the authority for live orchestration. The conveyor writes an ordered event stream before replacing current-state projections, then checkpoints the active stream at semantic boundaries such as initialization, decisions, role starts, role recovery, and role completion. Dashboard commands query the database directly through `state.snapshot` and `state.validate`.

Generated Markdown and JSON remain useful, but they are views: prompt inputs, authored import/export surfaces, migration aids, handoff packets, or compatibility surfaces. If a projection disagrees with `.diffmogger/runtime/canonical_state_brief.md` or `.diffmogger/runtime/orchestration.sqlite3`, rebuild or inspect through the dashboard/API instead of treating the projection as truth.

Remaining compatibility boundaries are deliberately narrow: `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` still carries prompt-facing status and horizon text for older generated targets. New targets do not generate human queue Markdown or `TICKET_RUN.md`; if old targets already contain those files, helpers may import them once into typed SQLite state.

## Human Bridge Modes

Mode `file_only` uses the dashboard Inbox backed by SQLite. Codex records requests there; the human replies in the dashboard; Codex handles replies on a later run and records concise resolution notes. Summary and status requests are answered through the dashboard or requested local artifacts.

Mode `local_notifier` adds the optional notifier service for native local desktop notifications. Mode `discord_notifier` routes progress updates and direct messages through Discord, with optional local desktop notifications. In multi-role automation, local commits created by the integrator send brief progress-channel updates with the commit subject and work summary.

## Optional Notifier Service

Diffmogger includes `services/agentic-notifier/`. Target projects remain decoupled from it: they call `POST http://127.0.0.1:8765/api/notify` if it is running, and otherwise record pending outbound messages in typed human-message state.

If a human message asks for a direct reply or status summary and notifier mode is enabled, the automation should send a concise `event_kind: "message"` notification through the notifier. Human-unlock requests and blockers that need user input also use `event_kind: "message"`. Writing a Markdown-only note is not sufficient for that request. If the notifier is unavailable, the automation records `NOTIFIER_UNREACHABLE` in typed human-message state and continues useful work.

## Horizon Progression

The task file communicates the current product horizon or ticket-run phase to agents and humans. Each run should update `## Product Horizon State` with evidence, remaining work, and an advancement decision: `stay`, `advance`, or `defer`, while runtime events and next actions remain canonical in SQLite.

When the current horizon is satisfied, the run should move `Current horizon` to the next horizon and append a dated note to `## Horizon Transition Log` with the previous horizon, new horizon, evidence, and checks. If a later regression undermines an earlier horizon, do not reset the current horizon; make the regression the next sprint-sized task and document the risk.

Generated horizons are mode-aware. Continuous-improvement targets use intake-derived product horizons. Ticket-campaign targets use bounded phases around readiness-only bootstrap, dependency-aware one-ticket implementation, verification, final reporting, and stopping new launches.

## State Compaction

Long-running Markdown state can become context bloat. Use `.diffmogger/scripts/compact_agent_state.py --dry-run <target-project>` to review a conservative compaction plan. The script preserves unresolved human requests and deferred multi-role manifests, keeps recent state, summarizes transient multi-role artifacts before cleanup, and archives concise rollups instead of silently deleting important entries.

## Status Rules

Use `ACTIVE` when useful work remains.

Use `ACTIVE_WITH_PENDING_USER_INPUT` when a human request is open but unrelated work remains.

Use `BLOCKED_ON_USER` only when no valuable work can continue without the human.

Use `BLOCKED_ON_ENVIRONMENT` when local setup, permissions, dependencies, or external service configuration prevent progress.

Use `CRITICAL_STOP` when continuing autonomously could be unsafe.

## Definition Of Done For A Run

A run is done when it has produced an integrated deliverable or an honest blocker, run relevant checks where possible, updated the dynamic task file, and left the next run with a clear next sprint.
