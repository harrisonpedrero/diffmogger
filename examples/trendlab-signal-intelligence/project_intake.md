# Project Intake: TrendLab

## Summary

TrendLab is a fictional signal intelligence app for monitoring public trend events, scoring evidence, and producing research briefs. It is designed to exercise Diffmogger's workflow without relying on a real product domain.

## Product Goal

Create a local-first app that ingests fixture trend events, scores relevance/novelty/confidence/risk, shows evidence-backed dashboards, and generates comparison reports.

## Target User

Product strategists, researchers, and builders who want to evaluate emerging opportunities without wiring real APIs on day one.

## Desired First Demo

A dashboard shows fixture trend events, scored signals, source evidence, a generated brief, and a simple strategy/comparison report.

## Tech Preferences

- TypeScript
- Web app with reusable core package if useful
- Fixture-first data model
- Tests for scoring and report generation

## Constraints

- No live external data required.
- No paid API calls.
- Keep all real integrations optional and config-gated.

## Safety Rules

- Do not read `.env`.
- Do not scrape websites without terms review.
- Do not make investment, medical, legal, or safety-critical recommendations.
- Do not publish externally without approval.

## External Services

- Optional read-only news/search adapter later.
- Optional local notifier bridge later.

## Verification

- `npm test`
- `npm run lint`
- `npm run typecheck`
- `npm run build`
- `./scripts/demo_all.sh`

## Automation Cadence

Hourly at first. Every 15 minutes only with lock-file behavior.

## Human Bridge

Enabled. Use file-only mode first, then optional local notifier API.

## Worker Agents

Allowed for read-only architecture review, test gap review, product polish review, and risk review.

## Meaningful Deliverable

A verified product increment that improves the dashboard, scoring, report generation, fixtures, or evaluation workflow.

## Beyond MVP

Add adapter architecture, source-quality attribution, confidence calibration, richer reports, alerting, and daily review capsules.

## Assumptions

- The first version is research/demo software, not advice software.
- Fixture data is enough to prove the workflow.
