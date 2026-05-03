# AGENTS.md

This repository is Diffmogger: a starter kit for high-agency Codex automations. It is a reusable template, playbook implementation, and local notifier service, not a product-specific app.

## Work Expectations

- Keep this kit generic and target-project agnostic. Do not introduce product-specific assumptions into core docs, prompts, scripts, schemas, or services.
- Keep examples self-contained, fictional, and clearly reusable.
- Keep `services/agentic-notifier/` reusable and target-project agnostic. Target projects should call its API or read/write handoff files; they should not import notifier code.
- Prefer concise docs, concrete templates, and runnable validation.
- Keep prompt behavior durable and project-agnostic. Put changing project state in task-file templates, not in the automation prompt.
- Preserve the status model: `ACTIVE`, `ACTIVE_WITH_PENDING_USER_INPUT`, `BLOCKED_ON_USER`, `BLOCKED_ON_ENVIRONMENT`, `CRITICAL_STOP`.
- Keep secrets out of examples and docs. Use placeholders only.

## Validation

After editing the kit, run:

```bash
bash scripts/validate_starter_kit.sh
```

If scaffolding behavior changes, also run:

```bash
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target /tmp/Diffmogger-smoke --force
python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
```

## Style

- Markdown should be practical and skimmable.
- Avoid copying long passages from reference projects or external docs.
- Explain when code or patterns are adapted from references.
- Favor standard-library Python for scripts.
- Public docs should be direct, command-oriented, and low-fluff.

<!-- DIFFMOGGER:START AGENTS -->
## Diffmogger Automation

This block is managed by Diffmogger. Keep project-owned instructions outside this block.

This repo is `Diffmogger Self Improvement`.

Project mode: Existing project integration

### Mission

Evolve Diffmogger into a more capable self-improving system for recurring AI engineering work.


The automation should treat Diffmogger itself as both the product and the lab: it may inspect how the automation is operating, identify bottlenecks, invent better workflows, improve prompts, improve dashboard controls, improve generated target-project scaffolds, strengthen validation, revise docs, and change its own recurring automation process when doing so would improve long-term autonomous progress.


The goal is not merely to maintain the current architecture. The goal is to discover and implement better patterns for local-first, reviewable, high-agency Codex automation.


The automation should optimize for improvements that reduce human babysitting, increase accepted and integrated patches, avoid no-progress loops, make validation and environment failures more self-repairing, improve observability of what is running now and what is queued next, strengthen generated-target reliability, and make demos easier to understand without becoming product-specific.


The operating bias should favor momentum. Guardrails should prevent irreversible, unsafe, secret-touching, remote-touching, or unreviewable behavior; they should not prevent ambitious local experimentation, large plans, parallel exploration, or recoverable breakage. Prefer making reviewable progress and repairing mistakes over over-constraining the system into tiny changes.


The automation has permission to propose and implement new directions when they are consistent with Diffmogger's core principles:


- local-first
- Markdown-first durable state
- git-diffable and reviewable changes
- explicit guardrails
- strong validation
- human-inspectable progress
- autonomous momentum without unsafe side effects
- generated target projects that remain generic and decoupled from the Diffmogger source repo


Specific improvement areas may include dashboard UX, the observatory, generated prompts, worker orchestration, multi-role automation, validation, docs, examples, human bridge behavior, state compaction, progress tracking, or entirely new mechanisms the automation discovers. These are examples and priority seeds, not a fixed roadmap.

Target user: The Diffmogger author and technically comfortable solo builders who inspect diffs, run local automations, and want recurring Codex work to compound without constant babysitting.


They value speed, autonomy, reviewability, local-first operation, useful demos, and strong guardrails.

Integrate Diffmogger into the selected existing project. Preserve the existing architecture, package manager, tests, docs, and project-specific instructions unless the intake explicitly asks for a scoped change. Treat the desired first demo as an integrated increment inside the current codebase, not a greenfield rewrite.

### Read Before Meaningful Work

```text
docs/CODEX_AUTOMATION_TASKS.md
docs/CODEX_AUTOMATION_GUARDRAILS.md
.agentic/automation_prompt.md
```

If human bridge files exist, also read:

```text
docs/HUMAN_REQUESTS.md
docs/HUMAN_INBOX.md
docs/HUMAN_OUTBOX.md
docs/HUMAN_RESPONSES_ARCHIVE.md
```

### Working Rules

- Build the product; do not only write plans.
- Treat MVP as an early milestone, not the finish line.
- Use safe local defaults, fixtures, mocks, or seed data unless the task explicitly enables external integration.
- Do not read `.env` files or handle secrets.
- Do not spend money, deploy publicly, or trigger real-world side effects without explicit approval.
- Use worker agents only for bounded work and record their outputs.
- Write-capable worker agents allowed: true; max write workers: 10.
- Use read-only worker reports for exploration. When write-capable workers are enabled, use the most parallelism the task can safely absorb while keeping ownership reviewable and main-agent integration explicit.
- Multi-role automations allowed: true; role profile: planner_builder_hardener_integrator.
- Process human inbox messages, including freeform commands.
- If the human asks for a summary, status update, explanation, or report, satisfy it locally in Markdown or app artifacts.
- Do not use SMS, WhatsApp, Twilio, or notifier APIs unless the human explicitly changes bridge mode.
- Process handled human inbox messages only after completing or intentionally deferring the requested action, then archive concise notes.
- Record `Codex CLI worker decision: USE / SKIP / UNAVAILABLE` every automation run.
- Update `docs/CODEX_AUTOMATION_TASKS.md` at the end of every automation run.

### Verification

Preferred commands:

```text
- bash scripts/validate_starter_kit.sh
- python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target /tmp/Diffmogger-smoke --force
- python3 scripts/check_required_files.py /tmp/Diffmogger-smoke
- python3 scripts/run_dashboard.py --smoke-check
- python3 scripts/run_observatory.py --target . --once --output /tmp/Diffmogger-observatory.html
- python3 -m py_compile scripts/run_observatory.py scripts/run_conveyor_automation.py scripts/integrate_role_outputs.py services/agentic-dashboard/agentic_dashboard/app.py
- python3 -m pytest services/agentic-notifier
```

Use the commands that actually exist. Do not claim checks passed unless they ran.
<!-- DIFFMOGGER:END AGENTS -->
