from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.runtime.preflight import build_parallelization_preflight_report
from diffmogger.runtime.state_store import write_ticket_run_state


def write_text(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_intake(root: Path, *, write_workers: bool = True) -> None:
    write_text(
        root,
        ".agentic/project_intake.json",
        json.dumps(
            {
                "project_name": "Preflight Fixture",
                "product_goal": "Exercise first-run DAG readiness.",
                "target_user": "Automation maintainers",
                "desired_first_demo": "A ready DAG preflight report.",
                "worker_agents_allowed": True,
                "write_worker_agents_allowed": write_workers,
                "max_write_worker_count": 3 if write_workers else 0,
                "parallel_execution_mode": "aggressive",
                "symbol_graph_languages": ["python", "typescript", "javascript", "rust", "go", "java"],
            },
            sort_keys=True,
        )
        + "\n",
    )


def write_test_command(root: Path) -> None:
    write_text(root, "package.json", json.dumps({"scripts": {"test": "echo ok"}}, sort_keys=True) + "\n")


def seed_tickets(root: Path, tickets: list[dict[str, object]]) -> None:
    write_ticket_run_state(
        root,
        {
            "run_id": "preflight-fixture",
            "halt_when_complete": True,
            "notify_on_complete": False,
            "tickets": tickets,
        },
        actor_role="preflight_test",
        event_type="preflight_test.ticket_run_seeded",
    )


class ParallelizationPreflightTests(unittest.TestCase):
    def test_ready_report_lists_expected_parallel_wave(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_intake(target)
            write_test_command(target)
            write_text(target, "src/auth.py", "def login(user):\n    return user\n")
            write_text(target, "src/billing.py", "def invoice(user):\n    return user\n")
            seed_tickets(
                target,
                [
                    {"id": "AUTH-1", "summary": "Update auth behavior.", "status": "pending", "paths": ["src/auth.py"]},
                    {
                        "id": "BILL-1",
                        "summary": "Update billing behavior.",
                        "status": "pending",
                        "paths": ["src/billing.py"],
                    },
                ],
            )

            report = build_parallelization_preflight_report(target)

        self.assertEqual("ready", report["status"], report["risk_areas"])
        groups = report["expected_parallelization"]
        self.assertTrue(any(group["same_wave_parallel"] for group in groups), groups)
        task_sets = {
            frozenset(item["task_id"] for item in group["items"])
            for group in groups
            if group["same_wave_parallel"]
        }
        self.assertIn(frozenset({"AUTH-1", "BILL-1"}), task_sets)
        checks = report["checks"]
        self.assertEqual(0, checks["symbol_index_freshness"]["stale_file_count"])
        self.assertGreater(checks["validation_commands"]["command_count"], 0)
        self.assertTrue(checks["dashboard_dag"]["available"])
        self.assertFalse(report["risk_areas"])

    def test_warning_report_identifies_parser_failure_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_intake(target)
            write_test_command(target)
            write_text(target, "src/broken.py", "def broken(:\n    pass\n")
            seed_tickets(
                target,
                [
                    {
                        "id": "BROKEN-1",
                        "summary": "Repair broken module.",
                        "status": "pending",
                        "paths": ["src/broken.py"],
                    }
                ],
            )

            report = build_parallelization_preflight_report(target)

        self.assertEqual("warn", report["status"], report["risk_areas"])
        self.assertTrue(
            any(risk["area"] == "extractor_health" and risk["severity"] == "warn" for risk in report["risk_areas"]),
            report["risk_areas"],
        )
        python_health = report["checks"]["extractor_health_by_language"]["Python"]
        self.assertGreaterEqual(python_health["failed_count"], 1)

    def test_block_report_identifies_missing_validation_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_intake(target)
            write_text(target, "src/auth.py", "def login(user):\n    return user\n")
            seed_tickets(
                target,
                [
                    {"id": "AUTH-1", "summary": "Update auth behavior.", "status": "pending", "paths": ["src/auth.py"]},
                ],
            )

            report = build_parallelization_preflight_report(target)

        self.assertEqual("block", report["status"], report["risk_areas"])
        self.assertTrue(
            any(risk["area"] == "validation_commands" and risk["severity"] == "block" for risk in report["risk_areas"]),
            report["risk_areas"],
        )
        self.assertEqual(0, report["checks"]["validation_commands"]["command_count"])

    def test_local_command_reports_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_intake(target)
            write_test_command(target)
            write_text(target, "src/auth.py", "def login(user):\n    return user\n")
            seed_tickets(
                target,
                [
                    {"id": "AUTH-1", "summary": "Update auth behavior.", "status": "pending", "paths": ["src/auth.py"]},
                ],
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "preflight_parallelization_readiness.py"),
                    "--target",
                    str(target),
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("parallelization_preflight_v1", report["report"])
        self.assertIn(report["status"], {"ready", "warn", "block"})
        self.assertIn("expected_parallelization", report)
        self.assertIn("serialized_tasks", report)


if __name__ == "__main__":
    unittest.main()
