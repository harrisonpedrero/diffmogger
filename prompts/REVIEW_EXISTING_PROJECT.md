# Review Existing Project Prompt

Use this to retrofit an existing repo into the agentic automation workflow. Prefer
the `.diffmogger/` sidecar layout for new retrofits; use legacy `.agentic/`,
`docs/`, and `target/` paths only for targets that already lack a sidecar
manifest.

---

You are retrofitting this existing repository for high-agency recurring Codex automations.

Read the existing README, package/build files, tests, scripts, docs, and architecture before writing files.

Create a concise retrofit plan, then implement the automation docs:

- `AGENTS.md`
- `.diffmogger/agentic/automation_prompt.md`
- `.diffmogger/state/CODEX_AUTOMATION_TASKS.md`
- `.diffmogger/state/CODEX_AUTOMATION_GUARDRAILS.md`
- `.diffmogger/state/HUMAN_BRIDGE_SETUP.md`
- `.diffmogger/state/AUTONOMY_EXPERIMENT_LOG.md`
- `.diffmogger/state/DAILY_AUTOMATION_REVIEW.md`
- local helper scripts under `.diffmogger/scripts/` for locks, run control, worker reports, worker summaries, state compaction, and the canonical state brief

Respect the existing stack and conventions. Do not rewrite the product just to fit the kit.

Canonical live orchestration state should remain `.diffmogger/runtime/orchestration.sqlite3`. Typed automation control, execution DAG nodes and edges, repository capability manifest, validation receipts, blockers, human messages, and next actions live there; conveyor stage fields are compatibility projections only. `.diffmogger/runtime/canonical_state_brief.md` is the generated state view agents read instead of inspecting SQLite manually. Preserve or add DAG scheduler config fields for parallel execution mode, symbol graph languages, write-confidence thresholds, and max parallel scope/write workers.

The initial typed automation control state and generated task projection should honestly describe:

- what exists
- how to run it
- known verification commands
- Codex CLI worker decision expectations
- human bridge mode: `disabled`, `file_only`, or `local_notifier`
- lock wrapper behavior with `CODEX_LOCK_ALREADY_ACQUIRED=true`
- missing or flaky setup
- risks
- best next sprint-sized improvement

If the repo has unclear setup, create a human request only when the owner must act. Otherwise infer and document safe assumptions.

The recurring automation prompt must distinguish structured human replies from freeform commands. In `file_only` mode, summary/status requests should be satisfied through the dashboard or requested local artifacts. In `local_notifier` or `discord_notifier` mode, if the human asks to be messaged, replied to, or sent a status update, the automation should use `POST http://127.0.0.1:8765/api/notify` with `event_kind: "message"` when available and should record `NOTIFIER_UNREACHABLE` in typed human-message state when unavailable.

Run available validation commands if safe. Record validation receipts in typed state and refresh the generated task projection with results.
