# Generate Project Automation Prompts

Use this prompt after a project intake brief exists. It is the main starter prompt for creating lean project-specific prompts and automation docs under the `.diffmogger/` sidecar layout.

---

You are generating project-specific Codex automation files from a project intake brief.

Read the intake brief first. If values are missing, make reasonable defaults and document assumptions. Do not ask questions unless a missing value would make the workflow unsafe.

Respect the intake's project mode. For `fresh_project`, generate files for a new target repo. For `existing_project`, respect existing architecture, commands, docs, and project-specific instructions; add Diffmogger guidance as a clearly marked managed section when updating existing `AGENTS.md` or existing project-owned development docs. Generated Diffmogger-owned runtime state should live under `.diffmogger/`. The current runtime uses `.diffmogger/runtime/orchestration.sqlite3` as canonical live orchestration state, with typed automation control, execution DAG nodes/edges, repository capability manifest, validation receipts, blockers, and next actions exposed through `.diffmogger/runtime/canonical_state_brief.md`.

Create these files as complete drafts:

```text
.diffmogger/agentic/automation_prompt.md
AGENTS.md
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/DEVELOPMENT.md
.diffmogger/scripts/acquire_codex_lock.sh
.diffmogger/scripts/release_codex_lock.sh
.diffmogger/scripts/run_conveyor_automation.sh
.diffmogger/scripts/run_conveyor_automation.py
.diffmogger/scripts/run_role_automation.sh
.diffmogger/scripts/integrate_role_outputs.py
.diffmogger/scripts/list_deferred_patches.py
.diffmogger/scripts/run_observatory.py
.diffmogger/scripts/repair_environment.py
.diffmogger/scripts/state_brief.py
.diffmogger/scripts/spawn_worker_agent.sh
.diffmogger/scripts/summarize_worker_outputs.py
.diffmogger/scripts/compact_agent_state.py
.diffmogger/schemas/orchestration_state.schema.json
```

## Requirements

For existing-project integration, the first runnable demo means a meaningful integrated increment inside the current codebase, not a greenfield rewrite.

Supplemental PDFs, research notes, design docs, CSVs, or Markdown notes should be copied under `.diffmogger/context/` and tracked in intake/dashboard state. Do not generate a separate project-context Markdown index.

The generated `.diffmogger/agentic/automation_prompt.md` is used for recurring automation. It should be durable and behavioral. It must tell Codex to read the canonical state brief, generated task projection, and guardrails every run, follow the mode-aware progression plan, support worker agents, support the human bridge, use lock files, compact generated Markdown projections when needed, verify work, and update canonical SQLite state plus generated handoff projections.

It must explicitly read and follow:

```text
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/runtime/canonical_state_brief.md
```

It must say that the task file is dynamic and rewritten at the end of every run, but is not the runtime authority. It must say canonical runtime state lives in `.diffmogger/runtime/orchestration.sqlite3`; typed automation control, execution DAG nodes/edges, repository capability manifest, validation receipts, blockers, human messages, and next actions live there; conveyor stage fields and `.diffmogger/runtime/automation_conveyor_state.json` are generated read-model projections. `.diffmogger/runtime/canonical_state_brief.md` is the generated view agents read instead of inspecting SQLite manually. It must say the guardrails file is static and should not be rewritten unless the user explicitly asks or the current task is specifically to improve guardrails.

The automation prompt must include this exact language:

```text
Treat each run as a substantial engineering sprint.
If tickets remain, automation must produce work.
Do not finish after a tiny task if there is obvious adjacent work that can be completed safely in the same run.
If the selected task finishes quickly, immediately choose the next highest-value adjacent task and continue.
Do not stop merely because a basic demo exists. A working baseline is not the finish line.
If all listed tasks are done, inspect the project and generate the next valuable backlog yourself, staying aligned with the mission and guardrails.
```

The generated task projection must include:

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

Typed automation control and the generated task projection must include current horizon, horizon goal, advancement criteria, evidence gathered this run, advancement decision (`stay`, `advance`, or `defer`), next horizon candidate, and remaining work before advancement. The automation prompt must tell Codex to advance to the next horizon only when criteria are met and to append evidence to the horizon transition log when advancement happens. For `campaign_mode: bounded`, the generated horizons should be bounded ticket-run phases, bootstrap must be readiness-only, normal runs should use dependency-aware `scripts/ticket_run.py . next --json` selection for one ticket per run, and prompts must not tell Codex to invent open-ended roadmap work after all tickets are done. If tickets remain but are blocked, prompts must create unblocker work. For `campaign_mode: ongoing`, prompts should allow safe generic ticket drafting from typed runtime context when no dependency-ready ticket remains.

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

For `local_notifier`, the generated automation prompt must say the notifier is for local desktop notifications only. For `discord_notifier`, it must say progress uses `event_kind: "progress"`, direct human messages use `event_kind: "message"`, local automation commits trigger brief progress-channel notifications with the commit subject and work summary, and Discord credentials stay only in `services/agentic-notifier/.env`. If the notifier is unavailable in either notifier mode, Codex should record the pending outbound message in typed human-message state and continue useful work. While the current status vocabulary is active, `ACTIVE_WITH_PENDING_USER_INPUT` can annotate that state unless no useful work remains.

