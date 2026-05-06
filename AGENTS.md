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

## Source Repo Guidance

This checkout is the Diffmogger source kit, not a generated target project. Do not assume root-level target automation files such as `.agentic/automation_prompt.md`, `docs/CODEX_AUTOMATION_TASKS.md`, `docs/HUMAN_INBOX.md`, or `docs/HUMAN_OUTBOX.md` exist here. Those files live under `templates/` and are scaffolded into target projects.

- Public-facing behavior should describe installing or scaffolding Diffmogger into other repos.
- Root docs, prompts, templates, scripts, schemas, and services must stay reusable across target projects.
- Template changes should keep generated target repos decoupled from this source checkout at runtime.
- When auditing generated behavior, scaffold into a temporary target such as `/tmp/Diffmogger-smoke` and inspect that target rather than treating this repo root as the generated project.
- Do not add self-improvement, self-run, or project-specific managed automation blocks to this root `AGENTS.md`; keep recurring target-project instructions in `templates/AGENTS.md` and related templates.
