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

All listed tickets are completed or blocked with evidence, verification notes, and a local final report.

## Tech Preferences

- Preserve the existing project stack.
- Use the existing test and lint commands.

## Constraints

- Local-only work.
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

## Automation Cadence

Every 60 minutes until the ticket run is complete or blocked.

## Human Bridge

Disabled.

## Automation Run Mode

ticket_campaign

## Ticket Completion Notify

false

## Worker Agents

Allowed for read-only test-gap and risk reviews.

## Meaningful Deliverable

A completed or honestly blocked ticket with evidence and verification notes.

## Long-Run Direction

None. Stop when the bounded ticket run is complete or fully blocked.

## Assumptions

- Tickets are local and do not require network access.
