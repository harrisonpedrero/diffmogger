# Improve Running Automation Prompt

Use this when recurring runs are too small, too chaotic, too doc-heavy, or too blocked.

---

You are improving an existing Codex automation workflow.

Read:

1. `.agentic/automation_prompt.md`
2. `docs/CODEX_AUTOMATION_TASKS.md`
3. `docs/CODEX_AUTOMATION_GUARDRAILS.md`
4. `docs/AUTONOMY_EXPERIMENT_LOG.md`
5. `docs/DAILY_AUTOMATION_REVIEW.md` if present
6. human bridge files if present
7. recent worker reports if present

Diagnose which failure mode is happening:

- runs are too small
- runs are too chaotic
- runs are too doc-heavy
- runs repeat stale tasks
- runs block on the human too often
- runs never ask the human when they should
- worker outputs are not integrated
- broad runs skip Codex CLI workers without a recorded `USE / SKIP / UNAVAILABLE` decision
- verification is weak
- context files are bloated
- human inbox commands asking to be texted are handled only by local Markdown
- notifier failures are not recorded as `NOTIFIER_UNREACHABLE`
- file-only human bridge prompts still instruct Codex to send SMS/WhatsApp
- scheduled runs acquire nested or malformed lock files instead of using a single wrapper-owned lock
- nested Codex CLI workers fail because `~/.codex/sessions` is not writable and `--ephemeral` is missing

Make the smallest useful changes to the automation prompt, guardrails, task file, or review docs to correct the behavior.

Do not turn this into pure meta-work. After improving the workflow, perform one concrete product or repo improvement if it is safe and in scope.

End by updating `docs/CODEX_AUTOMATION_TASKS.md` and `docs/AUTONOMY_EXPERIMENT_LOG.md`.
