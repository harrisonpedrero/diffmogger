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
- Optional helpers: Diffmogger `scripts/spawn_worker_agent.sh` and `scripts/summarize_worker_outputs.py` can write and consolidate reports under `target/agent_runs/<run_id>/`.

## Known Issues

- Product baseline still needs to be created or inspected.
- Verification commands may need adjustment after bootstrap.
- Scheduled runs should use `scripts/acquire_codex_lock.sh` and `scripts/release_codex_lock.sh` or equivalent lock behavior before code mutation.

## Pending Human Requests

- None yet.

Human bridge mode:

- File-only mode is always available.
- If Diffmogger's local notifier is running, this project may call `POST http://127.0.0.1:8765/api/notify`.
- The automation must read `docs/HUMAN_INBOX.md` at run start, interpret structured replies and freeform commands, remove handled entries only after completion or intentional deferral, and archive concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.
- If a human asks to be texted, messaged, or sent a status update, the automation should use the local notifier rather than only writing Markdown.
- If the notifier is unavailable, record the intended outbound message in `docs/HUMAN_OUTBOX.md` with status `NOTIFIER_UNREACHABLE` and continue useful work.

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
