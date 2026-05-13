# Multi-Role Progress

Generated dashboard/export projection for optional multi-role automation. SQLite in `target/orchestration.sqlite3` is the live state authority; `target/canonical_state_brief.md` is the bounded state view agents should read at run start.

Role profile: `{{AUTOMATION_ROLE_PROFILE}}`

Continuous conveyor mode uses one local dispatcher that prioritizes queued integration first, baseline preflight/repair, safety triage, typed human-message handling, fast-follow replanning after planner deferral changes, one focused hardener pass after integrated builder work, catch-up hardening for the oldest unverified `candidate_done` cluster, planner-needed transitions, and builder momentum by default.

## Project State At Last Integration

- Current product horizon: H1 Runnable baseline
- Latest evidence: Initial scaffold only; no multi-role integrator run has completed yet.
- Last integrator run: none
- Last verification status: not run

## Cumulative Metrics

- Total integrator runs: 0
- Accepted patches by role:
  - planner: 0
  - builder: 0
  - hardener: 0
- Deferred patches by role:
  - planner: 0
  - builder: 0
  - hardener: 0
- Current deferred queue depth: 0
- Mean time from role-run completion to integration: unknown
- Human messages handled: 0
- Human requests created: 0
- Human requests resolved: 0

## Recent Activity Log

- No multi-role integrator runs yet.

## Historical Summary

- No compacted multi-role history yet.

## Deferred-Patch Backlog

- None.

## UI Artifact Backlog

- Playwright UI artifacts path: `docs/backlog/ui_artifacts/<run_id>/`
- Current screenshot-backed UI bugs: none yet.
- Hardener and Integrator validation runs should link any `browser_take_screenshot` artifact here when a UI bug is deferred for Builder follow-up.

## Architectural Decisions

- None yet.

## Role Health

- planner: no runs yet
- builder: no runs yet
- hardener: no runs yet
- integrator: no runs yet
