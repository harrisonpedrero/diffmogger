# Concepts

This kit turns an idea into a repo-local operating system for recurring Codex work.

## The Core Split

Stable automation prompt:
Behavior that should remain true every run. It says how Codex should operate, not the full backlog.

Static guardrails:
Lean constraints that prevent dangerous or off-mission behavior.

Dynamic task file:
Current state, last run, checks, blockers, human requests, and next sprint. Codex rewrites this at the end of every run.

Sidecar ownership:
New generated targets keep Diffmogger-owned prompts, state, queue data, worktrees, logs, and imported context under `.diffmogger/`. The generated `.diffmogger/manifest.json` is the path source of truth for runners, validation, dashboard views, and patch exclusion. Existing generated targets may still use the legacy `.agentic/`, `docs/`, and `target/` layout.

## Bootstrap Vs Recurring Automation

The bootstrap prompt is project-specific and temporary. Use it once or a few times to create the product baseline, docs, tests, and automation state.

The recurring automation prompt is durable. It should survive beyond the initial scope and tell Codex how to keep compounding progress, or how to stop cleanly when the selected run mode is bounded.

## Sprint-Sized Runs

A scheduled run should be large enough to matter and small enough to verify. It should usually include implementation, checks, artifact updates, and task-file rewrite.

## Product Horizons

Product horizons are a progression system, not a loose aspiration list. Generated task files include:

```text
## Product Horizon State
## Horizon Transition Log
```

Every run should work mainly inside the current horizon, gather evidence, and end with an explicit advancement decision:

```text
stay | advance | defer
```

Diffmogger scaffolds mode-aware horizons from the project intake. Continuous-improvement projects get product horizons such as:

1. H1 Runnable baseline.
2. H2 Local-first demo.
3. H3 Serious core functionality.
4. H4 Evaluation, reporting, or comparison layer.
5. H5 Safe integration architecture.
6. H6 Showcase quality.
7. H7 Long-run direction aligned with the mission.
8. H8 Automation process improvement.

Ticket-campaign projects use bounded ticket-run phases instead: ticket-run readiness, ticket implementation, verification and hardening, completion report, and stop. In that mode bootstrap is readiness-only, `.diffmogger/state/TICKET_RUN.md` remains the source of truth, optional `depends_on` arrays define ticket prerequisites, and normal campaign runs use `python3 .diffmogger/scripts/ticket_run.py . next --json` to act on one dependency-ready ticket at a time. The automation should not invent open-ended roadmap work after the listed tickets are complete or blocked.

When a horizon's advancement criteria are met, the automation should update the current horizon to the next horizon and append evidence to the transition log. If a later regression undermines an earlier horizon, the automation should keep the current horizon but make the regression the next sprint-sized task.

## Human Input

Human input is asynchronous. The automation should request only meaningful unlocks, keep working around pending input, and consume replies on later runs.

In file-only mode, summary or status requests are answered locally in Markdown or app artifacts. In notifier modes, requests to be messaged should send a concise outbound response through the local notifier when available. Either way, the automation should archive handled entries and keep `.diffmogger/state/HUMAN_INBOX.md` as an active queue, not a permanent log.

## Worker Agents

Workers are helpers, not owners. They inspect, review, or prototype bounded areas. The main agent integrates and verifies.

Every recurring run should record whether Codex CLI workers were used, skipped, or unavailable.

Generated target repos include helper scripts for read-only worker reports. Optional write-capable workers are disabled unless the intake explicitly enables them. When enabled, they are bounded acceleration: the main agent chooses a parallelism budget, gives workers reviewable ownership, and owns review/integration.

## Lock Files

Scheduled runs should acquire `.diffmogger/runtime/codex_automation.lock` before mutating code. The bundled acquire/release scripts record run metadata, detect stale locks, and fail cleanly when another active run exists.

## State Compaction

Markdown handoff files are useful because they live in the repo, but they can grow into context bloat. `.diffmogger/scripts/compact_agent_state.py` preserves unresolved human requests, keeps recent state, and archives concise rollups for older handled entries.
