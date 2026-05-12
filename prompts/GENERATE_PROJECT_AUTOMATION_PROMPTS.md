# Generate Project Automation Prompts

Use this prompt after a project intake brief exists. It is the main starter prompt for creating project-specific prompts and automation docs. New targets should use the `.diffmogger/` sidecar layout; legacy `.agentic/`, `docs/`, and `target/` paths are only for targets that already lack `.diffmogger/manifest.json`.

---

You are generating project-specific Codex automation files from a project intake brief.

Read the intake brief first. If values are missing, make reasonable defaults and document assumptions. Do not ask questions unless a missing value would make the workflow unsafe.

Respect the intake's project mode. For `fresh_project`, generate files for a new target repo. For `existing_project`, preserve existing architecture, commands, docs, and project-specific instructions; add Diffmogger guidance as a clearly marked managed section when updating existing `AGENTS.md` or existing project-owned development docs. Generated Diffmogger-owned runtime state should live under `.diffmogger/`; canonical live orchestration state is `.diffmogger/runtime/orchestration.sqlite3`, with `.diffmogger/runtime/canonical_state_brief.md` regenerated as the bounded state view for agents.

Create these files as complete Markdown drafts:

```text
.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md
.diffmogger/state/PROJECT_CONTEXT.md
.diffmogger/agentic/automation_prompt.md
AGENTS.md
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/HUMAN_BRIDGE_SETUP.md
.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md
.diffmogger/state/DAILY_AUTOMATION_REVIEW.md
.diffmogger/scripts/acquire_codex_lock.sh
.diffmogger/scripts/release_codex_lock.sh
.diffmogger/scripts/run_codex_automation.sh
.diffmogger/scripts/run_observatory.py
.diffmogger/scripts/repair_environment.py
.diffmogger/scripts/state_brief.py
.diffmogger/scripts/spawn_worker_agent.sh
.diffmogger/scripts/summarize_worker_outputs.py
.diffmogger/scripts/compact_agent_state.py
.diffmogger/schemas/orchestration_state.schema.json
```

## Requirements

The generated `.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md` is used once or a few times. It should be project-specific, scaffold the product, create automation docs, create verification commands, and get to a first runnable demo.

For existing-project integration, the first runnable demo means a meaningful integrated increment inside the current codebase, not a greenfield rewrite.

The generated `.diffmogger/state/PROJECT_CONTEXT.md` should index supplemental project context when provided, such as PDFs, research notes, design docs, CSVs, or Markdown notes. It must warn not to include secrets, credentials, paid-account exports, or private production data.

The generated `.diffmogger/agentic/automation_prompt.md` is used for recurring automation. It should be durable and behavioral. It must tell Codex to read the dynamic task file and guardrails every run, follow the mode-aware progression plan, support worker agents, support the human bridge, use lock files, compact generated Markdown projections when needed, verify work, and update canonical SQLite state plus generated handoff projections.

It must explicitly read and follow:

```text
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/PROJECT_CONTEXT.md
.diffmogger/runtime/canonical_state_brief.md
.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md if present
```

It must say that the task file is dynamic and rewritten at the end of every run, but is not the runtime authority. It must say canonical runtime state lives in `.diffmogger/runtime/orchestration.sqlite3`; `.diffmogger/runtime/canonical_state_brief.md` is the generated view agents read instead of inspecting SQLite manually; `.diffmogger/runtime/automation_conveyor_state.json` is generated for compatibility. It must say the guardrails file is static and should not be rewritten unless the user explicitly asks or the current task is specifically to improve guardrails.

The automation prompt must include this exact language:

```text
Treat each run as a substantial engineering sprint.
Do not finish after a tiny task if there is obvious adjacent work that can be completed safely in the same run.
If the selected task finishes quickly, immediately choose the next highest-value adjacent task and continue.
Do not stop merely because a basic demo exists. A working baseline is not the finish line.
If all listed tasks are done, inspect the project and generate the next valuable backlog yourself, staying aligned with the mission and guardrails.
```

The task file must include:

- `AUTOMATION_STATUS: ACTIVE`
- current project state
- product horizon state
- horizon transition log
- completed last run
- checks from last run
- worker-agent activity
- known issues
- pending human requests
- best next milestone
- suggested next sprint-sized task
- mode-appropriate backlog or deferred/follow-up ticket section
- continue/block/critical-stop rationale

