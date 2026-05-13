# Backlog Artifacts

This directory stores durable, human-inspectable backlog evidence.

When Playwright MCP finds a UI or browser-backed failure, save screenshots under:

```text
docs/backlog/ui_artifacts/<run_id>/<issue-slug>.png
```

Record the screenshot path in typed runtime state or the role manifest, then refresh `docs/CODEX_AUTOMATION_TASKS.md` and `docs/MULTI_ROLE_PROGRESS.md` as generated projections when relevant so the next Builder receives a visually grounded ticket.
