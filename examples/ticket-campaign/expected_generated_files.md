# Expected Generated Files: PatchQueue

The generation prompt should produce the standard automation file set plus the ticket source:

```text
AGENTS.md
.diffmogger/manifest.json
.diffmogger/agentic/automation_prompt.md
.diffmogger/state/INITIAL_BOOTSTRAP_PROMPT.md
.diffmogger/state/PROJECT_CONTEXT.md
.diffmogger/state/CODEX_AUTOMATION_TASKS.md
.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md
.diffmogger/state/TICKET_RUN.md
.diffmogger/scripts/run_process_watchdog.py
.diffmogger/scripts/diffmogger_paths.py
.diffmogger/scripts/ticket_run.py
```

The generated bootstrap prompt should keep ticket-campaign bootstrap readiness-only: it may confirm setup, ticket parsing, and verification state, but must not implement ticket acceptance criteria or mark tickets done.

The generated `.diffmogger/agentic/verification_commands.txt` should contain bootstrap-safe commands that pass before any ticket implementation work starts. Desired future project checks may remain in the ticket source or sidecar state until the project surfaces that run them exist.

The generated recurring prompt should use bounded ticket-run phases: ticket-run readiness, one dependency-aware ticket implementation per run, verification and hardening, completion report, and stop.

The generated task file should keep `## Product Horizon State` for compatibility, but its current horizon should be a ticket-run phase and its backlog section should be `## Deferred / Follow-Up Tickets`.

The generated prompt and task file should not use product-roadmap language such as `MVP`, `Beyond MVP`, or `Ambitious extensions`. `.diffmogger/state/TICKET_RUN.md` is the source of truth for scope, optional `depends_on` arrays order dependent tickets, and automation should stop launching new work after all tickets are done or blocked.
