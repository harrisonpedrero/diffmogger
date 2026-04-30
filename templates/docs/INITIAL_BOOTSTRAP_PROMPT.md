# Initial Bootstrap Prompt: {{PROJECT_NAME}}

Paste this into Codex for the first manual run in the target repo.

---

You are working in a fresh or newly-retrofitted repo for `{{PROJECT_NAME}}`.

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `docs/CODEX_AUTOMATION_TASKS.md`.
4. `docs/CODEX_AUTOMATION_GUARDRAILS.md`.
5. `docs/HUMAN_BRIDGE_SETUP.md`.
6. `.agentic/automation_prompt.md` if present.

## Goal

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

Desired first demo: {{DESIRED_FIRST_DEMO}}

## Tech Preferences

{{TECH_PREFERENCES}}

## Constraints

{{HARD_CONSTRAINTS}}

## Safety Constraints

{{SAFETY_CONSTRAINTS}}

## Human Bridge

Human bridge enabled: {{HUMAN_BRIDGE_ENABLED}}

If enabled, create project-side human bridge files:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_INBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

Do not handle messaging credentials in this repo. If local notifier API mode is later enabled, this repo may call:

```text
POST http://127.0.0.1:8765/api/notify
```

Generated automation docs should say that freeform inbox requests such as `send me a summary`, `text me the blockers`, or `status update` require an outbound notifier response when available, not only a Markdown note. If the notifier is unavailable, record `NOTIFIER_UNREACHABLE` in `docs/HUMAN_OUTBOX.md`.

## Build Requirements

Create an initial local-first baseline with:

- runnable setup
- first demo path
- clear repo structure
- fixtures, mocks, or local seed data where external services would otherwise be needed
- verification commands
- automation docs
- at least one useful test or smoke check when practical
- explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` behavior in the recurring automation prompt

## Verification

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Run the commands that exist or that you create. Do not claim checks passed unless they ran.

## End

Update `docs/CODEX_AUTOMATION_TASKS.md` with current repo state, completed work, checks, generated artifacts, Codex CLI worker decision, worker activity, human messages sent, known issues, pending human requests, best next milestone, suggested next sprint-sized task, and status.

Do not stop merely because a basic demo exists. This is the first horizon, not the final product.
