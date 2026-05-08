# Operating Model

## Loop

1. Scheduler wakes Codex.
2. The target repo's scheduler wrapper, usually `.diffmogger/scripts/run_codex_automation.sh`, reads `.diffmogger/manifest.json`, acquires the manifest-declared lock path, and grants `$HOME/.codex` access for nested Codex CLI startup.
3. Codex reads `AGENTS.md`, `.diffmogger/agentic/automation_prompt.md`, `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`, `.diffmogger/state/PROJECT_CONTEXT.md`, and `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`.
4. Codex reads human bridge files when enabled. In file-only mode it handles manual replies locally; in notifier modes it sends direct notifier responses when the human asked to be messaged.
5. Codex removes handled inbox entries only after the requested action is complete or intentionally deferred.
6. Codex reads `## Product Horizon State`, chooses the highest-value sprint-sized milestone inside the current horizon, and gathers advancement evidence.
7. Codex records a `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` decision plus a worker strategy: `READ_ONLY_REPORTS`, `WRITE_WORKERS`, `INTEGRATION_ONLY`, or `NO_WORKERS`.
8. Codex may spawn bounded read-only workers if useful, optionally through `.diffmogger/scripts/spawn_worker_agent.sh`.
9. If the generated target intake explicitly enabled write-capable workers, Codex may spawn up to the capped write-worker count as bounded acceleration for work that can split into reviewable lanes. The main agent must choose a parallelism budget, define enough ownership/contracts to keep work coherent, review diffs, integrate, verify, and update task state.
10. Codex implements, verifies, and updates artifacts.
11. Codex rewrites the task file and logs product horizon state, horizon transitions, worker decisions, human messages, checks, artifacts, and status state.
12. The scheduler wrapper releases the lock through local `.diffmogger/scripts/release_codex_lock.sh` when possible and Codex returns a concise summary.

## Optional Multi-Role Loop

The default loop is single-lane. When a generated target explicitly enables `multi_role_automations_allowed`, the dashboard may install four local launchd jobs instead:

- planner: hourly at minute `0`
- builder: minutes `10` and `40`
- hardener: minutes `20` and `50`
- integrator: minutes `25` and `55`

As an alternative, the dashboard can install one continuous conveyor LaunchAgent. The conveyor runs `.diffmogger/scripts/run_conveyor_automation.sh`, records state in `.diffmogger/runtime/automation_conveyor_state.json`, and chooses the next runnable lane from queue depth, planner deferral changes, planning freshness, builder momentum, and bounded hardening after integrated builder work. Conveyor state includes the active role run and a bounded future decision queue for local observability.

Generated targets also include an optional automation signal helper. When `automation_signals_enabled` is true, `.diffmogger/state/AUTOMATION_SIGNALS.md` defines recurring local nudges and `.diffmogger/runtime/automation_signals.json` records due/completed state. Signals never override guardrails or task state.

When `automation_run_mode` is `ticket_campaign`, generated targets also use `.diffmogger/state/TICKET_RUN.md` and `.diffmogger/scripts/ticket_run.py`. Bootstrap is readiness-only in this mode. Normal campaign runs use `python3 .diffmogger/scripts/ticket_run.py . next --json` to select one dependency-ready ticket, preserve file order as the human priority order, and avoid continuing into the next ticket in the same run. The conveyor and single-lane wrapper stop launching new work after all tickets are done with evidence, or after all remaining tickets are blocked, then write `.diffmogger/runtime/ticket_run_completion.json`, a Markdown completion report, and a native desktop notification or durable fallback record. Remote push/PR creation remains manual.

Planner, builder, and hardener start from the current main `HEAD` in isolated worktrees under `.diffmogger/runtime/automation_worktrees/<role>/<run_id>/` and queue patches under `.diffmogger/runtime/automation_queue/<role>/<run_id>/`. Seeing partially integrated state from earlier patches in the same cycle is accepted behavior.

The integrator owns the main checkout. It acquires `.diffmogger/runtime/codex_automation.lock`, checkpoints dirty main changes as automation-authored local commits, runs `git apply --check` FIFO, batch-verifies clean patches, falls back to individual verification on failure, commits accepted patches locally, records deferred patches with machine-readable root causes, updates `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`, and maintains `.diffmogger/state/MULTI_ROLE_PROGRESS.md`.

Full-suite verification is explicit config in `.diffmogger/agentic/verification_commands.txt`. Builder and planner patches use manifest-declared checks or `.diffmogger/agentic/smoke_commands.txt` patch-scoped checks unless a manifest requires full verification. Hardener and finalization work can require the full suite.

