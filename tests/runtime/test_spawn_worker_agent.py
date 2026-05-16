from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[2]
WORKER_HELPER = ROOT / "scripts" / "target" / "spawn_worker_agent.sh"


class SpawnWorkerAgentTests(unittest.TestCase):
    def write_codex_stub(self, root: Path) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "codex"
        stub.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
prompt="${@: -1}"
report_path="$(printf '%s' "$prompt" | awk -F'Output report: ' '/Output report: / {print $2; exit}')"
if [[ -z "$report_path" ]]; then
  echo "missing output report" >&2
  exit 3
fi
mkdir -p "$(dirname "$report_path")"
cat >"$report_path" <<EOF
# Worker Report

- status: PASS

## Findings

- Stub worker wrote the requested report.
EOF
""",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return bin_dir

    def test_write_mode_rejects_whitespace_only_ownership_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            result = subprocess.run(
                [
                    "bash",
                    str(WORKER_HELPER),
                    "--target",
                    str(target),
                    "--run-id",
                    "worker-scope-test",
                    "--mode",
                    "write",
                    "--ownership",
                    " \n\t ",
                    "--prompt",
                    "Implement one bounded validation improvement.",
                ],
                text=True,
                capture_output=True,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("--mode write requires --ownership", result.stderr)
            self.assertFalse((target / "target" / "agent_runs").exists())

    def test_explicit_report_path_writes_exact_requested_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            report_path = root / "reports" / "custom-worker-report.md"
            bin_dir = self.write_codex_stub(root)
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}

            result = subprocess.run(
                [
                    "bash",
                    str(WORKER_HELPER),
                    "--target",
                    str(target),
                    "--run-id",
                    "report-path-test",
                    "--role",
                    "builder-ticket-002",
                    "--read-only",
                    "--report-path",
                    str(report_path),
                    "--prompt",
                    "Write the report exactly where requested.",
                ],
                text=True,
                capture_output=True,
                env=env,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(report_path.exists())
            self.assertIn(f"WORKER_REPORT path={report_path}", result.stdout)
            self.assertTrue((report_path.parent / "custom-worker-report.raw.log").exists())
            self.assertFalse((target / "target" / "agent_runs").exists())


if __name__ == "__main__":
    unittest.main()