The product horizon state must include current horizon, horizon goal, advancement criteria, evidence gathered this run, advancement decision (`stay`, `advance`, or `defer`), next horizon candidate, and remaining work before advancement. The automation prompt must tell Codex to advance to the next horizon only when criteria are met and to append evidence to the horizon transition log when advancement happens. For `ticket_campaign`, the generated horizons should be bounded ticket-run phases, bootstrap must be readiness-only, normal runs should use dependency-aware `scripts/ticket_run.py . next --json` selection for one ticket per run, and prompts must not tell Codex to invent open-ended roadmap work after all tickets are done or blocked.

The guardrails file must stay lean and include:

- scope boundaries
- secrets policy
- external side effects policy
- quality policy
- worker-agent policy
- human-intervention policy
- status policy
- context-bloat policy

The human bridge docs and automation prompt must support four modes:

1. disabled
2. dashboard-backed file-only mode
3. local desktop notifier mode: `POST http://127.0.0.1:8765/api/notify`
4. Discord notifier mode: `POST http://127.0.0.1:8765/api/notify`

For `file_only`, the generated docs must say the human reviews requests and replies through the Diffmogger dashboard, and summary/status requests are satisfied through the dashboard or requested local artifacts. It must not tell Codex to call Discord or notifier APIs in file-only mode.

For `local_notifier`, the generated automation prompt must say the notifier is for local desktop notifications only. For `discord_notifier`, it must say progress uses `event_kind: "progress"`, direct human messages use `event_kind: "message"`, local automation commits trigger brief progress-channel notifications with the commit subject and work summary, and Discord credentials stay only in `services/agentic-notifier/.env`. If the notifier is unavailable in either notifier mode, Codex should record the pending outbound message in typed human-message state, continue useful work, and use `ACTIVE_WITH_PENDING_USER_INPUT` unless no useful work remains.

The generated automation prompt must read `.diffmogger/runtime/canonical_state_brief.md` at the start of each run, handle queued human messages from typed state, and record concise resolution notes through typed human-message APIs.

The generated automation prompt must classify freeform dashboard human-message commands. In notifier modes, if the human asks to `send me`, `message me`, `reply with`, provide a `status update`, explain `what have you done so far?`, or `summarize progress`, the automation must send a concise `event_kind: "message"` notification through the local notifier when available. Human-unlock requests, blockers requiring user input, and replies to user messages also use `event_kind: "message"`. It must not satisfy that request only by writing Markdown. If the notifier is unavailable, it must record the intended outbound message in typed human-message state with status `NOTIFIER_UNREACHABLE` and continue useful work.

For direct human-requested outbound responses, include this payload option if the notifier supports it:

```json
{
  "request_id": "MSG-YYYY-MM-DD-001",
  "type": "human_requested_summary",
  "priority": "normal",
  "summary": "Progress summary requested by human",
  "event_kind": "message",
  "message_body": "<concise direct response>",
  "minimum_user_action": "None.",
  "reply_format": "Optional follow-up request.",
  "dedupe_key": "MSG-YYYY-MM-DD-001:v1",
  "expects_reply": false
}
```

Outbound text should target 300-900 characters, use at most five short bullets, avoid raw stack traces, avoid secrets, and avoid embedded URLs unless explicitly necessary and allowed by the messaging setup.

Worker-agent instructions must use this output convention:

```text
.diffmogger/runtime/agent_runs/<run_id>/worker_<role>.md
```

Main-agent ownership rule: worker agents may explore, review, or prototype, but the main automation agent owns integration and verification.

