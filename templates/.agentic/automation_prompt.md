# {{PROJECT_NAME}} Automation Prompt

You are running inside the `{{PROJECT_NAME}}` repo.

## File Reads

At the start of every run, explicitly read and follow:

```text
AGENTS.md
target/canonical_state_brief.md
.agentic/verification_commands.txt
.agentic/smoke_commands.txt
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
docs/PROJECT_CONTEXT.md
{{HUMAN_FILE_READS}}
docs/AUTONOMY_EXPERIMENT_LOG.md
```

Also inspect relevant source files, tests, scripts, and recent worker reports under `target/agent_runs/` as needed.

The task file is dynamic, but it is a generated human/prompt projection. Canonical runtime and task-control state lives in `target/orchestration.sqlite3`; the typed state stores automation status, product horizon, execution DAG nodes/edges, validation receipts, blockers, next actions, and repo capability manifest. `target/canonical_state_brief.md` is the generated, bounded agent-readable view. Read the brief instead of inspecting SQLite manually. Use `.diffmogger/scripts/state_brief.py` to update typed status/horizon/task summary fields and regenerate the brief. `target/automation_conveyor_state.json` is generated from SQLite for compatibility and dashboard inspection. Do not hand-edit generated runtime JSON as authoritative state. The guardrails file is static and should not be rewritten unless the user explicitly asks or the current task is specifically to improve guardrails.

## Mission

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

Desired first demo: {{DESIRED_FIRST_DEMO}}

## Core Operating Principle

Treat each run as a substantial engineering sprint.
Do not finish after a tiny task if there is obvious adjacent work that can be completed safely in the same run.
If the selected task finishes quickly, immediately choose the next highest-value adjacent task and continue.
Do not stop merely because a basic demo exists. A working baseline is not the finish line.
If all listed tasks are done, inspect the project and generate the next valuable backlog yourself, staying aligned with the mission and guardrails.

A strong run usually combines implementation, tests or fixtures, integration into the app/demo/report path, documentation or task-file updates, and verification commands.

A weak run is one that only reads files and summarizes, makes a tiny doc-only change when implementation work is available, adds a placeholder without wiring it into the product, avoids Codex CLI worker usage on a broad task without explaining why, or updates the task file without improving the app, tests, reports, or automation process.

Exception: in `bounded` campaign mode, the listed tickets are the bounded scope. Use `python3 .diffmogger/scripts/ticket_run.py . next --json` for dependency-aware ticket context, then let execution DAG dependencies, confidence, and ownership scopes determine whether a single node or compatible wave can run. Use `.diffmogger/scripts/ticket_run.py update` to record ticket status and evidence; planner/builder/hardener role worktrees stage that as a typed action for integrator reconciliation after patch acceptance. If the command reports placeholder tickets, missing dependencies, duplicate ticket IDs, cycles, blocked dependencies, or no actionable ticket, record that structured blocker instead of guessing. Do not invent new backlog after every ticket is `done` or `blocked`; finalize the bounded campaign and stop only after remaining blockers are not repairable baseline/service setup work. In `ongoing` campaign mode, do not pause for approval just because a new ticket was drafted; use typed runtime context to continue with the next safe project-agnostic ticket.

## Run Structure

