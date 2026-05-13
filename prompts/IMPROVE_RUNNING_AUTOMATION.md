# Improve Running Automation Prompt

Use this when recurring runs are too small, too chaotic, too doc-heavy, or too blocked.

---

You are improving an existing Codex automation workflow.

Read:

1. `.diffmogger/agentic/automation_prompt.md`
2. `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`
3. `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`
4. `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md`
5. `.diffmogger/state/DAILY_AUTOMATION_REVIEW.md` if present
6. human bridge files if present
7. recent worker reports if present
8. `.diffmogger/runtime/canonical_state_brief.md`, or dashboard `state.snapshot` when debugging the brief itself

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
- agents are treating Markdown or JSON projections as authoritative runtime state
- human-message commands asking for direct messages are handled only by local Markdown instead of typed state/notifier delivery
- notifier failures are not recorded as `NOTIFIER_UNREACHABLE`
- file-only human bridge prompts still instruct Codex to call notifier APIs
- automation runs acquire nested or malformed lock files instead of using a single wrapper-owned lock
- nested Codex CLI workers fail because `~/.codex` is not writable from the parent sandbox, child workers use a stale `--ask-for-approval never` command shape, or child workers hit macOS nested `sandbox-exec` failures instead of using the nested-child bypass shape

Make the smallest useful changes to the automation prompt, guardrails, typed automation control state, generated projections, or review docs to correct the behavior.

Do not turn this into pure meta-work. After improving the workflow, perform one concrete product or repo improvement if it is safe and in scope.

End by updating typed runtime state first, then refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` and `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md` as generated handoff/progress projections. Do not bypass typed SQLite for live automation status, horizon, stage, capability, validation, blocker, human-message, or next-action decisions, and do not ask agents to inspect SQLite manually when the canonical state brief is sufficient.
