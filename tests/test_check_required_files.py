from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_SCRIPT = ROOT / "scripts" / "scaffold_project_docs.py"
CHECK_SCRIPT = ROOT / "scripts" / "check_required_files.py"
GENERIC_INTAKE = ROOT / "examples" / "generic-web-app" / "project_intake.md"
TRENDLAB_INTAKE = ROOT / "examples" / "trendlab-signal-intelligence" / "project_intake.md"


class RequiredFilesCheckTests(unittest.TestCase):
    def scaffold_target(self, target: Path, intake: Path = GENERIC_INTAKE) -> None:
        subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD_SCRIPT),
                "--intake",
                str(intake),
                "--target",
                str(target),
            ],
            check=True,
            text=True,
            capture_output=True,
        )

    def run_check(self, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CHECK_SCRIPT),
                "--human-bridge-mode",
                "file_only",
                str(target),
            ],
            text=True,
            capture_output=True,
        )

    def test_scaffolded_target_keeps_first_review_checklist_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)

            result = self.run_check(target)

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_continuous_scaffold_uses_intake_specific_horizons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            prompt = (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8")
            task = (target / "docs" / "CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")

            self.assertIn("H2 Local-first demo", prompt)
            self.assertIn("weekly board", prompt)
            self.assertIn("recurring review capsules", prompt)
            self.assertIn("## Improvement Backlog", task)
            self.assertNotIn("H2 Offline/local demo", prompt)

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target, TRENDLAB_INTAKE)
            prompt = (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8")

            self.assertIn("scored signals", prompt)
            self.assertIn("generated brief", prompt)
            self.assertIn("source-quality attribution", prompt)

    def test_ticket_campaign_scaffold_uses_ticket_phases_without_product_roadmap_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.NamedTemporaryFile("w", suffix=".json") as intake:
            target = Path(tmp)
            intake.write(
                """
{
  "project_name": "Ticket Campaign Smoke",
  "product_goal": "Resolve a bounded set of local tickets.",
  "target_user": "Maintainer reviewing local patches.",
  "desired_first_demo": "All listed tickets completed or blocked with evidence.",
  "human_bridge_enabled": false,
  "human_bridge_mode": "disabled",
  "automation_run_mode": "ticket_campaign",
  "verification_commands": ["npm test"]
}
""".strip()
            )
            intake.flush()

            self.scaffold_target(target, Path(intake.name))
            prompt = (target / ".agentic" / "automation_prompt.md").read_text(encoding="utf-8")
            task = (target / "docs" / "CODEX_AUTOMATION_TASKS.md").read_text(encoding="utf-8")
            combined = prompt + "\n" + task

            self.assertIn("T1 Ticket-run readiness", combined)
            self.assertIn("T4 Completion report and stop", combined)
            self.assertIn("## Deferred / Follow-Up Tickets", task)
            for forbidden in ["MVP", "Beyond MVP", "Ambitious extensions"]:
                self.assertNotIn(forbidden, combined)

            result = subprocess.run(
                [
                    sys.executable,
                    str(CHECK_SCRIPT),
                    "--human-bridge-mode",
                    "disabled",
                    "--ticket-campaign-enabled",
                    str(target),
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_missing_development_file_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            (target / "docs" / "DEVELOPMENT.md").unlink()

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("docs/DEVELOPMENT.md: missing", result.stderr)

    def test_development_checklist_marker_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            development = target / "docs" / "DEVELOPMENT.md"
            development.write_text(
                development.read_text(encoding="utf-8").replace(
                    "Run Safety Check",
                    "Run local checks",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("docs/DEVELOPMENT.md: missing marker 'Run Safety Check'", result.stderr)

    def test_development_review_bundle_command_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            development = target / "docs" / "DEVELOPMENT.md"
            development.write_text(
                development.read_text(encoding="utf-8").replace(
                    "--review-dir /tmp/Diffmogger-review",
                    "--review-output /tmp/Diffmogger-self-review.md",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "docs/DEVELOPMENT.md: missing marker 'python3 scripts/run_observatory.py --target . --review-dir /tmp/Diffmogger-review'",
                result.stderr,
            )

    def test_observatory_first_review_marker_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            observatory = target / "scripts" / "run_observatory.py"
            observatory.write_text(
                observatory.read_text(encoding="utf-8").replace(
                    "First Review Readiness",
                    "Review Readiness",
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "scripts/run_observatory.py: missing marker 'First Review Readiness'",
                result.stderr,
            )

    def test_scaffolded_runner_uses_target_local_lock_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            runner = target / "scripts" / "run_codex_automation.sh"
            runner_text = runner.read_text(encoding="utf-8")

            self.assertIn("CODEX_LOCK_CONTEXT", runner_text)
            self.assertIn('target_name="$(basename "$TARGET")"', runner_text)
            self.assertNotIn("Diffmogger Self Improvement scheduled sprint", runner_text)

            result = self.run_check(target)

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)

    def test_self_run_lock_context_regression_fails_required_files_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.scaffold_target(target)
            runner = target / "scripts" / "run_codex_automation.sh"
            runner.write_text(
                runner.read_text(encoding="utf-8").replace(
                    'bash scripts/acquire_codex_lock.sh "$lock_context" || exit 0',
                    'bash scripts/acquire_codex_lock.sh "Diffmogger Self Improvement scheduled sprint" || exit 0',
                ),
                encoding="utf-8",
            )

            result = self.run_check(target)

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "scripts/run_codex_automation.sh: forbidden self-run marker",
                result.stderr,
            )


if __name__ == "__main__":
    unittest.main()