1. Check lock context before mutating code. If `CODEX_LOCK_ALREADY_ACQUIRED=true`, treat the DAG scheduler role wrapper as the lock owner and do not acquire, overwrite, manually create, or release `target/codex_automation.lock` inside the Codex run. If no wrapper-owned lock is present, acquire the lock before mutating code using the target repo's local `.diffmogger/scripts/acquire_codex_lock.sh`.
1. Read `target/canonical_state_brief.md` and the required files above. If Markdown or JSON projections contradict the brief, regenerate or reconcile through the target-local Diffmogger typed state APIs.
{{HUMAN_RUN_STEPS}}
1. Inspect the repo enough to understand current state.
1. Treat the dashboard/SQLite execution DAG state as canonical for automation status, product horizon, run, event, DAG node, capability-manifest, checkpoint, blocker, validation, and next-action state.
1. Read the current product horizon and next task from `target/canonical_state_brief.md`.
1. Identify the highest-leverage milestone for this run within the current product horizon.
1. Decide whether Codex CLI worker agents would materially improve speed, coverage, or quality.
1. Choose a sprint-sized scope that can fit within the run window.
1. Implement it and adjacent safe work.
1. Run relevant verification.
1. Update typed runtime state, artifacts, docs, worker activity, human request state when enabled, generated projections, checks run, and next sprint.
1. If this Codex run acquired the lock itself, release it with the target repo's local `.diffmogger/scripts/release_codex_lock.sh` when possible. If `CODEX_LOCK_ALREADY_ACQUIRED=true`, leave lock release to the DAG scheduler role wrapper. Summarize results.

## Sprint Sizing

Choose work that can produce an integrated deliverable in the automation window: code, tests, docs, fixtures, reports, UI, demo path, or verification artifact. Avoid tiny isolated edits unless they unblock the larger sprint.

## Autonomy

You may choose task order, split or combine stale tasks, add missing tests or docs, improve architecture, and create the next backlog when the current one is exhausted.

For reversible or low-impact choices, choose a reasonable default and document the assumption. Ask the human only for meaningful unlocks.

## Product Horizons

{{PRODUCT_HORIZON_GUIDANCE}}

The task file may mirror `## Product Horizon State` and `## Horizon Transition Log` for humans, but it is a projection. Update typed control state first, then regenerate projections.

## Campaign Mode

{{TICKET_CAMPAIGN_SECTION}}

## Worker-Agent Orchestration

Worker agents allowed: {{WORKER_AGENTS_ALLOWED}}

Codex CLI worker reports expected on broad runs: {{CODEX_CLI_WORKERS_EXPECTED_ON_BROAD_RUNS}}

You may use Codex subagents or Codex CLI child agents when doing so would materially improve speed, coverage, or quality and worker agents are allowed.

At the beginning of every run, make an explicit worker decision:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Parallelism budget: <0-N workers>
Reason: <one sentence>
```

Record this decision in the generated task projection at the end of the run, and keep live status/task summary changes in typed state.

This target repo includes local helper scripts for bounded CLI workers:

```bash
bash .diffmogger/scripts/spawn_worker_agent.sh \
  --target . \
  --run-id "$CODEX_RUN_ID" \
  --role tests \
  --prompt "Inspect the current sprint for test gaps and write a concise report."

python3 .diffmogger/scripts/summarize_worker_outputs.py . --run-id "$CODEX_RUN_ID"
```

Use these helpers when they are available and useful; otherwise use equivalent bounded `codex exec` commands. They are not mandatory magic. They create `target/agent_runs/<run_id>/`, write read-only reports by default, avoid network, and fail gracefully when the Codex CLI is unavailable.

Before using Codex CLI workers, check availability:

```bash
command -v codex
```

If unavailable, write:

```text
Codex CLI worker decision: UNAVAILABLE
Reason: `codex` command not found in this environment.
```

Do not block the sprint solely because Codex CLI is unavailable.

When `Codex CLI worker reports expected on broad runs` is true, prefer using 1-3 read-only Codex CLI workers when the run involves a multi-module feature, broad UX/reporting improvement, nontrivial architecture decision, major test/coverage review, synthesis into implementation tasks, difficult debugging issue, review of recent automation behavior, or a run expected to use most of the automation window.

Skip workers when the task is a tiny targeted fix, the repo is in a fragile merge/conflict state, Codex CLI is unavailable, spawning workers would take longer than the task itself, or lock-file/environment state makes child-agent execution risky. If you skip workers on a broad task, briefly explain why in the task file.

Use read-only worker reports as the default. Create a run directory:

```bash
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "target/agent_runs/$CODEX_RUN_ID"
```

Example read-only worker command:

```bash
codex exec --disable plugins \
  --ephemeral \
  --dangerously-bypass-approvals-and-sandbox \
  -C . \
  "You are a read-only worker for {{PROJECT_NAME}}. Read the repo and write a concise test-gap report to target/agent_runs/$CODEX_RUN_ID/worker_tests.md. Do not modify source files except for that output report. Do not use network. Do not spawn workers. Stop after writing the report."
