# Ticket Run: {{PROJECT_NAME}}

This file is the bounded source of truth for `ticket_campaign` automation mode.
Keep tickets local, reviewable, and free of secrets.
When `notify_on_complete` is true, finalization sends a native local desktop
notification and records `LOCAL_NOTIFICATION_FAILED` in `.diffmogger/state/HUMAN_OUTBOX.md`
if the laptop notification path is unavailable.

```json ticket-run
{
  "run_id": "{{PROJECT_SLUG}}-ticket-run",
  "status": "active",
  "halt_when_complete": true,
  "notify_on_complete": {{TICKET_COMPLETION_NOTIFY}},
  "report_path": ".diffmogger/runtime/ticket_run_reports/{{PROJECT_SLUG}}-ticket-run.md",
  "tickets": {{TICKET_RUN_TICKETS_JSON}}
}
```

## Status Rules

- Use `pending` before work starts.
- Use `in_progress` while a role is actively implementing.
- Use `candidate_done` when implementation exists but hardening or final verification remains.
- Use `done` only after acceptance criteria and verification evidence are recorded.
- Use `blocked` when no safe local work can complete the ticket without human action.

Use optional `depends_on` arrays to require another ticket ID to be `done` with
evidence before this ticket can be selected. Normal campaign runs use:

```bash
python3 .diffmogger/scripts/ticket_run.py . next --json
```

That command preserves file order as the human priority order, while skipping
tickets whose dependencies are not ready. Each normal run should act on at most
one selected ticket.

When every ticket is `done`, or when all remaining tickets are `blocked`, the
automation writes the final report and stops launching new work.

## Native Dashboard

Use the native dashboard Ticket Queue panel to inspect, add, edit, delete,
bulk import, or draft tickets. The dashboard preserves this Markdown wrapper
and updates only the fenced `json ticket-run` block.

Bulk import accepts Markdown, CSV, and JSON. Examples:

```markdown
- TICKET-001: Add the local setup check
- TICKET-002: Document the review path
  depends_on: TICKET-001
```

```csv
id,summary,depends_on,acceptance_criteria,verification_commands
TICKET-001,Add setup check,,Setup check passes,python -m unittest
```

```json
[
  {
    "id": "TICKET-001",
    "summary": "Add the local setup check",
    "status": "pending"
  }
]
```
