from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.conveyor.state import load_state, write_state
from diffmogger.runtime.state_store import (
    CONVEYOR_PROJECTION_NAME,
    RUNNER_PROJECTION_NAME,
    automation_control_state,
    canonical_state_brief_path_for_target,
    load_conveyor_state,
    load_runner_state,
    render_canonical_state_brief,
    state_snapshot,
    validate_state_database,
    write_canonical_state_brief,
    write_runner_state,
)


class StateStoreTests(unittest.TestCase):
    def test_initializes_sqlite_and_generated_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"

            state = load_conveyor_state(projection_path)
            snapshot = state_snapshot(target)

            self.assertEqual(2, state["schema_version"])
            self.assertEqual("sqlite", snapshot["authority"])
            self.assertEqual("ok", snapshot["status"])
            self.assertGreaterEqual(snapshot["counts"]["events"], 1)
            self.assertTrue(Path(snapshot["database"]["path"]).exists())
            self.assertTrue(projection_path.exists())
            projected = json.loads(projection_path.read_text(encoding="utf-8"))
            self.assertEqual("sqlite", projected["canonical_state"]["authority"])
            self.assertEqual(CONVEYOR_PROJECTION_NAME, projected["canonical_state"]["projection"])
            self.assertEqual("sqlite", projected["state_machine"]["authority"])
            self.assertEqual("intake", projected["state_machine"]["current_stage"])
            self.assertEqual(10, len(projected["state_machine"]["stage_contracts"]))
            self.assertIn("capability_manifest", snapshot)
            self.assertTrue(snapshot["capability_manifest"]["digest"])

    def test_legacy_json_is_imported_once_as_compatibility_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            projection_path.parent.mkdir(parents=True, exist_ok=True)
            projection_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "cycles": 7,
                        "role_counts": {"builder": 3},
                        "history": [{"role": "builder", "exit_code": 0}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            imported = load_conveyor_state(projection_path)
            first_snapshot = state_snapshot(target)
            loaded_again = load_conveyor_state(projection_path)
            second_snapshot = state_snapshot(target)

            self.assertEqual(7, imported["cycles"])
            self.assertEqual(7, loaded_again["cycles"])
            self.assertEqual(first_snapshot["counts"]["events"], second_snapshot["counts"]["events"])
            self.assertEqual("compatibility.legacy_conveyor_json_imported", first_snapshot["last_event"]["event_type"])

    def test_conveyor_write_state_materializes_typed_next_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projection_path = Path(tmp) / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["decision_queue"] = [
                {"role": "builder", "state": "next", "reason": "builder lane is next runnable work"},
                {"role": "hardener", "state": "standby", "reason": "verify recently changed work"},
            ]

            write_state(
                projection_path,
                state,
                event_type="test.decision_recorded",
                actor_role="test",
                phase="decision",
            )
            snapshot = state_snapshot(Path(tmp))
            validation = validate_state_database(Path(tmp))

            self.assertEqual("pass", validation["status"])
            self.assertEqual(2, len(snapshot["next_actions"]))
            self.assertEqual("builder", snapshot["next_actions"][0]["owner_role"])
            self.assertEqual("test.decision_recorded", snapshot["last_event"]["event_type"])

            db = sqlite3.connect(snapshot["database"]["path"])
            try:
                event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                projection_count = db.execute("SELECT COUNT(*) FROM projections").fetchone()[0]
            finally:
                db.close()
            self.assertGreaterEqual(event_count, 2)
            self.assertGreaterEqual(projection_count, 3)

    def test_builder_role_owns_implementation_even_when_reason_mentions_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["last_decision"] = {
                "role": "builder",
                "reason": "builder-first policy: last integration accepted no patches",
                "decided_at": "2026-05-12T22:06:54+00:00",
            }

            write_state(
                projection_path,
                state,
                event_type="conveyor.decision_recorded",
                actor_role="conveyor",
                phase="decision",
            )
            decision_machine = state_snapshot(target)["conveyor_machine"]
            self.assertEqual("implementation", decision_machine["current_stage"])
            self.assertEqual("ready", decision_machine["stage_status"])
            self.assertEqual("builder", decision_machine["owner_role"])

            state["active_role_run"] = {
                "role": "builder",
                "run_id": "20260512T220654Z-conveyor-builder",
                "status": "running",
                "reason": "builder-first policy: last integration accepted no patches",
                "started_at": "2026-05-12T22:06:54+00:00",
            }
            write_state(
                projection_path,
                state,
                event_type="role_run.started",
                actor_role="builder",
                phase="role_execution",
            )
            running_machine = state_snapshot(target)["conveyor_machine"]
            latest_attempt = running_machine["stage_attempts"][0]

            self.assertEqual("implementation", running_machine["current_stage"])
            self.assertEqual("running", running_machine["stage_status"])
            self.assertEqual("builder", running_machine["owner_role"])
            self.assertEqual("builder", running_machine["work_item"]["workspace_id"])
            self.assertEqual("implementation", latest_attempt["stage"])
            self.assertEqual("builder", latest_attempt["owner_role"])
            self.assertEqual("pass", validate_state_database(target)["status"])

    def test_planner_decision_owns_planning_even_when_reason_mentions_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["last_decision"] = {
                "role": "planner",
                "reason": "hardener completed; planner gets the next state-machine pass",
                "decided_at": "2026-05-12T23:11:51+00:00",
            }

            write_state(
                projection_path,
                state,
                event_type="conveyor.decision_recorded",
                actor_role="conveyor",
                phase="decision",
            )
            machine = state_snapshot(target)["conveyor_machine"]

            self.assertEqual("planning", machine["current_stage"])
            self.assertEqual("ready", machine["stage_status"])
            self.assertEqual("planner", machine["owner_role"])
            self.assertEqual("pass", validate_state_database(target)["status"])

    def test_role_decision_owns_stage_even_when_reason_mentions_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["last_decision"] = {
                "role": "builder",
                "reason": "builder implements user-facing error recovery",
                "decided_at": "2026-05-12T23:30:00+00:00",
            }

            write_state(
                projection_path,
                state,
                event_type="conveyor.decision_recorded",
                actor_role="conveyor",
                phase="decision",
            )
            machine = state_snapshot(target)["conveyor_machine"]

            self.assertEqual("implementation", machine["current_stage"])
            self.assertEqual("ready", machine["stage_status"])
            self.assertEqual("builder", machine["owner_role"])
            self.assertEqual("pass", validate_state_database(target)["status"])

    def test_validation_files_materialize_as_typed_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            runtime_dir = target / "target"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "baseline_verification.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "passing",
                        "checks_run": ["python3 -m unittest"],
                        "first_seen_at": "2026-05-12T10:00:00+00:00",
                        "last_seen_at": "2026-05-12T10:02:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            (runtime_dir / "integration_safety_check.json").write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "command": "python3 scripts/check_integration_safety.py",
                        "checked_at": "2026-05-12T10:03:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            snapshot = state_snapshot(target)
            machine = snapshot["conveyor_machine"]
            receipts = machine["validation_receipts"]

            self.assertEqual("passed", machine["work_item"]["validation_status"])
            self.assertEqual(2, len(receipts))
            self.assertEqual(
                {"baseline_verification", "integration_safety"},
                {receipt["kind"] for receipt in receipts},
            )

    def test_false_positive_baseline_blocker_is_superseded_with_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            runtime_dir = target / "target"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "baseline_verification.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "blocked_environment",
                        "category": "missing_env_var",
                        "root_cause": "Missing required environment variable `EBADENGINE`.",
                        "failure_signature": "verification_environment_failure:missing_env_var:abc",
                        "checks_run": ["npm ci", "npm test"],
                        "detail": "\n".join(
                            [
                                "$ npm ci",
                                "exit=0",
                                "npm warn EBADENGINE Unsupported engine {",
                                "npm warn EBADENGINE   required: { node: '^20.19.0 || ^22.13.0 || >=24' }",
                                "npm warn EBADENGINE }",
                            ]
                        ),
                        "first_seen_at": "2026-05-12T10:00:00+00:00",
                        "last_seen_at": "2026-05-12T10:02:00+00:00",
                    }
                ),
                encoding="utf-8",
            )

            snapshot = state_snapshot(target)
            machine = snapshot["conveyor_machine"]
            receipts = machine["validation_receipts"]

            self.assertEqual("warning", machine["work_item"]["validation_status"])
            self.assertEqual("warn", receipts[0]["status"])
            self.assertEqual([], snapshot["open_blockers"])

            db = sqlite3.connect(snapshot["database"]["path"])
            db.row_factory = sqlite3.Row
            try:
                row = db.execute("SELECT status, payload_json FROM blockers WHERE kind = 'baseline_verification'").fetchone()
            finally:
                db.close()
            self.assertIsNotNone(row)
            self.assertEqual("superseded", row["status"])
            payload = json.loads(row["payload_json"])
            review = payload["blocker_review"]
            self.assertEqual("false_positive", review["verdict"])
            self.assertFalse(review["is_blocker"])
            self.assertTrue(review["rerun_recommended"])

    def test_task_markdown_seeds_control_once_but_is_not_live_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            task = target / "docs" / "CODEX_AUTOMATION_TASKS.md"
            task.parent.mkdir(parents=True)
            task.write_text(
                "AUTOMATION_STATUS: ACTIVE\n"
                "\n"
                "Last updated: initial\n"
                "\n"
                "## Product Horizon State\n"
                "\n"
                "- Current horizon: H1 Runnable baseline\n"
                "- Advancement decision: stay\n"
                "\n"
                "## Best Next Milestone\n"
                "\n"
                "Prove typed state owns automation control.\n",
                encoding="utf-8",
            )

            seeded = automation_control_state(target)
            task.write_text(
                "AUTOMATION_STATUS: CRITICAL_STOP\n"
                "\n"
                "## Product Horizon State\n"
                "\n"
                "- Current horizon: H9 Poisoned Markdown\n"
                "- Advancement decision: advance\n",
                encoding="utf-8",
            )
            loaded = automation_control_state(target)

            self.assertEqual("ACTIVE", seeded["status"])
            self.assertEqual("ACTIVE", loaded["status"])
            self.assertEqual("H1 Runnable baseline", loaded["horizon"])
            self.assertNotEqual("H9 Poisoned Markdown", loaded["horizon"])

    def test_runner_state_is_sqlite_backed_with_json_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_runner.json"

            write_runner_state(
                projection_path,
                {"schema_version": 1, "state": "running", "pid": 1234, "started_at": "2026-05-03T22:30:00+00:00"},
            )
            loaded = load_runner_state(projection_path)
            projected = json.loads(projection_path.read_text(encoding="utf-8"))
            snapshot = state_snapshot(target)

            self.assertEqual("running", loaded["state"])
            self.assertEqual("sqlite", projected["canonical_state"]["authority"])
            self.assertEqual(RUNNER_PROJECTION_NAME, projected["canonical_state"]["projection"])
            self.assertGreaterEqual(snapshot["counts"]["events"], 2)

    def test_canonical_state_brief_is_bounded_markdown_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            projection_path = target / "target" / "automation_conveyor_state.json"
            state = load_state(projection_path)
            state["decision_queue"] = [
                {"role": "builder", "state": "next", "reason": "build the next small reusable increment"}
            ]
            write_state(projection_path, state, event_type="test.brief_decision")

            result = write_canonical_state_brief(target)
            brief_path = canonical_state_brief_path_for_target(target)
            markdown = brief_path.read_text(encoding="utf-8")

            self.assertEqual(str(brief_path), result["path"])
            self.assertIn("# Canonical State Brief", markdown)
            self.assertIn("authority: SQLite orchestration state is canonical", markdown)
            self.assertIn("target/orchestration.sqlite3", markdown)
            self.assertIn("builder: next", markdown)
            self.assertNotIn(str(target), markdown)

            rendered = render_canonical_state_brief(state_snapshot(target), target=target)
            self.assertIn("## Projection Freshness", rendered)


if __name__ == "__main__":
    unittest.main()