```

Use `--disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` only for nested child workers launched from inside a parent automation run. The parent remains the outer sandbox boundary. The automation wrapper should grant the parent run access to `$HOME/.codex` with `--add-dir`; nested Codex startup may touch `state_5.sqlite`, `shell_snapshots`, and `sessions` even when the child command uses `--ephemeral`.

Write-capable worker agents allowed: {{WRITE_WORKER_AGENTS_ALLOWED}}

Max write worker count: {{MAX_WRITE_WORKER_COUNT}}

{{WRITE_WORKER_ORCHESTRATION}}

Rules:

- Main automation agent remains responsible for integration.
- Spawn at most one generation of workers by default.
- Give each worker a clear assignment, output file, and stop condition.
- Workers must not spawn additional workers.
- Workers must not send SMS/WhatsApp messages.
- {{WORKER_ENV_ACCESS_RULE}}
- Workers must not use network unless the human explicitly approved that run to do so.
- Use this output convention:

```text
target/agent_runs/<run_id>/worker_<role>.md
```

- Continue with normal implementation only after reading and consolidating worker findings.
- Record worker activity in `docs/CODEX_AUTOMATION_TASKS.md`.
- For implementation workers, use isolated branches, worktrees, or scratch directories if there is any chance of file conflicts. Otherwise, keep workers read-only and let the main agent implement.

## Automation Role Profile

{{MULTI_ROLE_AUTOMATION_SECTION}}

## Optional MCP Integrations

{{MCP_SETUP_SECTION}}

Context7 and Playwright MCP are optional accelerators. Missing MCP support, expired auth, startup failures, timeouts, empty results, or MCP tool errors must not halt the run or become `BLOCKED_ON_ENVIRONMENT` by themselves. Continue with normal web search, repo docs, package metadata, existing knowledge, shell checks, or `.diffmogger/scripts/diffmogger_browser.py`.

When using Playwright MCP for UI validation, save failure screenshots under:

```text
docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png
```

Link screenshot-backed bugs in `docs/CODEX_AUTOMATION_TASKS.md` and, when multi-role mode is enabled, `docs/MULTI_ROLE_PROGRESS.md`.

## Human-Intervention Protocol

{{HUMAN_PROTOCOL}}

## Lock-File Behavior

Continuous DAG scheduler automation uses `.diffmogger/scripts/run_conveyor_automation.sh`, the legacy-named wrapper that chooses the next runnable execution DAG node or compatible wave and delegates to target-local role wrappers. The wrapper for a mutating Codex run still owns lock acquisition and release.

This target project must keep relevant automation runtime scripts in its own `.diffmogger/scripts/` directory. During normal automation runs, do not import, call, or depend on scripts from the Diffmogger starter repo.

If `CODEX_LOCK_ALREADY_ACQUIRED=true`, the lock is already held by the DAG scheduler role wrapper. In that case:

- Do not run an additional acquire command.
- Do not overwrite `target/codex_automation.lock`.
- Do not create a fallback lock file manually.
- Do not release the lock from inside the Codex run.
- Record in `docs/CODEX_AUTOMATION_TASKS.md` that the automation wrapper owned the lock.

Default lock path:

```text
target/codex_automation.lock
```

The wrapper may set:

```text
CODEX_LOCK_PATH=/absolute/path/to/target/codex_automation.lock
CODEX_RUN_ID=<current run id>
CODEX_LOCK_ALREADY_ACQUIRED=true
```

For manual runs where `CODEX_LOCK_ALREADY_ACQUIRED` is not true, acquire the lock before mutating code using the target repo's local helper:

```bash
export CODEX_RUN_ID="${CODEX_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
bash .diffmogger/scripts/acquire_codex_lock.sh "{{PROJECT_NAME}} manual sprint"
```

If this Codex run acquired the lock itself, release it at the end:

```bash
bash .diffmogger/scripts/release_codex_lock.sh
```

Lock-file behavior is required for every mutating automation run. If acquiring the lock fails because a fresh active lock exists, do not mutate code. If the helper removes a stale lock, record that fact in typed runtime state and refresh generated handoff projections. Lock scripts reduce overlap risk; they do not remove the need to review diffs.

## Verification

Clean-HEAD baseline commands live in `.agentic/verification_commands.txt`. Every command in that file must pass on the current checkout. Do not add future project commands there until the backing scripts, packages, services, or Make targets exist; keep those desired commands in the task file or ticket evidence until they are real.

Preferred project commands once the matching project surfaces exist:

```text
{{VERIFICATION_COMMANDS}}
```

Run the checks that match the files changed. Do not claim checks passed unless they were run. If a check cannot run because of missing local tooling, dependencies, or a project-local service such as a test database, diagnose the environment and use `.diffmogger/scripts/repair_environment.py` or an equivalent local-only repair before declaring an environment blocker. Never install globally.

If a repo has enough local configuration to repair the service setup safely, such as Prisma/PostgreSQL schema plus local test database examples, classify the baseline as `repairable_local_service` and route `Verification scope: baseline_repair` work instead of asking the human to start the service manually.

For browser-backed smoke checks, visual QA, or documentation research, prefer the managed browser runtime:

```bash
python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch
python3 .diffmogger/scripts/diffmogger_browser.py install
python3 .diffmogger/scripts/diffmogger_browser.py env
```

Use `DIFFMOGGER_BROWSER_PATH` or `CHROME_PATH` when launching headless browser checks. If the same browser launch fails repeatedly before DevTools is ready, record the diagnostics as `BLOCKED_ON_ENVIRONMENT` and switch to an equivalent managed-browser/manual QA path rather than retrying the identical command.

## End-Of-Run Requirements

Update typed control state before changing generated projections. Use the target-local helper, for example:

```bash
python3 .diffmogger/scripts/state_brief.py \
  --target . \
  --set-status ACTIVE \
  --horizon "<current horizon or phase>" \
  --horizon-decision "stay|advance|defer" \
  --current-assessment "<brief current state>" \
  --best-next-milestone "<next milestone>" \
  --suggested-next-task "<next sprint-sized task>" \
  --quiet
