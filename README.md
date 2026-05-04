# Diffmogger

A Markdown-first operating system for recurring AI coding agents.

Diffmogger is for solo and small-team projects that want recurring Codex automation to compound instead of restarting from scratch. It externalizes agent state into repo-local Markdown so scheduled runs can preserve context, verify their own work, ask for human unlocks asynchronously, and keep moving around blockers.

It is different from a pile of prompt files or a basic scheduled agent run because it includes the operating plumbing around the agent: task state, guardrails, inbox/outbox files, archives, lock files, worker reports, validation markers, and a local optional human bridge. The goal is not enterprise autonomy infrastructure. Diffmogger is alpha, local-first, git-diffable workflow scaffolding for ambitious personal and small-team engineering work.

Model/runtime note: Diffmogger was designed and tested with Codex running GPT-5.5. Other Codex models or non-Codex agent runtimes may work, but they have not been validated and may require prompt or workflow tuning. The templates are intentionally local-first and text-based so they can be adapted over time.

## Who This Is For

Diffmogger is a fit for:

- solo founders
- indie builders
- students
- lab engineers
- small teams
- people running ambitious recurring agent work on personal or small-team repos

Diffmogger is not a fit for teams that need enterprise autonomy infrastructure today. It does not provide RBAC, a formal audit pipeline, an SLO story, or a multi-user governance model. It is not appropriate for production autonomous deploys without additional review, compliance, release, and incident-response infrastructure.

## Core Idea

Diffmogger splits recurring agent work into stable instructions and mutable state:

- Stable prompt: durable recurring behavior.
- Static guardrails: constraints that should not churn every run.
- Dynamic task file: current state, checks, blockers, pending human requests, and next sprint.
- Verification: tests, builds, demos, screenshots, reports, or an honest note about what could not run.
- Lock files: reduce overlapping scheduled mutations of the same checkout.
- Worker helpers: bounded reports by default, optional bounded write workers as acceleration when explicitly enabled, integrated by the main agent.
- Multi-role mode: optional local-only planner, builder, hardener, and integrator schedules with isolated worktrees and FIFO patch integration.
- Human bridge: manual Markdown queues first, optional local notifier later.

The operating model is:

```text
stable automation prompt
+ static guardrails
+ dynamic Markdown task file
+ scheduled sprint runs
+ verification
+ lock files
+ optional bounded worker agents
+ optional decoupled human bridge
```

Generated target projects stay decoupled from Diffmogger. They use generated docs/prompts and, optionally, call a loopback notifier API. They should not import notifier code.

The status model is explicit and preserved across generated prompts:

```text
ACTIVE
ACTIVE_WITH_PENDING_USER_INPUT
BLOCKED_ON_USER
BLOCKED_ON_ENVIRONMENT
CRITICAL_STOP
```

## How This Is Different

| Compared with | Practical difference |
| --- | --- |
| `AGENTS.md`, `.cursorrules`, and static prompt files | Those are mostly static instructions. Diffmogger adds dynamic state plumbing: task file, inbox, archive, lock, compaction, worker reports, and validation. |
| Codex Automations and scheduled-run features | Those provide a scheduler. Diffmogger provides an operating model for making scheduled runs compound: externalized state, sprint sizing, status model, human bridge protocol, worker-agent conventions, verification, and backlog rewriting. |
| Interactive agents such as Cursor, Cline, and Aider | Those assume a human is in the loop every turn. Diffmogger targets unattended recurring runs where the agent must preserve state, verify, ask for unlocks asynchronously, and continue around blockers. |
| Agent frameworks such as LangGraph, CrewAI, AutoGen, and AutoGPT | Those are runtimes and frameworks. Diffmogger is a workflow scaffold layered on top of an existing CLI agent, with no new runtime lock-in. |
| Hosted autonomy tools | Hosted systems may hide state or bind users to a vendor workflow. Diffmogger is local-first, repo-local, and git-diffable. |

## What Is Novel Here

The individual ingredients are familiar: Markdown files, scheduled runs, lock files, worker agents, validation scripts, and human handoff queues. Diffmogger's useful claim is about the system boundary: it packages those ingredients into one local, reviewable control loop for recurring Codex work.

The design choices that matter are:

