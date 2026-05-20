# Development

Project: `{{PROJECT_NAME}}`

Goal: {{PRODUCT_GOAL}}

## Setup

Keep setup notes short and executable. Prefer project-local dependencies, fixtures, mocks, and seed data.

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

Run the scheduler:

```bash
bash .diffmogger/scripts/run_conveyor_automation.sh --dry-run
bash .diffmogger/scripts/run_conveyor_automation.sh --once
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

Wrappers load target env files into process environment when allowed. Never print, summarize, commit, or copy secret values.

## Ticket Campaigns

{{TICKET_CAMPAIGN_DEVELOPMENT_SECTION}}