The generated automation prompt must read `.diffmogger/runtime/canonical_state_brief.md` at the start of each run, handle queued human messages from typed state, and record concise resolution notes through typed human-message APIs.

The generated automation prompt must classify freeform dashboard human-message commands. In notifier modes, if the human asks to `send me`, `message me`, `reply with`, provide a `status update`, explain `what have you done so far?`, or `summarize progress`, the automation must send a concise `event_kind: "message"` notification through the local notifier when available. Human-unlock requests, pending input records, and replies to user messages also use `event_kind: "message"`. It must not satisfy that request only by writing Markdown. If the notifier is unavailable, it must record the intended outbound message in typed human-message state with status `NOTIFIER_UNREACHABLE` and continue useful work.

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

Keep read-only worker-report behavior as the current exploration default. Read-only workers are the default for exploration, review, risk checks, product polish, and test-gap analysis.

Support bounded write workers as an always-available capability. `write_worker_agents_allowed` is a deprecated compatibility mirror and must not disable write workers when absent or false. Use `max_write_worker_count`, capped at 10 with a default of 3, and `write_worker_guidance` to shape how many write workers the main agent may choose per run. Generated targets should treat write workers as optional bounded acceleration rather than a last resort.

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

Support the current continuous automation architecture: the typed execution DAG scheduler with the `planner_builder_hardener_integrator` role profile. Do not describe it as permanent. Diffmogger should generate work rather than merely detect blockers: required validation failures create repair work, missing tools create setup/harness work, external services create mock/local-fixture/defer work, browser/MCP failures create alternate validation or deferred QA work, repeated failures create split/reframe/planner work, human input creates pending input records, and automation continues independent work. Treat `campaign_mode` as the user-facing setup choice: `bounded` stops only after seeded/imported tickets are complete with evidence, while `ongoing` drafts/enqueues safe project-agnostic follow-up tickets from typed runtime context and continues.

Generated docs and config must document DAG scheduler fields: `parallel_execution_mode`, `symbol_graph_languages`, `parallel_write_min_confidence`, `parallel_write_direct_confidence`, `max_parallel_write_workers`, and `max_parallel_scope_workers`.

Generated targets must include `.diffmogger/scripts/run_conveyor_automation.sh`, `.diffmogger/scripts/run_conveyor_automation.py`, `.diffmogger/scripts/run_role_automation.sh`, `.diffmogger/scripts/integrate_role_outputs.py`, `.diffmogger/scripts/list_deferred_patches.py`, `.diffmogger/scripts/run_observatory.py`, `.diffmogger/scripts/repair_environment.py`, `.diffmogger/agentic/roles/planner.md`, `.diffmogger/agentic/roles/builder.md`, `.diffmogger/agentic/roles/hardener.md`, `.diffmogger/agentic/roles/integrator.md`, `.diffmogger/state/DEVELOPMENT.md`, and `.diffmogger/schemas/orchestration_state.schema.json` as local automation helpers/contracts.

Generated multi-role prompts must state that:

- every role is local-only and must never push, fetch, pull, configure remotes, set upstream tracking, or run remote-affecting git commands
- no-remote violations are safety stops; while the current status vocabulary is active, record them as `CRITICAL_STOP`
- continuous DAG scheduler mode prioritizes queued integration first, baseline repair and unblocker work when needed, compatible build waves, review/hardening, validation, targeted repairs, and serialized integration
- builder and hardener start from latest main `HEAD` in isolated worktrees and may see partially integrated state from earlier patches in the cycle
- integrator owns the main checkout, dirty-checkpoint commits, FIFO patch application, batched verification with individual fallback, local commits, canonical state/task projection updates, and retention
- successful empty role patches are recorded as `skipped` instead of queued for integration
- deferred patches must use machine-readable `deferral_reason` values

Generated guardrails must prohibit recursive role spawning, unbounded write ownership, blind acceptance of role patches, destructive cleanup, remote git operations, and hook-based pushes.

Lock-file instructions should reference the target repo's local DAG scheduler and role wrappers, `.diffmogger/scripts/acquire_codex_lock.sh`, and `.diffmogger/scripts/release_codex_lock.sh` helpers, the default `.diffmogger/runtime/codex_automation.lock` path, `CODEX_LOCK_PATH` overrides, stale-lock detection, `CODEX_RUN_ID` identity for safe release, and `CODEX_LOCK_ALREADY_ACQUIRED=true` for wrapper-owned runs.

State-compaction instructions should reference `.diffmogger/scripts/compact_agent_state.py --dry-run <target-project>`, retain unresolved human requests and deferred multi-role manifests, summarize transient multi-role artifacts, and archive concise rollups rather than silently deleting active state.

## Output

Return each file in a separate fenced Markdown block with a filename heading. Keep the files ready to paste into the target repo.
