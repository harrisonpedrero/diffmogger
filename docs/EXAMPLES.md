# Examples

The `examples/` directory contains intake briefs and expected generated files.

## Generic Web App

Use `examples/generic-web-app/project_intake.md` to test the kit against a normal product idea. It exercises project goals, target users, stack preferences, first demo, verification, human bridge, and worker-agent settings.

## SignalForge-Inspired

Use `examples/signalforge-inspired/project_intake.md` to see how the reference product pattern becomes generic. It keeps the useful workflow ideas while avoiding project-specific crypto assumptions in the kit itself.

## Smoke Test

```bash
python3 scripts/scaffold_project_docs.py --intake examples/generic-web-app/project_intake.md --target /tmp/Diffmogger-example --force
python3 scripts/check_required_files.py /tmp/Diffmogger-example
```