- Markdown-first state is the shared substrate: stable behavior is separated from mutable state, so the recurring prompt stays durable while `docs/CODEX_AUTOMATION_TASKS.md` carries current blockers, checks, human requests, horizon state, and the next sprint.
- The run lifecycle is explicit: acquire a lock, read state, choose a sprint-sized milestone, decide whether workers are useful, implement, verify, update artifacts, rewrite state, and leave a clear continuation point.
- Worker parallelism is bounded: read-only worker reports are the default, while write-capable workers require explicit intake opt-in, reviewable ownership, lightweight coordination, and main-agent integration.
- Multi-role automation is opt-in and local-only: role work happens in isolated git worktrees, the integrator owns the main checkout, and no generated role may push, fetch, pull, or configure remotes.
- Decoupled human bridge behavior is asynchronous and operationalized. File-only queues work without credentials, while the optional notifier keeps SMS/WhatsApp credentials in a separate service and forces delivery failures to be recorded instead of hand-waved.
- Explicit failure modes are part of the contract. `ACTIVE_WITH_PENDING_USER_INPUT`, `BLOCKED_ON_USER`, `BLOCKED_ON_ENVIRONMENT`, and `CRITICAL_STOP` let the automation keep working around partial blockers while still making hard stops visible.
- Marker-enforced contracts keep the scaffold honest by checking load-bearing prompt, template, schema, and documentation expectations during local validation.
- The generated project is meant to stand on its own. Target repos get local scripts, guardrails, task files, worker conventions, compaction helpers, and validation markers instead of depending on the Diffmogger checkout at runtime.

## Autonomous Case Studies

These are observations from private repositories that ran on Diffmogger. They are included to show the behavior the kit is trying to make repeatable: multi-run compounding, explicit fallback paths, and useful progress without synchronous babysitting.

### Rust quantitative trading engine

- The automation carried a prerequisite chain across runs: deterministic replay catalogs became reviewable, replay failures became data-quality gates, and strategy work had to consume those gates instead of bypassing them.
- Later sprints reused the earlier artifacts for provenance-aware strategy reports and explicit settlement transitions across reserves, inventory, cash, and equity.
- The run history produced regression infrastructure around the artifacts already being generated, including tolerance-aware comparators, stable case keys, retained history, and named baselines.
- Why it matters: Diffmogger helped the agent compound engineering state over multiple sprints instead of producing disconnected patches.

### Signal-intelligence dashboard

- The automation advanced product-facing source intelligence features across adapter contracts, source-quality scoring, conflict handling, evaluation paths, and UI/report surfacing.
- When `tsx` hit sandbox-blocked IPC, the run changed strategy instead of stopping at a blocker note: report scripts were bundled through the existing `esbuild` path and executed under Node.
- The workaround stayed inside the project contract: real adapters remained behind interfaces, fixtures drove verification, and the end-to-end demo script stayed the health check.
- Why it matters: Diffmogger made runtime friction part of the recorded project state, so a blocked tool path became a durable implementation decision rather than a dead end.

### Research-facing web app

- Persistent sandbox permission errors made the Codex CLI worker path unreliable, and Mach-service permissions blocked Playwright-based visual checks.
- The automation degraded gracefully: it used in-session read-only review for bounded critique and JSDOM smoke tests for UI verification when a browser path was unavailable.
- Work still moved across data, dashboard, report, export, and test surfaces while the environment constraint was preserved for later runs.
- A UI rendering bug surfaced through the file-based human inbox, was picked up by a later automation run, and was repaired without a synchronous handoff.
- Why it matters: Diffmogger gave the agent fallback lanes and asynchronous human correction instead of assuming every worker, browser, or reviewer path would be available.

## What Diffmogger Creates

- automation prompt template
- guardrails template
- dynamic task file template
- project context template and optional context-file index
- bootstrap prompt
- autonomy experiment log
- human request, inbox, outbox, and archive templates
- validation scripts
- scaffold script
- lock scripts: `scripts/acquire_codex_lock.sh`, `scripts/release_codex_lock.sh`
- scheduled-run wrapper template: `scripts/run_codex_automation.sh`
- continuous conveyor wrapper: `scripts/run_conveyor_automation.sh`, `scripts/run_conveyor_automation.py`
- local observatory page: `scripts/run_observatory.py`
- local environment repair helper: `scripts/repair_environment.py`
- optional automation signal helper: `scripts/update_automation_signals.py`
- worker helper scripts: `scripts/spawn_worker_agent.sh`, `scripts/summarize_worker_outputs.py`
- optional multi-role prompts: `.agentic/roles/planner.md`, `builder.md`, `hardener.md`, `integrator.md`
- optional multi-role scripts: `scripts/run_role_automation.sh`, `scripts/integrate_role_outputs.py`, `scripts/list_deferred_patches.py`
- optional progress ledger: `docs/MULTI_ROLE_PROGRESS.md`
- state compaction script: `scripts/compact_agent_state.py`
- bundled local notifier service in `services/agentic-notifier/`
- standalone dashboard in `services/agentic-dashboard/`

