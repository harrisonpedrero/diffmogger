# Contributing

Diffmogger is alpha, local-first workflow scaffolding. Contributions should keep the kit generic, testable, and safe to inspect in a public repo.

Before opening a PR:

- Run `bash scripts/validate_starter_kit.sh`.
- If touching `services/agentic-notifier/`, use a venv and run `python -m pytest` from that directory.
- Do not commit secrets, real Apprise URLs/tokens, personal contact details, live tunnel URLs, or local machine paths.
- Do not weaken guardrails, status markers, or validation markers without explaining why.
- Keep examples local-first, dry-run friendly, and mockable.
- Open issues and PRs with clear reproduction steps, rationale, or the workflow gap being addressed.

Avoid adding product-specific assumptions to core docs, prompts, scripts, schemas, or services. Keep product-flavored material inside self-contained examples.
