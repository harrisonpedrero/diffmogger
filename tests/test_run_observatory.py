from __future__ import annotations

import importlib.util
import json
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OBSERVATORY_PATHS = [
    ROOT / "scripts" / "run_observatory.py",
    ROOT / "templates" / "scripts" / "run_observatory.py",
]


def load_observatory(path: Path):
    module_name = (
        "observatory_under_test_"
        + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    )
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ObservatorySnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_observatory(path)) for path in OBSERVATORY_PATHS]

    def write_text(self, root: Path, relative: str, content: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    def write_json(self, root: Path, relative: str, data: object) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return path

    def seed_target(self, root: Path) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE

            Last updated: 2026-05-03T22:30:00+00:00

            ## Current Project State

            - Current assessment: Observatory state is ready for local review.

            ## Product Horizon State

            - Current horizon: H2 Offline/local demo
            - Advancement decision: stay

            ## Checks From Last Run

            - PASS: `bash scripts/validate_starter_kit.sh`
            - FAIL with environment note: `python3 -m pytest services/agentic-notifier` missing pytest.

            ## Known Issues

            - System python lacks pytest.

            ## Best Next Milestone

            Complete the self-run review path.

            ## Suggested Next Sprint-Sized Task

            Add a local validation fixture.
            """,
        )
        self.write_text(
            root,
            "docs/HUMAN_REQUESTS.md",
            """
            # Human Requests

            ## Active Requests

            None.

            ## Request Template

            ```markdown
            ### HR-YYYY-MM-DD-001

            - status: awaiting_user
            ```

            ## HR-2026-05-03-001

            - status: active

            ## HR-2026-05-03-002

            - status: resolved
            """,
        )
        self.write_text(
            root,
            "docs/HUMAN_INBOX.md",
            """
            # Human Inbox

            ## Active Inbound Messages

            None.

            ## Entry Template

            ```markdown
            ### INBOX-YYYY-MM-DD-001

            - status: unhandled
            ```

            ## INBOX-2026-05-03-001

            - status: unhandled

            #### Body

            Please summarize status.
            """,
        )
        self.write_text(
            root,
            "docs/HUMAN_OUTBOX.md",
            """
            # Human Outbox

            ## Outbound Records

            None.

            ## Entry Template

            ```markdown
            ### OUTBOX-YYYY-MM-DD-001

            - status: local_record
            ```

            ## OUTBOX-2026-05-03-001

            - status: local_record
            """,
        )
        self.write_text(
            root,
            "docs/MULTI_ROLE_PROGRESS.md",
            """
            # Multi-Role Progress

            ## Cumulative Metrics

            - Current deferred queue depth: 1

            ## Recent Activity Log

            - builder queued an observatory smoke patch.

            ## Deferred-Patch Backlog

            - planner stale patch awaiting triage.
            """,
        )
        self.write_json(
            root,
            "target/automation_signals.json",
            {
                "schema_version": 1,
                "updated_at": "2026-05-03T22:30:00+00:00",
                "signals": [
                    {
                        "id": "validation-sweep",
                        "owner_role": "hardener",
                        "priority": "medium",
                        "cadence": "weekly",
                        "instructions": "Run or improve validation coverage.",
                        "active": True,
                        "next_due_at": "2026-05-03T22:30:00+00:00",
                        "last_completed_at": None,
                        "last_completed_by": None,
                    },
                    {
                        "id": "human-inbox-triage",
                        "owner_role": "planner",
                        "priority": "high",
                        "cadence": "daily",
                        "instructions": "Check human inbox files.",
                        "active": True,
                        "next_due_at": "2026-05-03T22:31:00+00:00",
                        "last_completed_at": None,
                        "last_completed_by": None,
                    },
                    {
                        "id": "prompt-self-audit",
                        "owner_role": "planner",
                        "priority": "medium",
                        "cadence": "weekly",
                        "instructions": "Review prompt fit.",
                        "active": False,
                        "next_due_at": "2026-05-10T22:30:00+00:00",
                        "last_completed_at": "2026-05-03T22:00:00+00:00",
                        "last_completed_by": "planner",
                    },
                ],
            },
        )
        self.write_json(
            root,
            "target/automation_queue/builder/run-queued/manifest.json",
            {
                "role": "builder",
                "run_id": "run-queued",
                "status": "queued",
                "summary": "Queued smoke patch.",
                "changed_files": ["scripts/run_observatory.py"],
                "created_at": "2026-05-03T22:30:00+00:00",
            },
        )
        self.write_json(
            root,
            "target/automation_conveyor_state.json",
            {
                "schema_version": 1,
                "cycles": 1,
                "updated_at": "2026-05-03T22:30:00+00:00",
                "decision_queue": [
                    {"role": "integrator", "state": "ready", "reason": "queued patch needs integration"}
                ],
                "integrator_no_progress": {
                    "active": True,
                    "streak": 2,
                    "threshold": 2,
                    "reason": "integrator accepted 0 patches; deferred queue stayed blocked for staleness:no_detail",
                    "planner_requested_at": None,
                },
                "history": [],
            },
        )

    def seed_first_run_target(self, root: Path) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE

            Last updated: 2026-05-03T22:45:00+00:00

            ## Current Project State

            - Current assessment: Fresh local automation state is ready for first review.

            ## Product Horizon State

            - Current horizon: H2 Offline/local demo
            - Advancement decision: stay

            ## Checks From Last Run

            - PASS: `bash scripts/validate_starter_kit.sh`

            ## Known Issues

            None.

            ## Best Next Milestone

            Start the first conveyor pass.

            ## Suggested Next Sprint-Sized Task

            Run one local builder lane and integrate the result.
            """,
        )
        self.write_text(
            root,
            "docs/MULTI_ROLE_PROGRESS.md",
            """
            # Multi-Role Progress

            ## Recent Activity Log

            No multi-role activity recorded yet.

            ## Deferred-Patch Backlog

            None.
            """,
        )

    def test_build_snapshot_counts_active_human_bridge_records(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    snapshot = module.build_snapshot(target)

                    self.assertEqual(snapshot["human"]["pending_requests"], 1)
                    self.assertEqual(snapshot["human"]["unhandled_inbox"], 1)
                    self.assertEqual(snapshot["human"]["outbound_records"], 1)
                    self.assertEqual(snapshot["queue"]["totals"]["queued"], 1)
                    self.assertEqual(snapshot["progress"]["deferred_queue_depth"], 1)

    def test_signal_and_validation_snapshots_feed_self_review(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)

                    snapshot = module.build_snapshot(target)
                    active_signal_ids = [item["id"] for item in snapshot["signals"]["active"]]
                    review_items = {item["label"]: item["body"] for item in snapshot["review"]["items"]}

                    self.assertEqual(active_signal_ids, ["human-inbox-triage", "validation-sweep"])
                    self.assertEqual(snapshot["signals"]["active_count"], 2)
                    self.assertEqual(snapshot["task"]["validation"]["counts"]["pass"], 1)
                    self.assertEqual(snapshot["task"]["validation"]["counts"]["fail"], 1)
                    self.assertIn("1 pass, 1 fail", snapshot["task"]["validation"]["summary"])
                    self.assertIn("human-inbox-triage", review_items["Signals"])
                    self.assertIn("1 queued", review_items["Queue and conveyor"])
                    self.assertIn("No-progress circuit breaker active", review_items["Queue and conveyor"])

    def test_review_markdown_export_summarizes_local_state(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    output = target / "target" / "self-review.md"

                    exit_code = module.main(
                        [
                            "--target",
                            str(target),
                            "--review-output",
                            str(output),
                        ]
                    )

                    report = output.read_text(encoding="utf-8")
                    self.assertEqual(exit_code, 0)
                    self.assertIn("# Diffmogger Self-Review Snapshot", report)
                    self.assertIn("automation_status: `ACTIVE`", report)
                    self.assertIn("## Validation", report)
                    self.assertIn("PASS:", report)
                    self.assertIn("FAIL:", report)
                    self.assertIn("`human-inbox-triage`", report)
                    self.assertIn("queued_patches: 1", report)
                    self.assertIn("no_progress_circuit: active after 2/2", report)
                    self.assertIn("staleness:no_detail", report)
                    self.assertIn("pending_requests: 1", report)
                    self.assertIn("System python lacks pytest", report)
                    self.assertIn("Add a local validation fixture", report)

    def test_first_run_empty_states_explain_future_queue_outputs(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_first_run_target(target)

                    snapshot = module.build_snapshot(target)
                    review_items = {item["label"]: item["body"] for item in snapshot["review"]["items"]}
                    decision = snapshot["conveyor"]["decision_queue"][0]
                    html = module.render_html(snapshot, live=False)
                    report = module.render_review_markdown(snapshot)

                    self.assertIn("First role patch manifests", snapshot["empty_states"]["patch_queue"])
                    self.assertIn("First role patch manifests", review_items["Queue and conveyor"])
                    self.assertEqual(decision["state"], "first-run")
                    self.assertIn("first conveyor cycle", decision["reason"])
                    self.assertIn("No conveyor timeline yet", html)
                    self.assertIn("first_run_queue_state:", report)
                    self.assertIn("First role patch manifests", report)


if __name__ == "__main__":
    unittest.main()