Repository layout:

```text
docs/                         Kit documentation.
prompts/                      Reusable prompts.
templates/                    Files scaffolded into target projects.
examples/                     Example intake briefs.
schemas/                      Reference JSON Schemas.
scripts/                      Validation, scaffolding, lock, worker, and compaction helpers.
services/agentic-notifier/    Reusable local SMS/WhatsApp bridge.
services/agentic-dashboard/   Standalone local configuration wizard and dashboard.
```

## Quickstart

The dashboard is the easiest path for a fresh project or an existing-project integration. It launches as a native local window, checks prerequisites, walks through project configuration, scaffolds target files, and starts the first Codex bootstrap run.

```bash
git clone https://github.com/harrisonpedrero/diffmogger.git Diffmogger
cd Diffmogger
bash scripts/validate_starter_kit.sh
python3 scripts/run_dashboard.py
```

In the dashboard:

1. Review the prerequisite checklist.
2. Fill in the project intake.
3. Add optional context files such as PDFs, research notes, CSVs, or design docs.
4. Choose the target project directory.
5. Click **Scaffold & Bootstrap**.

### First Review Checklist

After bootstrap or before a demo, use one local review path instead of hunting through separate files:

1. From the Diffmogger starter-kit source, run `bash scripts/validate_starter_kit.sh`.
2. Launch `python3 scripts/run_dashboard.py`, open the target, and use Monitor tab **Run Safety Check**.
3. Click **Export Review Bundle** or, from the repo being reviewed, run `python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review`.
4. Open `/tmp/Diffmogger-review/Diffmogger-observatory.html` and inspect `/tmp/Diffmogger-review/Diffmogger-self-review.md`.
5. Review the first-review readiness, safety status, validation state, active role or queue, known issues, next sprint recommendation, and next-run worker strategy in the observatory, Markdown export, or dashboard **Worker Strategy Controls** panel.

The generated target includes local runtime scripts under `scripts/`. After the first bootstrap produces a runnable baseline, use the target repo's own `scripts/run_codex_automation.sh` for recurring Codex automation.

The dashboard records **Run Safety Check** results in the selected target's gitignored
`target/integration_safety_check.json`; the exported review bundle reads that marker so the
Markdown and HTML review reflect the safety check you just ran.

For the manual CLI path, see `docs/FRESH_PROJECT_SETUP.md`.

Use a virtual environment for Python package work. Homebrew Python may reject system-wide `pip` installs because of externally managed environment protections.

For dashboard details, see `docs/DASHBOARD.md`.

## Dashboard

The standalone dashboard is the primary setup flow for fresh projects and existing-project integrations, and a convenience layer over the same Markdown-first scaffold contract.

It supports:

- a configuration wizard backed by `schemas/project_intake.schema.json`
- fresh-project and existing-project modes
- the full project intake, including constraints, safety rules, automation prohibitions, human bridge choices, worker-agent settings, deliverable definition, and beyond-MVP direction
- optional bounded write-worker settings with a capped count and guidance text
- optional automation signals for recurring local review nudges
- optional multi-role automation mode with fixed role-specific launchd jobs, continuous conveyor scheduling, and local-only git guards
- optional local observatory launch and Markdown self-review export for active signal nudges, conveyor state, active role runs, queued patches, validation state, the latest recorded integration-safety result, and recent automation timeline
- a Monitor tab **Run Safety Check** action that runs `scripts/check_integration_safety.py` and shows the local result in the dashboard log
- **Worker Strategy Controls** that mirror the observatory's next-run recommendation, can launch a bounded read-only report, explicitly owned write worker, or local integrator lane when appropriate, and load the latest consolidated worker summary
- optional context-file import into target `docs/context/`
- generated `docs/PROJECT_CONTEXT.md`
- a single `Scaffold & Bootstrap` pipeline
- gated `Start Scheduled Automation` and `Pause Scheduled Automation` launchd controls after bootstrap completes
- `Open Diffmogger Project` for reopening a target with existing dashboard state or launchd automation
- prerequisite checks for Python, Tkinter, Codex CLI, shell tools, permissions, and optional notifier health
- a compact automation monitor for selected Markdown files
- file-only messages to the next automation run when SMS/WhatsApp is disabled or unavailable

