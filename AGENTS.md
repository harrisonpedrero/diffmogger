# AGENTS.md

This repository is Diffmogger: a starter kit for high-agency Codex automations. It is a reusable template, playbook implementation, and local notifier service, not a product-specific app.

## Work Expectations

- Keep this kit generic and target-project agnostic. Do not introduce product-specific assumptions into core docs, prompts, scripts, schemas, or services.
- Keep examples self-contained, fictional, and clearly reusable.
- Prefer concise docs, concrete templates, and runnable validation.
- Keep prompt behavior durable and project-agnostic. Put changing project state in typed SQLite runtime state; task-file Markdown is a generated prompt/handoff projection, not the authority.
- Treat the typed automation activity runtime as the runtime control plane: execution DAG nodes/edges, default work item, repo capability manifest, transitions, validation receipts, blockers, and next actions live in SQLite. Markdown and JSON are projections or authored inputs.
- Treat Diffmogger as a work generator, not a blocker detector. If tickets remain, the scheduler must always produce repair, setup, mock, fixture, defer, split, reframe, review, documentation, or alternate-ticket work.
- Treat blockers as planning inputs, not automation stop states. `BLOCKED_ON_USER` and `BLOCKED_ON_ENVIRONMENT` preserve the status model but must not pause automation while any independent or unblocker work can continue.
- Convert validation failures into repair/setup/harness/mock/defer DAG work: required check failures create repair work, missing tools create setup/harness work, external services create mock/local-fixture/defer work, browser/MCP failures create alternate validation or deferred QA work, and repeated failures create split/reframe/planner work. Human input becomes pending input records while automation continues independent work.
- Remove normal fallback language that tells agents to stop on a blocker. The fallback is to create unblocker work unless all tickets are done with evidence.
- In generated multi-role targets, ticket-state changes from planner/builder/hardener worktrees must be staged through typed runtime actions and reconciled by the integrator; do not make isolated worktrees hand-edit projections or directly mutate canonical ticket state.
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

## Source Repo Guidance

This checkout is the Diffmogger source kit. Keep its public behavior, generated templates, examples, and local services reusable across arbitrary target projects.

- Public-facing behavior should describe installing or scaffolding Diffmogger into other repos.
- Root docs, prompts, templates, scripts, schemas, and services must stay reusable across target projects.
- Template changes should keep generated target repos decoupled from this source checkout at runtime.
- When auditing generated behavior, scaffold into a temporary target such as `/tmp/Diffmogger-smoke` and inspect that target rather than treating this repo root as the generated project.
