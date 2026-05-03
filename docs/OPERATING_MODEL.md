# Operating Model

## Loop

1. Scheduler wakes Codex.
2. The target repo's scheduler wrapper, usually `scripts/run_codex_automation.sh`, acquires `target/codex_automation.lock` through local `scripts/acquire_codex_lock.sh` and grants `$HOME/.codex` access for nested Codex CLI startup.
3. Codex reads `AGENTS.md`, `.agentic/automation_prompt.md`, `docs/CODEX_AUTOMATION_GUARDRAILS.md`, `docs/PROJECT_CONTEXT.md`, and `docs/CODEX_AUTOMATION_TASKS.md`.
4. Codex reads human bridge files when enabled. In file-only mode it handles manual replies locally; in local-notifier mode it sends notifier responses when the human asked to be texted.
5. Codex removes handled inbox entries only after the requested action is complete or intentionally deferred.
6. Codex reads `## Product Horizon State`, chooses the highest-value sprint-sized milestone inside the current horizon, and gathers advancement evidence.
7. Codex records a `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` decision plus a worker strategy: `READ_ONLY_REPORTS`, `WRITE_WORKERS`, `INTEGRATION_ONLY`, or `NO_WORKERS`.
8. Codex may spawn bounded read-only workers if useful, optionally through `scripts/spawn_worker_agent.sh`.
9. If the generated target intake explicitly enabled write-capable workers, Codex may spawn up to the capped write-worker count as bounded acceleration for work that can split into reviewable lanes. The main agent must choose a parallelism budget, define enough ownership/contracts to keep work coherent, review diffs, integrate, verify, and update task state.
10. Codex implements, verifies, and updates artifacts.
11. Codex rewrites the task file and logs product horizon state, horizon transitions, worker decisions, human messages, checks, artifacts, and status state.
12. The scheduler wrapper releases the lock through local `scripts/release_codex_lock.sh` when possible and Codex returns a concise summary.

## Optional Multi-Role Loop

The default loop is single-lane. When a generated target explicitly enables `multi_role_automations_allowed`, the dashboard may install four local launchd jobs instead:

- planner: hourly at minute `0`
- builder: minutes `10` and `40`
- hardener: minutes `20` and `50`
- integrator: minutes `25` and `55`

As an alternative, the dashboard can install one continuous conveyor LaunchAgent. The conveyor runs `scripts/run_conveyor_automation.sh`, records state in `target/automation_conveyor_state.json`, and chooses the next runnable lane from queue depth, planning freshness, builder momentum, and bounded hardening after integrated builder work. Conveyor state includes the active role run and a bounded future decision queue for local observability.

Generated targets also include an optional automation signal helper. When `automation_signals_enabled` is true, `docs/AUTOMATION_SIGNALS.md` defines recurring local nudges and `target/automation_signals.json` records due/completed state. Signals never override guardrails or task state.

Planner, builder, and hardener start from the current main `HEAD` in isolated worktrees under `target/automation_worktrees/<role>/<run_id>/` and queue patches under `target/automation_queue/<role>/<run_id>/`. Seeing partially integrated state from earlier patches in the same cycle is accepted behavior.

The integrator owns the main checkout. It acquires `target/codex_automation.lock`, checkpoints dirty main changes as automation-authored local commits, runs `git apply --check` FIFO, batch-verifies clean patches, falls back to individual verification on failure, commits accepted patches locally, records deferred patches with machine-readable reasons, updates `docs/CODEX_AUTOMATION_TASKS.md`, and maintains `docs/MULTI_ROLE_PROGRESS.md`.

Multi-role mode is local-only. Role prompts prohibit pushes, fetches, pulls, remote configuration, upstream tracking, and remote-affecting git commands. Runtime scripts refuse configured remotes unless `MULTI_ROLE_ALLOW_REMOTES=1` is set, and the integrator refuses executable hooks containing `git push`.

## Main State Files

