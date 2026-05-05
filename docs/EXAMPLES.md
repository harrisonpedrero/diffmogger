# Examples

The `examples/` directory contains intake briefs and expected generated files.

## Generic Web App

Use `examples/generic-web-app/project_intake.md` to test the kit against a normal fresh-project idea. It exercises project mode, project goals, target users, stack preferences, first demo, verification, human bridge, and worker-agent settings.

The dashboard can add supplemental context files at setup time. Those files are copied into the generated target under `docs/context/` and indexed in `docs/PROJECT_CONTEXT.md`.

## TrendLab Signal Intelligence

Use `examples/trendlab-signal-intelligence/project_intake.md` to exercise a more involved fictional product brief. It keeps the workflow reusable while covering fixture data, scoring, reports, and human-in-the-loop requests.

## Ticket Campaign

Use `examples/ticket-campaign/project_intake.md` to exercise bounded ticket-campaign mode. It checks that generated automation uses ticket-run phases, treats `docs/TICKET_RUN.md` as scope, and avoids open-ended roadmap language.

## Smoke Test

```bash
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target /tmp/Diffmogger-example --force
python3 scripts/check_required_files.py --human-bridge-mode file_only /tmp/Diffmogger-example
```
