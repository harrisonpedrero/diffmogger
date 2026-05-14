from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from diffmogger.runtime.state_store import human_messages_snapshot
TICKET_RUN_PATHS = [
    ROOT / "src" / "diffmogger" / "runtime" / "ticket_run.py",
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
                    target = Path(tmp).resolve()
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

    def test_role_worktree_target_resolves_to_canonical_ticket_state(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "builder" / "run-1"
                    worktree.mkdir(parents=True)
                    module.write_ticket_run_state(
                        target,
                        {
                            "run_id": "run-worktree",
                            "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                        },
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )

                    loaded, ticket_path, _text = module.load_ticket_run(worktree)
                    summary = module.ticket_summary(loaded, worktree)

                    self.assertEqual("run-worktree", loaded["run_id"])
                    self.assertEqual(1, summary["counts"]["pending"])
                    self.assertEqual(target / ".diffmogger" / "runtime" / "orchestration.sqlite3", ticket_path)

    def test_role_worktree_load_reads_canonical_ticket_state_read_only(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "builder" / "run-1"
                    worktree.mkdir(parents=True)
                    calls: list[tuple[Path, bool]] = []
                    original_load_state = module.load_ticket_run_state

                    def fake_load_state(load_target: Path, *, read_only: bool = False):
                        calls.append((load_target.resolve(), read_only))
                        if not read_only:
                            raise AssertionError("role worktree ticket reads must be read-only")
                        return {
                            "run_id": "run-worktree",
                            "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                        }

                    try:
                        module.load_ticket_run_state = fake_load_state
                        loaded, ticket_path, _text = module.load_ticket_run(worktree)
                    finally:
                        module.load_ticket_run_state = original_load_state

                    self.assertEqual([(target, True)], calls)
                    self.assertEqual("run-worktree", loaded["run_id"])
                    self.assertEqual(target / ".diffmogger" / "runtime" / "orchestration.sqlite3", ticket_path)

    def test_role_worktree_load_uses_readonly_snapshot_when_configured(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "builder" / "run-1"
                    worktree.mkdir(parents=True)
                    snapshot_path = worktree / ".diffmogger" / "runtime" / "automation_queue" / "builder" / "run-1" / "ticket_state_snapshot.json"
                    snapshot_path.parent.mkdir(parents=True)
                    snapshot_path.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "data": {
                                    "run_id": "run-snapshot",
                                    "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                                },
                            }
                        ),
                        encoding="utf-8",
                    )
                    original_load_state = module.load_ticket_run_state
                    old_snapshot = os.environ.get("DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT")
                    old_direct = os.environ.pop("DIFFMOGGER_TICKET_STATE_DIRECT", None)

                    def fail_load_state(*_args, **_kwargs):
                        raise AssertionError("snapshot-backed role reads should not open canonical SQLite")

                    try:
                        os.environ["DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT"] = str(snapshot_path)
                        module.load_ticket_run_state = fail_load_state
                        loaded, ticket_path, _text = module.load_ticket_run(worktree)
                    finally:
                        module.load_ticket_run_state = original_load_state
                        if old_snapshot is None:
                            os.environ.pop("DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT", None)
                        else:
                            os.environ["DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT"] = old_snapshot
                        if old_direct is not None:
                            os.environ["DIFFMOGGER_TICKET_STATE_DIRECT"] = old_direct

                    self.assertEqual("run-snapshot", loaded["run_id"])
                    self.assertEqual(target / ".diffmogger" / "runtime" / "orchestration.sqlite3", ticket_path)

    def test_role_worktree_write_if_valid_reads_previous_state_read_only(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "builder" / "run-1"
                    worktree.mkdir(parents=True)
                    seed = {
                        "run_id": "run-worktree",
                        "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                    }
                    next_data = {
                        "run_id": "run-worktree",
                        "tickets": [
                            {
                                "id": "T-1",
                                "summary": "Do it",
                                "status": "candidate_done",
                                "evidence": ["builder completed implementation"],
                            }
                        ],
                    }
                    calls: list[tuple[Path, bool]] = []
                    original_load_state = module.load_ticket_run_state

                    def fake_load_state(load_target: Path, *, read_only: bool = False):
                        calls.append((load_target.resolve(), read_only))
                        if not read_only:
                            raise AssertionError("staged ticket updates must read previous state read-only")
                        return seed

                    try:
                        module.load_ticket_run_state = fake_load_state
                        result = module.write_if_valid(worktree, module.ticket_state_path(target), "", next_data)
                    finally:
                        module.load_ticket_run_state = original_load_state

                    self.assertEqual([(target, True)], calls)
                    self.assertTrue(result["staged"])
                    actions_path = module.ticket_state_actions_path(worktree)
                    self.assertIsNotNone(actions_path)
                    actions = json.loads(actions_path.read_text(encoding="utf-8"))["actions"]
                    self.assertEqual("update_ticket", actions[0]["action"])
                    self.assertEqual("candidate_done", actions[0]["ticket"]["status"])

    def test_role_worktree_write_if_valid_uses_snapshot_for_staged_actions(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "builder" / "run-1"
                    worktree.mkdir(parents=True)
                    seed = {
                        "run_id": "run-worktree",
                        "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                    }
                    snapshot_path = worktree / ".diffmogger" / "runtime" / "automation_queue" / "builder" / "run-1" / "ticket_state_snapshot.json"
                    snapshot_path.parent.mkdir(parents=True)
                    snapshot_path.write_text(
                        json.dumps({"schema_version": 1, "data": seed}),
                        encoding="utf-8",
                    )
                    next_data = {
                        "run_id": "run-worktree",
                        "tickets": [
                            {
                                "id": "T-1",
                                "summary": "Do it",
                                "status": "candidate_done",
                                "evidence": ["builder completed implementation"],
                            }
                        ],
                    }
                    original_load_state = module.load_ticket_run_state
                    old_snapshot = os.environ.get("DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT")
                    old_direct = os.environ.pop("DIFFMOGGER_TICKET_STATE_DIRECT", None)

                    def fail_load_state(*_args, **_kwargs):
                        raise AssertionError("snapshot-backed staged writes should not open canonical SQLite")

                    try:
                        os.environ["DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT"] = str(snapshot_path)
                        module.load_ticket_run_state = fail_load_state
                        result = module.write_if_valid(worktree, module.ticket_state_path(target), "", next_data)
                    finally:
                        module.load_ticket_run_state = original_load_state
                        if old_snapshot is None:
                            os.environ.pop("DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT", None)
                        else:
                            os.environ["DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT"] = old_snapshot
                        if old_direct is not None:
                            os.environ["DIFFMOGGER_TICKET_STATE_DIRECT"] = old_direct

                    self.assertTrue(result["staged"])
                    actions_path = module.ticket_state_actions_path(worktree)
                    self.assertIsNotNone(actions_path)
                    actions = json.loads(actions_path.read_text(encoding="utf-8"))["actions"]
                    self.assertEqual("update_ticket", actions[0]["action"])
                    self.assertEqual(module.ticket_digest(seed["tickets"][0]), actions[0]["start_hash"])
                    self.assertEqual("candidate_done", actions[0]["ticket"]["status"])

    def test_role_worktree_update_stages_typed_ticket_action(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "builder" / "run-1"
                    worktree.mkdir(parents=True)
                    seed = {
                        "run_id": "run-worktree",
                        "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                    }
                    module.write_ticket_run_state(
                        target,
                        seed,
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    actions_path = (
                        worktree
                        / ".diffmogger"
                        / "runtime"
                        / "automation_queue"
                        / "builder"
                        / "run-1"
                        / "ticket_state_actions.json"
                    )
                    env = os.environ.copy()
                    env["DIFFMOGGER_TICKET_STATE_ACTIONS_PATH"] = str(actions_path)

                    result = subprocess.run(
                        [
                            sys.executable,
                            str(path),
                            str(worktree),
                            "update",
                            "--ticket-id",
                            "T-1",
                            "--ticket-json",
                            json.dumps(
                                {
                                    "summary": "Do it",
                                    "status": "candidate_done",
                                    "evidence": ["builder completed implementation"],
                                }
                            ),
                            "--json",
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                        env=env,
                    )

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertTrue(payload["staged"])
                    self.assertEqual("typed_state_action", payload["ticket_source"])
                    self.assertEqual(1, payload["staged_action_count"])
                    canonical = module.load_ticket_run_state(target)
                    self.assertEqual("pending", canonical["tickets"][0]["status"])
                    actions = json.loads(actions_path.read_text(encoding="utf-8"))["actions"]
                    self.assertEqual("update_ticket", actions[0]["action"])
                    self.assertEqual("T-1", actions[0]["ticket_id"])
                    self.assertEqual("pending", seed["tickets"][0]["status"])
                    self.assertEqual("candidate_done", actions[0]["ticket"]["status"])
                    self.assertTrue(actions[0]["start_hash"])
                    self.assertTrue(actions[0]["end_hash"])

    def test_role_worktree_delete_stages_typed_ticket_action(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp).resolve()
                    (target / ".diffmogger").mkdir(parents=True)
                    (target / ".diffmogger" / "manifest.json").write_text(
                        json.dumps({"schema_version": 1, "layout": "sidecar_v1"}),
                        encoding="utf-8",
                    )
                    worktree = target / ".diffmogger" / "runtime" / "automation_worktrees" / "planner" / "run-1"
                    worktree.mkdir(parents=True)
                    module.write_ticket_run_state(
                        target,
                        {
                            "run_id": "run-worktree",
                            "tickets": [{"id": "T-1", "summary": "Do it", "status": "pending"}],
                        },
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    actions_path = (
                        worktree
                        / ".diffmogger"
                        / "runtime"
                        / "automation_queue"
                        / "planner"
                        / "run-1"
                        / "ticket_state_actions.json"
                    )
                    env = os.environ.copy()
                    env["DIFFMOGGER_TICKET_STATE_ACTIONS_PATH"] = str(actions_path)

                    result = subprocess.run(
                        [sys.executable, str(path), str(worktree), "delete", "--ticket-id", "T-1", "--json"],
                        text=True,
                        capture_output=True,
                        check=False,
                        env=env,
                    )

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertTrue(payload["staged"])
                    self.assertEqual(1, payload["staged_action_count"])
                    canonical = module.load_ticket_run_state(target)
                    self.assertEqual(1, len(canonical["tickets"]))
                    actions = json.loads(actions_path.read_text(encoding="utf-8"))["actions"]
                    self.assertEqual("delete_ticket", actions[0]["action"])
                    self.assertEqual("T-1", actions[0]["ticket_id"])
                    self.assertTrue(actions[0]["start_hash"])

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
                    outbox = human_messages_snapshot(target)["outbox"]
                    self.assertEqual(1, len(outbox))
                    self.assertEqual("NOTIFIER_UNREACHABLE", outbox[0]["status"])
                    self.assertIn("**Ticket campaign run-3: COMPLETE**", outbox[0]["body"])
                    self.assertIn("**Tickets**", outbox[0]["body"])
                    self.assertIn("T-1 [DONE] Finish ticket", outbox[0]["body"])
                    self.assertIn("Evidence: pytest passed", outbox[0]["body"])

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

    def run_next_json(self, script_path: Path, target: Path) -> dict[str, object]:
        result = subprocess.run(
            [sys.executable, str(script_path), str(target), "next", "--json"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual("", result.stderr)
        self.assertEqual(0, result.returncode)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, dict)
        return data

    def test_next_selects_dependency_ready_ticket_in_file_order(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-order",
                            "tickets": [
                                {"id": "T-2", "status": "pending", "depends_on": ["T-1"]},
                                {"id": "T-1", "status": "pending"},
                            ],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("selected", result["status"])
                    self.assertEqual("implement_pending", result["action"])
                    self.assertEqual("T-1", result["ticket"]["id"])
                    self.assertEqual(
                        [{"ticket_id": "T-2", "depends_on": "T-1", "dependency_status": "pending"}],
                        result["waiting_on_dependencies"],
                    )

    def test_claim_next_marks_pending_ticket_in_progress(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-claim",
                            "tickets": [
                                {"id": "T-1", "summary": "Build first slice", "status": "pending"},
                                {"id": "T-2", "summary": "Follow up", "status": "pending", "depends_on": ["T-1"]},
                            ],
                        },
                    )

                    result = subprocess.run(
                        [
                            sys.executable,
                            str(path),
                            str(target),
                            "claim-next",
                            "--role",
                            "builder",
                            "--run-id",
                            "builder-run-1",
                            "--json",
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )

                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    payload = json.loads(result.stdout)
                    loaded = module.load_ticket_run_state(target)
                    self.assertTrue(payload["claimed"])
                    self.assertEqual("T-1", payload["selected"]["ticket"]["id"])
                    self.assertEqual("resume_in_progress", payload["next"]["action"])
                    self.assertEqual(1, payload["summary"]["counts"]["in_progress"])
                    self.assertEqual(1, payload["summary"]["counts"]["pending"])
                    self.assertEqual("in_progress", loaded["tickets"][0]["status"])
                    self.assertEqual("builder", loaded["tickets"][0]["claimed_by"])
                    self.assertEqual("builder-run-1", loaded["tickets"][0]["claimed_run_id"])

    def test_next_skips_ticket_with_blocked_dependency(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-blocked",
                            "tickets": [
                                {"id": "T-1", "status": "blocked", "blocker": "needs human"},
                                {"id": "T-2", "status": "pending", "depends_on": ["T-1"]},
                                {"id": "T-3", "status": "pending"},
                            ],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("selected", result["status"])
                    self.assertEqual("T-3", result["ticket"]["id"])
                    self.assertEqual([{"ticket_id": "T-2", "depends_on": "T-1"}], result["blocked_dependencies"])

    def test_next_prefers_candidate_verification(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-candidate",
                            "tickets": [
                                {"id": "T-1", "status": "pending"},
                                {"id": "T-2", "status": "candidate_done"},
                            ],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("selected", result["status"])
                    self.assertEqual("verify_candidate", result["action"])
                    self.assertEqual("T-2", result["ticket"]["id"])

    def test_next_reports_missing_dependency(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-missing",
                            "tickets": [{"id": "T-1", "status": "pending", "depends_on": ["T-missing"]}],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("blocked", result["status"])
                    self.assertEqual("missing ticket dependency", result["reason"])
                    self.assertEqual([{"ticket_id": "T-1", "depends_on": "T-missing"}], result["missing_dependencies"])
                    self.assertIsNone(result["ticket"])

    def test_next_reports_dependency_cycle_when_no_ticket_is_actionable(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-cycle",
                            "tickets": [
                                {"id": "T-1", "status": "pending", "depends_on": ["T-2"]},
                                {"id": "T-2", "status": "pending", "depends_on": ["T-1"]},
                            ],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("blocked", result["status"])
                    self.assertEqual("dependency cycle", result["reason"])
                    self.assertEqual([["T-1", "T-2", "T-1"]], result["dependency_cycles"])
                    self.assertIsNone(result["ticket"])

    def test_next_reports_no_actionable_ticket(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(target, {"run_id": "run-next-empty", "tickets": []})

                    result = self.run_next_json(path, target)

                    self.assertEqual("blocked", result["status"])
                    self.assertEqual("ticket queue has no tickets", result["reason"])
                    self.assertIsNone(result["ticket"])

    def test_next_reports_placeholder_only_ticket_source(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-placeholder",
                            "tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Replace this sample with the first startup ticket.",
                                    "status": "pending",
                                }
                            ],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("blocked", result["status"])
                    self.assertEqual("ticket queue still contains placeholder tickets", result["reason"])
                    self.assertEqual("TICKET-001", result["placeholder_tickets"][0]["id"])
                    self.assertIsNone(result["ticket"])

    def test_next_reports_duplicate_ticket_ids_as_ambiguous(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_ticket_run(
                        target,
                        {
                            "run_id": "run-next-duplicates",
                            "tickets": [
                                {"id": "T-1", "status": "pending"},
                                {"id": "T-1", "status": "pending"},
                            ],
                        },
                    )

                    result = self.run_next_json(path, target)

                    self.assertEqual("blocked", result["status"])
                    self.assertEqual("duplicate ticket ids", result["reason"])
                    self.assertEqual(["T-1"], result["duplicate_ticket_ids"])
                    self.assertIsNone(result["ticket"])

    def test_import_parsers_normalize_markdown_csv_and_json(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                markdown = """
                ## TICKET-001: Build local setup
                - acceptance: Setup can run locally
                - verification: python3 -m unittest

                - TICKET-002: Document the workflow
                """.strip()
                csv_text = "id,summary,depends_on,verification\nTICKET-003,Wire queue,TICKET-001,pytest\n"
                json_text = json.dumps({"tickets": [{"id": "TICKET-004", "summary": "Review result"}]})

                markdown_tickets = module.parse_import_tickets(markdown, "markdown")
                csv_tickets = module.parse_import_tickets(csv_text, "csv")
                json_tickets = module.parse_import_tickets(json_text, "json")

                self.assertEqual("TICKET-001", markdown_tickets[0]["id"])
                self.assertEqual(["python3 -m unittest"], markdown_tickets[0]["verification_commands"])
                self.assertEqual(["TICKET-001"], csv_tickets[0]["depends_on"])
                self.assertEqual("Review result", json_tickets[0]["summary"])

    def test_write_preserves_markdown_wrapper_and_replaces_only_fenced_json(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    ticket_path = self.write_ticket_run(
                        target,
                        {
                            "run_id": "preserve-wrapper",
                            "tickets": [{"id": "TICKET-001", "summary": "Original", "status": "pending"}],
                        },
                    )
                    original = ticket_path.read_text(encoding="utf-8")
                    next_data = {
                        "run_id": "preserve-wrapper",
                        "tickets": [{"id": "TICKET-002", "summary": "Replacement", "status": "pending"}],
                    }

                    module.write_ticket_run_data(ticket_path, original, next_data)
                    updated = ticket_path.read_text(encoding="utf-8")
                    loaded, _path, _text = module.load_ticket_run(target)

                    self.assertTrue(updated.startswith("# Ticket Run\n\n```json ticket-run\n"))
                    self.assertTrue(updated.endswith("\n```\n"))
                    self.assertEqual("TICKET-002", loaded["tickets"][0]["id"])

    def test_import_modes_placeholder_replacement_and_append(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                placeholder_data = {
                    "run_id": "import-modes",
                    "tickets": [
                        {
                            "id": "TICKET-001",
                            "summary": "Replace this sample with the first startup ticket.",
                            "status": "pending",
                        }
                    ],
                }
                imported = [{"id": "TICKET-010", "summary": "Real ticket", "status": "pending"}]

                replaced = module.data_with_imported_tickets(placeholder_data, imported, "replace-placeholder")
                appended = module.data_with_imported_tickets(replaced, imported, "append")

                self.assertEqual(["TICKET-010"], [ticket["id"] for ticket in replaced["tickets"]])
                self.assertEqual(["TICKET-010", "TICKET-010"], [ticket["id"] for ticket in appended["tickets"]])

    def test_validation_reports_duplicate_ids_missing_dependencies_and_cycles(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                data = {
                    "tickets": [
                        {"id": "T-1", "summary": "First", "status": "pending", "depends_on": ["T-2"]},
                        {"id": "T-1", "summary": "Duplicate", "status": "pending"},
                        {"id": "T-2", "summary": "Second", "status": "pending", "depends_on": ["T-1"]},
                        {"id": "T-3", "summary": "Missing dependency", "status": "pending", "depends_on": ["NOPE-1"]},
                    ]
                }

                issues = module.ticket_validation_issues(data)
                issue_types = {issue["type"] for issue in issues}

                self.assertIn("duplicate_id", issue_types)
                self.assertIn("missing_dependency", issue_types)
                self.assertIn("dependency_cycle", issue_types)


if __name__ == "__main__":
    unittest.main()
