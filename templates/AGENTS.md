# AGENTS.md

This repo is `{{PROJECT_NAME}}`.

Mission: {{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

Project mode: {{PROJECT_MODE_LABEL}}

## Read First

```text
.diffmogger/runtime/canonical_state_brief.md
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/agentic/automation_prompt.md
```

## Operating Rules

- Build, repair, defer, split, or create unblocker work before asking the user.
- Pending human input does not stop unrelated work.
- Failed validation creates work: repair for required check failures, setup/harness for missing tools, mock/local-fixture/defer for external services, alternate validation or deferred QA for browser/MCP failures, and split/reframe/planner work after repeated failures.
- Blockers are node metadata, not a campaign-ending status.
- Diffmogger is a work generator. If tickets remain, keep producing scheduler-runnable work unless continuing would be unsafe or destructive.
- Current status labels are compatibility vocabulary. Record `CRITICAL_STOP` only when that vocabulary is active and continuing would be unsafe, destructive, credential-exposing, or corrupting.
- Treat `.diffmogger/runtime/orchestration.sqlite3` as canonical runtime state. Markdown and JSON files are handoffs, authored inputs, or generated projections.
- Read `.diffmogger/runtime/canonical_state_brief.md` instead of inspecting SQLite manually.
- Refresh `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` only after typed state changes.
- Use `.diffmogger/scripts/ticket_run.py` for ticket state. Planner, designer, builder, and hardener worktrees stage typed ticket actions for integrator reconciliation.
- For UI work, read `.diffmogger/agentic/design_contract.md`. Builder and hardener must use the active design contract, design review evidence, UI visual validation receipts, or explicit deferred validation/setup work before claiming clean UI completion.
- Parallel scheduler waves are bounded and ownership-driven. If non-overlap is unclear, reduce fanout, run read-only scoping, or create setup/repair/indexing work.
- {{ENV_ACCESS_AGENTS_RULE}}
- Use safe local defaults, fixtures, mocks, or seed data unless the task explicitly enables external integration.
- Do not spend money, deploy publicly, print secrets, or trigger real-world side effects without explicit approval.
- Worker agents are optional acceleration for bounded work. Max write workers: {{MAX_WRITE_WORKER_COUNT}}.

## Verification

Full-suite commands live in `.diffmogger/agentic/verification_commands.txt`; smoke commands live in `.diffmogger/agentic/smoke_commands.txt`.
Run the checks that actually exist and record what happened. Do not claim checks passed unless they ran.

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

## Design And UI Validation

{{DESIGN_CAPABILITY_SECTION}}

{{UI_VALIDATION_SECTION}}
