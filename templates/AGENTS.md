# AGENTS.md

This repo is `{{PROJECT_NAME}}`.

## Mission

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

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
{{HUMAN_AGENTS_RULES}}
- Record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every automation run.
- Update `docs/CODEX_AUTOMATION_TASKS.md` at the end of every automation run.

## Verification

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Use the commands that actually exist. Do not claim checks passed unless they ran.
