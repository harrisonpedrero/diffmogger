# Codex Automation Tasks

Generated handoff projection. SQLite in `.diffmogger/runtime/orchestration.sqlite3` is the live runtime authority; `.diffmogger/runtime/canonical_state_brief.md` is the bounded agent-readable state brief.

AUTOMATION_STATUS: ACTIVE

Last updated: {{CREATED_AT}}

## Current Project State

- Project: `{{PROJECT_NAME}}`
- Goal: {{PRODUCT_GOAL}}
- Target user: {{TARGET_USER}}
- Desired runnable milestone: {{DESIRED_FIRST_DEMO}}
- Current baseline: scaffold initialized; no product ticket has run yet.
- State authority: `.diffmogger/runtime/orchestration.sqlite3`
- State brief: `.diffmogger/runtime/canonical_state_brief.md`

## Automation Must Never Do

{{AUTOMATION_MUST_NEVER_DO}}

## Product Horizon State

- Current horizon: {{CURRENT_HORIZON}}
- Horizon goal: {{HORIZON_GOAL}}
- Advancement decision: stay
- Next horizon candidate: {{NEXT_HORIZON_CANDIDATE}}

## Checks From Last Run

- Not run yet.
- Full-suite config: `.diffmogger/agentic/verification_commands.txt`
- Smoke config: `.diffmogger/agentic/smoke_commands.txt`
- Preferred commands: `{{VERIFICATION_COMMANDS_INLINE}}`

## Scheduler Work

- Scheduler: continuous DAG scheduler via `.diffmogger/scripts/run_temporal_worker.sh`
- Current selected action: none yet
- Ready work: first run should select ticket/setup work from typed runtime state
- Parallel policy: bounded non-overlap waves, scoped validation groups, conflict telemetry, and serialized integration gates
- Running work: none
- Done work: scaffold initialized
- Unblocker policy: if tickets remain, build, repair, defer, split, or create unblocker work before asking the user

{{TICKET_CAMPAIGN_TASK_NOTES}}

## Validation And Repair

- Required validation failure creates repair work.
- Missing tools create setup/harness work.
- External service failures create mock/local-fixture/defer work.
- Browser/MCP failures create alternate validation or deferred QA work.
- Repeated failures create split/reframe/planner work.
- Under the current status vocabulary, only unsafe corruption, credential exposure, destructive risk, or real-world side-effect risk should become `CRITICAL_STOP`.

## Human Input

- Pending requests: none yet.
- Pending human input does not stop unrelated work.
- Blockers are node metadata, not campaign-ending status.

{{HUMAN_TASK_NOTES}}

## Known Issues

{{INITIAL_KNOWN_ISSUES}}

## Best Next Milestone

{{BEST_NEXT_MILESTONE}}

## Suggested Next Sprint-Sized Task

{{SUGGESTED_NEXT_SPRINT_TASK}}

## {{BACKLOG_SECTION_HEADING}}

{{BACKLOG_SECTION_BODY}}

## Continue/Block/Critical-Stop Rationale

{{CONTINUE_RATIONALE}}