Before applying full-suite-required patches, the integrator records clean-HEAD baseline verification in `.diffmogger/runtime/baseline_verification.json`. A failing baseline becomes a `baseline_verification_blocker` for normal hardener/finalization patches, but does not reject unrelated builder patches whose focused checks pass. Missing project-local services, such as an unavailable local PostgreSQL test database in a repo with Prisma/Postgres test configuration, are classified as `repairable_local_service` and routed to baseline repair before `BLOCKED_ON_ENVIRONMENT`. Patches that intentionally repair the baseline should declare `Verification scope: baseline_repair`.

Hardener may add tests, rewrite brittle or stale tests, broaden meaningful coverage, update fixtures/mocks, and remove obsolete tests when that improves verification quality. It must not remove or weaken tests merely to make checks pass, and summaries should include `Test change rationale:` whenever hardener touches tests.

Deferred duplicate builder patches are triaged before launching more equivalent builder work. The integrator can mark older equivalent patches `superseded` and keep the freshest deferred patch as `retryable`, `retryable-after-environment-repair`, or `replace-from-current-HEAD` so planner/integrator triage happens before another builder retry.

Multi-role mode is local-only. Role prompts prohibit pushes, fetches, pulls, remote configuration, upstream tracking, and remote-affecting git commands. Runtime scripts refuse configured remotes unless `MULTI_ROLE_ALLOW_REMOTES=1` is set, and the integrator refuses executable hooks containing `git push`.

## Main State Files

New generated targets keep Diffmogger-owned state under `.diffmogger/` and ignore that namespace locally. Existing generated targets may still use the legacy `.agentic/`, `docs/`, and `target/` paths; generated helper scripts resolve both layouts through `.diffmogger/manifest.json` when present.

- `AGENTS.md`: repository-wide instructions Codex loads automatically.
- `.diffmogger/manifest.json`: generated ownership manifest and path source of truth.
- `.diffmogger/agentic/automation_prompt.md`: recurring automation behavior.
- `.diffmogger/agentic/roles/*.md`: optional static role prompts for multi-role mode.
- `.diffmogger/scripts/run_conveyor_automation.py`: optional work-conserving local scheduler.
- `.diffmogger/scripts/run_observatory.py`: optional local browser observatory for signal, conveyor, queue, log, and progress state.
- `.diffmogger/scripts/ticket_run.py`: bounded ticket-campaign status, dependency-aware next-ticket selection, halt, report, and local desktop notification helper.
- `.diffmogger/scripts/repair_environment.py`: local environment diagnosis and safe repair helper.
- `.diffmogger/scripts/update_automation_signals.py`: optional recurring signal refresher and completion helper.
- `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`: static boundaries.
- `.diffmogger/state/PROJECT_CONTEXT.md`: optional supplemental context index for PDFs, research notes, design docs, and other reusable references.
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`: dynamic handoff.
- `.diffmogger/state/TICKET_RUN.md`: optional bounded ticket-campaign source of truth.
- `.diffmogger/state/MULTI_ROLE_PROGRESS.md`: durable progress, metrics, deferred backlog, architectural decisions, and role health for multi-role mode.
- `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md`: lessons about the workflow itself.
- `.diffmogger/state/DAILY_AUTOMATION_REVIEW.md`: review capsule for humans.
- `.diffmogger/state/HUMAN_INBOX.md`: active unhandled human replies.
- `.diffmogger/state/HUMAN_OUTBOX.md`: outbound human requests, direct status messages, and failed notifier attempts.
- `.diffmogger/state/HUMAN_RESPONSES_ARCHIVE.md`: concise handled reply archive.

## Human Bridge Modes

Mode `file_only` uses Markdown queues only. Codex writes requests to `.diffmogger/state/HUMAN_REQUESTS.md`; the human replies in `.diffmogger/state/HUMAN_INBOX.md`; Codex handles replies on a later run and archives concise notes. Summary and status requests are answered locally in Markdown or app artifacts.

Mode `local_notifier` adds the optional notifier service for native local desktop notifications. Mode `discord_notifier` routes progress updates and direct messages through Discord, with optional local desktop notifications. In multi-role automation, local commits created by the integrator send brief progress-channel updates with the commit subject and work summary.

## Optional Notifier Service

Diffmogger includes `services/agentic-notifier/`. Target projects remain decoupled from it: they call `POST http://127.0.0.1:8765/api/notify` if it is running, and otherwise fall back to writing request and outbox files.

If a human inbox entry asks for a message, direct reply, or status summary and notifier mode is enabled, the automation should send a concise `event_kind: "message"` notification through the notifier. Human-unlock requests and blockers that need user input also use `event_kind: "message"`. Writing a Markdown-only note is not sufficient for that request. If the notifier is unavailable, the automation records `NOTIFIER_UNREACHABLE` in `.diffmogger/state/HUMAN_OUTBOX.md` and continues useful work.

## Horizon Progression

The task file owns the current product horizon or ticket-run phase. Each run should update `## Product Horizon State` with evidence, remaining work, and an advancement decision: `stay`, `advance`, or `defer`.

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