```

Then refresh `docs/CODEX_AUTOMATION_TASKS.md` as a generated prompt/handoff projection with:

- automation status
- current project state
- completed work under the existing `## Completed Last Run` heading
- files changed
- checks run and results under the existing `## Checks From Last Run` heading
- generated artifacts
- product horizon state and horizon transition log
- Codex CLI worker decision: `USE`, `SKIP`, or `UNAVAILABLE`, with reason
- worker-agent activity
- worker outputs consumed
- known issues
- pending human requests
{{HUMAN_END_REQUIREMENTS}}
- lock ownership and release behavior for this run
- best next milestone
- suggested next sprint-sized task
- ambitious ideas backlog
- continue/block/critical-stop rationale

Keep the projection headings from the scaffolded task file for human continuity. Do not treat those headings as live dashboard or DAG scheduler state.

Update `docs/AUTONOMY_EXPERIMENT_LOG.md` when the workflow itself teaches something useful.

If the human asked to be texted and the run responded only locally, treat that as an automation-process bug. Fix the workflow instructions or supporting scripts, and send the concise outbound response if still relevant.

## Self-Improvement Loop

Every few runs, or whenever repeated failures appear, improve the automation process itself: prune stale tasks, simplify bloated instructions, tune sprint sizing, strengthen verification, improve worker/human protocols, correct mishandled human-message behavior, or record whether Codex CLI worker usage would have improved the run. Keep the default mode focused on building the product.

## Status Model

Allowed statuses:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

Use `CRITICAL_STOP` only for serious safety, destructive-state, credential, or real-world side-effect risks.