- `AGENTS.md`: repository-wide instructions Codex loads automatically.
- `.agentic/automation_prompt.md`: recurring automation behavior.
- `.agentic/roles/*.md`: optional static role prompts for multi-role mode.
- `scripts/run_conveyor_automation.py`: optional work-conserving local scheduler.
- `scripts/run_observatory.py`: optional local browser observatory for signal, conveyor, queue, log, and progress state.
- `scripts/repair_environment.py`: local environment diagnosis and safe repair helper.
- `scripts/update_automation_signals.py`: optional recurring signal refresher and completion helper.
- `docs/CODEX_AUTOMATION_GUARDRAILS.md`: static boundaries.
- `docs/PROJECT_CONTEXT.md`: optional supplemental context index for PDFs, research notes, design docs, and other reusable references.
- `docs/CODEX_AUTOMATION_TASKS.md`: dynamic handoff.
- `docs/MULTI_ROLE_PROGRESS.md`: durable progress, metrics, deferred backlog, architectural decisions, and role health for multi-role mode.
- `docs/AUTONOMY_EXPERIMENT_LOG.md`: lessons about the workflow itself.
- `docs/DAILY_AUTOMATION_REVIEW.md`: review capsule for humans.
- `docs/HUMAN_INBOX.md`: active unhandled human replies.
- `docs/HUMAN_OUTBOX.md`: outbound human requests, direct status messages, and failed notifier attempts.
- `docs/HUMAN_RESPONSES_ARCHIVE.md`: concise handled reply archive.

## Human Bridge Modes

Mode `file_only` uses Markdown queues only. Codex writes requests to `docs/HUMAN_REQUESTS.md`; the human replies in `docs/HUMAN_INBOX.md`; Codex handles replies on a later run and archives concise notes. Summary and status requests are answered locally in Markdown or app artifacts.

Mode `local_notifier` adds the optional notifier service.

## Optional Notifier Service

Diffmogger includes `services/agentic-notifier/`. Target projects remain decoupled from it: they call `POST http://127.0.0.1:8765/api/notify` if it is running, and otherwise fall back to writing request and outbox files.

If a human inbox entry asks for a text, message, direct reply, or status summary, the automation should send a concise SMS/WhatsApp response through the notifier. Writing a Markdown-only note is not sufficient for that request. If the notifier is unavailable, the automation records `NOTIFIER_UNREACHABLE` in `docs/HUMAN_OUTBOX.md` and continues useful work.

## Horizon Progression

The task file owns the current product horizon. Each run should update `## Product Horizon State` with evidence, remaining work, and an advancement decision: `stay`, `advance`, or `defer`.

When the current horizon is satisfied, the run should move `Current horizon` to the next horizon and append a dated note to `## Horizon Transition Log` with the previous horizon, new horizon, evidence, and checks. If a later regression undermines an earlier horizon, do not reset the current horizon; make the regression the next sprint-sized task and document the risk.

## State Compaction

Long-running Markdown state can become context bloat. Use `scripts/compact_agent_state.py --dry-run <target-project>` to review a conservative compaction plan. The script preserves unresolved human requests and deferred multi-role manifests, keeps recent state, summarizes transient multi-role artifacts before cleanup, and archives concise rollups instead of silently deleting important entries.

## Status Rules

Use `ACTIVE` when useful work remains.

Use `ACTIVE_WITH_PENDING_USER_INPUT` when a human request is open but unrelated work remains.

Use `BLOCKED_ON_USER` only when no valuable work can continue without the human.

Use `BLOCKED_ON_ENVIRONMENT` when local setup, permissions, dependencies, or external service configuration prevent progress.

Use `CRITICAL_STOP` when continuing autonomously could be unsafe.

## Definition Of Done For A Run

A run is done when it has produced an integrated deliverable or an honest blocker, run relevant checks where possible, updated the dynamic task file, and left the next run with a clear next sprint.
