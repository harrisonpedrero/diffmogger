from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TICKET_RUN_PATHS = [
    ROOT / "scripts" / "ticket_run.py",
    ROOT / "templates" / "scripts" / "ticket_run.py",
]


def load_ticket_run(path: Path):
    module_name = "ticket_run_under_test_" + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TicketRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_ticket_run(path)) for path in TICKET_RUN_PATHS]

    def write_ticket_run(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / "docs" / "TICKET_RUN.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Ticket Run\n\n```json ticket-run\n"
            + json.dumps(payload, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )
        return path

    def test_status_summarizes_active_ticket_run(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    data = {
                        "run_id": "run-1",
                        "halt_when_complete": True,
                        "tickets": [
                            {"id": "T-1", "status": "done", "evidence": ["pytest passed"]},
                            {"id": "T-2", "status": "pending"},
                        ],
                    }
                    self.write_ticket_run(target, data)

                    loaded, _ticket_path, _text = module.load_ticket_run(target)
                    summary = module.ticket_summary(loaded, target)

                    self.assertEqual(summary["status"], "active")
                    self.assertEqual(summary["counts"]["done"], 1)
                    self.assertFalse(summary["should_halt"])

    def test_done_ticket_without_evidence_does_not_halt(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    data = {
                        "run_id": "run-2",
                        "halt_when_complete": True,
                        "tickets": [{"id": "T-1", "status": "done", "evidence": []}],
                    }
                    self.write_ticket_run(target, data)

                    summary = module.ticket_summary(data, target)

                    self.assertEqual(summary["status"], "active")
                    self.assertEqual(summary["done_missing_evidence"], ["T-1"])
                    self.assertFalse(summary["should_halt"])

    def test_finalize_writes_report_and_outbox_fallback_when_notifier_unreachable(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    (target / ".agentic").mkdir()
                    (target / ".agentic" / "project_intake.json").write_text(
                        json.dumps(
                            {
                                "automation_run_mode": "ticket_campaign",
                                "human_bridge_mode": "local_notifier",
                                "ticket_completion_notify": True,
                                "local_notifications_enabled": True,
                            }
                        ),
                        encoding="utf-8",
                    )
                    data = {
                        "run_id": "run-3",
                        "halt_when_complete": True,
                        "notify_on_complete": True,
                        "report_path": "target/ticket_run_reports/run-3.md",
                        "tickets": [
                            {
                                "id": "T-1",
                                "summary": "Finish ticket",
                                "status": "done",
                                "verification_commands": ["pytest"],
                                "evidence": ["pytest passed"],
                                "related_commits": ["abc1234"],
                            }
                        ],
                    }
                    self.write_ticket_run(target, data)

                    original_post = module.post_notifier
                    try:
                        module.post_notifier = lambda _payload: (_ for _ in ()).throw(module.urllib.error.URLError("offline"))
                        result = module.finalize(target)
                    finally:
                        module.post_notifier = original_post

                    self.assertTrue(result["finalized"])
                    self.assertEqual(result["status"], "complete")
                    self.assertEqual(result["notification"]["status"], "fallback_outbox")
                    self.assertTrue((target / "target" / "ticket_run_reports" / "run-3.md").exists())
                    self.assertTrue((target / "target" / "ticket_run_completion.json").exists())
                    outbox = (target / "docs" / "HUMAN_OUTBOX.md").read_text(encoding="utf-8")
                    self.assertIn("NOTIFIER_UNREACHABLE", outbox)
                    self.assertIn("**Ticket campaign run-3: COMPLETE**", outbox)
                    self.assertIn("**Tickets**", outbox)
                    self.assertIn("T-1 [DONE] Finish ticket", outbox)
                    self.assertIn("Evidence: pytest passed", outbox)

    def test_malformed_ticket_block_fails_loudly(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    ticket_path = target / "docs" / "TICKET_RUN.md"
                    ticket_path.parent.mkdir(parents=True)
                    ticket_path.write_text(
                        textwrap.dedent(
                            """
                            # Ticket Run

                            ```json ticket-run
                            {"run_id":
                            ```
                            """
                        ).lstrip(),
                        encoding="utf-8",
                    )

                    with self.assertRaises(SystemExit):
                        module.load_ticket_run(target)


if __name__ == "__main__":
    unittest.main()
