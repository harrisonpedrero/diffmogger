# Improve Running Automation Prompt

Use this when recurring runs are too small, too chaotic, too doc-heavy, or too blocked.

---

You are improving an existing Codex automation workflow.

Read:

1. `.diffmogger/agentic/automation_prompt.md`
2. `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`
3. `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`
4. `.diffmogger/runtime/canonical_state_brief.md`, or dashboard `state.snapshot` when debugging the brief itself
5. recent worker reports or validation artifacts if present

Diagnose which failure mode is happening:

- runs are too small
- runs are too chaotic
- runs are too doc-heavy
- runs repeat stale tasks
- runs treat blocker annotations as idle states
- runs fail to create setup, repair, defer, split, or unblocker work
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

Make the smallest useful changes to the automation prompt, guardrails, typed automation control state, generated projections, or runtime scripts to correct the behavior.

Do not turn this into pure meta-work. After improving the workflow, perform one concrete product or repo improvement if it is safe and in scope.

End by updating typed runtime state first, regenerate `.diffmogger/runtime/canonical_state_brief.md`, then refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` as the generated handoff projection. Do not bypass typed SQLite for live automation status, horizon, stage, capability, validation, blocker, human-message, or next-action decisions, and do not ask agents to inspect SQLite manually when the canonical state brief is sufficient.
