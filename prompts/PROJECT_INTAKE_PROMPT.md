# Project Intake Prompt

Use this prompt with Codex or a project owner when the project idea is still rough.

---

You are helping me turn a project idea into a high-agency Codex automation workflow.

Interview me briefly and produce a concise project intake brief. If I provide an uploaded brief or rough notes, infer what you can, ask only for material gaps, and document assumptions.

Capture:

1. Project name.
2. Project mode: fresh project or existing project integration.
3. Product goal.
4. Target user.
5. Desired first demo.
6. Tech preferences.
7. Hard constraints.
8. Safety constraints.
9. External services or integrations.
10. Verification commands or expected checks.
11. Desired automation cadence as an integer number of minutes greater than 30.
12. Whether a human bridge is enabled.
13. Human bridge mode: file-only, local notifier, or disabled.
14. Whether freeform human requests should receive SMS/WhatsApp responses when the notifier is available.
15. Whether worker agents are allowed and whether Codex CLI worker reports are expected on broad runs.
16. Whether optional write-capable worker agents are allowed, the maximum write-worker count from 0-10, and guidance that write workers are optional and only for large, well-planned changes with disjoint ownership.
17. Whether optional recurring automation signals are enabled. Default to disabled unless explicitly requested.
18. Whether optional multi-role automations are allowed, the role profile, checkpoint-commit preference, base cadence, scheduling strategy, and local-only remote opt-in. Default multi-role to disabled unless explicitly requested.
19. What counts as a meaningful integrated deliverable.
20. What beyond-MVP should look like.
21. What the automation must never do.

For existing project integration, explicitly capture what already exists, which stack and commands must be preserved, and what the first integrated change should prove.

Output in this structure:

```markdown
# Project Intake: <project name>

## Summary

## Project Mode

## Product Goal

## Target User

## Desired First Demo

## Tech Preferences

## Constraints

## Safety Rules

## Automation Must Never Do

## External Services

## Verification

## Automation Cadence

## Human Bridge

## Worker Agents

## Write Worker Agents

## Max Write Workers

## Write Worker Guidance

## Multi-Role Automations

## Automation Role Profile

## Automation Checkpoint Commits

## Multi-Role Base Cadence

## Meaningful Deliverable

## Beyond MVP

## Assumptions
```

Keep the intake practical. The next step is to generate project-specific automation prompts and docs from it.
