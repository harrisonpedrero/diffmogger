# Project Intake: PatchQueue

## Summary

PatchQueue is a fictional bounded ticket run for applying a small local maintenance queue.

## Project Mode

existing_project

## Product Goal

Resolve a bounded set of local tickets with reviewable patches, evidence, and a completion report.

## Target User

Maintainers who want Codex to finish a known queue without inventing new roadmap work.

## Desired First Demo

A readiness-only bootstrap followed by one dependency-aware ticket run, with evidence, verification notes, and local final reporting when the campaign eventually completes.

## Tech Preferences

- Respect the existing project stack.
- Use the existing test and lint commands.

## Constraints

- Local-only work.
- Bootstrap must not implement tickets.
- Normal campaign runs should respect ticket dependencies; the DAG scheduler may group disjoint ready work when ownership and confidence allow.
- Do not create new tickets after the listed queue is complete.

## Safety Rules

- Do not read local `.env*` files unless env access is explicitly enabled.
- Do not push, deploy, or contact external services.

## Automation Must Never Do

- Never print, store, or commit secrets.
- Never push, deploy, publish, or contact real users without approval.
- Never invent extra tickets after the campaign is complete.

## External Services

None required.

## Environment Access Policy

project_commands_only

## Verification

- `npm test`

## Automation Mode

Continuous execution DAG scheduler with planner/builder/hardener/integrator roles until every ticket is done with evidence. Blocked tickets become unblocker DAG work.

## DAG Scheduler Config

parallel_execution_mode: aggressive
symbol_graph_languages: python, typescript, javascript
parallel_write_min_confidence: 0.75
parallel_write_direct_confidence: 0.75
max_parallel_write_workers: 3
max_parallel_scope_workers: 2

## Human Bridge

Disabled.

## Campaign Mode

bounded

## Ticket Completion Notify

false

## Ticket Run Seed Tickets

[
  {
    "id": "TICKET-001",
    "summary": "Add a local queue health check",
    "status": "pending",
    "acceptance_criteria": [
      "The fictional queue health check reports pass/fail status without network access."
    ],
    "verification_commands": [
      "npm test"
    ]
  },
  {
    "id": "TICKET-002",
    "summary": "Document the maintainer review path",
    "depends_on": [
      "TICKET-001"
    ],
    "status": "pending",
    "acceptance_criteria": [
      "The local review notes explain how maintainers inspect the queue result."
    ],
    "verification_commands": [
      "npm test"
    ]
  }
]

## Worker Agents

Allowed for read-only test-gap and risk reviews.

## Meaningful Deliverable

A completed selected ticket with evidence and verification notes, or unblocker work that moves a remaining ticket forward.

## Long-Run Direction

None. Stop only when the bounded ticket run is complete with evidence; blocked tickets become unblocker work.

## Assumptions

- Tickets are local and do not require network access.
- If a ticket depends on another ticket, it uses `depends_on` in the dashboard-backed SQLite ticket queue.
