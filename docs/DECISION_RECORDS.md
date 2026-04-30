# Decision Records

## DR-001: Separate Stable Prompt From Dynamic Task State

Decision: keep recurring behavior in `.agentic/automation_prompt.md` and changing state in `docs/CODEX_AUTOMATION_TASKS.md`.

Why: earlier automation trials showed that recurring agents need stable behavior plus fresh handoff state. Combining them makes prompts stale and bloated.

## DR-002: Prefer File-Only Human Bridge First

Decision: document local-file mode as the first human bridge and Diffmogger's bundled local notifier API as the advanced mode.

Why: file mode requires no credentials, no webhook, and no network setup. The notifier pattern is powerful but should remain separate so Codex does not handle Twilio credentials.

## DR-003: Worker Agents Are Bounded And Main-Agent Integrated

Decision: workers produce bounded reports or isolated prototypes under `target/agent_runs/<run_id>/`.

Why: the playbook recommends manager-worker-integrator behavior. Official Codex docs describe subagents as parallel specialist workflows, but they cost extra tokens and inherit sandbox policy, so the main agent must use them intentionally.

## DR-004: Validation Is Local And Network-Free

Decision: `scripts/validate_starter_kit.sh` checks structure, non-empty markdown, JSON parsing, key phrases, and required template sections without web access.

Why: users should be able to trust the kit before configuring Codex, Twilio, or any external service.

## DR-005: Bundle The Notifier But Keep Targets Decoupled

Decision: include a reusable notifier under `services/agentic-notifier/`, while generated target projects only know the loopback API and handoff file paths.

Why: the starter repo should be complete, but target projects should not import notifier code or handle messaging credentials.

## DR-006: Treat Human-Requested Text As Outbound Messaging

Decision: generated automations must interpret freeform inbox commands such as "send me a summary" or "status update" as requests to send SMS/WhatsApp through the notifier when it is available.

Why: writing a local Markdown summary does not satisfy a human request to be messaged. The automation must record notifier failures explicitly as `NOTIFIER_UNREACHABLE` and avoid claiming delivery.

## DR-007: Record Codex CLI Worker Decisions Every Run

Decision: every recurring automation run should record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` with a one-sentence reason.

Why: broad autonomous runs benefit from bounded independent review, but worker use should be deliberate, auditable, and skipped with a reason when it would add overhead or when `codex` is unavailable.

## DR-008: Make Lock Files Executable, Not Only Advisory

Decision: include `scripts/acquire_codex_lock.sh` and `scripts/release_codex_lock.sh` with run metadata, stale-lock detection, and run-id-aware release behavior.

Why: short-cadence automations need a real local overlap guard. The scripts are intentionally simple and auditable rather than distributed lock infrastructure.

## DR-009: Keep Worker Helpers Optional And Bounded

Decision: include worker helper scripts for read-only reports and mechanical report summaries, while keeping main-agent integration mandatory.

Why: helper scripts make the convention runnable, but worker outputs can add noise if treated as automatic truth.

## DR-010: Treat Notifier Pydantic Models As Runtime Authority

Decision: the notifier API's Pydantic model is authoritative at runtime. `schemas/human_request.schema.json` is reference documentation checked by tests for field drift.

Why: schema generation can become a project of its own. A small drift test gives practical honesty without pretending all schemas are enforced everywhere.

## DR-011: Generated Target Repos Own Runtime Scripts

Decision: scaffold target-local copies of lock, schedule, worker, summary, and compaction scripts under `scripts/`.

Why: target automations should not depend on the Diffmogger checkout at runtime. The starter repo is a source for scaffolding and reference docs; generated projects should be movable and schedulable on their own.

## DR-012: Scheduler Wrapper Owns Scheduled-Run Locks

Decision: generated scheduled runs use `scripts/run_codex_automation.sh` to acquire and release `target/codex_automation.lock`, and export `CODEX_LOCK_ALREADY_ACQUIRED=true` so the Codex prompt does not acquire a second lock.

Why: a first fresh-project run showed that both the wrapper and the prompt could attempt lock creation. One lock owner is easier to reason about and avoids malformed fallback lock files.

## DR-013: File-Only And Notifier Human Bridges Are Separate Modes

Decision: generated prompts and docs distinguish `file_only`, `local_notifier`, and `disabled` human bridge modes.

Why: file-only mode is a valid long-term workflow, not merely notifier failure mode. In file-only mode, status and summary requests are local artifacts; in local-notifier mode, those same requests may require outbound SMS/WhatsApp.

## DR-014: Nested Codex CLI Workers Use Ephemeral Sessions

Decision: worker helper scripts and generated prompts use `codex exec --ephemeral` for nested CLI workers.

Why: nested Codex workers launched from inside a scheduled automation sandbox may be unable to write `~/.codex/sessions`. Ephemeral child sessions avoid that failure while preserving the bounded worker-report pattern.

## Source Summary From References

Local playbook PDF:
Recurring automations should act as substantial engineering sprints, read stable guardrails and dynamic task state, verify work, use lock files for short cadence, ask humans asynchronously for unlocks, and use bounded worker agents without giving up main-agent ownership.

Product automation trial:
A real project benefits from `.agentic/automation_prompt.md`, `CODEX_AUTOMATION_TASKS.md`, lean guardrails, human bridge docs, daily review, autonomy log, and end-of-run updates. Product-specific content should stay outside the core kit or inside clearly fictional examples.

Agentic Notifier reference:
A separate local service can own Twilio credentials, expose `POST /api/notify`, receive Twilio inbound webhooks, dedupe messages, and write human replies into project markdown files. Diffmogger adapts the generic pieces into `services/agentic-notifier/` and replaces product-specific path names with target-project configuration.

Official Codex docs checked on 2026-04-29:
Codex CLI runs locally, `AGENTS.md` provides layered project guidance, `codex exec` supports non-interactive scripted runs, Automations schedule recurring tasks, subagents support explicit parallel specialized workflows, and sandbox/approval controls should be chosen according to risk.

Official Twilio docs checked on 2026-04-29:
Twilio messaging webhooks deliver incoming message details to a configured application URL, request parameters can evolve, SDK signature validation is recommended, and WhatsApp through Twilio can use webhooks for inbound messages.