For existing projects, select the existing repo directory and choose existing-project mode in the wizard. Frame the intake as an integration task: describe the current stack, the existing commands to preserve, and the first meaningful integrated deliverable. Diffmogger adds or updates managed sections in existing `AGENTS.md` and `docs/DEVELOPMENT.md` instead of replacing those files outright.

The dashboard stores UI state in the selected target repo at `.agentic/dashboard_state.json`, so closing and reopening the dashboard does not require repeating setup.

## Validation

Run the full local validation:

```bash
bash scripts/validate_starter_kit.sh
```

Validation is intentionally marker- and smoke-test based. It checks that load-bearing files, markers, schemas, scaffold paths, and notifier tests are present and runnable. It does not prove semantic correctness, production safety, or that a generated automation will make good decisions.
It also exercises the optional multi-role scaffold path, integrator remote guards, lock refusal, stale-patch deferral classification, and a small local integration smoke target.

Run a scaffold smoke test:

```bash
python3 scripts/scaffold_project_docs.py \
  --intake examples/generic-web-app/project_intake.md \
  --target /tmp/Diffmogger-smoke \
  --force

python3 scripts/check_required_files.py /tmp/Diffmogger-smoke

python3 scripts/check_integration_safety.py
```

The same integration-safety verifier is also available in the dashboard Monitor tab through **Run Safety Check**. The observatory and Markdown self-review export surface the latest recorded integration-safety result from task-state checks.

Run notifier tests:

```bash
cd services/agentic-notifier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
```

Tests use fake Twilio clients and dry-run paths. They do not require real credentials, ngrok, or real SMS.

## Worker Agents

Worker agents are bounded helpers. The main agent remains the integrator.

Use workers for independent review, architecture checks, test-gap analysis, risk review, product polish review, or isolated prototypes. Prefer read-only reports first.

Write-capable workers are disabled unless a generated target intake explicitly enables:

```json
{
  "write_worker_agents_allowed": true,
  "max_write_worker_count": 10,
  "write_worker_guidance": "Use the most parallelism the task can safely absorb while keeping ownership reviewable."
}
```

The scaffold caps write workers at 10. Generated prompts ask the main agent to choose a worker strategy and parallelism budget each run, use as much parallelism as the task can safely absorb, keep coordination lightweight, review worker diffs, integrate, verify, and update task state. Integration-only runs with no workers are valid when faster or safer.

Outputs go under:

```text
target/agent_runs/<run_id>/worker_<role>.md
```

Optional helpers:

```bash
export CODEX_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"

bash scripts/spawn_worker_agent.sh \
  --target ../my-project \
  --run-id "$CODEX_RUN_ID" \
  --role tests \
  --prompt "Inspect the current sprint for test gaps and write a concise report."

python3 scripts/summarize_worker_outputs.py ../my-project --run-id "$CODEX_RUN_ID"
```

The helpers use `codex exec --disable plugins --ephemeral --dangerously-bypass-approvals-and-sandbox` for nested child workers, avoid network, tell workers not to spawn more workers, and fail gracefully if the Codex CLI is unavailable. Generated scheduled wrappers also grant the parent run access to `$HOME/.codex` so nested Codex CLI workers can authenticate and start inside the parent sandbox. The scary-looking bypass is for the nested child only; the scheduled parent remains the outer sandbox boundary. These helpers are optional convenience scripts, not mandatory magic.

When write workers are enabled in a target, the helper requires explicit write mode and an ownership scope:

```bash
bash scripts/spawn_worker_agent.sh \
  --mode write \
  --target ../my-project \
  --run-id "$CODEX_RUN_ID" \
  --role feature_a \
  --ownership "src/feature-a/** and tests/feature-a/** only" \
  --prompt "Implement the assigned slice and report changed files/checks."
```

Codex CLI must be available for `codex exec` helpers:

