# Development

Project: `{{PROJECT_NAME}}`

Goal: {{PRODUCT_GOAL}}

## Setup

Keep setup notes short and executable. Prefer project-local dependencies, fixtures, mocks, and seed data for safe local milestones. When the product depends on real or external data, document the source-mode strategy, connector/cache path, provenance/freshness expectations, and how unavailable live sources are deferred without disguising fallback data as real.

## Verification

Full-suite commands:

```text
.diffmogger/agentic/verification_commands.txt
```

Smoke commands:

```text
.diffmogger/agentic/smoke_commands.txt
```

Preferred commands:

```text
{{VERIFICATION_COMMANDS}}
```

If validation fails, create work instead of stopping automation. Failed validation creates work:

- required check failure -> repair work
- missing tool -> setup or harness work
- external service failure -> mock, local fixture, or defer work
- browser/MCP failure -> alternate validation or deferred QA work
- repeated failure -> split, reframe, or planner work

## Automation

Canonical state lives in `.diffmogger/runtime/orchestration.sqlite3`.
Read `.diffmogger/runtime/canonical_state_brief.md`; use `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` as the generated handoff projection.
When `automation_checkpoint_commits` is enabled, accepted patches become local-only project-change commits after integration and validation. Diffmogger records accepted commit hashes in typed ticket state and never pushes or touches remotes.

Run the scheduler:

```bash
bash .diffmogger/scripts/run_temporal_worker.sh --policy --max-fanout 2
bash .diffmogger/scripts/run_temporal_worker.sh --temporal --max-fanout 2
```

Useful runtime helpers:

```bash
python3 .diffmogger/scripts/state_brief.py .
python3 .diffmogger/scripts/ticket_run.py . status --json
python3 .diffmogger/scripts/ticket_run.py . next --json
python3 .diffmogger/scripts/repair_environment.py --target .
```

Browser-backed checks should prefer the managed browser helper:

```bash
python3 .diffmogger/scripts/diffmogger_browser.py doctor --launch
```

## Design And UI Validation

{{DESIGN_CAPABILITY_SECTION}}

{{UI_VALIDATION_SECTION}}

Active design contract projections:

```text
.diffmogger/agentic/design_contract.md
.diffmogger/agentic/design_contract.json
```

Wrappers load target env files into process environment when allowed. Never print, summarize, commit, or copy secret values.

## Ticket Campaigns

{{TICKET_CAMPAIGN_DEVELOPMENT_SECTION}}
