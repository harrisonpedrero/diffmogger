from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WATCHDOG = ROOT / "scripts" / "runtime" / "run_process_watchdog.py"


class RunProcessWatchdogTests(unittest.TestCase):
    def run_watchdog(
        self,
        tmp_path: Path,
        command: list[str],
        *,
        idle_timeout_seconds: str = "1",
        progress_paths: list[Path] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        stdout = tmp_path / "stdout.log"
        stderr = tmp_path / "stderr.log"
        status_path = tmp_path / "watchdog.json"
        args = [
            sys.executable,
            str(WATCHDOG),
            "--stdout-file",
            str(stdout),
            "--stderr-file",
            str(stderr),
            "--status-file",
            str(status_path),
            "--timeout-seconds",
            "30",
            "--idle-timeout-seconds",
            idle_timeout_seconds,
            "--termination-grace-seconds",
            "0",
        ]
        for path in progress_paths or []:
            args.extend(["--progress-path", str(path)])
        args.extend(["--", *command])
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
        status = json.loads(status_path.read_text(encoding="utf-8"))
        return result, status

    def test_silent_process_is_stopped_by_idle_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result, status = self.run_watchdog(
                tmp_path,
                [sys.executable, "-c", "import time; time.sleep(60)"],
            )

        self.assertEqual(124, result.returncode, result.stdout + result.stderr)
        self.assertTrue(status["idle_timed_out"])
        self.assertFalse(status["timed_out"])
        self.assertEqual("idle_timeout", status["termination_reason"])
        self.assertEqual(124, status["exit_code"])

    def test_stdout_progress_resets_idle_timeout(self) -> None:
        script = textwrap.dedent(
            """
            import time

            for index in range(4):
                print(f"tick {index}", flush=True)
                time.sleep(0.35)
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result, status = self.run_watchdog(
                tmp_path,
                [sys.executable, "-c", script],
                idle_timeout_seconds="2",
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(status["idle_timed_out"])
        self.assertEqual("progress_path_changed", status["last_progress_reason"])

    def test_watched_directory_progress_resets_idle_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            watched = tmp_path / "worktree"
            watched.mkdir()
            script = textwrap.dedent(
                """
                import sys
                import time
                from pathlib import Path

                path = Path(sys.argv[1]) / "heartbeat.txt"
                for index in range(4):
                    path.write_text(str(index), encoding="utf-8")
                    time.sleep(0.35)
                """
            )
            result, status = self.run_watchdog(
                tmp_path,
                [sys.executable, "-c", script, str(watched)],
                idle_timeout_seconds="2",
                progress_paths=[watched],
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(status["idle_timed_out"])
        self.assertEqual("progress_path_changed", status["last_progress_reason"])


if __name__ == "__main__":
    unittest.main()
