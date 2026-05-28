# Codex Automation Guardrails

Build `{{PROJECT_NAME}}`: {{PRODUCT_GOAL}}

Stay aligned with: {{TARGET_USER}}

## Safety

{{AUTOMATION_MUST_NEVER_DO}}
- Do not spend money, deploy publicly, publish externally, contact real users, or trigger real-world side effects without explicit approval.
- Prefer fixtures, mocks, local seed data, and dry-run modes for safe local milestones, but keep them visibly labeled. If real, live, public, official, or third-party data is part of the product value, create connector/cache/provenance/defer work instead of claiming fallback data is complete.
{{ENV_ACCESS_GUARDRAILS_POLICY}}
- Never print, summarize, commit, or copy secret values.

## Liveness

- Diffmogger is a work generator, not a blocker detector.
- Build, repair, defer, split, or create unblocker work before asking the user.
- Pending human input does not stop unrelated work.
- Failed validation creates work by default.
- Blockers are node metadata, not a campaign-ending status.
- Required check failures create repair work.
- Missing tools create setup/harness work.
- External service failures create mock/local-fixture/defer work.
- Browser/MCP failures create alternate validation or deferred QA work.
- Repeated failures create split/reframe/planner work.
- Under the current status vocabulary, only unsafe corruption, credential exposure, destructive risk, or real-world side-effect risk should become `CRITICAL_STOP`.

## Status

Current compatibility statuses:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

These names are compatibility defaults, not permanent doctrine. `ACTIVE` is the normal operating status. `ACTIVE_WITH_PENDING_USER_INPUT` means input exists. `BLOCKED_ON_USER` and `BLOCKED_ON_ENVIRONMENT` are annotations, not scheduler gates while useful independent work remains.

## Runtime State

- Canonical runtime state is `.diffmogger/runtime/orchestration.sqlite3`.
- Read `.diffmogger/runtime/canonical_state_brief.md` for the bounded state view.
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` is a generated handoff projection.
- Do not hand-edit projections as authority.

## Workers And Git

- Use worker agents only for bounded subtasks.
- Main agent or integrator owns integration.
- Keep integration serialized when ownership overlaps.
- Never push, fetch, pull, configure remotes, set upstream tracking, or run remote-touching git commands unless the human explicitly changes policy.
- Acquire `.diffmogger/runtime/codex_automation.lock` before mutating code outside scheduler-owned role runs.
