# Initial Bootstrap Prompt: {{PROJECT_NAME}}

Paste this into Codex for the first manual run in the target repo.

---

You are working in a fresh or newly-retrofitted repo for `{{PROJECT_NAME}}`.

Project mode: {{PROJECT_MODE_LABEL}}

{{PROJECT_MODE_GUIDANCE}}

Read first:

1. `README.md` if present.
2. `AGENTS.md` if present.
3. `target/canonical_state_brief.md` if present.
4. `docs/CODEX_AUTOMATION_TASKS.md`.
5. `docs/CODEX_AUTOMATION_GUARDRAILS.md`.
6. `docs/HUMAN_BRIDGE_SETUP.md` if present.
7. `docs/PROJECT_CONTEXT.md` if present.
8. `.agentic/automation_prompt.md` if present.

Canonical runtime/task state belongs in `target/orchestration.sqlite3`; typed execution DAG nodes/edges, repository capability manifest, validation receipts, blockers, and next actions live there. Conveyor stage fields are compatibility projections only. `target/canonical_state_brief.md` is the generated agent-readable view. Markdown and JSON files are prompt inputs, handoff surfaces, authored import/export surfaces, projections, exports, or migration aids.

## Goal

{{PRODUCT_GOAL}}

Target user: {{TARGET_USER}}

Desired runnable milestone: {{DESIRED_FIRST_DEMO}}

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

## Ticket Campaign Mode

{{TICKET_CAMPAIGN_TASK_NOTES}}

## Build Requirements

Create an initial local-first baseline with:

{{BOOTSTRAP_SCOPE_BOUNDARY}}

- runnable setup
- runnable milestone path
- clear repo structure
- fixtures, mocks, or local seed data where external services would otherwise be needed
- verification commands
- automation docs
- at least one useful test or smoke check when practical
- explicit `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` behavior in the recurring automation prompt

## Verification

Record full-suite commands in `.agentic/verification_commands.txt`. This file is a clean-HEAD baseline gate, so every command in it must pass against the current checkout. Do not put future project commands there until the backing scripts, packages, services, or Make targets exist. Keep desired future commands in this document, the dashboard ticket queue, or typed automation control/generation projections until they are real. Use `.agentic/smoke_commands.txt` for narrower patch or sprint checks when useful.

Bootstrap-safe baseline commands currently scaffolded:

```text
{{BOOTSTRAP_BASELINE_COMMANDS}}
```

Preferred project commands once the matching project surfaces exist:

```text
{{VERIFICATION_COMMANDS}}
```

Run the commands that exist or that you create. Do not claim checks passed unless they ran.

## End

Update canonical runtime state first, including typed automation control, validation receipts, blockers, human-message state, and next actions. Then regenerate/update `docs/CODEX_AUTOMATION_TASKS.md` with current repo state, product horizon state, {{INITIAL_PROGRESS_EVIDENCE_LABEL}}, completed work under `## Completed Last Run`, checks under `## Checks From Last Run`, generated artifacts, Codex CLI worker decision, worker activity, known issues, pending human requests if enabled, best next milestone, suggested next sprint-sized task, and status. Treat the Markdown as a generated projection, not live state authority.

{{BOOTSTRAP_END_NOTE}}
