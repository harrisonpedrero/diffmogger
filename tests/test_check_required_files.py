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


class RequiredFilesCheckTests(unittest.TestCase):
    def scaffold_target(self, target: Path) -> None:
        subprocess.run(
            [
                sys.executable,
                str(SCAFFOLD_SCRIPT),
                "--intake",
                str(GENERIC_INTAKE),
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


if __name__ == "__main__":
    unittest.main()
