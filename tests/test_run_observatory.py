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
            - PASS: `python3 scripts/check_integration_safety.py`
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

            - Total integrator runs: 15
            - Accepted patches by role:
              - planner: 3
              - builder: 6
              - hardener: 4
            - Deferred patches by role:
              - planner: 2
              - builder: 1
              - hardener: 0
            - Current deferred queue depth: 1

            ## Recent Activity Log

            - builder queued an observatory smoke patch.

            ## Deferred-Patch Backlog

            - planner `planner-stale`: staleness; Patch base no longer matches HEAD.
            - builder `builder-conflict`: conflict; docs/CODEX_AUTOMATION_TASKS.md changed since role start.
            - builder `builder-verify`: verification_failure; $ bash scripts/validate_starter_kit.sh
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

    def seed_first_review_ready_target(self, root: Path) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE

            Last updated: 2026-05-04T03:45:00+00:00

            ## Current Project State

            - Current assessment: First-review path is ready for a local demo.

            ## Product Horizon State

            - Current horizon: H6 Showcase quality
            - Advancement decision: stay

            ## Checks From Last Run

            - PASS: `bash scripts/validate_starter_kit.sh`
            - PASS: `python3 scripts/check_integration_safety.py`

            ## Known Issues

            None.

            ## Suggested Next Sprint-Sized Task

            Continue builder momentum.
            """,
        )
        self.write_text(
            root,
            "docs/DEVELOPMENT.md",
            """
            # Development

            ### First Review Checklist

            1. Run `bash scripts/validate_starter_kit.sh`.
            2. Click **Run Safety Check**.
            3. Render `Diffmogger-observatory.html`.
            4. Export `Diffmogger-self-review.md`.
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

    def seed_priority_target(self, root: Path, *, include_deferred_pressure: bool) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE

            Last updated: 2026-05-03T22:50:00+00:00

            ## Current Project State

            - Current assessment: Action-plan priority fixtures are ready.

            ## Product Horizon State

            - Current horizon: H4 Evaluation/reporting/comparison layer
            - Advancement decision: stay

            ## Checks From Last Run

            - FAIL: `bash scripts/validate_starter_kit.sh`

            ## Known Issues

            - Validation fixture failed.

            ## Suggested Next Sprint-Sized Task

            Repair local validation.
            """,
        )
        backlog = (
            "- builder `builder-verify`: verification_failure; $ bash scripts/validate_starter_kit.sh"
            if include_deferred_pressure
            else "None."
        )
        depth = 1 if include_deferred_pressure else 0
        self.write_text(
            root,
            "docs/MULTI_ROLE_PROGRESS.md",
            f"""
            # Multi-Role Progress

            ## Cumulative Metrics

            - Total integrator runs: 4
            - Accepted patches by role:
              - builder: 2
            - Deferred patches by role:
              - builder: {depth}
            - Current deferred queue depth: {depth}

            ## Recent Activity Log

            - validation fixture state recorded.

            ## Deferred-Patch Backlog

            {backlog}
            """,
        )
        self.write_json(
            root,
            "target/automation_signals.json",
            {
                "schema_version": 1,
                "updated_at": "2026-05-03T22:50:00+00:00",
                "signals": [
                    {
                        "id": "validation-sweep",
                        "owner_role": "hardener",
                        "priority": "medium",
                        "cadence": "weekly",
                        "instructions": "Improve validation coverage.",
                        "active": True,
                        "next_due_at": "2026-05-03T22:50:00+00:00",
                        "last_completed_at": None,
                        "last_completed_by": None,
                    }
                ],
            },
        )
        self.write_json(
            root,
            "target/automation_conveyor_state.json",
            {
                "schema_version": 1,
                "cycles": 2,
                "updated_at": "2026-05-03T22:50:00+00:00",
                "decision_queue": [
                    {"role": "builder", "state": "ready", "reason": "builder momentum is available"}
                ],
            },
        )
        if include_deferred_pressure:
            self.write_json(
                root,
                "target/automation_queue/builder/run-deferred/manifest.json",
                {
                    "role": "builder",
                    "run_id": "run-deferred",
                    "status": "deferred",
                    "summary": "Deferred validation patch.",
                    "deferral_reason": "verification_failure",
                    "changed_files": ["scripts/validate_starter_kit.sh"],
                    "created_at": "2026-05-03T22:50:00+00:00",
                },
            )

    def seed_follow_through_target(self, root: Path) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE

            Last updated: 2026-05-03T23:00:00+00:00

            ## Current Project State

            - Current assessment: Follow-through reporting fixture is ready.

            ## Product Horizon State

            - Current horizon: H4 Evaluation/reporting/comparison layer
            - Advancement decision: stay

            ## Checks From Last Run

            - PASS: `bash scripts/validate_starter_kit.sh`

            ## Suggested Next Sprint-Sized Task

            Continue builder momentum with the next scoped local increment.
            """,
        )
        self.write_text(
            root,
            "docs/MULTI_ROLE_PROGRESS.md",
            """
            # Multi-Role Progress

            ## Cumulative Metrics

            - Total integrator runs: 2
            - Accepted patches by role:
              - planner: 0
              - builder: 1
              - hardener: 0
            - Deferred patches by role:
              - planner: 0
              - builder: 0
              - hardener: 0
            - Current deferred queue depth: 0

            ## Recent Activity Log

            - builder completed a local reporting increment.

            ## Deferred-Patch Backlog

            None.
            """,
        )
        self.write_json(
            root,
            "target/automation_conveyor_state.json",
            {
                "schema_version": 1,
                "cycles": 3,
                "updated_at": "2026-05-03T23:00:00+00:00",
                "history": [
                    {
                        "role": "builder",
                        "reason": "builder momentum was available",
                        "exit_code": 0,
                        "started_at": "2026-05-03T22:58:00+00:00",
                        "finished_at": "2026-05-03T23:00:00+00:00",
                        "progress_success": True,
                    }
                ],
            },
        )
        self.write_json(
            root,
            "target/action_plan_history.json",
            {
                "schema_version": 1,
                "updated_at": "2026-05-03T22:57:30+00:00",
                "records": [
                    {
                        "recorded_at": "2026-05-03T22:57:30+00:00",
                        "status": "still_pending",
                        "previous_recommendation": "Run integrator triage for 1 deferred backlog item(s).",
                        "expected_lane": "integrator",
                        "observed_lane": "none",
                        "observed_result": "No conveyor or queue outcome recorded yet.",
                        "current_recommendation": "Run integrator triage for 1 deferred backlog item(s).",
                        "current_lane": "integrator",
                        "no_progress": "active after 2/2",
                        "accepted_total": 0,
                        "deferred_queue_depth": 1,
                    },
                    {
                        "recorded_at": "2026-05-03T22:55:00+00:00",
                        "status": "superseded",
                        "previous_recommendation": "Repair local validation.",
                        "expected_lane": "hardener",
                        "observed_lane": "builder",
                        "observed_result": "builder completed with progress",
                        "current_recommendation": "Continue builder momentum with the next scoped local increment.",
                        "current_lane": "builder",
                        "no_progress": "inactive",
                        "accepted_total": 1,
                        "deferred_queue_depth": 0,
                    },
                ],
            },
        )

    def seed_queued_integrator_target(self, root: Path) -> None:
        self.write_text(
            root,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE

            Last updated: 2026-05-03T23:10:00+00:00

            ## Current Project State

            - Current assessment: Queued patch export fixture is ready.

            ## Product Horizon State

            - Current horizon: H4 Evaluation/reporting/comparison layer
            - Advancement decision: stay

            ## Checks From Last Run

            - PASS: `bash scripts/validate_starter_kit.sh`

            ## Known Issues

            None.

            ## Suggested Next Sprint-Sized Task

            Continue builder momentum with the next scoped local increment.
            """,
        )
        self.write_text(
            root,
            "docs/MULTI_ROLE_PROGRESS.md",
            """
            # Multi-Role Progress

            ## Cumulative Metrics

            - Total integrator runs: 2
            - Accepted patches by role:
              - planner: 0
              - builder: 1
              - hardener: 0
            - Deferred patches by role:
              - planner: 0
              - builder: 0
              - hardener: 0
            - Current deferred queue depth: 0

            ## Recent Activity Log

            - builder queued a local observatory export patch.

            ## Deferred-Patch Backlog

            None.
            """,
        )
        self.write_json(
            root,
            "target/automation_queue/builder/run-queued-export/manifest.json",
            {
                "role": "builder",
                "run_id": "run-queued-export",
                "status": "queued",
                "summary": "Queued observatory export patch.",
                "changed_files": ["scripts/run_observatory.py", "tests/test_run_observatory.py"],
                "created_at": "2026-05-03T23:10:00+00:00",
            },
        )
        self.write_json(
            root,
            "target/automation_conveyor_state.json",
            {
                "schema_version": 1,
                "cycles": 3,
                "updated_at": "2026-05-03T23:10:00+00:00",
                "decision_queue": [
                    {"role": "integrator", "state": "ready", "reason": "queued patch needs integration"}
                ],
                "history": [],
            },
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
                    self.assertEqual(len(snapshot["progress"]["deferred_backlog"]), 3)
                    triage_groups = {
                        item["reason"]: item
                        for item in snapshot["progress"]["deferred_triage"]["groups"]
                    }
                    self.assertEqual(triage_groups["staleness"]["count"], 1)
                    self.assertEqual(triage_groups["conflict"]["count"], 1)
                    self.assertEqual(triage_groups["verification_failure"]["count"], 1)

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
                    self.assertEqual(snapshot["task"]["validation"]["counts"]["pass"], 2)
                    self.assertEqual(snapshot["task"]["validation"]["counts"]["fail"], 1)
                    self.assertIn("2 pass, 1 fail", snapshot["task"]["validation"]["summary"])
                    self.assertEqual(snapshot["task"]["integration_safety"]["status"], "pass")
                    self.assertIn("check_integration_safety.py", snapshot["task"]["integration_safety"]["summary"])
                    self.assertIn("human-inbox-triage", review_items["Signals"])
                    self.assertIn("Latest recorded integration-safety check passed", review_items["Integration safety"])
                    self.assertIn("First-review path needs attention", review_items["First review"])
                    self.assertIn("1 queued", review_items["Queue and conveyor"])
                    self.assertIn("No-progress circuit breaker active", review_items["Queue and conveyor"])
                    self.assertIn("Process 1 unhandled human inbox", review_items["Action plan"])
                    self.assertIn("3 deferred backlog item", review_items["Deferred triage"])
                    self.assertIn("Start with `staleness`", review_items["Deferred triage"])
                    self.assertEqual(snapshot["scorecard"]["status"], "attention")
                    self.assertEqual(snapshot["scorecard"]["action_plan"]["label"], "Process human inbox")
                    self.assertEqual(snapshot["scorecard"]["action_plan"]["lane"], "planner")
                    scorecard_items = {item["label"]: item for item in snapshot["scorecard"]["items"]}
                    self.assertEqual(scorecard_items["Accepted patches"]["value"], 13)
                    self.assertIn("builder 6", scorecard_items["Accepted patches"]["detail"])
                    self.assertEqual(scorecard_items["Deferred pressure"]["value"], "1/1")
                    self.assertIn("1 staleness", scorecard_items["Deferred pressure"]["detail"])
                    self.assertEqual(scorecard_items["Validation"]["value"], "2/1")
                    self.assertEqual(scorecard_items["Integration safety"]["value"], "pass")
                    self.assertEqual(scorecard_items["Integration safety"]["kind"], "good")
                    self.assertEqual(scorecard_items["First review"]["value"], "attention")
                    self.assertEqual(scorecard_items["First review"]["kind"], "warn")
                    first_review_items = {item["label"]: item for item in snapshot["first_review"]["items"]}
                    self.assertEqual(first_review_items["Checklist docs"]["status"], "fail")
                    self.assertEqual(first_review_items["Validation"]["status"], "fail")
                    self.assertEqual(first_review_items["Run Safety Check"]["status"], "pass")

    def test_first_review_readiness_appears_in_snapshot_html_and_markdown(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_first_review_ready_target(target)

                    snapshot = module.build_snapshot(target)
                    first_review = snapshot["first_review"]
                    first_review_items = {item["label"]: item for item in first_review["items"]}
                    review_items = {item["label"]: item["body"] for item in snapshot["review"]["items"]}
                    scorecard_items = {item["label"]: item for item in snapshot["scorecard"]["items"]}
                    html = module.render_html(snapshot, live=False)
                    report = module.render_review_markdown(snapshot)

                    self.assertEqual(first_review["status"], "ready")
                    self.assertIn("First-review path is ready", first_review["summary"])
                    self.assertEqual(first_review_items["Checklist docs"]["status"], "pass")
                    self.assertIn("docs/DEVELOPMENT.md", first_review_items["Checklist docs"]["detail"])
                    self.assertEqual(first_review_items["Validation"]["status"], "pass")
                    self.assertEqual(first_review_items["Run Safety Check"]["status"], "pass")
                    self.assertIn("First-review path is ready", review_items["First review"])
                    self.assertEqual(scorecard_items["First review"]["value"], "ready")
                    self.assertEqual(scorecard_items["First review"]["kind"], "good")
                    self.assertIn("First review", html)
                    self.assertIn("## First Review Readiness", report)
                    self.assertIn("status: ready", report)
                    self.assertIn("Checklist docs: pass", report)
                    self.assertIn("Run Safety Check: pass", report)

    def test_dashboard_safety_record_feeds_first_review_readiness(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_first_run_target(target)
                    self.write_text(
                        target,
                        "docs/DEVELOPMENT.md",
                        """
                        # Development

                        ### First Review Checklist

                        1. Run `bash scripts/validate_starter_kit.sh`.
                        2. Click **Run Safety Check**.
                        3. Render `Diffmogger-observatory.html`.
                        4. Export `Diffmogger-self-review.md`.
                        """,
                    )
                    self.write_json(
                        target,
                        "target/integration_safety_check.json",
                        {
                            "schema_version": 1,
                            "checked_at": "2026-05-04T04:50:00+00:00",
                            "source": "dashboard_run_safety_check",
                            "status": "pass",
                            "exit_code": 0,
                            "command": "python3 scripts/check_integration_safety.py .",
                            "selected_target": str(target),
                            "checked_target": str(ROOT),
                            "summary": "Dashboard Run Safety Check passed against the kit source.",
                        },
                    )

                    snapshot = module.build_snapshot(target)
                    first_review_items = {item["label"]: item for item in snapshot["first_review"]["items"]}

                    self.assertEqual("pass", snapshot["task"]["integration_safety"]["status"])
                    self.assertIn("Dashboard Run Safety Check passed", snapshot["task"]["integration_safety"]["summary"])
                    self.assertEqual("ready", snapshot["first_review"]["status"])
                    self.assertEqual("pass", first_review_items["Run Safety Check"]["status"])

    def test_prebootstrap_generated_target_gets_target_local_validation_action(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.write_text(
                        target,
                        "docs/CODEX_AUTOMATION_TASKS.md",
                        """
                        # Codex Automation Tasks

                        AUTOMATION_STATUS: ACTIVE

                        Last updated: 2026-05-04T05:20:00+00:00

                        ## Current Project State

                        - Current assessment: not bootstrapped yet.

                        ## Product Horizon State

                        - Current horizon: H1 Runnable baseline
                        - Advancement decision: stay

                        ## Checks From Last Run

                        - Not run yet. Bootstrap run should discover or create verification commands.

                        ## Known Issues

                        - Product baseline still needs to be created or inspected.

                        ## Suggested Next Sprint-Sized Task

                        Run the initial bootstrap prompt.
                        """,
                    )
                    self.write_text(
                        target,
                        "docs/DEVELOPMENT.md",
                        """
                        # Development

                        ### First Review Checklist

                        1. Run `bash scripts/validate_starter_kit.sh` from the Diffmogger source when reviewing kit behavior.
                        2. Click **Run Safety Check**.
                        3. Render `Diffmogger-observatory.html`.
                        4. Export `Diffmogger-self-review.md`.
                        """,
                    )
                    self.write_json(
                        target,
                        "target/integration_safety_check.json",
                        {
                            "schema_version": 1,
                            "checked_at": "2026-05-04T05:20:00+00:00",
                            "source": "dashboard_run_safety_check",
                            "status": "pass",
                            "exit_code": 0,
                            "command": "python3 scripts/check_integration_safety.py .",
                            "selected_target": str(target),
                            "checked_target": str(ROOT),
                            "summary": "Dashboard Run Safety Check passed against the kit source.",
                        },
                    )

                    snapshot = module.build_snapshot(target)
                    first_review_items = {item["label"]: item for item in snapshot["first_review"]["items"]}
                    missing_actions = snapshot["first_review"]["missing_actions"]
                    report = module.render_review_markdown(snapshot)

                    self.assertFalse((target / "scripts" / "validate_starter_kit.sh").exists())
                    self.assertEqual("attention", snapshot["first_review"]["status"])
                    self.assertEqual("warn", first_review_items["Validation"]["status"])
                    self.assertIn("target-local validation", first_review_items["Validation"]["detail"])
                    self.assertIn("Complete the first bootstrap", missing_actions[0])
                    self.assertNotIn("validate_starter_kit.sh", missing_actions[0])
                    self.assertIn("Complete the first bootstrap", report)

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
                    history_path = target / "target" / "action_plan_history.json"
                    history = json.loads(history_path.read_text(encoding="utf-8"))
                    self.assertEqual(exit_code, 0)
                    self.assertIn("# Diffmogger Self-Review Snapshot", report)
                    self.assertIn("automation_status: `ACTIVE`", report)
                    self.assertIn("## Action Plan", report)
                    self.assertIn("recommendation: Process 1 unhandled human inbox message(s) before role work.", report)
                    self.assertIn("lane: `planner`", report)
                    self.assertIn("## Action Follow-Through", report)
                    self.assertIn("status: superseded", report)
                    self.assertIn("expected_lane: `hardener`", report)
                    self.assertIn("## Recommendation History", report)
                    self.assertIn("history_file: `target/action_plan_history.json`", report)
                    self.assertIn("accepted_total: 13", report)
                    self.assertEqual(history["schema_version"], 1)
                    self.assertEqual(len(history["records"]), 1)
                    self.assertEqual(history["records"][0]["status"], "superseded")
                    self.assertIn("## Scorecard", report)
                    self.assertIn("Accepted patches: 13", report)
                    self.assertIn("Deferred pressure: 1/1", report)
                    self.assertIn("## Validation", report)
                    self.assertIn("PASS:", report)
                    self.assertIn("FAIL:", report)
                    self.assertIn("## Integration Safety", report)
                    self.assertIn("status: pass", report)
                    self.assertIn("command: `python3 scripts/check_integration_safety.py`", report)
                    self.assertIn("`human-inbox-triage`", report)
                    self.assertIn("queued_patches: 1", report)
                    self.assertIn("no_progress_circuit: active after 2/2", report)
                    self.assertIn("staleness:no_detail", report)
                    self.assertIn("## Deferred Patch Triage", report)
                    self.assertIn("summary: 3 deferred backlog item(s): 1 staleness, 1 conflict, 1 verification_failure.", report)
                    self.assertIn("recommended_next_action: Start with `staleness`", report)
                    self.assertIn("conflict: 1 item(s); roles: builder 1", report)
                    self.assertIn("verification_failure: 1 item(s); roles: builder 1", report)
                    self.assertIn("pending_requests: 1", report)
                    self.assertIn("System python lacks pytest", report)
                    self.assertIn("Add a local validation fixture", report)

    def test_review_dir_export_writes_named_html_and_markdown_artifacts(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_first_review_ready_target(target)
                    output_dir = target / "target" / "first-review"

                    exit_code = module.main(
                        [
                            "--target",
                            str(target),
                            "--review-dir",
                            str(output_dir),
                        ]
                    )

                    html_path = output_dir / module.FIRST_REVIEW_OBSERVATORY_FILENAME
                    report_path = output_dir / module.FIRST_REVIEW_SELF_REVIEW_FILENAME
                    history_path = target / "target" / "action_plan_history.json"
                    html = html_path.read_text(encoding="utf-8")
                    report = report_path.read_text(encoding="utf-8")

                    self.assertEqual(exit_code, 0)
                    self.assertIn("Diffmogger Observatory", html)
                    self.assertIn("First review", html)
                    self.assertIn("# Diffmogger Self-Review Snapshot", report)
                    self.assertIn("## First Review Readiness", report)
                    self.assertIn("status: ready", report)
                    self.assertTrue(history_path.exists())

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
                    self.assertEqual(snapshot["scorecard"]["action_plan"]["lane"], "builder")
                    self.assertIn("Continue builder momentum", review_items["Action plan"])
                    self.assertEqual(decision["state"], "first-run")
                    self.assertIn("first conveyor cycle", decision["reason"])
                    self.assertIn("No conveyor timeline yet", html)
                    self.assertIn("Scorecard", html)
                    self.assertIn("Action Plan", html)
                    self.assertIn("Continue builder momentum", html)
                    self.assertIn("## Action Plan", report)
                    self.assertIn("first_run_queue_state:", report)
                    self.assertIn("First role patch manifests", report)
                    self.assertIn("No deferred patch backlog recorded", report)

    def test_review_markdown_export_recommends_integrator_for_queued_patches(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_queued_integrator_target(target)
                    output = target / "target" / "queued-self-review.md"

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
                    self.assertIn("## Action Plan", report)
                    self.assertIn("recommendation: Run integrator on 1 queued patch(es).", report)
                    self.assertIn("lane: `integrator`", report)
                    self.assertIn("## Action Follow-Through", report)
                    self.assertIn("status: superseded", report)
                    self.assertIn("current_recommendation: Run integrator on 1 queued patch(es).", report)
                    self.assertIn("queued_patches: 1", report)
                    self.assertIn("deferred_patches: 0", report)
                    self.assertIn("next_lane: `integrator` (ready) - queued patch needs integration", report)
                    self.assertIn("No deferred patch backlog recorded", report)

    def test_action_plan_follow_through_marks_followed_completed_lane(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_follow_through_target(target)

                    snapshot = module.build_snapshot(target)
                    follow = snapshot["follow_through"]
                    history = snapshot["recommendation_history"]
                    review_items = {item["label"]: item["body"] for item in snapshot["review"]["items"]}
                    report = module.render_review_markdown(snapshot)
                    html = module.render_html(snapshot, live=False)

                    self.assertEqual(follow["status"], "followed")
                    self.assertEqual(follow["expected_lane"], "builder")
                    self.assertEqual(follow["observed_lane"], "builder")
                    self.assertIn("builder completed with progress", follow["observed_result"])
                    self.assertIn("followed", review_items["Action follow-through"])
                    self.assertIn("3 recommendation follow-through record", review_items["Recommendation history"])
                    self.assertEqual(len(history["records"]), 3)
                    self.assertEqual(history["records"][0]["status"], "followed")
                    self.assertEqual(history["records"][0]["accepted_total"], 1)
                    self.assertEqual(history["records"][1]["no_progress"], "active after 2/2")
                    self.assertIn("## Action Follow-Through", report)
                    self.assertIn("status: followed", report)
                    self.assertIn("observed_lane: `builder`", report)
                    self.assertIn("builder completed with progress", report)
                    self.assertIn("## Recommendation History", report)
                    self.assertIn("3 recommendation follow-through record", report)
                    self.assertIn("no_progress: active after 2/2", report)
                    self.assertIn("Action Follow-Through", html)
                    self.assertIn("Recommendation History", html)
                    self.assertIn("followed", html)

    def test_deferred_pressure_action_plan_outranks_validation_failures(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_priority_target(target, include_deferred_pressure=True)

                    snapshot = module.build_snapshot(target)
                    action_plan = snapshot["scorecard"]["action_plan"]

                    self.assertEqual(action_plan["label"], "Run integrator triage")
                    self.assertEqual(action_plan["lane"], "integrator")
                    self.assertIn("1 deferred backlog item", action_plan["recommendation"])
                    self.assertIn("verification_failure", action_plan["why"])
                    self.assertEqual(snapshot["follow_through"]["status"], "superseded")
                    self.assertEqual(snapshot["follow_through"]["expected_lane"], "hardener")

    def test_validation_action_plan_outranks_signal_and_builder_momentum(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_priority_target(target, include_deferred_pressure=False)

                    snapshot = module.build_snapshot(target)
                    action_plan = snapshot["scorecard"]["action_plan"]

                    self.assertEqual(action_plan["label"], "Repair validation")
                    self.assertEqual(action_plan["lane"], "hardener")
                    self.assertIn("1 validation issue", action_plan["recommendation"])
                    self.assertIn("1 fail", action_plan["why"])


if __name__ == "__main__":
    unittest.main()
