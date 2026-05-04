# Pre-Release Checklist

Use this before the first public alpha push and before future release tags.

This checklist records the release checks for the current public-alpha pass. It should be re-run before future releases or after material changes. A completed checkbox means the item passed for the recorded review, not that it is continuously guaranteed forever.

- [x] `LICENSE` exists.
- [x] README clone URL checked.
- [x] Validation passes with `bash scripts/validate_starter_kit.sh`.
- [x] Integration safety defaults pass with `python3 scripts/check_integration_safety.py`.
- [x] Notifier tests pass in a venv.
- [x] GitHub Actions workflow present.
- [x] No secrets or PII in repo.
- [x] `.env` ignored.
- [x] Public positioning is honest alpha.
- [x] Known limitations documented.
- [x] No real Twilio credentials.
- [x] No personal phone numbers.
- [x] No ngrok URLs except placeholders.
- [x] No local macOS user-home absolute paths.
- [x] No stale workspace, personal-path, or product-specific positioning in Diffmogger README.

The secret/PII grep can match placeholder variable names, placeholder phone numbers, placeholder ngrok domains, or ordinary words containing `sk-`. Treat those as review prompts; remove any real credential, live URL, personal phone number, or local machine path before release.
