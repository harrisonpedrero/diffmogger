from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKER_HELPER = ROOT / "scripts" / "target" / "spawn_worker_agent.sh"


class SpawnWorkerAgentTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
