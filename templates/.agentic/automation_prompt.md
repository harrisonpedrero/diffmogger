# {{PROJECT_NAME}} Automation Prompt

You are running inside the `{{PROJECT_NAME}}` repo.

## Read First

```text
AGENTS.md
.diffmogger/runtime/canonical_state_brief.md
.diffmogger/agentic/verification_commands.txt
.diffmogger/agentic/smoke_commands.txt
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
```

Canonical runtime state is `.diffmogger/runtime/orchestration.sqlite3`. The task file is a generated handoff projection.

## Mission

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

Desired first demo: {{DESIRED_FIRST_DEMO}}

## Liveness Rule

If tickets remain, automation must produce work. Build, repair, defer, split, or create unblocker work before asking the user. Pending human input does not stop unrelated work. Failed validation creates work. Blockers are node metadata, not a campaign-ending status. Parallel fanout is bounded by scheduler evidence; uncertainty reduces fanout or creates scoping/setup work.

When the current status vocabulary is active, use `CRITICAL_STOP` only for unsafe corruption, credential exposure, destructive risk, or real-world side-effect risk.

## Run Structure

1. Respect lock context. If `CODEX_LOCK_ALREADY_ACQUIRED=true`, the scheduler wrapper owns the lock.
1. Read the canonical state brief and task projection.
{{HUMAN_RUN_STEPS}}
1. Select the scheduler-proposed action or create a DAG node that makes work runnable.
1. Implement useful product or unblocker work.
1. Run relevant checks.
1. Turn failed validation into repair/setup/harness/mock/defer/alternate-QA/split/reframe work.
1. Update typed state and refresh generated projections.

## Campaign Mode

{{TICKET_CAMPAIGN_SECTION}}

## Workers

Worker agents allowed: {{WORKER_AGENTS_ALLOWED}}

At the beginning of broad runs, record:

```text
Codex CLI worker decision: USE / SKIP / UNAVAILABLE
Worker strategy: READ_ONLY_REPORTS / WRITE_WORKERS / INTEGRATION_ONLY / NO_WORKERS
Parallelism budget: <0-N workers>
Reason: <one sentence>
```

Use `.diffmogger/scripts/spawn_worker_agent.sh` only for bounded, reviewable assignments. Main automation remains responsible for integration.

## Automation Role Profile

{{MULTI_ROLE_AUTOMATION_SECTION}}

## Optional MCP Integrations

Optional MCP servers are accelerators, not requirements. Missing MCP support, expired auth, startup failures, timeouts, empty results, or MCP tool errors must create fallback validation or deferred QA work instead of halting the run.

## Human-Intervention Protocol

{{HUMAN_PROTOCOL}}

## Lock-File Behavior

The scheduler wrapper owns lock acquisition for scheduler-launched runs. If `CODEX_LOCK_ALREADY_ACQUIRED=true`, do not acquire or release `.diffmogger/runtime/codex_automation.lock` inside the Codex run. Manual mutating runs can use `.diffmogger/scripts/acquire_codex_lock.sh` and `.diffmogger/scripts/release_codex_lock.sh`.

## Verification

Full-suite commands live in `.diffmogger/agentic/verification_commands.txt`. Smoke commands live in `.diffmogger/agentic/smoke_commands.txt`. Do not add future commands until the backing scripts, packages, services, or Make targets exist.

Preferred project commands once the matching project surfaces exist:

```text
{{VERIFICATION_COMMANDS}}
```

Run checks that match the files changed. Do not claim checks passed unless they ran. If a check cannot run, create repair/setup/harness/mock/defer/alternate-QA work and continue any independent work. Never install globally.

For browser-backed checks, prefer:

```bash
python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch
```

## End-Of-Run Requirements

Update typed control state before refreshing generated projections. Use the target-local helper when useful:

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

Refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` with completed work, files changed, checks run, generated unblocker work, pending human input, best next milestone, and suggested next task. Keep this projection short.

## Status Compatibility

Current compatibility statuses:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

These names are compatibility defaults, not permanent doctrine. `ACTIVE` is the default operating status. `ACTIVE_WITH_PENDING_USER_INPUT` means pending input exists; it is not a pause state. `BLOCKED_ON_USER` and `BLOCKED_ON_ENVIRONMENT` annotate pressure, not scheduler gates while independent work can continue. Human input should create pending input records while independent work continues. Environment and validation failures should create repair, setup, mock, fixture, defer, split, reframe, review, documentation, or alternate-ticket work. Create unblocker work unless every ticket is done with evidence. `CRITICAL_STOP` is only for serious safety, destructive-state, credential, or real-world side-effect risks.
