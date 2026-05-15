from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.conveyor.state import load_state, write_state
from diffmogger.runtime.state_store import (
    CONVEYOR_PROJECTION_NAME,
    RUNNER_PROJECTION_NAME,
    STATE_SCHEMA_VERSION,
    automation_control_state,
    can_start_execution_group,
    can_start_worker,
    canonical_state_brief_path_for_target,
    connect,
    database_path_for_target,
    load_conveyor_state,
    load_runner_state,
    parallelism_budgets_conn,
    render_canonical_state_brief,
    run_parallel_validation_conn,
    state_snapshot,
    validate_state_database,
    validation_jobs_conn,
    write_canonical_state_brief,
    write_runner_state,
    write_ticket_run_state,
)


class StateStoreTests(unittest.TestCase):
    def _write_intake(
        self,
        target: Path,
        *,
        worker_agents_allowed: bool = True,
        write_worker_agents_allowed: bool = False,
        max_write_worker_count: int = 0,
    ) -> None:
        agentic = target / ".agentic"
        agentic.mkdir(parents=True, exist_ok=True)
        (agentic / "project_intake.json").write_text(
            json.dumps(
                {
                    "project_name": "Parallel Budget Demo",
                    "product_goal": "Exercise reusable automation budget state.",
                    "target_user": "A local automation maintainer.",
                    "desired_first_demo": "Show budgeted conveyor state.",
                    "worker_agents_allowed": worker_agents_allowed,
                    "write_worker_agents_allowed": write_worker_agents_allowed,
                    "max_write_worker_count": max_write_worker_count,
                }
            ),
            encoding="utf-8",
        )

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
            self.assertEqual(STATE_SCHEMA_VERSION, snapshot["database"]["user_version"])
            self.assertIn("schema_migrations", snapshot["counts"])
            self.assertIn(STATE_SCHEMA_VERSION, {item["version"] for item in snapshot["schema_migrations"]})
            self.assertEqual("pass", snapshot["state_health_summary"]["status"])
            self.assertTrue(all(item["ok"] for item in snapshot["invariant_results"]))

    def test_parallelism_budget_defaults_disable_write_workers_until_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self._write_intake(
                target,
                worker_agents_allowed=True,
                write_worker_agents_allowed=False,
                max_write_worker_count=5,
            )

            snapshot = state_snapshot(target)
            budget_by_scope = {item["scope"]: item for item in snapshot["parallelism_budgets"]}

            self.assertTrue(budget_by_scope["read_only_workers"]["enabled"])
            self.assertEqual(3, budget_by_scope["read_only_workers"]["max_concurrent"])
            self.assertFalse(budget_by_scope["write_workers"]["enabled"])
            self.assertEqual(0, budget_by_scope["write_workers"]["max_concurrent"])
            self.assertIn("active_parallel_counts", snapshot)
            self.assertIn("budget_exhaustion_reasons", snapshot)

            with closing(connect(database_path_for_target(target))) as conn:
                self.assertTrue(can_start_worker(conn, "read_only", owner_role="builder")["allowed"])
                write_check = can_start_worker(conn, "write", owner_role="builder")
            self.assertFalse(write_check["allowed"])
            self.assertTrue(any("write_workers" in reason for reason in write_check["reasons"]))

    def test_write_worker_budget_respects_max_write_worker_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self._write_intake(
                target,
                worker_agents_allowed=True,
                write_worker_agents_allowed=True,
                max_write_worker_count=3,
            )

            state_snapshot(target)
            with closing(connect(database_path_for_target(target))) as conn:
                budgets = {item["scope"]: item for item in parallelism_budgets_conn(conn)}
                write_check = can_start_worker(conn, "write", owner_role="builder")

            self.assertTrue(budgets["write_workers"]["enabled"])
            self.assertEqual(3, budgets["write_workers"]["max_concurrent"])
            self.assertEqual(3, budgets["write_workers"]["max_per_role"]["builder"])
            self.assertTrue(write_check["allowed"])

    def test_active_execution_group_count_prevents_starting_new_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            state_snapshot(target)
            with closing(connect(database_path_for_target(target))) as conn:
                conn.execute(
                    """
                    UPDATE parallelism_budgets
                    SET max_concurrent = 1, enabled = 1, source = 'test'
                    WHERE scope = 'global'
                    """
                )
                conn.execute(
                    """
                    INSERT INTO execution_groups(
                        execution_group_id, status, mode, created_at, selected_by, reason, payload_json
                    )
                    VALUES(?, 'running', 'mixed', '2026-05-14T00:00:00+00:00', 'test', 'occupy slot', '{}')
                    """,
                    ("execution-group:test-running",),
                )
                conn.commit()
                check = can_start_execution_group(conn, "mixed", item_count=1)

            self.assertFalse(check["allowed"])
            self.assertTrue(any("global" in reason for reason in check["reasons"]))

    def test_read_only_budget_does_not_authorize_write_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self._write_intake(
                target,
                worker_agents_allowed=True,
                write_worker_agents_allowed=False,
                max_write_worker_count=0,
            )

            state_snapshot(target)
            with closing(connect(database_path_for_target(target))) as conn:
                read_only_check = can_start_worker(conn, "read_only", owner_role="planner")
                write_check = can_start_worker(conn, "write", owner_role="planner")

            self.assertTrue(read_only_check["allowed"])
            self.assertFalse(write_check["allowed"])

    def test_parallelism_budget_summary_appears_in_snapshot_and_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self._write_intake(
                target,
                worker_agents_allowed=True,
                write_worker_agents_allowed=True,
                max_write_worker_count=2,
            )

            snapshot = state_snapshot(target)
            rendered = render_canonical_state_brief(snapshot, target=target)

            self.assertIn("parallelism_budgets", snapshot)
            self.assertIn("active_parallel_counts", snapshot)
            self.assertIn("budget_exhaustion_reasons", snapshot)
            self.assertTrue(any(item["scope"] == "write_workers" for item in snapshot["parallelism_budgets"]))
            self.assertEqual(0, snapshot["active_parallel_counts"]["active_write_workers"])
            self.assertIn("scope=write_workers", rendered)

    def test_parallel_validation_runs_independent_commands_as_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            src = target / "src"
            src.mkdir(parents=True)
            (src / "one.py").write_text("VALUE = 1\n", encoding="utf-8")
            (src / "two.py").write_text("VALUE = 2\n", encoding="utf-8")

            commands = [
                {"command": f"{sys.executable} -m py_compile {src / 'one.py'}", "gate_id": "gate:one"},
                {"command": f"{sys.executable} -m py_compile {src / 'two.py'}", "gate_id": "gate:two"},
            ]
            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(conn, target, commands, selected_by="test", plan_id="plan:parallel")
                jobs = validation_jobs_conn(conn, limit=10)

            self.assertEqual("passed", result["status"])
            self.assertEqual(2, result["parallel_job_count"])
            self.assertEqual(0, result["serial_job_count"])
            self.assertEqual(2, len(result["jobs"]))
            self.assertEqual({"passed"}, {job["status"] for job in jobs})
            self.assertEqual({"read_only_check"}, {job["payload"]["classification"] for job in jobs})

    def test_parallel_validation_exclusive_command_runs_serially(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = f"{sys.executable} -c \"print('exclusive validation')\""

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [{"command": command, "classification": "exclusive", "exclusive": True, "gate_id": "gate:exclusive"}],
                    selected_by="test",
                    plan_id="plan:exclusive",
                )
                jobs = validation_jobs_conn(conn, limit=5)

            self.assertEqual("passed", result["status"])
            self.assertEqual(0, result["parallel_job_count"])
            self.assertEqual(1, result["serial_job_count"])
            self.assertEqual(1, len(jobs))
            self.assertTrue(jobs[0]["payload"]["exclusive"])
            self.assertEqual("exclusive", jobs[0]["payload"]["classification"])

    def test_parallel_validation_failed_required_job_fails_aggregate_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = f"{sys.executable} -c \"import sys; sys.exit(7)\""

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [{"command": command, "classification": "test", "required": True, "gate_id": "gate:required"}],
                    selected_by="test",
                    plan_id="plan:required-fail",
                )
                receipt = conn.execute(
                    "SELECT status FROM validation_receipts WHERE run_id = ?",
                    (result["execution_group_id"],),
                ).fetchone()

            self.assertEqual("failed", result["status"])
            self.assertEqual("failed", result["validation_job_summary"]["aggregate_status"])
            self.assertEqual("failed", result["jobs"][0]["status"])
            self.assertIsNotNone(receipt)
            self.assertEqual("fail", receipt["status"])

    def test_parallel_validation_optional_failed_job_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = f"{sys.executable} -c \"import sys; sys.exit(3)\""

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [{"command": command, "classification": "test", "required": False, "gate_id": "gate:optional"}],
                    selected_by="test",
                    plan_id="plan:optional-fail",
                )

            self.assertEqual("warning", result["status"])
            self.assertEqual("warning", result["validation_job_summary"]["aggregate_status"])
            self.assertEqual("warning", result["jobs"][0]["status"])

    def test_parallel_validation_records_log_artifact_and_snapshot_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = (
                f"{sys.executable} -c \"import sys; "
                "print('validation stdout marker'); "
                "print('validation stderr marker', file=sys.stderr)\""
            )

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [{"command": command, "classification": "test", "gate_id": "gate:logs"}],
                    selected_by="test",
                    plan_id="plan:logs",
                )
                artifact = conn.execute(
                    "SELECT * FROM artifacts WHERE artifact_id = ?",
                    (result["jobs"][0]["log_artifact_id"],),
                ).fetchone()

            self.assertIsNotNone(artifact)
            log_path = target / artifact["path"]
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("validation stdout marker", log_text)
            self.assertIn("validation stderr marker", log_text)

            snapshot = state_snapshot(target)
            rendered = render_canonical_state_brief(snapshot, target=target)
            self.assertEqual("passed", snapshot["validation_job_summary"]["aggregate_status"])
            self.assertTrue(snapshot["parallel_validation_available"])
            self.assertIn("validation_jobs:", rendered)
            self.assertNotIn("## stdout", json.dumps(snapshot["validation_job_summary"]))
            self.assertNotIn("## stderr", json.dumps(snapshot["validation_job_summary"]))

    def test_older_user_version_upgrades_through_schema_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            snapshot = state_snapshot(target)
            db_path = snapshot["database"]["path"]

            db = sqlite3.connect(db_path)
            try:
                db.execute("DROP TABLE schema_migrations")
                db.execute("PRAGMA user_version = 3")
                db.commit()
            finally:
                db.close()

            upgraded = state_snapshot(target)
            validation = validate_state_database(target)

            self.assertEqual(STATE_SCHEMA_VERSION, upgraded["database"]["user_version"])
            self.assertIn(STATE_SCHEMA_VERSION, {item["version"] for item in upgraded["schema_migrations"]})
            self.assertEqual("pass", upgraded["state_health_summary"]["status"])
            self.assertEqual("pass", validation["status"])

    def test_invalid_event_hash_chain_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            snapshot = state_snapshot(target)
            db = sqlite3.connect(snapshot["database"]["path"])
            try:
                event_id = db.execute("SELECT event_id FROM events ORDER BY event_id ASC LIMIT 1").fetchone()[0]
                db.execute("UPDATE events SET event_hash = ? WHERE event_id = ?", ("not-a-valid-hash", event_id))
                db.commit()
            finally:
                db.close()

            validation = validate_state_database(target)
            hash_items = [item for item in validation["items"] if item.get("invariant") == "events.hash_chain"]

            self.assertEqual("fail", validation["status"])
            self.assertEqual("fail", validation["state_health_summary"]["status"])
            self.assertEqual(1, len(hash_items))
            self.assertFalse(hash_items[0]["ok"])
            self.assertTrue(hash_items[0]["failures"])

    def test_missing_required_projection_event_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            snapshot = state_snapshot(target)
            db = sqlite3.connect(snapshot["database"]["path"])
            try:
                db.execute(
                    "UPDATE projections SET event_id = ? WHERE name = ?",
                    (999999, CONVEYOR_PROJECTION_NAME),
                )
                db.commit()
            finally:
                db.close()

            validation = validate_state_database(target)
            projection_items = [
                item for item in validation["items"] if item.get("invariant") == "projections.event_id_exists"
            ]

            self.assertEqual("fail", validation["status"])
            self.assertEqual(1, len(projection_items))
            self.assertFalse(projection_items[0]["ok"])

    def test_state_snapshot_includes_invariant_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = state_snapshot(Path(tmp))
            invariant_names = {item["name"] for item in snapshot["invariant_results"]}

            self.assertEqual("pass", snapshot["state_health_summary"]["status"])
            self.assertIn("events.sequence_contiguous", invariant_names)
            self.assertIn("events.hash_chain", invariant_names)
            self.assertIn("projections.event_id_exists", invariant_names)

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

    def test_ticket_progress_advances_ticket_campaign_control_from_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            agentic = target / ".agentic"
            agentic.mkdir(parents=True)
            (agentic / "project_intake.json").write_text(
                json.dumps(
                    {
                        "project_name": "Ticket Campaign Demo",
                        "campaign_mode": "bounded",
                    }
                ),
                encoding="utf-8",
            )

            seeded = automation_control_state(target)
            self.assertEqual("T1 Ticket-run readiness", seeded["horizon"])

            write_ticket_run_state(
                target,
                {
                    "run_id": "ticket-campaign-demo",
                    "tickets": [
                        {
                            "id": "TICKET-001",
                            "summary": "Create the first reusable increment",
                            "status": "done",
                            "evidence": ["Verified locally."],
                        },
                        {
                            "id": "TICKET-002",
                            "summary": "Implement the next bounded increment",
                            "status": "pending",
                        },
                    ],
                },
                actor_role="integrator",
                event_type="ticket.run_reconciled",
            )

            control = automation_control_state(target)
            self.assertEqual("T2 Ticket implementation", control["horizon"])
            self.assertEqual("advance", control["horizon_decision"])
            self.assertEqual("bootstrapped", control["bootstrap_status"])
            self.assertIn("1/2 done", control["current_assessment"])
            self.assertIn("next dependency-ready ticket", control["best_next_milestone"])

            brief = write_canonical_state_brief(target)
            markdown = Path(brief["path"]).read_text(encoding="utf-8")
            self.assertIn("current_horizon: T2 Ticket implementation", markdown)
            self.assertIn('counts={"done":1,"pending":1}', markdown)

            db = sqlite3.connect(target / "target" / "orchestration.sqlite3")
            try:
                event_types = [
                    row[0]
                    for row in db.execute(
                        "SELECT event_type FROM events WHERE phase = 'automation_control' ORDER BY event_id"
                    ).fetchall()
                ]
            finally:
                db.close()
            self.assertIn("automation.control_updated", event_types)

    def test_candidate_and_terminal_ticket_states_drive_later_campaign_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            agentic = target / ".agentic"
            agentic.mkdir(parents=True)
            (agentic / "project_intake.json").write_text(
                json.dumps(
                    {
                        "project_name": "Ticket Campaign Demo",
                        "campaign_mode": "bounded",
                    }
                ),
                encoding="utf-8",
            )

            write_ticket_run_state(
                target,
                {
                    "run_id": "ticket-campaign-demo",
                    "tickets": [
                        {"id": "TICKET-001", "summary": "First increment", "status": "done"},
                        {"id": "TICKET-002", "summary": "Candidate increment", "status": "candidate_done"},
                        {"id": "TICKET-003", "summary": "Next increment", "status": "pending"},
                    ],
                },
                actor_role="integrator",
                event_type="ticket.run_reconciled",
            )
            verifying = automation_control_state(target)
            self.assertEqual("T3 Verification and hardening", verifying["horizon"])
            self.assertIn("candidate ticket", verifying["best_next_milestone"])

            write_ticket_run_state(
                target,
                {
                    "run_id": "ticket-campaign-demo",
                    "tickets": [
                        {"id": "TICKET-001", "summary": "First increment", "status": "done"},
                        {"id": "TICKET-002", "summary": "Second increment", "status": "done"},
                    ],
                },
                actor_role="integrator",
                event_type="ticket.run_reconciled",
            )
            complete = automation_control_state(target)
            self.assertEqual("T4 Completion report and stop", complete["horizon"])
            self.assertEqual("complete", complete["bootstrap_status"])
            self.assertIn("completion report", complete["best_next_milestone"])

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
