# Archived Decision Records

These records preserve historical source-kit decisions. Active setup and operating guidance lives in `docs/README.md`, `DEVELOPMENT.md`, and `docs/OPERATING_MODEL.md`.

## DR-001: Separate Stable Prompt From Typed Runtime State

Decision: keep recurring behavior in `.diffmogger/agentic/automation_prompt.md` and changing runtime/task-control state in `.diffmogger/runtime/orchestration.sqlite3`. `.diffmogger/state/CODEX_AUTOMATION_TASKS.md` remains a generated prompt/handoff projection.

Why: earlier automation trials showed that recurring agents need stable behavior plus fresh handoff state. Combining them makes prompts stale and bloated; keeping live state typed makes dashboard, conveyor, and observatory behavior auditable.

## DR-002: Prefer File-Only Human Bridge First

Decision: document local-file mode as the first human bridge and Diffmogger's bundled local notifier API as the advanced mode.

Why: file mode requires no credentials, no Discord bot, and no network setup. The notifier pattern is powerful but should remain separate so Codex does not handle Discord credentials.

## DR-003: Worker Agents Are Bounded And Main-Agent Integrated

Decision: workers produce bounded reports or isolated prototypes under `.diffmogger/runtime/agent_runs/<run_id>/`.

Why: the playbook recommends manager-worker-integrator behavior. Official Codex docs describe subagents as parallel specialist workflows, but they cost extra tokens and inherit sandbox policy, so the main agent must use them intentionally.

## DR-004: Validation Is Local And Network-Free

Decision: `scripts/validate_starter_kit.sh` checks structure, non-empty markdown, JSON parsing, key phrases, and required template sections without web access.

Why: users should be able to trust the kit before configuring Codex, Discord, or any external service.

## DR-005: Bundle The Notifier But Keep Targets Decoupled

Decision: include a reusable notifier under `services/agentic-notifier/`, while generated target projects only know the loopback API and handoff file paths.

Why: the starter repo should be complete, but target projects should not import notifier code or handle messaging credentials.

## DR-006: Treat Human-Requested Text As Outbound Messaging

Decision: generated automations must interpret freeform inbox commands such as "send me a summary" or "status update" as requests to send a direct notifier message when notifier mode is available.

Why: writing a local Markdown summary does not satisfy a human request to be messaged. The automation must record notifier failures explicitly as `NOTIFIER_UNREACHABLE` and avoid claiming delivery.

## DR-007: Record Codex CLI Worker Decisions Every Run

