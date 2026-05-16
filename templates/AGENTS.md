# AGENTS.md

This repo is `{{PROJECT_NAME}}`.

Project mode: {{PROJECT_MODE_LABEL}}

## Mission

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

{{PROJECT_MODE_GUIDANCE}}

## Read Before Meaningful Work

```text
target/canonical_state_brief.md
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
.agentic/automation_prompt.md
```

{{HUMAN_AGENTS_READ_BLOCK}}

## Working Rules

- Build the product; do not only write plans.
- {{AGENTS_PROGRESS_RULE}}
- Use safe local defaults, fixtures, mocks, or seed data unless the task explicitly enables external integration.
- {{ENV_ACCESS_AGENTS_RULE}}
- Do not spend money, deploy publicly, or trigger real-world side effects without explicit approval.
- Use worker agents only for bounded work and record their outputs.
- Write-capable worker agents allowed: {{WRITE_WORKER_AGENTS_ALLOWED}}; max write workers: {{MAX_WRITE_WORKER_COUNT}}.
- Use read-only worker reports for exploration. When write-capable workers are enabled, use the most parallelism the task can safely absorb while keeping ownership reviewable and main-agent integration explicit.
- Automation role profile: {{AUTOMATION_ROLE_PROFILE}}.
{{HUMAN_AGENTS_RULES}}
- Treat `.diffmogger/runtime/orchestration.sqlite3` as canonical automation state. Read `.diffmogger/runtime/canonical_state_brief.md` for current state instead of inspecting SQLite manually. Markdown and JSON files under `.diffmogger/state/` and `.diffmogger/runtime/` are prompt inputs, handoffs, authored surfaces, compatibility shims, or generated projections.
- Automation status, product horizon, execution DAG nodes/edges, validation receipts, blockers, next actions, and repo capability manifest are typed SQLite records. Conveyor stage fields are compatibility projections only. Use `.diffmogger/scripts/state_brief.py` and other generated helpers/dashboards to record state changes; do not hand-edit runtime projections as authority.
- In ticket-campaign mode, use `.diffmogger/scripts/ticket_run.py` to update ticket status. In planner/builder/hardener worktrees this stages a typed ticket-state action for integrator reconciliation after patch acceptance; do not mark completion only by editing Markdown or generated JSON.
- Record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every automation run.
- Refresh `docs/CODEX_AUTOMATION_TASKS.md` only as a generated prompt/handoff projection after typed state is updated.

## Verification

Full-suite commands are configured in `.agentic/verification_commands.txt`.
Every command in that file must pass on the current checkout. Do not add desired future commands there until the backing scripts, packages, services, or Make targets exist.
Use them for hardener/finalization or when explicitly required; builder/planner patches may use narrower checks from `.agentic/smoke_commands.txt` or the role manifest.
The integrator records clean-HEAD baseline verification in `target/baseline_verification.json`; unrelated focused patches should not be rejected solely because that baseline is already failing.
Hardener may add, rewrite, broaden, or remove obsolete tests when it improves verification quality, but must include `Test change rationale:` when touching tests and must not delete tests merely to pass checks.

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Use the commands that actually exist. Do not claim checks passed unless they ran.
