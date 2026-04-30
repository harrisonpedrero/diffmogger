# Review Existing Project Prompt

Use this to retrofit an existing repo into the agentic automation workflow.

---

You are retrofitting this existing repository for high-agency recurring Codex automations.

Read the existing README, package/build files, tests, scripts, docs, and architecture before writing files.

Create a concise retrofit plan, then implement the automation docs:

- `AGENTS.md`
- `.agentic/automation_prompt.md`
- `docs/CODEX_AUTOMATION_TASKS.md`
- `docs/CODEX_AUTOMATION_GUARDRAILS.md`
- `docs/HUMAN_REQUESTS.md`
- `docs/HUMAN_INBOX.md`
- `docs/HUMAN_OUTBOX.md`
- `docs/HUMAN_RESPONSES_ARCHIVE.md`
- `docs/HUMAN_BRIDGE_SETUP.md`
- `docs/AUTONOMY_EXPERIMENT_LOG.md`
- `docs/DAILY_AUTOMATION_REVIEW.md`
- local helper scripts under `scripts/` for lock, scheduled run, worker reports, worker summaries, and state compaction

Respect the existing stack and conventions. Do not rewrite the product just to fit the kit.

The first task file should honestly describe:

- what exists
- how to run it
- known verification commands
- Codex CLI worker decision expectations
- human bridge mode: `disabled`, `file_only`, or `local_notifier`
- lock wrapper behavior with `CODEX_LOCK_ALREADY_ACQUIRED=true`
- missing or flaky setup
- risks
- best next sprint-sized improvement

If the repo has unclear setup, create a human request only when the owner must act. Otherwise infer and document safe assumptions.

The recurring automation prompt must distinguish structured human replies from freeform commands. In `file_only` mode, summary/status requests should be satisfied locally in Markdown or app artifacts. In `local_notifier` mode, if the human asks to be texted, messaged, or sent a status update, the automation should use `POST http://127.0.0.1:8765/api/notify` when available and should record `NOTIFIER_UNREACHABLE` in `docs/HUMAN_OUTBOX.md` when unavailable.

Run available validation commands if safe. Update the task file with results.
