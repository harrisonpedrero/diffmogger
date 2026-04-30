# Concepts

This kit turns an idea into a repo-local operating system for recurring Codex work.

## The Core Split

Stable automation prompt:
Behavior that should remain true every run. It says how Codex should operate, not the full backlog.

Static guardrails:
Lean constraints that prevent dangerous or off-mission behavior.

Dynamic task file:
Current state, last run, checks, blockers, human requests, and next sprint. Codex rewrites this at the end of every run.

## Bootstrap Vs Recurring Automation

The bootstrap prompt is project-specific and temporary. Use it once or a few times to create the product baseline, docs, tests, and automation state.

The recurring automation prompt is durable. It should survive beyond the MVP and tell Codex how to keep compounding progress.

## Sprint-Sized Runs

A scheduled run should be large enough to matter and small enough to verify. It should usually include implementation, checks, artifact updates, and task-file rewrite.

## Product Horizons

1. Runnable baseline.
2. Offline demo.
3. Serious core functionality.
4. Research, evaluation, or comparison layer.
5. Safe integration architecture.
6. Showcase quality.
7. Ambitious extensions.
8. Process improvement.

## Human Input

Human input is asynchronous. The automation should request only meaningful unlocks, keep working around pending input, and consume replies on later runs.

If a human inbox message asks to be texted, messaged, or sent a status update, the automation should send a concise outbound response through the local notifier when available. It should archive the handled entry and keep `docs/HUMAN_INBOX.md` as an active queue, not a permanent log.

## Worker Agents

Workers are helpers, not owners. They inspect, review, or prototype bounded areas. The main agent integrates and verifies.

Every recurring run should record whether Codex CLI workers were used, skipped, or unavailable.

Diffmogger includes optional helper scripts for read-only worker reports, but the main agent remains the integrator.

## Lock Files

Scheduled runs should acquire `target/codex_automation.lock` before mutating code. The bundled acquire/release scripts record run metadata, detect stale locks, and fail cleanly when another active run exists.

## State Compaction

Markdown handoff files are useful because they live in the repo, but they can grow into context bloat. `scripts/compact_agent_state.py` preserves unresolved human requests, keeps recent state, and archives concise rollups for older handled entries.
