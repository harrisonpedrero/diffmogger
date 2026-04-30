# Project Intake Prompt

Use this prompt with Codex or a project owner when the project idea is still rough.

---

You are helping me turn a project idea into a high-agency Codex automation workflow.

Interview me briefly and produce a concise project intake brief. If I provide an uploaded brief or rough notes, infer what you can, ask only for material gaps, and document assumptions.

Capture:

1. Project name.
2. Product goal.
3. Target user.
4. Desired first demo.
5. Tech preferences.
6. Hard constraints.
7. Safety constraints.
8. External services or integrations.
9. Verification commands or expected checks.
10. Desired automation cadence.
11. Whether a human bridge is enabled.
12. Human bridge mode: file-only, local notifier, or disabled.
13. Whether freeform human requests should receive SMS/WhatsApp responses when the notifier is available.
14. Whether worker agents are allowed and whether Codex CLI worker reports are expected on broad runs.
15. What counts as a meaningful integrated deliverable.
16. What beyond-MVP should look like.
17. What the automation must never do.

Output in this structure:

```markdown
# Project Intake: <project name>

## Summary

## Product Goal

## Target User

## Desired First Demo

## Tech Preferences

## Constraints

## Safety Rules

## External Services

## Verification

## Automation Cadence

## Human Bridge

## Worker Agents

## Meaningful Deliverable

## Beyond MVP

## Assumptions
```

Keep the intake practical. The next step is to generate project-specific automation prompts and docs from it.
