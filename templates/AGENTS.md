# AGENTS.md

This repo is `{{PROJECT_NAME}}`.

Project mode: {{PROJECT_MODE_LABEL}}

## Mission

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

{{PROJECT_MODE_GUIDANCE}}

## Read Before Meaningful Work

```text
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
.agentic/automation_prompt.md
```

{{HUMAN_AGENTS_READ_BLOCK}}

## Working Rules

- Build the product; do not only write plans.
- Treat MVP as an early milestone, not the finish line.
- Use safe local defaults, fixtures, mocks, or seed data unless the task explicitly enables external integration.
- Do not read `.env` files or handle secrets.
- Do not spend money, deploy publicly, or trigger real-world side effects without explicit approval.
- Use worker agents only for bounded work and record their outputs.
- Write-capable worker agents allowed: {{WRITE_WORKER_AGENTS_ALLOWED}}; max write workers: {{MAX_WRITE_WORKER_COUNT}}.
- Use read-only worker reports for exploration. When write-capable workers are enabled, use the most parallelism the task can safely absorb while keeping ownership reviewable and main-agent integration explicit.
- Multi-role automations allowed: {{MULTI_ROLE_AUTOMATIONS_ALLOWED}}; role profile: {{AUTOMATION_ROLE_PROFILE}}.
{{HUMAN_AGENTS_RULES}}
- Record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every automation run.
- Update `docs/CODEX_AUTOMATION_TASKS.md` at the end of every automation run.

## Verification

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Use the commands that actually exist. Do not claim checks passed unless they ran.