Decision: every recurring automation run should record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` with a one-sentence reason.

Why: broad autonomous runs benefit from bounded independent review, but worker use should be deliberate, auditable, and skipped with a reason when it would add overhead or when `codex` is unavailable.

## DR-008: Make Lock Files Executable, Not Only Advisory

Decision: include `.diffmogger/scripts/acquire_codex_lock.sh` and `.diffmogger/scripts/release_codex_lock.sh` with run metadata, stale-lock detection, and run-id-aware release behavior.

Why: short-cadence automations need a real local overlap guard. The scripts are intentionally simple and auditable rather than distributed lock infrastructure.

## DR-009: Keep Worker Helpers Optional And Bounded

Decision: include worker helper scripts for read-only reports and mechanical report summaries, while keeping main-agent integration mandatory.

Why: helper scripts make the convention runnable, but worker outputs can add noise if treated as automatic truth.

## DR-010: Treat Notifier Pydantic Models As Runtime Authority

Decision: the notifier API's Pydantic model is authoritative at runtime. `schemas/human_request.schema.json` is reference documentation checked by tests for field drift.

Why: schema generation can become a project of its own. A small drift test gives practical honesty without pretending all schemas are enforced everywhere.

## DR-011: Generated Target Repos Own Runtime Scripts

Decision: scaffold target-local copies of lock, schedule, worker, summary, and compaction entrypoints under `.diffmogger/scripts/`.

Why: target automations should not depend on the Diffmogger checkout at runtime. The starter repo is a source for scaffolding and reference docs; generated projects should be movable and schedulable on their own.

Current note: Python entrypoints are now thin wrappers over the bundled `.diffmogger/lib/diffmogger/` runtime copied from `src/diffmogger/`; shell entrypoints remain physical target-local scripts.

## DR-012: Scheduler Wrapper Owns Scheduled-Run Locks

Decision: generated scheduled runs use conveyor role wrappers to acquire and release `.diffmogger/runtime/codex_automation.lock`, and export `CODEX_LOCK_ALREADY_ACQUIRED=true` so the Codex prompt does not acquire a second lock.

Why: a first fresh-project run showed that both the wrapper and the prompt could attempt lock creation. One lock owner is easier to reason about and avoids malformed fallback lock files.

## DR-013: File-Only And Notifier Human Bridges Are Separate Modes

Decision: generated prompts and docs distinguish `file_only`, `local_notifier`, `discord_notifier`, and `disabled` human bridge modes.

Why: file-only mode is a valid long-term workflow, not merely notifier failure mode. In file-only mode, status and summary requests are local artifacts; in notifier modes, those same requests may require outbound Discord or local desktop notification delivery.

## DR-014: Nested Codex CLI Workers Need Parent Codex-Home Access And Child Sandbox Bypass

Decision: worker helper scripts and generated prompts use `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` for nested CLI workers, and generated scheduled wrappers run the parent automation with `--add-dir "$HOME/.codex"`.

Why: nested Codex workers launched from inside a scheduled automation sandbox may touch `~/.codex/state_5.sqlite`, `~/.codex/shell_snapshots`, and `~/.codex/sessions` during startup even when the child worker uses `--ephemeral`. After startup, macOS can reject a second child workspace sandbox with `sandbox-exec: sandbox_apply: Operation not permitted`. The scheduled parent remains the outer sandbox boundary, so the nested child bypass avoids the second sandbox layer while preserving the bounded worker-report pattern.

## DR-015: Write-Capable Workers Are Explicitly Opt-In And Main-Agent Integrated

Decision: generated target projects support optional bounded write-capable workers only when the intake explicitly enables `write_worker_agents_allowed`, with `max_write_worker_count` capped at 10 and read-only worker reports preserved as the default.

Why: high-throughput implementation can help when work can split into reviewable lanes, but overlapping autonomous writes are risky. The main agent must choose a strategy and parallelism budget each run, define enough ownership and contracts before spawning write workers, tell workers they are not alone in the codebase, review and integrate diffs, run verification, update typed runtime state, and refresh generated projections. Integration-only runs with no workers remain valid when faster or safer.

## DR-016: Multi-Role Worktree Orchestration Is Opt-In

Decision: generated target projects may opt into the v1 `planner_builder_hardener_integrator` profile. Older intakes used `multi_role_automations_allowed` as the selector; current intakes use canonical `automation_role_profile` and treat the boolean as a derived compatibility mirror. Planner, builder, and hardener run in isolated local worktrees from current main `HEAD`; the integrator owns the main checkout and processes queued patches FIFO.

Why: separate roles can increase useful autonomous throughput without making every target adopt that complexity. Fresh-HEAD role runs minimize stale work, while integrator-side `git apply --check` preserves correctness.

## DR-017: Dirty Main Changes Become Local Checkpoint Commits

Decision: when multi-role integrator runs find a dirty main checkout, they commit those pre-existing changes as-is with an automation-identifying author before applying queued role patches.

Why: human changes should never stall autonomous progress. A local checkpoint commit preserves the bytes and gives the human a reset point if they prefer to restore an uncommitted working state.

## DR-018: Batch Verification Falls Back To Individual Verification

Decision: the integrator batch-applies queued patches that pass `git apply --check`, runs verification once, and commits accepted patches separately. If batch verification fails, it resets to the pre-batch head and verifies patches individually, deferring failures and continuing.

Why: the common path should be fast, but failure attribution must stay clean enough for the planner and human to understand which patch broke verification.

## DR-019: No-Push Enforcement Is Layered

Decision: generated role prompts prohibit pushes, fetches, pulls, remote configuration, upstream tracking, and remote-affecting git commands as `CRITICAL_STOP` conditions. Runtime scripts also refuse configured remotes unless `MULTI_ROLE_ALLOW_REMOTES=1` is set, and the integrator refuses executable hooks containing `git push`.

Why: prompts guide agent intent, while script guards catch mistakes and environment drift. Multi-role automation is local-only by default.

## DR-020: Multi-Role Progress Is A Generated Projection

Decision: generated multi-role targets include `.diffmogger/state/MULTI_ROLE_PROGRESS.md` as a human-readable export/projection. Durable state for project status, cumulative metrics, recent activity, deferred backlog, integration summaries, and role health lives in SQLite plus role manifests.

Why: role run directories and logs are transient. Humans still need a compact weeks-long view, but automation decisions must come from typed state and role manifests rather than scraped Markdown.

## DR-021: Planner Runs Hourly For Stable Execution

Decision: the v1 multi-role schedule runs the planner hourly at minute `0`, while builder, hardener, and integrator run on staggered half-hour offsets.

Why: implementation roles should execute against a stable plan through two implementation cycles, while still giving the planner regular chances to adapt to deferred work. Continuous conveyor fast-follow after a planner patch is deferred or resolved is the narrow exception, so stale planning gets replaced from fresh `HEAD` without broadly preempting builder and hardener lanes.

## DR-022: Continuous Conveyor Is An Opt-In Scheduling Strategy

Decision: generated targets include `.diffmogger/scripts/run_conveyor_automation.sh` and `.diffmogger/scripts/run_conveyor_automation.py`. Dashboard-managed schedules can use one conveyor LaunchAgent instead of exact periodic role jobs.

Why: work-conserving automation should keep useful local work moving when prior lanes finish early or role timing would otherwise leave gaps. The conveyor records reviewable local state, uses its own dispatcher lock, delegates mutation to existing wrappers, and prioritizes queued integration, fast-follow replanning for planner deferral changes, due planning, builder momentum, and one hardener pass after integrated builder work.

## DR-023: Supersede Stale Planner Patches From Fresh HEAD

Decision: when a planner patch is deferred for staleness and later accepted work already covers its intent, future planner work should treat the stale patch as superseded instead of retrying it. The integrator may keep the deferred manifest visible for audit, but replacement work should start from current `HEAD`.

Why: planner patches coordinate future work; they should not churn current docs or schedules from an obsolete base. Fast-follow replanning after planner deferrals gives the system a fresh planning pass without disrupting builder/hardener momentum.

## DR-024: New Targets Use A Diffmogger Sidecar Namespace

Decision: new generated targets keep Diffmogger-owned prompts, state, runtime files, imported context, queue data, worktrees, and logs under `.diffmogger/`, with `.diffmogger/manifest.json` as the path source of truth for scaffold, validation, runners, dashboard surfaces, patch exclusion, and runtime-state writes.

Why: the older layout scattered generated files across `.agentic/`, `docs/`, and `target/`, which made git ignore rules, worktree seeding, patch filtering, and target-project path collisions harder to reason about. A single ignored sidecar namespace makes ownership explicit while preserving legacy target compatibility.

## DR-025: Canonical Runtime Package With Target-Local Wrappers

Decision: canonical Python runtime source lives under `src/diffmogger/`. Root `scripts/*.py` are compatibility wrappers that import package modules, and generated target `.diffmogger/scripts/*.py` wrappers are rendered from the runtime entrypoint manifest and canonical wrapper template. Scaffolding copies `src/diffmogger/` into target repos under `.diffmogger/lib/diffmogger/` and records the bundle in `.diffmogger/manifest.json`.

Why: the earlier layout kept Python implementation in multiple tracked locations, which made ownership unclear and made drift prevention depend on exact file comparisons. Manifest-generated wrappers preserve command names while making source ownership explicit.

## Source Summary From References

Local playbook PDF:
Recurring automations should act as substantial engineering sprints, read stable guardrails and dynamic task state, verify work, use lock files for short cadence, ask humans asynchronously for unlocks, and use bounded worker agents without giving up main-agent ownership.

Product automation trial:
A real project benefits from a stable automation prompt, dynamic task state, lean guardrails, human bridge state, daily review, autonomy log, and end-of-run updates. New Diffmogger targets place those generated files under `.diffmogger/`; product-specific content should stay outside the core kit or inside clearly fictional examples.

Agentic Notifier reference:
A separate local service can own Discord credentials, expose `POST /api/notify`, route outbound progress/messages, capture bot mentions/replies from a configured messaging channel, dedupe messages, and write human replies into project markdown files. Diffmogger adapts the generic pieces into `services/agentic-notifier/` and replaces product-specific path names with target-project configuration.

Official Codex docs checked on 2026-04-29:
Codex CLI runs locally, `AGENTS.md` provides layered project guidance, `codex exec` supports non-interactive scripted runs, Automations schedule recurring tasks, subagents support explicit parallel specialized workflows, and sandbox/approval controls should be chosen according to risk.

Official Discord docs checked on 2026-05-04:
Discord bot applications can send messages through bot permissions, read message content when Message Content Intent is enabled, and should be invited with least-needed OAuth2 permissions such as View Channels, Send Messages, and Read Message History.
