# Initial Bootstrap Prompt: {{PROJECT_NAME}}

Paste this into Codex for the first manual run in the target repo.

---

You are working in a fresh or newly-retrofitted repo for `{{PROJECT_NAME}}`.

Project mode: {{PROJECT_MODE_LABEL}}

{{PROJECT_MODE_GUIDANCE}}

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `docs/CODEX_AUTOMATION_TASKS.md`.
4. `docs/CODEX_AUTOMATION_GUARDRAILS.md`.
5. `docs/HUMAN_BRIDGE_SETUP.md` if present.
6. `docs/PROJECT_CONTEXT.md` if present.
7. `.agentic/automation_prompt.md` if present.

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

## Automation Must Never Do

{{AUTOMATION_MUST_NEVER_DO}}

## Additional Context

{{ADDITIONAL_CONTEXT_FILES}}

## Human Bridge

{{HUMAN_BOOTSTRAP_SECTION}}

## Worker Agents

{{WORKER_BOOTSTRAP_SECTION}}

## Multi-Role Automation

{{MULTI_ROLE_BOOTSTRAP_SECTION}}

## Automation Signals

{{AUTOMATION_SIGNALS_BOOTSTRAP_SECTION}}

## Ticket Campaign Mode

{{TICKET_CAMPAIGN_TASK_NOTES}}

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

Record full-suite commands in `.agentic/verification_commands.txt`. Keep broad suites there for hardener/finalization, and use `.agentic/smoke_commands.txt` for narrower multi-role patch checks when useful.

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

Run the commands that exist or that you create. Do not claim checks passed unless they ran.

## End

Update `docs/CODEX_AUTOMATION_TASKS.md` with current repo state, product horizon state, {{INITIAL_PROGRESS_EVIDENCE_LABEL}}, completed work, checks, generated artifacts, Codex CLI worker decision, worker activity, known issues, pending human requests if enabled, best next milestone, suggested next sprint-sized task, and status.

{{BOOTSTRAP_END_NOTE}}
