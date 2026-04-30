# Codex Automation Tasks

AUTOMATION_STATUS: ACTIVE

Last updated: {{CREATED_AT}}

## Current Project State

- Project: `{{PROJECT_NAME}}`
- Goal: {{PRODUCT_GOAL}}
- Target user: {{TARGET_USER}}
- Desired first demo: {{DESIRED_FIRST_DEMO}}
- Tech preferences: {{TECH_PREFERENCES}}
- Current baseline: not bootstrapped yet.

## Completed Last Run

- Initial automation files scaffolded.

## Checks From Last Run

- Not run yet. Bootstrap run should discover or create verification commands.
- Preferred commands: `{{VERIFICATION_COMMANDS}}`

## Worker-Agent Activity

- Codex CLI worker decision: SKIP
- Reason: Initial scaffold only; no sprint has run yet.
- Workers used: none yet.
- Worker outputs consumed: none yet.
- Local helpers: `scripts/spawn_worker_agent.sh` and `scripts/summarize_worker_outputs.py` can write and consolidate reports under `target/agent_runs/<run_id>/`.

## Known Issues

- Product baseline still needs to be created or inspected.
- Verification commands may need adjustment after bootstrap.
- Scheduled runs should use `scripts/run_codex_automation.sh`, which wraps local lock acquire/release before code mutation.

## Pending Human Requests

- None yet.

{{HUMAN_TASK_NOTES}}

## Human Messages Sent

- None yet.

## Best Next Milestone

Create the first runnable local baseline for `{{PROJECT_NAME}}` and verify it.

## Suggested Next Sprint-Sized Task

Run `docs/INITIAL_BOOTSTRAP_PROMPT.md` in Codex to scaffold the first demo, setup docs, checks, and automation state.

## Ambitious Ideas Backlog

- Improve the first demo until it is easy for the target user to understand.
- Add an evaluation/reporting layer once the baseline works.
- Add safe integration architecture behind mocks or feature gates.
- Add worker-agent reviews once the project has enough surface area.

## Continue/Block/Critical-Stop Rationale

Continue. The project has a clear mission and no active blocker.
