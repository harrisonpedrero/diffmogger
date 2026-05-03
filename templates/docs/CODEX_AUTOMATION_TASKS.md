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

- Current horizon: H1 Runnable baseline
- Horizon goal: Create or confirm a runnable local baseline for `{{PROJECT_NAME}}`.
- Advancement criteria:
  - Setup path is documented.
  - A local run or demo command exists.
  - At least one useful verification command exists and has run, or an environment blocker is documented.
- Evidence gathered this run:
  - Initial scaffold only; bootstrap has not run yet.
- Advancement decision: stay
- Next horizon candidate: H2 Offline/local demo
- Remaining work before advancement:
  - Run the bootstrap prompt, create or inspect the baseline, and record verification results.

## Horizon Transition Log

- None yet.

## Completed Last Run

- Initial automation files scaffolded.

## Checks From Last Run

- Not run yet. Bootstrap run should discover or create verification commands.
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

## Known Issues

- Product baseline still needs to be created or inspected.
- Verification commands may need adjustment after bootstrap.
- Scheduled runs should use `scripts/run_codex_automation.sh`, which wraps local lock acquire/release before code mutation.
- Optional continuous conveyor scheduling should use `scripts/run_conveyor_automation.sh`, which records local scheduler state and delegates to the target-local wrappers.

## Pending Human Requests

- None yet.

{{HUMAN_TASK_NOTES}}

## Human Messages Sent

- None yet.

## Best Next Milestone

Complete H1 Runnable baseline for `{{PROJECT_NAME}}` and record whether the project is ready to advance to H2 Offline/local demo.

## Suggested Next Sprint-Sized Task

Run `docs/INITIAL_BOOTSTRAP_PROMPT.md` in Codex to scaffold the first demo, setup docs, checks, automation state, and H1 advancement evidence.

## Ambitious Ideas Backlog

- Improve the first demo until it is easy for the target user to understand.
- Add an evaluation/reporting layer once the baseline works.
- Add safe integration architecture behind mocks or feature gates.
- Add worker-agent reviews once the project has enough surface area.

## Continue/Block/Critical-Stop Rationale

Continue. The project has a clear mission and no active blocker.
