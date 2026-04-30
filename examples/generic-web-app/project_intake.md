# Project Intake: FocusBoard

## Summary

FocusBoard is a local-first web app for solo builders to plan, execute, and review weekly project work.

## Product Goal

Create a simple product workspace that turns project goals into weekly boards, daily focus plans, progress summaries, and lightweight review artifacts.

## Target User

Solo founders, engineers, and creative builders managing one to three active projects.

## Desired First Demo

A user can create a project, add goals, generate a weekly board from seed data, mark tasks done, and view a daily summary.

## Tech Preferences

- TypeScript
- Next.js or another simple web app stack
- Local JSON or SQLite storage for first demo
- Minimal dependencies

## Constraints

- Local-first demo.
- No paid services required.
- Keep setup under ten minutes.

## Safety Rules

- Do not read `.env`.
- Do not send notifications externally in the first demo.
- Do not publish or deploy without approval.

## External Services

- Optional calendar integration later.
- Optional SMS/email reminders later.

## Verification

- `npm test`
- `npm run lint`
- `npm run build`

## Automation Cadence

Hourly during active development. Every 30 minutes only after the first three runs are stable.

## Human Bridge

Enabled in file-only mode. Local notifier API can be added later.

## Worker Agents

Allowed for read-only architecture, test gap, and product polish reviews.

## Meaningful Deliverable

A runnable UI or local workflow improvement backed by tests, build, or a demo script.

## Beyond MVP

Add recurring review capsules, local import/export, richer planning views, and optional notification adapters behind feature gates.

## Assumptions

- The first version does not need authentication.
- Local data is acceptable for the first demo.
