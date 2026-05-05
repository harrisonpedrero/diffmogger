# Codex Automation Tasks

AUTOMATION_STATUS: ACTIVE

Last updated: {{CREATED_AT}}

## Current Project State

- Project: `{{PROJECT_NAME}}`
- Project mode: {{PROJECT_MODE_LABEL}}
- Goal: {{PRODUCT_GOAL}}
- Target user: {{TARGET_USER}}
- Desired first demo: {{DESIRED_FIRST_DEMO}}
- Tech preferences: {{TECH_PREFERENCES}}
- Project-mode guidance: {{PROJECT_MODE_GUIDANCE}}
- Current baseline: not bootstrapped yet.

## Automation Must Never Do

{{AUTOMATION_MUST_NEVER_DO}}

## Additional Project Context

{{ADDITIONAL_CONTEXT_FILES}}

## Product Horizon State

- Current horizon: {{CURRENT_HORIZON}}
- Horizon goal: {{HORIZON_GOAL}}
- Advancement criteria:
{{HORIZON_ADVANCEMENT_CRITERIA}}
- Evidence gathered this run:
  - Initial scaffold only; bootstrap has not run yet.
- Advancement decision: stay
- Next horizon candidate: {{NEXT_HORIZON_CANDIDATE}}
- Remaining work before advancement:
{{REMAINING_WORK_BEFORE_ADVANCEMENT}}

## Horizon Transition Log

- None yet.

## Completed Last Run

- Initial automation files scaffolded.

## Checks From Last Run

- Not run yet. Bootstrap run should discover or create verification commands.
- Full-suite config: `.agentic/verification_commands.txt`
- Preferred commands: `{{VERIFICATION_COMMANDS}}`

## Worker-Agent Activity

- Codex CLI worker decision: SKIP
- Worker strategy: NO_WORKERS
- Parallelism budget: 0 workers
- Reason: Initial scaffold only; no sprint has run yet.
- Workers used: none yet.
- Worker outputs consumed: none yet.
- Local helpers: `scripts/spawn_worker_agent.sh` and `scripts/summarize_worker_outputs.py` can write and consolidate reports under `target/agent_runs/<run_id>/`.

{{WRITE_WORKER_TASK_NOTES}}

{{MULTI_ROLE_TASK_NOTES}}

{{AUTOMATION_SIGNALS_TASK_NOTES}}

{{TICKET_CAMPAIGN_TASK_NOTES}}

## Known Issues

{{INITIAL_KNOWN_ISSUES}}

## Pending Human Requests

- None yet.

{{HUMAN_TASK_NOTES}}

## Human Messages Sent

- None yet.

## Best Next Milestone

{{BEST_NEXT_MILESTONE}}

## Suggested Next Sprint-Sized Task

{{SUGGESTED_NEXT_SPRINT_TASK}}

## {{BACKLOG_SECTION_HEADING}}

{{BACKLOG_SECTION_BODY}}

## Continue/Block/Critical-Stop Rationale

{{CONTINUE_RATIONALE}}
