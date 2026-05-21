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
5. Desired runnable milestone.
6. Tech preferences.
7. Hard constraints.
8. Safety constraints.
9. External services or integrations.
10. Verification commands or expected checks.
11. Environment access policy: project commands only, or direct local `.env*` reads allowed.
12. Whether a human bridge is enabled.
13. Human bridge mode: dashboard/SQLite records only, local notifier, Discord notifier, or disabled.
14. Whether freeform human requests should receive direct notifier messages when the notifier is available.
15. Whether read-only worker agents are allowed and whether Codex CLI worker reports are expected on broad runs.
16. Maximum write-worker count from 1-10 and guidance for using always-available write workers as bounded acceleration when work splits into reviewable lanes.
17. Checkpoint-commit preference and local-only remote opt-in for the typed execution DAG scheduler.
18. DAG scheduler config: `parallel_execution_mode`, `symbol_graph_languages`, `parallel_write_min_confidence`, `parallel_write_direct_confidence`, `max_parallel_write_workers`, and `max_parallel_scope_workers`.
19. Campaign mode: `bounded` for a seeded/imported ticket queue that stops only when all tickets are done with evidence, or `ongoing` for automatic generic ticket drafting and continued DAG-scheduled work.
20. Optional MCP servers: Context7 and/or Playwright, only when useful.
21. Seed tickets for a bounded ticket campaign, if any.
22. What counts as a meaningful integrated deliverable.
23. Long-run direction after the initial scope, unless the work is a bounded ticket campaign.
24. What the automation must never do.

For existing project integration, explicitly capture what already exists, which stack and commands should be respected, and what the first integrated change should prove.

Output in this structure:

```markdown
# Project Intake: <project name>

## Summary

## Project Mode

## Product Goal

## Target User

## Desired Runnable Milestone

## Tech Preferences

## Constraints

## Safety Rules

## Automation Must Never Do

## External Services

## Verification

## Environment Access

## Human Bridge

## Worker Agents

## Write Worker Agents

## Max Write Workers

## Write Worker Guidance

## Multi-Role Automations

## Automation Role Profile

## Automation Checkpoint Commits

## DAG Scheduler Config

## Automation Run Mode

## Optional MCP Servers

## Ticket Campaign Seed Tickets

## Meaningful Deliverable

## Long-Run Direction

## Assumptions
```

Keep the intake practical. The next step is to generate project-specific automation prompts and docs from it.