```bash
command -v codex
```

## Multi-Role Automation

Multi-role automation is an advanced, opt-in mode for target projects that need more throughput than one scheduled lane. The default remains the single-lane `scripts/run_codex_automation.sh` schedule.

Enable it in intake:

```json
{
  "multi_role_automations_allowed": true,
  "automation_role_profile": "planner_builder_hardener_integrator",
  "automation_checkpoint_commits": true,
  "multi_role_base_cadence_minutes": 30,
  "automation_schedule_strategy": "continuous_conveyor",
  "multi_role_allow_remotes": false,
  "automation_signals_enabled": true
}
```

Generated targets then receive role prompts under `.agentic/roles/`, helper scripts under `scripts/`, and `docs/MULTI_ROLE_PROGRESS.md`. The dashboard can write four fixed launchd jobs:

- planner: hourly at `:00`
- builder: `:10` and `:40`
- hardener: `:20` and `:50`
- integrator: `:25` and `:55`

Planner, builder, and hardener start from the latest main `HEAD` in isolated worktrees and queue patches. The integrator owns the main checkout, checkpoints dirty local changes as automation-authored local commits, runs `git apply --check`, batches verification, falls back to individual verification on failure, commits accepted patches locally, and updates task/progress docs.

Alternatively, continuous conveyor scheduling writes one LaunchAgent that runs `scripts/run_conveyor_automation.sh`, records state under `target/automation_conveyor_state.json`, and chooses the next runnable lane as soon as the previous lane exits. It prioritizes queued integration first, fast-follow replanning after a planner patch is newly deferred or a planner deferral is resolved, due planning second, builder momentum by default, and one hardener pass after integrated builder work. Conveyor state includes the active role run and a small future decision queue; `scripts/run_observatory.py` also reads `target/automation_signals.json` so the dashboard-launched observatory can show what is running now, what signal nudges are due, and what is likely next. Use `python3 scripts/list_deferred_patches.py . --markdown` for a grouped local triage view of deferred queue manifests.

Multi-role mode is local-only. Role prompts and scripts prohibit pushes, fetches, pulls, remote configuration, upstream tracking, and remote-affecting git commands. Scripts refuse to run with configured remotes unless `MULTI_ROLE_ALLOW_REMOTES=1` is set, and the integrator refuses executable git hooks containing `git push`.

## Human Bridge

Diffmogger supports two modes.

Mode A: manual file-only bridge.

- Target automation writes requests to `docs/HUMAN_REQUESTS.md`.
- The human manually replies in `docs/HUMAN_INBOX.md`.
- The next automation run consumes handled replies, removes them from the inbox, and archives concise notes in `docs/HUMAN_RESPONSES_ARCHIVE.md`.

This mode needs no SMS, no webhook, and no credentials. It is a valid long-term mode.

In file-only mode, status or summary requests are satisfied locally in Markdown or app artifacts. The automation should not try to send SMS/WhatsApp unless the project is explicitly switched to notifier mode.

Mode B: local notifier API.

- Target project calls `POST http://127.0.0.1:8765/api/notify`.
- `services/agentic-notifier` owns Twilio credentials.
- Twilio inbound webhook goes to `http://127.0.0.1:8787/twilio/inbound` through ngrok.
- The notifier writes replies to target `docs/HUMAN_INBOX.md`.
- Target automation resolves and archives handled replies.

Notifier provider failures return structured JSON and write `PROVIDER_SEND_FAILED` to `docs/HUMAN_OUTBOX.md` when target paths are configured. If the notifier API itself is unreachable, target automations should record `NOTIFIER_UNREACHABLE` and keep working where possible.

## Notifier Setup

Use a virtual environment. Do not install packages into Homebrew/system Python; a venv avoids externally managed environment errors on modern macOS Python setups.

```bash
cd services/agentic-notifier

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
python -m pytest
python -m agentic_notifier.run_service
```

Real Twilio values belong only in `services/agentic-notifier/.env`. Keep secrets out of target project docs, prompts, task files, and examples.
The example config starts with `DRY_RUN=true`; change it only when you intentionally want a real outbound send.

Expose only the webhook port with ngrok:

```bash
ngrok http 8787
```

Do not expose the local notify API unless you know why.

Practical SMS notes:

