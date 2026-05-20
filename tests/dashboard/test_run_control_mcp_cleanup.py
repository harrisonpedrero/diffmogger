from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.dashboard.commands import run_control


class RunControlMcpCleanupTests(unittest.TestCase):
    def test_owned_mcp_cleanup_keeps_unrelated_processes_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.mkdir()
            table = {
                100: {"pid": 100, "ppid": 1, "pgid": 100, "command": f"python run_conveyor_automation.py --target {target}"},
                101: {"pid": 101, "ppid": 100, "pgid": 100, "command": "npx -y @upstash/context7-mcp"},
                102: {"pid": 102, "ppid": 999, "pgid": 102, "command": f"bash {target}/.diffmogger/scripts/run_playwright_mcp.sh"},
                103: {"pid": 103, "ppid": 999, "pgid": 103, "command": "npx -y @upstash/context7-mcp"},
                104: {"pid": 104, "ppid": 105, "pgid": 104, "command": "node playwright-mcp"},
                105: {"pid": 105, "ppid": 1, "pgid": 105, "command": "codex exec user task"},
            }
            live = {"roots": [100], "pids": [100]}
            original_process_is_alive = run_control.process_is_alive
            try:
                run_control.process_is_alive = lambda pid: True  # type: ignore[assignment]
                pids = run_control.owned_mcp_cleanup_pids(target, live, table)
            finally:
                run_control.process_is_alive = original_process_is_alive  # type: ignore[assignment]

        self.assertEqual([101, 102], pids)


if __name__ == "__main__":
    unittest.main()