The generated automation prompt must make an explicit Codex CLI worker decision at the beginning of every run:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Parallelism budget: <0-N workers>
Reason: <one sentence>
```

It must check availability with `command -v codex` before using Codex CLI workers, record `UNAVAILABLE` if the command is missing, and continue the sprint. For broad or multi-module runs, Codex CLI worker usage should be expected unless skipped with a clear reason. Include the target repo's local `.diffmogger/scripts/spawn_worker_agent.sh` and `.diffmogger/scripts/summarize_worker_outputs.py` helper pattern and a read-only nested-child `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox -C .` fallback pattern. Also ensure the parent run wrapper invokes automation with `--add-dir "$HOME/.codex"` so nested Codex CLI workers can authenticate and start inside the parent sandbox.

Preserve read-only worker-report behavior. Read-only workers are the default for exploration, review, risk checks, product polish, and test-gap analysis.

Support optional bounded write workers only when the project intake explicitly enables `write_worker_agents_allowed`. The intake should also provide `max_write_worker_count`, capped at 10, and `write_worker_guidance`. Generated projects must keep write workers disabled when that field is absent or false, but enabled targets should treat write workers as bounded acceleration rather than a last resort.

When write workers are enabled, the generated automation prompt must teach the main agent to:

- make an explicit worker strategy decision every run
- choose a parallelism budget every run
- use the most parallelism the task can safely absorb
- define enough contracts, interfaces, data shapes, or command boundaries to keep parallel work coherent
- define reviewable file/module ownership for each write worker
- document any coordination protocol before overlapping ownership is allowed
- tell workers they are not alone in the codebase and must not revert unrelated edits or changes made by others
- require each worker to list changed files, checks run, integration notes, and risks
- review worker diffs rather than blindly accepting them
- integrate slices, resolve conflicts, run verification, and update canonical state plus generated task/handoff projections itself
- allow integration-only runs where no workers are spawned

Generated guardrails must prohibit unbounded recursive agents, overlapping write ownership without an explicit coordination protocol, blind acceptance of worker changes, and destructive cleanup.

If the target helper script supports write workers, keep read-only as the default mode and require an explicit write mode plus ownership scope for write-capable workers.

Support two continuous automation profiles. `single_lane` is the solo continuous profile for docs, research, cleanup, reports, small apps, bounded/simple work, and non-engineering workflows. `planner_builder_hardener_integrator` is the multi-role software-engineering profile for larger work where separate planning, implementation, verification, and integration lanes add value. If `automation_role_profile` is `single_lane` or `multi_role_automations_allowed` is false, generate the single-lane profile.

Generated targets must include `.diffmogger/scripts/run_conveyor_automation.sh`, `.diffmogger/scripts/run_conveyor_automation.py`, `.diffmogger/scripts/run_observatory.py`, `.diffmogger/scripts/repair_environment.py`, and `.diffmogger/schemas/orchestration_state.schema.json` as local automation helpers/contracts. When multi-role mode is enabled, also generate `.diffmogger/agentic/roles/planner.md`, `.diffmogger/agentic/roles/builder.md`, `.diffmogger/agentic/roles/hardener.md`, `.diffmogger/agentic/roles/integrator.md`, `.diffmogger/state/MULTI_ROLE_PROGRESS.md`, `.diffmogger/scripts/run_role_automation.sh`, `.diffmogger/scripts/integrate_role_outputs.py`, and `.diffmogger/scripts/list_deferred_patches.py`.

Generated multi-role prompts must state that:

- every role is local-only and must never push, fetch, pull, configure remotes, set upstream tracking, or run remote-affecting git commands
- no-remote violations are `CRITICAL_STOP`
- continuous conveyor mode prioritizes queued integration first, baseline repair and blocked-state triage when needed, builder momentum by default, and one hardener pass after integrated builder work
- builder and hardener start from latest main `HEAD` in isolated worktrees and may see partially integrated state from earlier patches in the cycle
- integrator owns the main checkout, dirty-checkpoint commits, FIFO patch application, batched verification with individual fallback, local commits, canonical state/projection updates, progress updates, and retention
- successful empty role patches are recorded as `skipped` instead of queued for integration
- deferred patches must use machine-readable `deferral_reason` values

Generated guardrails must prohibit recursive role spawning, unbounded write ownership, blind acceptance of role patches, destructive cleanup, remote git operations, and hook-based pushes.

Lock-file instructions should reference the target repo's local `.diffmogger/scripts/run_codex_automation.sh`, `.diffmogger/scripts/acquire_codex_lock.sh`, and `.diffmogger/scripts/release_codex_lock.sh` helpers, the default `.diffmogger/runtime/codex_automation.lock` path, `CODEX_LOCK_PATH` overrides, stale-lock detection, `CODEX_RUN_ID` identity for safe release, and `CODEX_LOCK_ALREADY_ACQUIRED=true` for wrapper-owned runs.

State-compaction instructions should reference `.diffmogger/scripts/compact_agent_state.py --dry-run <target-project>`, preserve unresolved human requests and deferred multi-role manifests, summarize transient multi-role artifacts, and archive concise rollups rather than silently deleting active state.

## Output

Return each file in a separate fenced Markdown block with a filename heading. Keep the files ready to paste into the target repo.