- `TWILIO_MESSAGING_SERVICE_SID` is supported.
- If set, the notifier sends with `messaging_service_sid` and does not pass `from_`.
- If absent, the notifier falls back to `TWILIO_FROM`.
- SMS via +1 10DLC may require A2P 10DLC approval.
- Twilio error `30034` usually means the sender or campaign is not registered or ready.
- WhatsApp sandbox can be used as an alternative if configured.
- Diffmogger does not require SMS to work.

## Lock Files And State Compaction

Short cadences need lock behavior. Generated target repos include `scripts/run_codex_automation.sh`, which wraps lock acquire/release around `codex exec` and grants `$HOME/.codex` access for nested Codex CLI startup:

```bash
bash scripts/run_codex_automation.sh
```

Default path:

```text
target/codex_automation.lock
```

The wrapper sets `CODEX_LOCK_ALREADY_ACQUIRED=true` so the automation prompt does not acquire a second lock. Set `TARGET=/absolute/path/to/target-project` when running from outside the target repo. The lock includes PID, timestamp, run id, host, stale threshold, and context. Stale detection defaults to 4 hours and can be tuned with `CODEX_LOCK_STALE_SECONDS`.

Lock scripts reduce overlapping-run risk. They do not remove the need to review diffs.

Long-running Markdown state can become context bloat. Diffmogger includes:

```bash
python3 scripts/compact_agent_state.py --dry-run ../my-project
python3 scripts/compact_agent_state.py ../my-project
```

It supports:

- `docs/HUMAN_INBOX.md`
- `docs/HUMAN_REQUESTS.md`
- `docs/HUMAN_OUTBOX.md`
- `docs/HUMAN_RESPONSES_ARCHIVE.md`
- `docs/CODEX_AUTOMATION_TASKS.md`
- `docs/MULTI_ROLE_PROGRESS.md`
- `docs/AUTONOMY_EXPERIMENT_LOG.md`
- `docs/DAILY_AUTOMATION_REVIEW.md`

The script preserves unresolved human requests and deferred multi-role manifests, keeps recent useful state, summarizes transient multi-role artifacts before cleanup, and archives concise rollups instead of silently deleting active data. Review the diff after compaction.

## Safety Defaults

- no secrets in prompts, task files, inboxes, or examples
- target automations should not read `.env`
- no spending, public publishing, deployment, messaging real users, or external side effects without approval
- multi-role automation is local-only by default and must not push, fetch, pull, configure remotes, or set upstream tracking
- integrations mocked, optional, or dry-run by default
- human bridge credentials stay in the notifier service, not product repos
- review diffs before trusting autonomous changes
- increase autonomy only after early runs produce useful, verifiable changes

## What It Is Not

- not production-ready autonomy infrastructure
- not enterprise autonomy infrastructure
- not a secret manager
- not a replacement for human review
- not a guarantee that agents make good decisions
- not a way to bypass platform rules
- not a deployment or incident-response system
- not appropriate for unsafe real-world side effects without review

## Known Limitations

- alpha and local-first
- Codex behavior can vary
- scheduled runs still need review
- Twilio/A2P setup can block SMS
- JSON schemas may be reference-only where runtime enforcement is not wired yet
- state compaction should be reviewed
- worker agents can create noise if overused
- Diffmogger has not been validated across other coding models or non-Codex agent runtimes
- no RBAC, formal audit pipeline, SLO story, or multi-user governance model

## Roadmap

- stronger schema/runtime alignment
- better worker output consolidation
- better state compaction
- example target projects
- richer case studies
- local dashboard for automation state
- more notifier channels such as Slack, email, and Discord

## Example Validation

Diffmogger includes fictional example intakes that exercise the generated automation workflow without binding the kit to one product domain.

Use `examples/generic-web-app/` for a straightforward product brief and `examples/trendlab-signal-intelligence/` for a more involved signal-intelligence brief with fixture data, scoring, reports, and human-in-the-loop requests.

## Schemas And Runtime

`schemas/` contains reference JSON Schemas for intake, automation state, and human bridge payloads. For the notifier API, the runtime Pydantic model in `services/agentic-notifier/agentic_notifier/models.py` is authoritative. A notifier test checks `schemas/human_request.schema.json` against that model so field drift is visible.

Known gap: not every schema is fully enforced at runtime yet. The roadmap includes stronger schema/runtime alignment.

## License

Diffmogger is released under the MIT License. See `LICENSE`.
