from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.conveyor.state import load_state, write_state
from diffmogger.runtime import state_store as state_store_module
from diffmogger.runtime.state_store import (
    AUTOMATION_ACTIVITY_PROJECTION_NAME,
    RUNNER_PROJECTION_NAME,
    STATE_SCHEMA_VERSION,
    automation_control_state,
    build_symbol_aware_validation_plan_conn,
    can_start_execution_group,
    can_start_worker,
    canonical_state_brief_path_for_target,
    connect,
    create_repair_nodes_for_failed_validation_conn,
    create_refresh_index_nodes_for_stale_evidence_conn,
    database_path_for_target,
    ensure_codebase_graph_conn,
    compact_runtime_telemetry_conn,
    conveyor_machine_payload,
    execution_dag_action_capabilities,
    execution_dag_edges_conn,
    execution_dag_read_model,
    failed_validation_jobs_requiring_dag_action_conn,
    import_legacy_target_state,
    load_conveyor_state,
    load_runner_state,
    materialize_execution_dag_conn,
    patch_lineage_summary_conn,
    parallelism_budgets_conn,
    reconcile_worker_results_into_execution_dag_conn,
    render_canonical_state_brief,
    record_runtime_phase_timing_conn,
    refresh_capability_manifest_conn,
    runtime_performance_summary_conn,
    run_refresh_index_node_conn,
    run_parallel_validation_conn,
    stable_json,
    state_snapshot,
    upsert_execution_dag_edge,
    upsert_execution_dag_node,
    upsert_worker_patch_lineage_conn,
    validate_state_database,
    validation_jobs_conn,
    worker_patch_lineage_conn,
    write_canonical_state_brief,
    write_runner_state,
    write_ticket_run_state,
)


class StateStoreTests(unittest.TestCase):
    def _activity_machine(self, target: Path) -> dict:
        with closing(connect(database_path_for_target(target))) as conn:
            return conveyor_machine_payload(conn, target)

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
                    "desired_first_demo": "Show budgeted activity state.",
                    "worker_agents_allowed": worker_agents_allowed,
                    "write_worker_agents_allowed": write_worker_agents_allowed,
                    "max_write_worker_count": max_write_worker_count,
                }
            ),
            encoding="utf-8",
        )

    def _seed_worker_patch_for_preflight(
        self,
        conn: sqlite3.Connection,
        *,
        patch_id: str,
        changed_files: list[str] | None = None,
        patch_path: str = "target/automation_queue/builder/run/changes.patch",
        base_commit: str = "",
        queued_at: str = "2026-05-15T00:00:00+00:00",
        leases: list[dict[str, object]] | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        worker_id = f"worker:{patch_id}"
        conn.execute(
            """
            INSERT INTO worker_agents(
                worker_id, execution_group_id, run_id, mode, role, status,
                context_pack_id, started_at, finished_at, payload_json
            )
            VALUES(?, 'execution-group:test', ?, 'write', 'builder', 'completed', '', ?, ?, '{}')
            """,
            (worker_id, patch_id, queued_at, queued_at),
        )
        conn.execute(
            """
            INSERT INTO worker_patches(
                patch_id, worker_id, execution_group_id, status, manifest_path,
                patch_path, changed_files_json, base_commit, leases_json,
                validation_evidence_json, conflict_signature, created_at,
                queued_at, integrated_at, payload_json
            )
            VALUES(?, ?, 'execution-group:test', 'queued', ?, ?, ?, ?, ?, '[]', '', ?, ?, '', ?)
            """,
            (
                patch_id,
                worker_id,
                f"target/automation_queue/builder/{patch_id}/manifest.json",
                patch_path,
                stable_json(changed_files or []),
                base_commit,
                stable_json(leases or []),
                queued_at,
                queued_at,
                stable_json(payload or {}),
            ),
        )

    def _seed_ready_integration_node(self, conn: sqlite3.Connection, patch_id: str, *, status: str = "ready") -> None:
        upsert_execution_dag_node(
            conn,
            node_id=f"dag-node:test:integrate:{patch_id}",
            task_id=f"task:{patch_id}",
            action_type="integrate",
            status=status,
            owner_role="integrator",
            patch_id=patch_id,
            patch_path=f"target/automation_queue/builder/{patch_id}/changes.patch",
            confidence=0.92,
            metadata={"source": "worker_patches", "patch_id": patch_id},
        )

    def _git_commit_all(self, target: Path, message: str) -> str:
        subprocess.run(["git", "add", "-A"], cwd=target, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Diffmogger", "-c", "user.email=diffmogger@example.invalid", "commit", "-q", "-m", message],
            cwd=target,
            check=True,
        )
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, text=True, capture_output=True, check=True).stdout.strip()

    def _worker_patch_fixture(
        self,
        target: Path,
        *,
        path: str = "src/app.py",
        before: str = "def value():\n    return 1\n",
        after: str = "def value():\n    return 2\n",
        patch_id: str = "patch:fixture",
    ) -> tuple[str, str]:
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        file_path = target / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(before, encoding="utf-8")
        base_commit = self._git_commit_all(target, "base")
        file_path.write_text(after, encoding="utf-8")
        diff = subprocess.run(["git", "diff", "--binary", "--", path], cwd=target, text=True, capture_output=True, check=True).stdout
        patch_rel = f"target/automation_queue/builder/{patch_id}/changes.patch"
        patch_path = target / patch_rel
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(diff, encoding="utf-8")
        subprocess.run(["git", "checkout", "--", path], cwd=target, check=True)
        return base_commit, patch_rel

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
            self.assertFalse(projection_path.exists())
            self.assertIn("automation_activity", snapshot)
            self.assertEqual("sqlite", snapshot["automation_activity"]["authority"])
            self.assertEqual(AUTOMATION_ACTIVITY_PROJECTION_NAME, snapshot["projection"]["name"])
            self.assertNotIn("conveyor_state", snapshot)
            self.assertNotIn("conveyor_machine", snapshot)
            self.assertIn("capability_manifest", snapshot)
            self.assertTrue(snapshot["capability_manifest"]["digest"])
            self.assertEqual(STATE_SCHEMA_VERSION, snapshot["database"]["user_version"])
            self.assertIn("schema_migrations", snapshot["counts"])
            self.assertIn(STATE_SCHEMA_VERSION, {item["version"] for item in snapshot["schema_migrations"]})
            self.assertIn("execution_dag", snapshot)
            self.assertEqual("sqlite", snapshot["execution_dag"]["authority"])
            self.assertGreater(snapshot["execution_dag"]["node_count"], 0)
            self.assertNotIn("progress_model", snapshot)
            self.assertEqual("pass", snapshot["state_health_summary"]["status"])
            self.assertTrue(all(item["ok"] for item in snapshot["invariant_results"]))

    def test_worker_patch_integration_preflight_orders_independent_patches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:a",
                        changed_files=["src/a.py"],
                        queued_at="2026-05-15T00:00:00+00:00",
                    )
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:b",
                        changed_files=["src/b.py"],
                        queued_at="2026-05-15T00:01:00+00:00",
                    )
                    self._seed_ready_integration_node(conn, "patch:a")
                    self._seed_ready_integration_node(conn, "patch:b")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            self.assertEqual(["patch:a", "patch:b"], preflight["safe_patch_ids"])
            self.assertEqual(0, preflight["likely_conflict_count"])
            self.assertEqual(
                [("patch:a", 1), ("patch:b", 2)],
                [(item["patch_id"], item["safe_order"]) for item in preflight["safe_order"]],
            )

    def test_worker_patch_integration_preflight_allows_limited_reconcilable_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:first",
                        changed_files=["src/app.py"],
                        queued_at="2026-05-15T00:00:00+00:00",
                    )
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:second",
                        changed_files=["src/app.py"],
                        queued_at="2026-05-15T00:01:00+00:00",
                    )
                    self._seed_ready_integration_node(conn, "patch:first")
                    self._seed_ready_integration_node(conn, "patch:second")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            self.assertEqual(["patch:first", "patch:second"], preflight["safe_patch_ids"])
            self.assertEqual(0, preflight["likely_conflict_count"])
            self.assertEqual(1, preflight["reconcilable_overlap_count"])
            overlap = preflight["reconcilable_overlaps"][0]
            self.assertEqual("patch:second", overlap["patch_id"])
            self.assertEqual(["patch:first"], overlap["conflict_patch_ids"])

    def test_worker_patch_integration_preflight_marks_true_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            base_commit, patch_rel = self._worker_patch_fixture(
                target,
                before="def value():\n    return 1\n",
                after="def value():\n    return 2\n",
                patch_id="patch:conflict",
            )
            (target / "src" / "app.py").write_text("def value():\n    return 3\n", encoding="utf-8")
            self._git_commit_all(target, "conflicting head")

            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:conflict",
                        changed_files=["src/app.py"],
                        patch_path=patch_rel,
                        base_commit=base_commit,
                    )
                    self._seed_ready_integration_node(conn, "patch:conflict")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            record = preflight["records"][0]
            self.assertEqual("true_conflict", record["status"])
            self.assertEqual(1, preflight["true_conflict_count"])
            self.assertEqual([], preflight["safe_patch_ids"])
            self.assertTrue(any(reason["kind"] == "integration_reconciliation_true_conflict" for reason in record["reasons"]))

    def test_worker_patch_integration_preflight_permits_already_applied_and_rebaseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            base_commit, applied_patch_rel = self._worker_patch_fixture(
                target,
                path="src/already.py",
                after="def value():\n    return 2\n",
                patch_id="patch:already",
            )
            (target / "src" / "already.py").write_text("def value():\n    return 2\n", encoding="utf-8")
            self._git_commit_all(target, "already applied")

            rebase_base, rebase_patch_rel = self._worker_patch_fixture(
                target,
                path="src/rebaseable.py",
                before="def value():\n    return 10\n",
                after="def value():\n    return 20\n",
                patch_id="patch:rebaseable",
            )
            (target / "src" / "rebaseable.py").write_text("# header\n\ndef value():\n    return 10\n", encoding="utf-8")
            self._git_commit_all(target, "same file unrelated context")

            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:already",
                        changed_files=["src/already.py"],
                        patch_path=applied_patch_rel,
                        base_commit=base_commit,
                        queued_at="2026-05-15T00:00:00+00:00",
                    )
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:rebaseable",
                        changed_files=["src/rebaseable.py"],
                        patch_path=rebase_patch_rel,
                        base_commit=rebase_base,
                        queued_at="2026-05-15T00:01:00+00:00",
                    )
                    self._seed_ready_integration_node(conn, "patch:already")
                    self._seed_ready_integration_node(conn, "patch:rebaseable")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            statuses = {record["patch_id"]: record["status"] for record in preflight["records"]}
            self.assertEqual("already_applied", statuses["patch:already"])
            self.assertEqual("rebaseable", statuses["patch:rebaseable"])
            self.assertEqual(["patch:already", "patch:rebaseable"], preflight["safe_patch_ids"])
            self.assertEqual(1, preflight["already_applied_count"])
            self.assertEqual(1, preflight["rebaseable_count"])

    def test_worker_patch_integration_preflight_blocks_protected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:protected",
                        changed_files=[".env.local"],
                    )
                    self._seed_ready_integration_node(conn, "patch:protected")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            record = preflight["records"][0]
            self.assertEqual("protected_path", record["status"])
            self.assertEqual(1, preflight["protected_path_count"])
            self.assertEqual([], preflight["safe_patch_ids"])

    def test_integrated_worker_patch_advances_ticket_to_candidate_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_ticket_run_state(
                target,
                {
                    "run_id": "ticket-run",
                    "tickets": [
                        {
                            "id": "TICKET-001",
                            "summary": "Create repository skeleton",
                            "status": "pending",
                        }
                    ],
                },
                actor_role="test",
                event_type="ticket.run_seeded",
            )
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:ticket",
                        changed_files=["src/app.py"],
                        payload={"task_id": "TICKET-001", "dag_node_id": "dag-node:test:build"},
                    )
                    upsert_worker_patch_lineage_conn(
                        conn,
                        patch_id="patch:ticket",
                        worker_id="worker:patch:ticket",
                        execution_group_id="execution-group:test",
                        task_id="TICKET-001",
                        source_dag_node_id="dag-node:test:build",
                        status="queued",
                    )
                    self._seed_ready_integration_node(conn, "patch:ticket")

                result = state_store_module.mark_worker_patches_integrated_conn(
                    conn,
                    target=target,
                    patch_ids=["patch:ticket"],
                    selected_by="test.integration",
                )
                ticket_row = conn.execute(
                    "SELECT status, payload_json FROM ticket_items WHERE ticket_id = 'TICKET-001'",
                ).fetchone()

            payload = json.loads(ticket_row["payload_json"])
            self.assertEqual("integrated", result["status"])
            self.assertEqual(["TICKET-001"], result["ticket_state"]["updated_ticket_ids"])
            self.assertEqual("candidate_done", ticket_row["status"])
            self.assertEqual("candidate_done", payload["status"])
            self.assertIn("Integrated validated worker patch patch:ticket for TICKET-001.", payload["evidence"])
            self.assertIn("Changed files: src/app.py.", payload["evidence"])
            loaded = state_store_module.load_ticket_run_state(target)
            self.assertEqual("candidate_done", loaded["tickets"][0]["status"])

    def test_role_manifest_sync_excludes_runtime_state_paths_from_patch_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            queue_dir = target / "target" / "automation_queue" / "builder" / "run-runtime"
            queue_dir.mkdir(parents=True)
            manifest_path = queue_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "role": "builder",
                        "run_id": "run-runtime",
                        "status": "queued",
                        "patch_path": "target/automation_queue/builder/run-runtime/changes.patch",
                        "changed_files": ["src/app.js"],
                        "runtime_state_changed_files": [".diffmogger/agentic/verification_commands.txt"],
                        "runtime_state_action_count": 1,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with closing(connect(database_path_for_target(target))) as conn:
                result = state_store_module.sync_queued_role_manifests_into_worker_patches_conn(conn, target)
                patch_id = result["patch_ids"][0]
                row = conn.execute("SELECT changed_files_json, payload_json FROM worker_patches WHERE patch_id = ?", (patch_id,)).fetchone()
                self._seed_ready_integration_node(conn, patch_id)

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            payload = json.loads(row["payload_json"])
            record = preflight["records"][0]
            self.assertEqual(["src/app.js"], json.loads(row["changed_files_json"]))
            self.assertEqual(["src/app.js"], payload["patch_cluster_changed_files"])
            self.assertEqual([".diffmogger/agentic/verification_commands.txt"], payload["runtime_state_changed_files"])
            self.assertNotEqual("protected_path", record["status"])
            self.assertEqual(0, preflight["protected_path_count"])

    def test_role_manifest_sync_recovers_parallel_worker_attribution_from_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            queue_dir = target / "target" / "automation_queue" / "builder" / "write-workers-sync-builder-auto-002"
            queue_dir.mkdir(parents=True)
            manifest_path = queue_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "builder",
                        "run_id": "write-workers-sync-builder-auto-002",
                        "patch_id": "worker-patch:sync",
                        "status": "queued",
                        "source": "parallel_write_worker",
                        "worker_id": "worker-agent:sync",
                        "execution_group_id": "execution-group:sync",
                        "patch_path": "target/automation_queue/builder/write-workers-sync-builder-auto-002/changes.patch",
                        "changed_files": ["src/planner.js"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            now = "2026-05-15T00:00:00+00:00"

            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            context_pack_id, started_at, finished_at, payload_json
                        )
                        VALUES('worker-agent:sync', 'execution-group:sync',
                               'write-workers-sync-builder-auto-002', 'write', 'builder',
                               'completed', '', ?, ?, '{}')
                        """,
                        (now, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path,
                            patch_path, changed_files_json, base_commit, leases_json,
                            validation_evidence_json, conflict_signature, created_at,
                            queued_at, integrated_at, payload_json
                        )
                        VALUES('worker-patch:sync', 'worker-agent:sync',
                               'execution-group:sync', 'queued',
                               'target/automation_queue/builder/write-workers-sync-builder-auto-002/manifest.json',
                               'target/automation_queue/builder/write-workers-sync-builder-auto-002/changes.patch',
                               ?, '', '[]', '[]', '', ?, ?, '', '{}')
                        """,
                        (json.dumps(["src/planner.js"]), now, now),
                    )
                    upsert_worker_patch_lineage_conn(
                        conn,
                        patch_id="worker-patch:sync",
                        worker_id="worker-agent:sync",
                        execution_group_id="execution-group:sync",
                        task_id="AUTO-002",
                        source_dag_node_id="dag-node:auto-002-build",
                        status="queued",
                    )

                result = state_store_module.sync_queued_role_manifests_into_worker_patches_conn(conn, target)
                patch_row = conn.execute(
                    "SELECT payload_json FROM worker_patches WHERE patch_id = 'worker-patch:sync'",
                ).fetchone()
                worker_row = conn.execute(
                    "SELECT payload_json FROM worker_agents WHERE worker_id = 'worker-agent:sync'",
                ).fetchone()

            self.assertEqual(["worker-patch:sync"], result["patch_ids"])
            patch_payload = json.loads(patch_row["payload_json"])
            worker_payload = json.loads(worker_row["payload_json"])
            self.assertEqual("AUTO-002", patch_payload["task_id"])
            self.assertEqual("dag-node:auto-002-build", patch_payload["dag_node_id"])
            self.assertEqual("AUTO-002", worker_payload["task_id"])
            self.assertEqual("dag-node:auto-002-build", worker_payload["dag_node_id"])
            self.assertEqual("parallel_write_worker", patch_payload["source"])

    def test_role_manifest_sync_clears_deferred_manifest_from_queued_worker_patches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            run_id = "run-deferred"
            queue_dir = target / "target" / "automation_queue" / "builder" / run_id
            queue_dir.mkdir(parents=True)
            manifest_path = queue_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "role": "builder",
                        "run_id": run_id,
                        "patch_id": "patch:stale-deferred",
                        "status": "deferred",
                        "patch_path": f"target/automation_queue/builder/{run_id}/changes.patch",
                        "changed_files": ["src/app.py"],
                        "deferral_reason": "verification_failure",
                        "deferral_detail": "Required verification failed after integration attempt.",
                        "integrated_at": "2026-05-20T15:37:25+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path.with_name("changes.patch").write_text("diff --git a/src/app.py b/src/app.py\n", encoding="utf-8")

            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:stale-deferred",
                        changed_files=["src/app.py"],
                        patch_path=f"target/automation_queue/builder/{run_id}/changes.patch",
                        payload={"task_id": "TICKET-001", "dag_node_id": "dag-node:test:build"},
                    )
                    self._seed_ready_integration_node(conn, "patch:stale-deferred")

                result = state_store_module.sync_queued_role_manifests_into_worker_patches_conn(conn, target, selected_by="test")
                patch_row = conn.execute("SELECT status, queued_at, payload_json FROM worker_patches WHERE patch_id = ?", ("patch:stale-deferred",)).fetchone()
                integration_row = conn.execute(
                    "SELECT status, blocker_reason FROM execution_dag_nodes WHERE patch_id = ? AND action_type = 'integrate'",
                    ("patch:stale-deferred",),
                ).fetchone()
                lineages = worker_patch_lineage_conn(conn, patch_id="patch:stale-deferred")

            payload = json.loads(patch_row["payload_json"])
            self.assertEqual(["patch:stale-deferred"], result["terminal_patch_ids"])
            self.assertEqual("deferred", patch_row["status"])
            self.assertEqual("", patch_row["queued_at"])
            self.assertEqual("verification_failure", payload["deferral_reason"])
            self.assertEqual("superseded", integration_row["status"])
            self.assertIn("deferred queued patch", integration_row["blocker_reason"])
            self.assertEqual("deferred", lineages[0]["status"])
            self.assertEqual("deferred", lineages[0]["integration_result"])

    def test_role_manifest_sync_clears_applied_manifest_from_queued_worker_patches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            run_id = "run-applied"
            queue_dir = target / "target" / "automation_queue" / "hardener" / run_id
            queue_dir.mkdir(parents=True)
            manifest_path = queue_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "role": "hardener",
                        "run_id": run_id,
                        "patch_id": "patch:stale-applied",
                        "status": "applied",
                        "patch_path": f"target/automation_queue/hardener/{run_id}/changes.patch",
                        "changed_files": ["tests/app.test.py"],
                        "integrated_at": "2026-05-20T15:40:00+00:00",
                        "accepted_commit": "abc123",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path.with_name("changes.patch").write_text("diff --git a/tests/app.test.py b/tests/app.test.py\n", encoding="utf-8")

            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:stale-applied",
                        changed_files=["tests/app.test.py"],
                        patch_path=f"target/automation_queue/hardener/{run_id}/changes.patch",
                        payload={"task_id": "TICKET-002", "dag_node_id": "dag-node:test:harden"},
                    )
                    self._seed_ready_integration_node(conn, "patch:stale-applied")

                result = state_store_module.sync_queued_role_manifests_into_worker_patches_conn(conn, target, selected_by="test")
                patch_row = conn.execute(
                    "SELECT status, queued_at, integrated_at, payload_json FROM worker_patches WHERE patch_id = ?",
                    ("patch:stale-applied",),
                ).fetchone()
                integration_row = conn.execute(
                    "SELECT status FROM execution_dag_nodes WHERE patch_id = ? AND action_type = 'integrate'",
                    ("patch:stale-applied",),
                ).fetchone()
                lineages = worker_patch_lineage_conn(conn, patch_id="patch:stale-applied")

            payload = json.loads(patch_row["payload_json"])
            self.assertEqual(["patch:stale-applied"], result["terminal_patch_ids"])
            self.assertEqual("integrated", patch_row["status"])
            self.assertEqual("", patch_row["queued_at"])
            self.assertEqual("2026-05-20T15:40:00+00:00", patch_row["integrated_at"])
            self.assertEqual("abc123", payload["accepted_commit"])
            self.assertEqual("done", integration_row["status"])
            self.assertEqual("integrated", lineages[0]["status"])
            self.assertEqual("integrated", lineages[0]["integration_result"])

    def test_reconciling_worker_patch_handoff_preserves_completed_review_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:build",
                        task_id="TICKET-001",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.91,
                        metadata={"summary": "Build input action state"},
                    )
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:handoff",
                        changed_files=["src/input.ts"],
                        payload={"task_id": "TICKET-001", "dag_node_id": "dag-node:test:build"},
                    )

                first = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                review_node_id = str(first["review_nodes"][0]["node_id"])
                validation_node_id = str(first["validation_nodes"][0]["node_id"])
                state_store_module.update_execution_dag_node_status_conn(
                    conn,
                    review_node_id,
                    status="done",
                    selected_by="test.review",
                )

                second = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                model = execution_dag_read_model(conn)
                review_row = conn.execute(
                    "SELECT status, attempt_count, finished_at FROM execution_dag_nodes WHERE node_id = ?",
                    (review_node_id,),
                ).fetchone()
                validation_row = conn.execute(
                    "SELECT status FROM execution_dag_nodes WHERE node_id = ?",
                    (validation_node_id,),
                ).fetchone()

            ready_ids = {str(node.get("node_id") or "") for node in model["all_ready_nodes"]}
            self.assertEqual("done", second["review_nodes"][0]["status"])
            self.assertEqual("done", review_row["status"])
            self.assertEqual(1, review_row["attempt_count"])
            self.assertTrue(review_row["finished_at"])
            self.assertEqual("ready", validation_row["status"])
            self.assertNotIn(review_node_id, ready_ids)
            self.assertIn(validation_node_id, ready_ids)

    def test_reconcile_reopens_blocked_worker_validation_after_completed_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:build",
                        task_id="TICKET-031",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.91,
                        metadata={"summary": "Build input action state"},
                    )
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:needs-validation-retry",
                        changed_files=["src/input.ts", "tests/input.test.ts"],
                        payload={"task_id": "TICKET-031", "dag_node_id": "dag-node:test:build"},
                    )

                first = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                review_node_id = str(first["review_nodes"][0]["node_id"])
                validation_node_id = str(first["validation_nodes"][0]["node_id"])
                state_store_module.update_execution_dag_node_status_conn(
                    conn,
                    review_node_id,
                    status="done",
                    selected_by="test.review",
                )
                validation_node = next(
                    node
                    for node in execution_dag_read_model(conn)["nodes"]
                    if node["node_id"] == validation_node_id
                )
                metadata = dict(validation_node["metadata"])
                metadata["retry_limit"] = 3
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id=validation_node_id,
                        task_id=str(validation_node["task_id"]),
                        action_type="validate",
                        status="blocked",
                        owner_role="hardener",
                        confidence=0.88,
                        attempt_count=2,
                        blocker_reason="failed validation: npm run test",
                        validation_receipt_refs=["receipt:validation-job:test"],
                        metadata=metadata,
                    )
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:validation-harness:test",
                        task_id="gate:test",
                        action_type="harness",
                        status="done",
                        owner_role="builder",
                        confidence=0.96,
                        blocker_reason="validation harness work needed",
                        metadata={
                            "source": "validation_jobs",
                            "scheduler_action": "create_repair_nodes",
                            "summary": "Create harness work for failed validation `npm run test`",
                            "attempt_count": 2,
                            "retry_limit": 3,
                            "patch_ids": ["patch:needs-validation-retry"],
                            "validation_node_ids": [validation_node_id],
                        },
                    )
                    upsert_execution_dag_edge(
                        conn,
                        source_node_id="dag-node:validation-harness:test",
                        target_node_id=validation_node_id,
                        dependency_kind="repairs",
                        reason="validation harness work must run before retrying validation",
                        confidence=0.94,
                    )

                second = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test.retry")
                model = execution_dag_read_model(conn)
                validation_row = conn.execute(
                    "SELECT status, attempt_count, blocker_reason, metadata_json FROM execution_dag_nodes WHERE node_id = ?",
                    (validation_node_id,),
                ).fetchone()

            ready_ids = {str(node.get("node_id") or "") for node in model["all_ready_nodes"]}
            validation_metadata = json.loads(validation_row["metadata_json"])
            self.assertEqual("reconciled", second["status"])
            self.assertEqual(1, second["unblocked_validation_node_count"])
            self.assertEqual("ready", validation_row["status"])
            self.assertEqual(2, validation_row["attempt_count"])
            self.assertEqual("", validation_row["blocker_reason"])
            self.assertEqual("dag-node:validation-harness:test", validation_metadata["last_validation_unblocker_node_id"])
            self.assertEqual(2, validation_metadata["last_validation_unblocked_attempt"])
            self.assertIn(validation_node_id, ready_ids)

    def test_worker_patch_preflight_allows_metadata_only_runtime_state_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            patch_path = target / "target" / "automation_queue" / "planner" / "run-metadata" / "changes.patch"
            patch_path.parent.mkdir(parents=True)
            patch_path.write_text("", encoding="utf-8")
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:metadata",
                        changed_files=[],
                        patch_path="target/automation_queue/planner/run-metadata/changes.patch",
                        payload={"runtime_state_action_count": 1},
                    )
                    self._seed_ready_integration_node(conn, "patch:metadata")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)

            record = preflight["records"][0]
            self.assertEqual("direct_apply", record["status"])
            self.assertEqual(["patch:metadata"], preflight["safe_patch_ids"])
            self.assertEqual(0, preflight["protected_path_count"])
            self.assertEqual(0, preflight["missing_metadata_count"])

    def test_review_dag_node_derives_scope_from_worker_patch_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "src").mkdir(parents=True)
            (target / "src" / "reviewed.py").write_text("def validateWorkspace():\n    return True\n", encoding="utf-8")
            with closing(connect(database_path_for_target(target))) as conn:
                capability = refresh_capability_manifest_conn(conn, target)
                ensure_codebase_graph_conn(conn, target, capability=capability)
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:review",
                        changed_files=["src/reviewed.py"],
                    )
                    review_node = upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:review:patch-review",
                        task_id="T-REVIEW",
                        action_type="review",
                        status="ready",
                        owner_role="hardener",
                        confidence=0.9,
                        metadata={"patch_id": "patch:review", "summary": "Review queued worker patch"},
                    )

                candidate, blocked = state_store_module._parallel_candidate_for_dag_node_conn(conn, target, review_node)

            self.assertIsNone(blocked)
            self.assertIsNotNone(candidate)
            preview_items = candidate["context_pack_preview"]["items"]
            self.assertTrue(any(item.get("path") == "src/reviewed.py" for item in preview_items), preview_items)

    def test_parallel_conflict_allows_disjoint_exact_symbols_in_same_file(self) -> None:
        first = {
            "execution_mode": "write_workers",
            "likely_touches": [
                {
                    "node_id": "file:workspace",
                    "path": "src/workspace.js",
                    "symbol_node_id": "symbol:validateWorkspace",
                    "symbol_resolution": "exact",
                }
            ],
            "required_leases": [],
        }
        second = {
            "execution_mode": "write_workers",
            "likely_touches": [
                {
                    "node_id": "file:workspace",
                    "path": "src/workspace.js",
                    "symbol_node_id": "symbol:renderWorkspace",
                    "symbol_resolution": "exact",
                }
            ],
            "required_leases": [],
        }
        broad = {
            "execution_mode": "write_workers",
            "likely_touches": [
                {
                    "node_id": "file:workspace",
                    "path": "src/workspace.js",
                }
            ],
            "required_leases": [],
        }

        self.assertEqual((False, ""), state_store_module._parallel_candidates_conflict(first, second))
        conflicts, _reason = state_store_module._parallel_candidates_conflict(first, broad)
        self.assertTrue(conflicts)

    def test_worker_patch_integration_preflight_blocks_missing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    self._seed_worker_patch_for_preflight(
                        conn,
                        patch_id="patch:missing",
                        changed_files=[],
                        patch_path="",
                    )
                    self._seed_ready_integration_node(conn, "patch:missing")

                preflight = state_store_module.worker_patch_integration_preflight_conn(conn, target=target)
                row = conn.execute(
                    "SELECT status, missing_metadata FROM worker_patch_integration_preflight WHERE patch_id = 'patch:missing'",
                ).fetchone()

            record = preflight["records"][0]
            self.assertEqual("missing_metadata", record["status"])
            self.assertEqual(1, preflight["missing_metadata_count"])
            self.assertEqual([], preflight["safe_patch_ids"])
            self.assertEqual("missing_metadata", row["status"])
            self.assertEqual(1, row["missing_metadata"])

    def test_state_snapshot_exposes_runtime_performance_timings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "src").mkdir()
            (target / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")

            snapshot = state_snapshot(target)
            performance = snapshot["runtime_performance"]
            latest_by_phase = performance["latest_by_phase"]

            for phase in ["indexing", "resolution", "impact_scoring", "scheduling", "dashboard_rendering"]:
                self.assertIn(phase, latest_by_phase)
                self.assertGreaterEqual(latest_by_phase[phase]["elapsed_ms"], 0)
            self.assertEqual(performance, snapshot["performance"])
            self.assertIsInstance(snapshot["slow_phase_warnings"], list)
            brief = render_canonical_state_brief(snapshot, target=target)
            self.assertIn("## Performance Guardrails", brief)
            self.assertIn("phase_timing", brief)

    def test_runtime_timing_compaction_bounds_old_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                with mock.patch.object(state_store_module, "RUNTIME_PHASE_TIMING_RETENTION_LIMIT", 5):
                    for index in range(9):
                        record_runtime_phase_timing_conn(
                            conn,
                            phase="indexing",
                            source="test",
                            started_at=f"2026-05-15T00:00:{index:02d}+00:00",
                            finished_at=f"2026-05-15T00:00:{index:02d}+00:00",
                            elapsed_ms=float(index),
                        )
                    summary = compact_runtime_telemetry_conn(conn)
                    remaining = conn.execute("SELECT COUNT(*) AS count FROM runtime_phase_timings").fetchone()["count"]
                    performance = runtime_performance_summary_conn(conn)

            self.assertEqual(4, summary["deleted_runtime_phase_timing_count"])
            self.assertEqual(5, remaining)
            self.assertEqual(5, performance["phase_counts"]["indexing"])

    def test_execution_dag_node_and_edge_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                plan = upsert_execution_dag_node(
                    conn,
                    task_id="T-100",
                    action_type="decompose",
                    status="done",
                    owner_role="planner",
                    confidence=0.91,
                    attempt_count=1,
                    metadata={"summary": "Plan reusable work"},
                )
                build = upsert_execution_dag_node(
                    conn,
                    task_id="T-100",
                    action_type="build",
                    status="ready",
                    owner_role="builder",
                    worktree_id="wt-builder",
                    worktree_path="/tmp/wt-builder",
                    patch_id="patch-100",
                    patch_path="target/automation_queue/builder/run/patch.diff",
                    confidence=0.82,
                    attempt_count=2,
                    validation_receipt_refs=["receipt:unit"],
                    metadata={"summary": "Build reusable work"},
                )
                edge = upsert_execution_dag_edge(
                    conn,
                    source_node_id=plan["node_id"],
                    target_node_id=build["node_id"],
                    dependency_kind="depends_on",
                    dependency_mode="hard",
                    reason="implementation depends on decomposition",
                    confidence=0.88,
                )
                model = execution_dag_read_model(conn)

            node_by_id = {node["node_id"]: node for node in model["nodes"]}
            persisted = node_by_id[build["node_id"]]
            self.assertEqual("T-100", persisted["task_id"])
            self.assertEqual("build", persisted["action_type"])
            self.assertEqual("build", persisted["canonical_action_type"])
            self.assertEqual("exclusive_write", persisted["lease_behavior"])
            self.assertEqual("builder", persisted["owner_role"])
            self.assertEqual("wt-builder", persisted["worktree"]["id"])
            self.assertEqual("patch-100", persisted["patch"]["id"])
            self.assertEqual(["receipt:unit"], persisted["validation_receipt_refs"])
            self.assertEqual(2, persisted["attempt_count"])
            self.assertTrue(any(item["node_id"] == build["node_id"] for item in model["ready_nodes"]))
            self.assertEqual("hard", edge["dependency_mode"])
            self.assertEqual("implementation depends on decomposition", edge["reason"])

    def test_execution_dag_action_capability_contract(self) -> None:
        capabilities = execution_dag_action_capabilities()
        expected = {
            "orchestrate",
            "decompose",
            "scope",
            "build",
            "review",
            "validate",
            "repair",
            "setup",
            "harness",
            "mock",
            "defer",
            "reframe",
            "split",
            "refresh_index",
            "integrate",
            "audit",
            "calibrate",
        }

        self.assertEqual(expected, set(capabilities))
        for action_type, capability in capabilities.items():
            with self.subTest(action_type=action_type):
                self.assertTrue(capability["permissions"])
                self.assertTrue(capability["required_inputs"])
                self.assertTrue(capability["outputs"])
                self.assertIn(capability["lease_behavior"], {"none", "read_only", "exclusive_write", "validation_budget", "serialized_repo"})
                self.assertIn(capability["execution_mode"], {"read_only", "write_workers", "validation", "mixed"})
                self.assertIn(capability["role_family"], {"planner", "builder", "hardener", "integrator"})
                self.assertIn("required_by_default", capability)
                self.assertIn("optional_by_default", capability)

        self.assertEqual("exclusive_write", capabilities["build"]["lease_behavior"])
        self.assertTrue(capabilities["integrate"]["serialized"])

    def test_stale_symbol_evidence_creates_refresh_index_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "src").mkdir(parents=True)
            (target / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            with closing(connect(database_path_for_target(target))) as conn:
                result = create_refresh_index_nodes_for_stale_evidence_conn(
                    conn,
                    target,
                    [
                        {
                            "reason_kind": "stale_symbol",
                            "task_id": "T-1",
                            "likely_touches": [{"path": "src/app.py"}],
                            "reason": "stale symbol owner evidence blocks scheduling",
                        }
                    ],
                    selected_by="test.stale_index",
                )

                self.assertEqual("created", result["status"])
                self.assertEqual(["src/app.py"], result["paths"])
                node = result["nodes"][0]
                self.assertEqual("refresh_index", node["action_type"])
                self.assertEqual("ready", node["status"])

                refreshed = run_refresh_index_node_conn(conn, target, dag_node_id=node["node_id"])
                model = execution_dag_read_model(conn)

            self.assertEqual("completed", refreshed["status"])
            refreshed_node = next(item for item in model["nodes"] if item["node_id"] == node["node_id"])
            self.assertEqual("completed", refreshed_node["status"])
            self.assertEqual(["src/app.py"], refreshed_node["metadata"]["paths"])

    def test_execution_dag_snapshot_rendering_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_ticket_run_state(
                target,
                {
                    "run_id": "dag-idempotent",
                    "tickets": [{"id": "T-1", "summary": "Update a reusable module", "status": "pending"}],
                },
                actor_role="test",
                event_type="ticket.run_seeded",
            )

            first = state_snapshot(target)
            second = state_snapshot(target)
            self.assertEqual(first["execution_dag"]["digest"], second["execution_dag"]["digest"])
            self.assertEqual(first["execution_dag"]["node_count"], second["execution_dag"]["node_count"])
            self.assertEqual(first["execution_dag"]["edge_count"], second["execution_dag"]["edge_count"])

            def dag_section(markdown: str) -> str:
                return markdown.split("## Execution DAG", 1)[1].split("## Runtime Activity", 1)[0]

            rendered_first = dag_section(render_canonical_state_brief(first, target=target))
            rendered_second = dag_section(render_canonical_state_brief(second, target=target))
            self.assertEqual(rendered_first, rendered_second)
            self.assertIn("ready_node", rendered_first)
            self.assertIn("T-1", rendered_first)

    def test_execution_dag_blocker_status_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_ticket_run_state(
                target,
                {
                    "run_id": "dag-blocker",
                    "tickets": [
                        {
                            "id": "T-2",
                            "summary": "Implement blocked work",
                            "status": "blocked",
                            "blocker": "needs reusable configuration",
                        }
                    ],
                },
                actor_role="test",
                event_type="ticket.run_seeded",
            )
            blocked = state_snapshot(target)["execution_dag"]
            blocked_build = [
                item
                for item in blocked["blocked_nodes"]
                if item.get("task_id") == "T-2" and item.get("action_type") == "build"
            ]
            self.assertEqual(1, len(blocked_build))
            self.assertIn("needs reusable configuration", json.dumps(blocked_build[0]))

            write_ticket_run_state(
                target,
                {
                    "run_id": "dag-blocker",
                    "tickets": [
                        {
                            "id": "T-2",
                            "summary": "Implement blocked work",
                            "status": "pending",
                        }
                    ],
                },
                actor_role="test",
                event_type="ticket.run_unblocked",
            )
            unblocked = state_snapshot(target)["execution_dag"]
            ready_scope = [
                item
                for item in unblocked["ready_nodes"]
                if item.get("task_id") == "T-2" and item.get("action_type") == "scope"
            ]
            blocked_build = [
                item
                for item in unblocked["blocked_nodes"]
                if item.get("task_id") == "T-2" and item.get("action_type") == "build"
            ]
            self.assertEqual(1, len(ready_scope))
            self.assertEqual(1, len(blocked_build))
            self.assertIn("scope", json.dumps(blocked_build[0]))

    def test_queued_builder_patch_materializes_in_progress_ticket_build_as_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            write_ticket_run_state(
                target,
                {
                    "run_id": "dag-handoff",
                    "tickets": [
                        {
                            "id": "TICKET-001",
                            "summary": "Create repository skeleton",
                            "status": "in_progress",
                        }
                    ],
                },
                actor_role="test",
                event_type="ticket.run_seeded",
            )
            now = "2026-05-15T00:00:00+00:00"
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            context_pack_id, started_at, finished_at, payload_json
                        )
                        VALUES('role-manifest:builder:run-001', 'serial-role:builder:run-001',
                               'run-001', 'write', 'builder', 'completed', '', ?, ?, ?)
                        """,
                        (
                            now,
                            now,
                            stable_json({"task_id": "TICKET-001", "dag_node_id": "dag-node:test:build"}),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path,
                            patch_path, changed_files_json, base_commit, leases_json,
                            validation_evidence_json, conflict_signature, created_at,
                            queued_at, integrated_at, payload_json
                        )
                        VALUES('role-patch:test', 'role-manifest:builder:run-001',
                               'serial-role:builder:run-001', 'queued',
                               'target/automation_queue/builder/run-001/manifest.json',
                               'target/automation_queue/builder/run-001/changes.patch',
                               ?, '', '[]', '[]', '', ?, ?, '', '{}')
                        """,
                        (json.dumps(["src/app.py"]), now, now),
                    )
                    materialize_execution_dag_conn(conn, target, {}, event_type="test.materialize")
                    model = execution_dag_read_model(conn)
                    ticket_row = conn.execute(
                        "SELECT status FROM ticket_items WHERE ticket_id = 'TICKET-001'",
                    ).fetchone()

            build_node = next(node for node in model["nodes"] if node["task_id"] == "TICKET-001" and node["action_type"] == "build")
            ticket_node = next(node for node in model["nodes"] if node["task_id"] == "TICKET-001" and node["action_type"] == "ticket")
            self.assertEqual("done", build_node["status"])
            self.assertEqual("in_progress", ticket_node["status"])
            self.assertEqual("in_progress", ticket_row["status"])
            self.assertEqual("role-patch:test", build_node["metadata"]["worker_patch_handoffs"][0]["patch_id"])

    def test_integrated_builder_patch_materializes_ticket_build_as_done(self) -> None:
        for ticket_status in ("pending", "in_progress"):
            with self.subTest(ticket_status=ticket_status):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    write_ticket_run_state(
                        target,
                        {
                            "run_id": "dag-handoff",
                            "tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Create repository skeleton",
                                    "status": ticket_status,
                                }
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_seeded",
                    )
                    now = "2026-05-15T00:00:00+00:00"
                    with closing(connect(database_path_for_target(target))) as conn:
                        with conn:
                            conn.execute(
                                """
                                INSERT INTO worker_agents(
                                    worker_id, execution_group_id, run_id, mode, role, status,
                                    context_pack_id, started_at, finished_at, payload_json
                                )
                                VALUES('role-manifest:builder:run-001', 'serial-role:builder:run-001',
                                       'run-001', 'write', 'builder', 'completed', '', ?, ?, ?)
                                """,
                                (
                                    now,
                                    now,
                                    stable_json({"task_id": "TICKET-001", "dag_node_id": "dag-node:test:build"}),
                                ),
                            )
                            conn.execute(
                                """
                                INSERT INTO worker_patches(
                                    patch_id, worker_id, execution_group_id, status, manifest_path,
                                    patch_path, changed_files_json, base_commit, leases_json,
                                    validation_evidence_json, conflict_signature, created_at,
                                    queued_at, integrated_at, payload_json
                                )
                                VALUES('role-patch:test', 'role-manifest:builder:run-001',
                                       'serial-role:builder:run-001', 'integrated',
                                       'target/automation_queue/builder/run-001/manifest.json',
                                       'target/automation_queue/builder/run-001/changes.patch',
                                       ?, '', '[]', '[]', '', ?, ?, ?, '{}')
                                """,
                                (json.dumps(["src/app.py"]), now, now, now),
                            )
                            materialize_execution_dag_conn(conn, target, {}, event_type="test.materialize")
                            model = execution_dag_read_model(conn)
                            ticket_row = conn.execute(
                                "SELECT status FROM ticket_items WHERE ticket_id = 'TICKET-001'",
                            ).fetchone()

                    build_node = next(node for node in model["nodes"] if node["task_id"] == "TICKET-001" and node["action_type"] == "build")
                    self.assertEqual("done", build_node["status"])
                    self.assertEqual(ticket_status, ticket_row["status"])
                    self.assertEqual("role-patch:test", build_node["metadata"]["worker_patch_handoffs"][0]["patch_id"])
                    self.assertEqual("integrated", build_node["metadata"]["worker_patch_handoffs"][0]["status"])

    def test_parallelism_budget_ignores_disabled_legacy_write_worker_flag(self) -> None:
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
            self.assertTrue(budget_by_scope["write_workers"]["enabled"])
            self.assertEqual(5, budget_by_scope["write_workers"]["max_concurrent"])
            self.assertIn("active_parallel_counts", snapshot)
            self.assertIn("budget_exhaustion_reasons", snapshot)

            with closing(connect(database_path_for_target(target))) as conn:
                self.assertTrue(can_start_worker(conn, "read_only", owner_role="builder")["allowed"])
                write_check = can_start_worker(conn, "write", owner_role="builder")
            self.assertTrue(write_check["allowed"])

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

    def test_disabled_legacy_write_worker_count_uses_default_capacity(self) -> None:
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
                budgets = {item["scope"]: item for item in parallelism_budgets_conn(conn)}

            self.assertTrue(read_only_check["allowed"])
            self.assertTrue(write_check["allowed"])
            self.assertEqual(3, budgets["write_workers"]["max_concurrent"])

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

    def test_why_not_parallel_read_model_groups_normalized_reasons(self) -> None:
        model = state_store_module.why_not_parallel_read_model(
            [
                {
                    "candidate_id": "candidate:missing",
                    "task_id": "T1",
                    "owner_role": "builder",
                    "action_kind": "build",
                    "reason_kind": "missing_direct_write_signal",
                    "reason": "write task needs a direct path or exact symbol",
                    "confidence_signals": ["keyword_advisory"],
                    "missing_confidence_signal": "direct_path_or_exact_symbol",
                },
                {
                    "candidate_id": "candidate:stale",
                    "task_id": "T2",
                    "owner_role": "builder",
                    "action_kind": "build",
                    "reason_kind": "missing_direct_write_signal",
                    "reason": "write task has stale symbol evidence only",
                    "confidence_signals": ["stale_symbol"],
                },
                {
                    "candidate_id": "candidate:lease",
                    "task_id": "T3",
                    "owner_role": "builder",
                    "action_kind": "build",
                    "reason_kind": "active_lease_conflict",
                    "reason": "required lease conflicts with an active lease",
                    "lease_conflicts": [{"lease_id": "lease:active"}],
                },
                {
                    "candidate_id": "candidate:scope",
                    "task_id": "T4",
                    "owner_role": "planner",
                    "action_kind": "scope",
                    "reason_kind": "insufficient_scoping_confidence",
                    "reason": "scope node has low confidence context",
                },
            ],
            skipped_scheduler_candidates=[
                {
                    "candidate_id": "scheduler:scope",
                    "execution_group_id": "execution-group:scope",
                    "action_kind": "launch_scope_group",
                    "skipped_reason": "read-only scope fanout unavailable: read_only_workers budget has 2 active item(s) for 2 slot(s)",
                    "blockers": [
                        {
                            "reason_kind": "read_only_scope_budget_blocked",
                            "reason": "read_only_workers budget has 2 active item(s) for 2 slot(s)",
                        }
                    ],
                }
            ],
        )

        groups = {item["reason_kind"]: item for item in model["reason_groups"]}

        self.assertEqual("blocked", model["status"])
        self.assertEqual(1, model["reason_counts"]["missing_direct_write_signal"])
        self.assertEqual(1, model["reason_counts"]["stale_symbol"])
        self.assertEqual(1, model["reason_counts"]["lease_conflict"])
        self.assertEqual(1, model["reason_counts"]["insufficient_scoping_confidence"])
        self.assertEqual(1, model["reason_counts"]["budget_blocked"])
        self.assertIn("Refresh the codebase index", groups["stale_symbol"]["next_action"])
        self.assertIn("Raise or free", groups["budget_blocked"]["next_action"])
        self.assertFalse(model["policy"]["worker_text_authorizes_writes"])

    def test_why_not_parallel_read_model_is_clear_for_exact_owner_group(self) -> None:
        model = state_store_module.why_not_parallel_read_model(
            [],
            parallelization_summary={"mode": "dry_run", "group_count": 1},
            proposed_execution_groups=[
                {
                    "execution_group_id": "execution-group:exact-owner",
                    "payload": {"execution_mode": "write_workers"},
                    "items": [{"task_id": "T1"}],
                }
            ],
        )

        self.assertEqual("clear", model["status"])
        self.assertEqual({}, model["reason_counts"])
        self.assertEqual(1, model["proposed_group_count"])
        self.assertEqual("Planning preview has proposed group(s) and no candidate reason groups.", model["summary"])

    def test_parallel_display_mode_hides_raw_dry_run_wording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group = state_store_module.decorate_execution_group_for_display(
                {
                    "execution_group_id": "execution-group:preview",
                    "status": "proposed",
                    "mode": "dry_run",
                    "reason": "read-only reviews can run together",
                    "payload": {
                        "planner_mode": "dry_run",
                        "execution_mode": "read_only",
                        "why_together": "read-only candidates do not write",
                    },
                    "items": [{"item_id": "item:1", "task_id": "T1", "owner_role": "hardener", "action_kind": "review"}],
                }
            )

            self.assertEqual("dry_run", group["mode"])
            self.assertEqual("planner_preview", group["display_mode"])
            self.assertEqual("Planning preview", group["display_mode_label"])
            self.assertEqual("Read-only workers", group["execution_mode_label"])

            brief = render_canonical_state_brief(
                {
                    "database": {"path": str(database_path_for_target(target)), "exists": True},
                    "automation_control": {"status": "ACTIVE"},
                    "execution_dag": {"nodes": [], "edges": [], "ready_nodes": [], "active_nodes": [], "blocked_nodes": []},
                    "proposed_execution_groups": [group],
                    "parallelization_summary": {
                        "mode": "dry_run",
                        "display_mode": "planner_preview",
                        "display_mode_label": "Planning preview",
                        "group_count": 1,
                        "grouped_task_count": 1,
                    },
                },
                target=target,
            )

            self.assertIn("## Parallel Execution", brief)
            self.assertNotIn("## Parallel Execution Dry Run", brief)
            self.assertIn("display_mode=Planning preview", brief)
            self.assertNotIn("mode=dry_run", brief)

    def test_execution_group_read_model_separates_running_recent_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                now = "2026-05-17T00:00:00+00:00"
                with conn:
                    conn.execute(
                        """
                        INSERT INTO execution_groups(
                            execution_group_id, status, mode, created_at, started_at, selected_by, reason, payload_json
                        )
                        VALUES('execution-group:running', 'running', 'read_only', ?, ?, 'test', 'running read-only group', '{}')
                        """,
                        (now, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO execution_groups(
                            execution_group_id, status, mode, created_at, started_at, finished_at, selected_by, reason, payload_json
                        )
                        VALUES('execution-group:completed-validation', 'completed', 'validation', ?, ?, ?, 'test', 'validation completed', '{}')
                        """,
                        (now, now, now),
                    )

                running = state_store_module.execution_groups_by_status_conn(conn, {"running"})
                recent = state_store_module.execution_groups_by_status_conn(conn, {"completed"})

            self.assertEqual(["execution-group:running"], [item["execution_group_id"] for item in running])
            self.assertEqual("Read-only workers", running[0]["display_mode_label"])
            self.assertEqual(["execution-group:completed-validation"], [item["execution_group_id"] for item in recent])
            self.assertEqual("Validation jobs", recent[0]["display_mode_label"])

    def test_scope_fanout_exhausted_uses_serialized_role_summary(self) -> None:
        model = state_store_module.why_not_parallel_read_model(
            [
                {
                    "candidate_id": "candidate:scope",
                    "task_id": "T1",
                    "action_kind": "launch_scope_group",
                    "reason_kind": "scope_fanout_exhausted",
                    "reason": "scope fanout exhausted",
                }
            ],
        )

        self.assertEqual("serialized_role_path", model["status"])
        self.assertIn("serialized or waiting paths", model["summary"])
        self.assertEqual("serialized_role_path", model["reason_groups"][0]["reason_kind"])
        self.assertEqual("No promotable ownership evidence; continuing with serialized role work.", model["reason_groups"][0]["human_summary"])
        self.assertEqual("scope_fanout_exhausted", model["reason_groups"][0]["examples"][0]["debug_reason_kind"])

    def test_worker_report_disposition_display_is_reconciled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            now = "2026-05-17T00:00:00+00:00"
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            started_at, finished_at, payload_json
                        )
                        VALUES('worker:accepted', '', 'run:accepted', 'read_only', 'hardener', 'completed', ?, ?, ?)
                        """,
                        (
                            now,
                            now,
                            stable_json(
                                {
                                    "finding_disposition_required": True,
                                    "disposition_status": "dispositioned",
                                    "accepted_findings": [{"id": "finding:1"}],
                                    "rejected_findings": [],
                                    "deferred_findings": [],
                                }
                            ),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            started_at, finished_at, payload_json
                        )
                        VALUES('worker:pending', '', 'run:pending', 'read_only', 'hardener', 'completed', ?, ?, ?)
                        """,
                        (
                            now,
                            now,
                            stable_json({"finding_disposition_required": True, "disposition_status": "pending"}),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            started_at, finished_at, payload_json
                        )
                        VALUES('worker:queued-patch', 'execution-group:write', 'run:write', 'write', 'builder', 'completed', ?, ?, ?)
                        """,
                        (now, now, stable_json({"finding_disposition_required": False, "disposition_status": "not_applicable"})),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path, patch_path,
                            changed_files_json, base_commit, leases_json, validation_evidence_json,
                            created_at, queued_at, payload_json
                        )
                        VALUES('patch:queued', 'worker:queued-patch', 'execution-group:write', 'queued',
                               'target/automation_queue/manifest.json', 'target/automation_queue/changes.patch',
                               '["src/example.py"]', 'HEAD', '[]', '[]', ?, ?, '{}')
                        """,
                        (now, now),
                    )

                model = state_store_module.worker_reports_read_model_conn(conn, limit=10)

            by_worker = {worker["worker_id"]: worker for worker in model["completed_worker_reports"]}
            self.assertEqual("dispositioned", by_worker["worker:accepted"]["disposition_status"])
            self.assertEqual("Findings dispositioned", by_worker["worker:accepted"]["disposition_label"])
            self.assertEqual("pending", by_worker["worker:pending"]["disposition_status"])
            self.assertTrue(by_worker["worker:pending"]["finding_disposition_required_effective"])
            self.assertEqual("awaiting_integrator_review", by_worker["worker:queued-patch"]["disposition_status"])
            self.assertEqual("Awaiting integrator review", by_worker["worker:queued-patch"]["disposition_label"])
            self.assertTrue(model["worker_finding_disposition_required"])
            self.assertEqual(1, model["worker_disposition_summary"]["awaiting_integrator_review_count"])

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
            self.assertEqual({"typecheck"}, {job["payload"]["classification"] for job in jobs})
            self.assertEqual({"parallel"}, {job["payload"]["run_lane"] for job in jobs})

    def test_validation_command_classification_covers_parallel_safe_families(self) -> None:
        classify = state_store_module.classify_validation_command

        self.assertEqual("unit_test", classify("python3 -m pytest tests/test_auth.py"))
        self.assertEqual("lint", classify("npm run lint"))
        self.assertEqual("typecheck", classify("pnpm run typecheck"))
        self.assertEqual("smoke", classify("python3 scripts/smoke_check.py"))
        self.assertEqual("docs_check", classify("markdownlint docs"))
        self.assertEqual("generated_helper", classify("python3 scripts/check_required_files.py ."))
        self.assertEqual("build", classify("npm run build"))
        self.assertEqual("resource_heavy", classify("bash scripts/validate_starter_kit.sh"))
        self.assertEqual("browser", classify("npx playwright test"))
        self.assertEqual("environment_repair", classify("npm ci"))
        self.assertEqual("exclusive", classify("python3 manage.py migrate deploy"))
        self.assertEqual("unit_test", classify("npm run test"))

    def test_vitest_package_validation_excludes_diffmogger_runtime_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}}),
                encoding="utf-8",
            )

            spec = state_store_module._validation_command_spec(  # type: ignore[attr-defined]
                "npm run test",
                index=1,
                target=target,
                default_plan_id="plan:vitest",
            )

        self.assertEqual("unit_test", spec["classification"])
        self.assertEqual("javascript_tests", spec["command_family"])
        self.assertIn("--exclude", spec["command"])
        self.assertIn(".diffmogger/**", spec["command"])
        runtime_exclusion = spec["planning_evidence"]["runtime_exclusion"]
        self.assertEqual([".diffmogger/**"], runtime_exclusion["excluded_globs"])
        self.assertEqual("vitest", runtime_exclusion["runner"])

    def test_jest_package_validation_does_not_get_vitest_exclude_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "package.json").write_text(
                json.dumps({"scripts": {"test": "jest"}}),
                encoding="utf-8",
            )

            spec = state_store_module._validation_command_spec(  # type: ignore[attr-defined]
                "npm run test",
                index=1,
                target=target,
                default_plan_id="plan:jest",
            )

        self.assertEqual("javascript_tests", spec["command_family"])
        self.assertEqual("npm run test", spec["command"])
        self.assertNotIn("runtime_exclusion", spec["planning_evidence"])

    def test_parallel_validation_splits_safe_checks_from_resource_heavy_serial_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            active = 0
            max_active = 0
            calls: list[tuple[str, str]] = []
            lock = threading.Lock()

            def fake_run(spec: dict[str, object]) -> dict[str, object]:
                nonlocal active, max_active
                lane = str(spec.get("run_lane") or "")
                classification = str(spec.get("classification") or "")
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                    calls.append((lane, classification))
                if lane == "parallel":
                    time.sleep(0.05)
                with lock:
                    active -= 1
                return {
                    "started_at": "2026-05-16T00:00:00+00:00",
                    "finished_at": "2026-05-16T00:00:01+00:00",
                    "duration_seconds": 1.0,
                    "exit_code": 0,
                    "stdout": classification,
                    "stderr": "",
                }

            commands = [
                {"command": "python3 -m pytest tests", "gate_id": "gate:unit"},
                {"command": "npm run lint", "gate_id": "gate:lint"},
                {"command": "python3 scripts/check_required_files.py .", "gate_id": "gate:helper"},
                {"command": "npm run build", "gate_id": "gate:build"},
                {"command": "npm ci", "gate_id": "gate:setup"},
            ]
            with mock.patch.object(state_store_module, "_run_validation_command", fake_run):
                with closing(connect(database_path_for_target(target))) as conn:
                    result = run_parallel_validation_conn(conn, target, commands, selected_by="test", plan_id="plan:split")
                    jobs = validation_jobs_conn(conn, limit=10)

            self.assertEqual("passed", result["status"])
            self.assertEqual(3, result["parallel_job_count"])
            self.assertEqual(2, result["serial_job_count"])
            self.assertGreaterEqual(max_active, 2)
            self.assertEqual({"unit_test", "lint", "generated_helper", "build", "environment_repair"}, {job["payload"]["classification"] for job in jobs})
            self.assertEqual(3, result["planning_evidence"]["run_lane_counts"]["parallel"])
            self.assertEqual(2, result["planning_evidence"]["run_lane_counts"]["serial"])
            self.assertTrue(all(job["payload"]["planning_evidence"]["run_lane"] in {"parallel", "serial"} for job in jobs))
            self.assertIn(("serial", "build"), calls)
            self.assertIn(("serial", "environment_repair"), calls)

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
            self.assertEqual("source_test_failure", result["jobs"][0]["payload"]["control_plane_classification"])
            self.assertIsNotNone(receipt)
            self.assertEqual("fail", receipt["status"])

    def test_parallel_validation_records_repaired_missing_pytest_as_passed(self) -> None:
        from diffmogger.runtime import repair_environment as repair_environment_module

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp).resolve()
            command = (
                f"{sys.executable} -c \"import sys; "
                "print('No module named pytest', file=sys.stderr); "
                "sys.exit(1)\""
            )
            diagnostics = [{"kind": "missing_pytest", "name": "pytest", "detail": "No module named pytest"}]

            def fake_diagnose_failure(_command: str, _exit_code: int, _output: str) -> list[dict[str, str]]:
                return diagnostics

            def fake_diagnose_and_repair(
                target_arg: Path,
                command_arg: str,
                exit_code: int,
                output: str,
                *,
                rerun: bool = False,
            ) -> repair_environment_module.EnvironmentRepairOutcome:
                self.assertEqual(target, target_arg)
                self.assertTrue(rerun)
                self.assertIn("No module named pytest", output)
                return repair_environment_module.EnvironmentRepairOutcome(
                    command=command_arg,
                    initial_exit_code=exit_code,
                    initial_output=output,
                    diagnostics=diagnostics,
                    repairs=["installed Python dependencies from pyproject extra `test` into target/automation_venvs/root"],
                    repair_performed=True,
                    final_command="target/automation_venvs/root/bin/python -m pytest",
                    final_exit_code=0,
                    final_output="1 passed",
                    environment_failure=False,
                )

            with mock.patch.object(repair_environment_module, "diagnose_failure", fake_diagnose_failure):
                with mock.patch.object(repair_environment_module, "diagnose_and_repair", fake_diagnose_and_repair):
                    with closing(connect(database_path_for_target(target))) as conn:
                        result = run_parallel_validation_conn(
                            conn,
                            target,
                            [{"command": command, "classification": "test", "required": True, "gate_id": "gate:pytest"}],
                            selected_by="test",
                            plan_id="plan:pytest-repair",
                        )
                        jobs = validation_jobs_conn(conn, limit=5)
                        receipt = conn.execute(
                            "SELECT status, payload_json FROM validation_receipts WHERE run_id = ?",
                            (result["execution_group_id"],),
                        ).fetchone()
                        artifact = conn.execute(
                            "SELECT path FROM artifacts WHERE artifact_id = ?",
                            (result["jobs"][0]["log_artifact_id"],),
                        ).fetchone()

            self.assertEqual("passed", result["status"])
            self.assertEqual("passed", result["jobs"][0]["status"])
            self.assertEqual("passed", jobs[0]["status"])
            payload = jobs[0]["payload"]
            self.assertEqual(1, payload["initial_exit_code"])
            self.assertTrue(payload["repair_performed"])
            self.assertFalse(payload["environment_failure"])
            self.assertEqual("verification_environment_failure", payload["failure_reason"])
            self.assertEqual("missing_pytest", payload["failure_category"])
            self.assertTrue(payload["validation_failure_signature"].startswith("verification_environment_failure:missing_pytest:"))
            self.assertIsNotNone(receipt)
            self.assertEqual("pass", receipt["status"])
            receipt_payload = json.loads(receipt["payload_json"])
            self.assertTrue(receipt_payload["repair_performed"])
            self.assertIsNotNone(artifact)
            log_text = (target / artifact["path"]).read_text(encoding="utf-8")
            self.assertIn("## environment repair", log_text)
            self.assertIn("initial_exit=1", log_text)
            self.assertIn("No module named pytest", log_text)
            self.assertIn("1 passed", log_text)

    def test_unrepaired_environment_validation_failure_creates_single_setup_node_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            now = "2026-05-15T00:00:00+00:00"
            signature = "verification_environment_failure:missing_pytest:deadbeef1234"
            payload = {
                "required": True,
                "classification": "test",
                "environment_failure": True,
                "repair_performed": False,
                "failure_reason": "verification_environment_failure",
                "failure_category": "missing_pytest",
                "failure_root_cause": "Missing pytest in the validation environment.",
                "validation_failure_signature": signature,
                "environment_repair": {
                    "blocked_reason": "No ignored local Python venv with declared requirements could satisfy the missing module."
                },
            }
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:env-validation",
                        task_id="T-env",
                        action_type="validate",
                        status="blocked",
                        owner_role="hardener",
                        confidence=0.9,
                        attempt_count=1,
                        metadata={"paths": ["tests/test_app.py"]},
                    )
                    conn.execute(
                        """
                        INSERT INTO execution_groups(
                            execution_group_id, status, mode, created_at, started_at, finished_at,
                            selected_by, reason, payload_json
                        )
                        VALUES('validation-group:env', 'failed', 'validation', ?, ?, ?, 'test', 'validation failed', '{}')
                        """,
                        (now, now, now),
                    )
                    for index in (1, 2):
                        conn.execute(
                            """
                            INSERT INTO validation_jobs(
                                job_id, execution_group_id, plan_id, gate_id, command, cwd,
                                status, started_at, finished_at, exit_code, log_artifact_id,
                                resource_profile, payload_json
                            )
                            VALUES(?, 'validation-group:env', 'validation-group:env', 'T-env',
                                   'python3 -m pytest', ?, 'failed', ?, ?, 1, ?, 'cpu', ?)
                            """,
                            (
                                f"validation-job:env-{index}",
                                str(target),
                                now,
                                now,
                                f"artifact:validation-log:env-{index}",
                                stable_json(payload),
                            ),
                        )

                jobs = validation_jobs_conn(conn, statuses={"failed"}, limit=10)
                self.assertEqual(2, len(failed_validation_jobs_requiring_dag_action_conn(conn, jobs)))
                created = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                skipped = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                remaining = failed_validation_jobs_requiring_dag_action_conn(conn, jobs)
                model = execution_dag_read_model(conn)
                edges = execution_dag_edges_conn(conn)

            self.assertEqual(0, created["repair_node_count"])
            self.assertEqual(1, created["unblocker_node_count"])
            self.assertEqual(0, created["blocker_node_count"])
            self.assertEqual("skipped", skipped["status"])
            self.assertEqual([], remaining)
            env_setup_nodes = [
                node
                for node in model["nodes"]
                if node["action_type"] == "setup" and node["status"] == "ready"
            ]
            self.assertEqual(1, len(env_setup_nodes))
            setup = env_setup_nodes[0]
            self.assertIn("Missing pytest", setup["blocker_reason"])
            self.assertEqual(signature, setup["metadata"]["failure_signature"])
            self.assertEqual("validation_setup", setup["metadata"]["unblocker_kind"])
            self.assertEqual("create_setup_work", setup["metadata"]["automation_disposition"])
            self.assertEqual([], [node for node in model["nodes"] if node["action_type"] == "repair"])
            self.assertIn(
                (setup["node_id"], "dag-node:test:env-validation", "repairs"),
                {(edge["source"], edge["target"], edge["dependency_kind"]) for edge in edges},
            )

    def test_generic_validation_repair_dedupes_active_nodes_by_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            now = "2026-05-15T00:00:00+00:00"
            signature = "verification_failure:runtime_anchor:deadbeef1234"
            payload = {
                "required": True,
                "classification": "test",
                "failure_reason": "verification_failure",
                "failure_category": "runtime_anchor",
                "failure_root_cause": "PlaceholderScene is missing the required runtime anchor.",
                "validation_failure_signature": signature,
            }
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:runtime-validation",
                        task_id="T-runtime",
                        action_type="validate",
                        status="blocked",
                        owner_role="hardener",
                        confidence=0.9,
                        attempt_count=1,
                        metadata={"paths": ["src/scenes/PlaceholderScene.ts"]},
                    )
                    conn.execute(
                        """
                        INSERT INTO execution_groups(
                            execution_group_id, status, mode, created_at, started_at, finished_at,
                            selected_by, reason, payload_json
                        )
                        VALUES('validation-group:runtime', 'failed', 'validation', ?, ?, ?, 'test', 'validation failed', '{}')
                        """,
                        (now, now, now),
                    )
                    for index in (1, 2):
                        conn.execute(
                            """
                            INSERT INTO validation_jobs(
                                job_id, execution_group_id, plan_id, gate_id, command, cwd,
                                status, started_at, finished_at, exit_code, log_artifact_id,
                                resource_profile, payload_json
                            )
                            VALUES(?, 'validation-group:runtime', 'validation-group:runtime', 'T-runtime',
                                   'python3 scripts/validate_runtime_entrypoint.py', ?, 'failed', ?, ?, 1, ?, 'cpu', ?)
                            """,
                            (
                                f"validation-job:runtime-{index}",
                                str(target),
                                now,
                                now,
                                f"artifact:validation-log:runtime-{index}",
                                stable_json(payload),
                            ),
                        )

                jobs = validation_jobs_conn(conn, statuses={"failed"}, limit=10)
                self.assertEqual(2, len(failed_validation_jobs_requiring_dag_action_conn(conn, jobs)))
                created = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                skipped = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                remaining = failed_validation_jobs_requiring_dag_action_conn(conn, jobs)
                model = execution_dag_read_model(conn)

            self.assertEqual(1, created["repair_node_count"])
            self.assertEqual(0, created["unblocker_node_count"])
            self.assertEqual("skipped", skipped["status"])
            self.assertEqual([], remaining)
            repair_nodes = [
                node
                for node in model["nodes"]
                if node["action_type"] == "repair" and node["status"] == "ready"
            ]
            self.assertEqual(1, len(repair_nodes))
            self.assertEqual(signature, repair_nodes[0]["metadata"]["failure_signature"])
            self.assertEqual("validation_jobs", repair_nodes[0]["metadata"]["source"])

    def test_validation_backpressure_blocks_same_ownership_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            now = "2026-05-15T00:00:00+00:00"
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO execution_groups(
                            execution_group_id, status, mode, created_at, started_at, finished_at,
                            selected_by, reason, payload_json
                        )
                        VALUES('validation-group:source', 'failed', 'validation', ?, ?, ?, 'test', 'validation failed', '{}')
                        """,
                        (now, now, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO validation_jobs(
                            job_id, execution_group_id, plan_id, gate_id, command, cwd,
                            status, started_at, finished_at, exit_code, log_artifact_id,
                            resource_profile, payload_json
                        )
                        VALUES('validation-job:source', 'validation-group:source', 'plan:source', 'gate:unit',
                               'python3 -m unittest', ?, 'failed', ?, ?, 1, '', 'cpu', ?)
                        """,
                        (
                            str(target),
                            now,
                            now,
                            stable_json(
                                {
                                    "required": True,
                                    "selected_paths": ["src/app.py"],
                                    "failure_reason": "source_test_failure",
                                }
                            ),
                        ),
                    )

                blocked = state_store_module._validation_backpressure_for_candidate_conn(
                    conn,
                    {
                        "execution_mode": "write_workers",
                        "likely_touches": [{"path": "src/app.py"}],
                    },
                )
                unrelated = state_store_module._validation_backpressure_for_candidate_conn(
                    conn,
                    {
                        "execution_mode": "write_workers",
                        "likely_touches": [{"path": "docs/readme.md"}],
                    },
                )

            self.assertEqual("validation_backpressure", blocked["reason_kind"])
            self.assertEqual(["src/app.py"], blocked["candidate_paths"])
            self.assertEqual({}, unrelated)

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
            self.assertEqual("source_test_failure", result["jobs"][0]["payload"]["control_plane_classification"])

    def test_configured_optional_missing_tool_is_classified_not_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [
                        {
                            "command": "definitely_missing_diffmogger_optional_tool --version",
                            "classification": "smoke",
                            "required": False,
                            "source": ".agentic/smoke_commands.txt",
                            "source_authority": "configured",
                            "gate_id": "gate:configured-optional",
                        }
                    ],
                    selected_by="test",
                    plan_id="plan:configured-optional",
                )

            self.assertEqual("warning", result["status"])
            payload = result["jobs"][0]["payload"]
            self.assertEqual("missing_optional_tool", payload["control_plane_classification"])
            self.assertNotIn("invalid_command_disposition", payload)

    def test_repairable_invalid_discovered_command_is_downgraded_not_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [
                        {
                            "command": "definitely_missing_diffmogger_optional_tool --version",
                            "classification": "test",
                            "required": False,
                            "source": "python project metadata",
                            "source_authority": "speculative",
                            "gate_id": "gate:optional-invalid",
                        }
                    ],
                    selected_by="test",
                    plan_id="plan:optional-invalid",
                )
                receipt = conn.execute(
                    "SELECT status, payload_json FROM validation_receipts WHERE run_id = ?",
                    (result["execution_group_id"],),
                ).fetchone()
                repair = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")

            self.assertEqual("warning", result["status"])
            self.assertEqual("warning", result["jobs"][0]["status"])
            payload = result["jobs"][0]["payload"]
            self.assertFalse(payload["required"])
            self.assertEqual("invalid_discovered_command", payload["control_plane_classification"])
            self.assertEqual("invalid_discovered_command", payload["invalid_command_disposition"]["status"])
            self.assertIsNotNone(receipt)
            self.assertEqual("warn", receipt["status"])
            receipt_payload = json.loads(receipt["payload_json"])
            self.assertEqual("invalid_discovered_command", receipt_payload["invalid_command_disposition"]["status"])
            self.assertEqual(0, repair["repair_node_count"])
            self.assertEqual(0, repair["blocker_node_count"])

    def test_unittest_only_target_does_not_require_undeclared_pytest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / ".agentic").mkdir()
            (target / ".agentic" / "verification_commands.txt").write_text(
                f"{sys.executable} -m unittest discover -s tests\n",
                encoding="utf-8",
            )
            (target / "pyproject.toml").write_text(
                "[project]\nname = \"fictional-app\"\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )
            (target / "tests").mkdir()
            (target / "tests" / "test_app.py").write_text(
                "import unittest\n\n"
                "class AppTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            with closing(connect(database_path_for_target(target))) as conn:
                capability = refresh_capability_manifest_conn(conn, target)
                result = run_parallel_validation_conn(conn, target, selected_by="test", plan_id="plan:unittest-only")

            pytest_commands = [item for item in capability["commands"] if item["command"] == "python3 -m pytest"]
            self.assertEqual([], pytest_commands)
            self.assertTrue(any(item["command"] == f"{sys.executable} -m unittest discover -s tests" and item["required"] for item in capability["commands"]))
            self.assertEqual("passed", result["status"])
            required_commands = [
                job["command"]
                for job in result["jobs"]
                if job["payload"].get("required")
            ]
            self.assertNotIn("python3 -m pytest", required_commands)

    def test_required_missing_validation_tool_is_classified_for_environment_setup_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [
                        {
                            "command": "definitely_missing_diffmogger_required_tool --version",
                            "classification": "test",
                            "required": True,
                            "source": ".agentic/verification_commands.txt",
                            "source_authority": "configured",
                            "gate_id": "gate:required-missing-tool",
                        }
                    ],
                    selected_by="test",
                    plan_id="plan:required-missing-tool",
                )
                jobs = validation_jobs_conn(conn, statuses={"failed"}, limit=5)
                repair = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                receipt = conn.execute(
                    "SELECT payload_json FROM validation_receipts WHERE run_id = ?",
                    (result["execution_group_id"],),
                ).fetchone()

            self.assertEqual("failed", result["status"])
            payload = result["jobs"][0]["payload"]
            self.assertTrue(payload["required"])
            self.assertEqual("missing_declared_dependency", payload["control_plane_classification"])
            self.assertEqual("verification_environment_failure", payload["failure_reason"])
            self.assertEqual("create_setup_work", payload["automation_disposition"])
            self.assertEqual(["setup", "harness"], payload["recommended_dag_actions"])
            self.assertFalse(payload["critical_stop_allowed"])
            self.assertIsNotNone(receipt)
            receipt_payload = json.loads(receipt["payload_json"])
            self.assertEqual("create_setup_work", receipt_payload["automation_disposition"])
            self.assertTrue(jobs)
            self.assertEqual(0, repair["repair_node_count"])
            self.assertEqual(1, repair["unblocker_node_count"])
            self.assertEqual(0, repair["blocker_node_count"])

    def test_external_service_validation_failure_creates_mock_or_fixture_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = (
                f"{sys.executable} -c \"import sys; "
                "print('External API returned 503 Service Unavailable', file=sys.stderr); "
                "sys.exit(1)\""
            )

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [
                        {
                            "command": command,
                            "classification": "smoke",
                            "required": True,
                            "gate_id": "gate:external-service",
                        }
                    ],
                    selected_by="test",
                    plan_id="plan:external-service",
                )
                repair = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                model = execution_dag_read_model(conn)

            self.assertEqual("failed", result["status"])
            payload = result["jobs"][0]["payload"]
            self.assertEqual("external_service_needs_mock_or_fixture", payload["control_plane_classification"])
            self.assertEqual("create_mock_or_fixture_work", payload["automation_disposition"])
            self.assertEqual(["mock", "defer"], payload["recommended_dag_actions"])
            self.assertEqual(0, repair["repair_node_count"])
            self.assertEqual(1, repair["unblocker_node_count"])
            mock_node = next(node for node in model["ready_nodes"] if node["action_type"] == "mock")
            mock_metadata = next(node["metadata"] for node in model["nodes"] if node["node_id"] == mock_node["node_id"])
            self.assertEqual("builder", mock_node["owner_role"])
            self.assertIn("mock", mock_metadata["candidate_unblocker_actions"])
            self.assertIn("defer", mock_metadata["candidate_unblocker_actions"])

    def test_browser_mcp_validation_failure_creates_deferred_qa_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = (
                f"{sys.executable} -c \"import sys; "
                "print('Playwright MCP browser navigation failed before DevTools was ready', file=sys.stderr); "
                "sys.exit(1)\""
            )

            with closing(connect(database_path_for_target(target))) as conn:
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    [
                        {
                            "command": command,
                            "classification": "browser",
                            "required": True,
                            "gate_id": "gate:browser-qa",
                        }
                    ],
                    selected_by="test",
                    plan_id="plan:browser-qa",
                )
                jobs = validation_jobs_conn(conn, statuses={"failed"}, limit=5)
                self.assertEqual(1, len(failed_validation_jobs_requiring_dag_action_conn(conn, jobs)))
                repair = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                remaining = failed_validation_jobs_requiring_dag_action_conn(conn, jobs)
                model = execution_dag_read_model(conn)

            self.assertEqual("failed", result["status"])
            payload = result["jobs"][0]["payload"]
            self.assertEqual("browser_or_mcp_deferred_qa", payload["control_plane_classification"])
            self.assertEqual("create_deferred_or_alternate_validation_work", payload["automation_disposition"])
            self.assertEqual(["defer", "validate", "harness"], payload["recommended_dag_actions"])
            self.assertEqual([], remaining)
            self.assertEqual(0, repair["repair_node_count"])
            self.assertEqual(1, repair["unblocker_node_count"])
            defer_node = next(node for node in model["ready_nodes"] if node["action_type"] == "defer")
            defer_metadata = next(node["metadata"] for node in model["nodes"] if node["node_id"] == defer_node["node_id"])
            self.assertEqual("planner", defer_node["owner_role"])
            self.assertIn("defer", defer_metadata["candidate_unblocker_actions"])
            self.assertIn("validate", defer_metadata["candidate_unblocker_actions"])

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
                    [{"command": command, "classification": "unit_test", "gate_id": "gate:logs"}],
                    selected_by="test",
                    plan_id="plan:logs",
                )
                artifact = conn.execute(
                    "SELECT * FROM artifacts WHERE artifact_id = ?",
                    (result["jobs"][0]["log_artifact_id"],),
                ).fetchone()
                receipt = conn.execute(
                    "SELECT payload_json FROM validation_receipts WHERE run_id = ?",
                    (result["execution_group_id"],),
                ).fetchone()

            self.assertIsNotNone(artifact)
            self.assertIsNotNone(receipt)
            log_path = target / artifact["path"]
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("validation stdout marker", log_text)
            self.assertIn("validation stderr marker", log_text)
            receipt_payload = json.loads(receipt["payload_json"])
            self.assertEqual("unit_test", receipt_payload["classification"])
            self.assertEqual("parallel", receipt_payload["run_lane"])
            self.assertEqual("unit_tests", receipt_payload["command_family"])
            self.assertTrue(receipt_payload["planning_evidence"]["parallel_safe"])

            snapshot = state_snapshot(target)
            rendered = render_canonical_state_brief(snapshot, target=target)
            self.assertEqual("passed", snapshot["validation_job_summary"]["aggregate_status"])
            self.assertTrue(snapshot["parallel_validation_available"])
            self.assertEqual({"unit_test": 1}, snapshot["validation_job_summary"]["classification_counts"])
            self.assertEqual(1, snapshot["validation_job_summary"]["parallel_job_count"])
            self.assertIn("validation_jobs:", rendered)
            self.assertNotIn("## stdout", json.dumps(snapshot["validation_job_summary"]))
            self.assertNotIn("## stderr", json.dumps(snapshot["validation_job_summary"]))

    def test_worker_validation_node_includes_symbol_aware_validation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / ".agentic").mkdir(parents=True)
            (target / ".agentic" / "verification_commands.txt").write_text(
                "python3 -m unittest\npython3 -m py_compile src/auth.py\n",
                encoding="utf-8",
            )
            (target / "src").mkdir()
            (target / "tests").mkdir()
            (target / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
            (target / "tests" / "test_auth.py").write_text(
                "from src.auth import login\n\n"
                "def test_login():\n"
                "    assert login()\n",
                encoding="utf-8",
            )

            now = "2026-05-15T00:00:00+00:00"
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    refresh_capability_manifest_conn(conn, target)
                    ensure_codebase_graph_conn(conn, target)
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:auth-build",
                        task_id="T-auth",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.91,
                        metadata={"summary": "Update auth login", "paths": ["src/auth.py"]},
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            context_pack_id, started_at, finished_at, payload_json
                        )
                        VALUES('worker:test-auth', 'execution-group:test-auth', 'run:test-auth',
                               'write', 'builder', 'completed', '', ?, ?, ?)
                        """,
                        (
                            now,
                            now,
                            stable_json({"task_id": "T-auth", "dag_node_id": "dag-node:test:auth-build"}),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path,
                            patch_path, changed_files_json, base_commit, leases_json,
                            validation_evidence_json, conflict_signature, created_at,
                            queued_at, integrated_at, payload_json
                        )
                        VALUES('patch:test-auth', 'worker:test-auth', 'execution-group:test-auth', 'queued',
                               'target/automation_queue/builder/run:test-auth/manifest.json',
                               'target/automation_queue/builder/run:test-auth/changes.patch',
                               ?, '', '[]', '[]', '', ?, ?, '', '{}')
                        """,
                        (json.dumps(["src/auth.py"]), now, now),
                    )
                result = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")

            self.assertEqual(1, result["validation_node_count"])
            metadata = result["validation_nodes"][0]["metadata"]
            plan = metadata["validation_plan"]
            self.assertEqual("targeted", plan["strategy"])
            self.assertTrue(metadata["validation_commands"])
            self.assertTrue(plan["selection_reasons"])
            self.assertTrue(
                any(
                    command["selection_kind"] == "likely_test"
                    and "tests.test_auth" in command["command"]
                    and "tests/test_auth.py" in command["payload"]["selected_paths"]
                    for command in metadata["validation_commands"]
                )
            )

    def test_empty_conflict_worker_patch_is_superseded_without_repair_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            patch_path = target / "target" / "automation_queue" / "builder" / "run-empty" / "changes.patch"
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text("", encoding="utf-8")
            now = "2026-05-15T00:00:00+00:00"
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:empty-build",
                        task_id="T-empty",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.91,
                        metadata={"summary": "Build should not be repaired from an empty patch"},
                    )
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:worker-repair:stale-empty",
                        task_id="T-empty",
                        action_type="repair",
                        status="ready",
                        owner_role="builder",
                        patch_id="patch:empty",
                        patch_path="target/automation_queue/builder/run-empty/changes.patch",
                        blocker_reason="empty-signature",
                        confidence=0.84,
                        metadata={"summary": "Stale repair from an empty worker patch"},
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            context_pack_id, started_at, finished_at, payload_json
                        )
                        VALUES('worker:empty', 'execution-group:empty', 'run-empty',
                               'write', 'builder', 'failed', '', ?, ?, ?)
                        """,
                        (
                            now,
                            now,
                            stable_json({"task_id": "T-empty", "dag_node_id": "dag-node:test:empty-build"}),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path,
                            patch_path, changed_files_json, base_commit, leases_json,
                            validation_evidence_json, conflict_signature, created_at,
                            queued_at, integrated_at, payload_json
                        )
                        VALUES('patch:empty', 'worker:empty', 'execution-group:empty',
                               'conflict', 'target/automation_queue/builder/run-empty/manifest.json',
                               'target/automation_queue/builder/run-empty/changes.patch',
                               '[]', '', '[]', '[]', 'empty-signature', ?, '', '', ?)
                        """,
                        (
                            now,
                            stable_json({"failure_reason": 'error: No valid patches in input (allow with "--allow-empty")'}),
                        ),
                    )
                result = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                patch_row = conn.execute("SELECT status, payload_json FROM worker_patches WHERE patch_id = 'patch:empty'").fetchone()
                active_repair_count = conn.execute(
                    """
                    SELECT count(*)
                    FROM execution_dag_nodes
                    WHERE action_type = 'repair'
                      AND patch_id = 'patch:empty'
                      AND status IN ('ready', 'pending', 'planned', 'queued', 'active', 'running', 'in_progress', 'blocked', 'waiting')
                    """
                ).fetchone()[0]
                repair_status = conn.execute(
                    "SELECT status FROM execution_dag_nodes WHERE node_id = 'dag-node:worker-repair:stale-empty'"
                ).fetchone()["status"]
                lineages = worker_patch_lineage_conn(conn, patch_id="patch:empty")

            self.assertEqual("reconciled", result["status"])
            self.assertEqual(1, result["superseded_patch_count"])
            self.assertEqual(0, result["repair_node_count"])
            self.assertEqual(0, active_repair_count)
            self.assertEqual("superseded", repair_status)
            self.assertEqual("superseded", patch_row["status"])
            self.assertEqual("superseded", lineages[0]["status"])
            self.assertEqual("superseded", lineages[0]["integration_result"])
            self.assertIn("superseded_reason", json.loads(patch_row["payload_json"]))

    def test_reconcile_supersedes_duplicate_queued_patch_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            old_manifest = target / "target" / "automation_queue" / "builder" / "run-old" / "manifest.json"
            new_manifest = target / "target" / "automation_queue" / "builder" / "run-new" / "manifest.json"
            old_manifest.parent.mkdir(parents=True, exist_ok=True)
            new_manifest.parent.mkdir(parents=True, exist_ok=True)
            old_manifest.write_text(json.dumps({"status": "queued", "patch_id": "patch:old"}) + "\n", encoding="utf-8")
            new_manifest.write_text(json.dumps({"status": "queued", "patch_id": "patch:new"}) + "\n", encoding="utf-8")
            old_manifest.with_name("changes.patch").write_text("old\n", encoding="utf-8")
            new_manifest.with_name("changes.patch").write_text("new\n", encoding="utf-8")
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:build",
                        task_id="AUTO-002",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.9,
                        metadata={"summary": "Build AUTO-002"},
                    )
                    for patch_id, run_id, created_at, manifest_path in (
                        ("patch:old", "run-old", "2026-05-19T17:30:00+00:00", old_manifest),
                        ("patch:new", "run-new", "2026-05-19T18:01:00+00:00", new_manifest),
                    ):
                        conn.execute(
                            """
                            INSERT INTO worker_agents(worker_id, execution_group_id, run_id, mode, role, status,
                                                       started_at, finished_at, payload_json)
                            VALUES(?, 'execution-group:auto-002', ?, 'write', 'builder', 'completed', ?, ?, ?)
                            """,
                            (
                                f"worker:{run_id}",
                                run_id,
                                created_at,
                                created_at,
                                stable_json({"task_id": "AUTO-002", "dag_node_id": "dag-node:test:build"}),
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO worker_patches(
                                patch_id, worker_id, execution_group_id, status, manifest_path,
                                patch_path, changed_files_json, base_commit, leases_json,
                                validation_evidence_json, conflict_signature, created_at,
                                queued_at, integrated_at, payload_json
                            )
                            VALUES(?, ?, 'execution-group:auto-002', 'queued', ?, ?, ?,
                                   '', '[]', '[]', '', ?, ?, '', '{}')
                            """,
                            (
                                patch_id,
                                f"worker:{run_id}",
                                str(manifest_path.relative_to(target)),
                                str(manifest_path.with_name("changes.patch").relative_to(target)),
                                json.dumps(["src/app.js", ".diffmogger/state/CODEX_AUTOMATION_TASKS.md"]),
                                created_at,
                                created_at,
                            ),
                        )
                original_preflight = state_store_module.worker_patch_integration_preflight_conn
                try:
                    state_store_module.worker_patch_integration_preflight_conn = lambda conn, target=None, limit=20, persist=True: {"records": []}  # type: ignore[assignment]
                    result = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                finally:
                    state_store_module.worker_patch_integration_preflight_conn = original_preflight  # type: ignore[assignment]
                statuses = {
                    str(row["patch_id"]): str(row["status"])
                    for row in conn.execute("SELECT patch_id, status FROM worker_patches").fetchall()
                }
                integration_patch_ids = [
                    str(row["patch_id"])
                    for row in conn.execute("SELECT patch_id FROM execution_dag_nodes WHERE action_type = 'integrate'").fetchall()
                ]
                read_model = state_store_module.worker_patch_read_model_conn(conn, target=target)

            self.assertEqual("reconciled", result["status"])
            self.assertEqual(["patch:old"], result["superseded_patch_ids"])
            self.assertEqual({"patch:old": "superseded", "patch:new": "queued"}, statuses)
            self.assertEqual(["patch:new"], integration_patch_ids)
            self.assertEqual("superseded", json.loads(old_manifest.read_text(encoding="utf-8"))["status"])
            self.assertEqual(1, read_model["patch_backlog_summary"]["queued_patch_count"])
            self.assertEqual(0, read_model["patch_backlog_summary"]["repeated_repair_count"])

    def test_reconcile_defers_true_conflict_worker_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            manifest_path = target / "target" / "automation_queue" / "builder" / "run-conflict" / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps({"status": "queued", "patch_id": "patch:conflict"}) + "\n", encoding="utf-8")
            manifest_path.with_name("changes.patch").write_text("conflict\n", encoding="utf-8")
            now = "2026-05-19T18:00:00+00:00"
            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:conflict-build",
                        task_id="AUTO-002",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.9,
                        metadata={"summary": "Build AUTO-002"},
                    )
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:worker-preflight-repair:conflict",
                        task_id="AUTO-002",
                        action_type="repair",
                        status="ready",
                        owner_role="builder",
                        patch_id="patch:conflict",
                        patch_path="target/automation_queue/builder/run-conflict/changes.patch",
                        blocker_reason="true conflict",
                        confidence=0.86,
                        metadata={"source": "worker_patch_integration_preflight", "summary": "Repair conflict"},
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_agents(worker_id, execution_group_id, run_id, mode, role, status,
                                                   started_at, finished_at, payload_json)
                        VALUES('worker:conflict', 'execution-group:conflict', 'run-conflict',
                               'write', 'builder', 'completed', ?, ?, ?)
                        """,
                        (
                            now,
                            now,
                            stable_json({"task_id": "AUTO-002", "dag_node_id": "dag-node:test:conflict-build"}),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path,
                            patch_path, changed_files_json, base_commit, leases_json,
                            validation_evidence_json, conflict_signature, created_at,
                            queued_at, integrated_at, payload_json
                        )
                        VALUES('patch:conflict', 'worker:conflict', 'execution-group:conflict', 'queued',
                               ?, ?, ?, '', '[]', '[]', '', ?, ?, '', '{}')
                        """,
                        (
                            str(manifest_path.relative_to(target)),
                            str(manifest_path.with_name("changes.patch").relative_to(target)),
                            json.dumps(["src/app.js"]),
                            now,
                            now,
                        ),
                    )

                original_preflight = state_store_module.worker_patch_integration_preflight_conn

                def fake_preflight(conn, target=None, limit: int = 20, persist: bool = True):
                    return {
                        "records": [
                            {
                                "patch_id": "patch:conflict",
                                "status": "true_conflict",
                                "reason_kind": "integration_reconciliation_true_conflict",
                                "integration_resolution_detail": "Patch no longer applies to current files.",
                                "reasons": [
                                    {
                                        "kind": "integration_reconciliation_true_conflict",
                                        "severity": "block",
                                        "reason": "Patch no longer applies to current files.",
                                    }
                                ],
                            }
                        ]
                    }

                try:
                    state_store_module.worker_patch_integration_preflight_conn = fake_preflight
                    result = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                finally:
                    state_store_module.worker_patch_integration_preflight_conn = original_preflight
                patch_row = conn.execute("SELECT status, payload_json FROM worker_patches WHERE patch_id = 'patch:conflict'").fetchone()
                defer_nodes = [
                    row["action_type"]
                    for row in conn.execute("SELECT action_type FROM execution_dag_nodes WHERE patch_id = 'patch:conflict' AND action_type = 'defer'").fetchall()
                ]
                repair_status = conn.execute(
                    "SELECT status FROM execution_dag_nodes WHERE node_id = 'dag-node:worker-preflight-repair:conflict'"
                ).fetchone()["status"]
                lineages = worker_patch_lineage_conn(conn, patch_id="patch:conflict")

            self.assertEqual(["patch:conflict"], result["deferred_patch_ids"])
            self.assertEqual(1, result["defer_node_count"])
            self.assertEqual("deferred", patch_row["status"])
            self.assertEqual("deferred", json.loads(manifest_path.read_text(encoding="utf-8"))["status"])
            self.assertEqual(["defer"], defer_nodes)
            self.assertEqual("superseded", repair_status)
            self.assertEqual("deferred", lineages[0]["status"])
            self.assertEqual("deferred", lineages[0]["integration_result"])
            self.assertIn("integration_reconciliation_true_conflict", json.loads(patch_row["payload_json"])["deferral_reason"])

    def test_parallel_validation_uses_dag_node_validation_plan_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            command = f"{sys.executable} -c \"print('planned dag validation')\""
            node_id = "dag-node:test:planned-validation"

            with closing(connect(database_path_for_target(target))) as conn:
                with conn:
                    upsert_execution_dag_node(
                        conn,
                        node_id=node_id,
                        task_id="T-plan",
                        action_type="validate",
                        status="ready",
                        owner_role="hardener",
                        confidence=0.9,
                        metadata={
                            "paths": ["src/app.py"],
                            "validation_plan": {
                                "schema_version": 1,
                                "strategy": "targeted",
                                "selection_reasons": ["unit test selected for impacted app symbol"],
                                "commands": [
                                    {
                                        "command": command,
                                        "classification": "test",
                                        "required": True,
                                        "gate_id": "gate:test:planned",
                                        "selection_kind": "likely_test",
                                        "selection_reason": "unit test selected for impacted app symbol",
                                        "selection_reasons": ["unit test selected for impacted app symbol"],
                                        "payload": {
                                            "schema_version": 1,
                                            "selection_kind": "likely_test",
                                            "selection_reason": "unit test selected for impacted app symbol",
                                            "selection_reasons": ["unit test selected for impacted app symbol"],
                                            "selected_paths": ["tests/test_app.py"],
                                        },
                                    }
                                ],
                            },
                        },
                    )
                result = run_parallel_validation_conn(
                    conn,
                    target,
                    commands=None,
                    selected_by="test",
                    plan_id=node_id,
                )
                jobs = validation_jobs_conn(conn, limit=5)

            self.assertEqual("passed", result["status"])
            self.assertEqual([command], [job["command"] for job in jobs])
            self.assertEqual("likely_test", jobs[0]["payload"]["selection"]["selection_kind"])

    def test_symbol_aware_validation_plan_broadens_for_low_confidence_interface_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "src").mkdir(parents=True)
            (target / "api").mkdir()
            (target / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run", "typecheck": "tsc --noEmit", "build": "vite build"}}),
                encoding="utf-8",
            )
            (target / "src" / "client.ts").write_text("export function fetchUser() { return '/users'; }\n", encoding="utf-8")
            (target / "api" / "openapi.yaml").write_text("openapi: 3.0.0\npaths: {}\n", encoding="utf-8")

            with closing(connect(database_path_for_target(target))) as conn:
                refresh_capability_manifest_conn(conn, target)
                ensure_codebase_graph_conn(conn, target)
                node = upsert_execution_dag_node(
                    conn,
                    node_id="dag-node:test:validate-interface",
                    task_id="T-api",
                    action_type="validate",
                    status="ready",
                    owner_role="hardener",
                    confidence=0.52,
                    metadata={
                        "summary": "Validate client and OpenAPI contract changes",
                        "paths": ["src/client.ts", "api/openapi.yaml"],
                    },
                )
                plan = build_symbol_aware_validation_plan_conn(conn, target, dag_node=node)

            self.assertEqual("broader", plan["strategy"])
            self.assertIn("shared_interface_impact", plan["escalation_reasons"])
            self.assertTrue(any(reason.startswith("low_confidence:") for reason in plan["escalation_reasons"]))
            self.assertIn("cross_language_interface_impact", plan["escalation_reasons"])
            self.assertTrue(plan["commands"])
            self.assertTrue(any(command["selection_kind"] == "interface_contract" for command in plan["commands"]))
            self.assertTrue(all(command["selection_reasons"] for command in plan["commands"]))

    def test_worker_patch_lineage_records_predicted_and_actual_impact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "src").mkdir()
            (target / "src" / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            (target / "src" / "extra.py").write_text("def extra():\n    return 2\n", encoding="utf-8")
            now = "2026-05-15T00:00:00+00:00"

            with closing(connect(database_path_for_target(target))) as conn:
                refresh_capability_manifest_conn(conn, target)
                ensure_codebase_graph_conn(conn, target)
                with conn:
                    conn.execute(
                        """
                        INSERT INTO worker_agents(
                            worker_id, execution_group_id, run_id, mode, role, status,
                            context_pack_id, started_at, finished_at, payload_json
                        )
                        VALUES('worker:lineage', 'execution-group:lineage', 'run:lineage',
                               'write', 'builder', 'completed', '', ?, ?, ?)
                        """,
                        (
                            now,
                            "2026-05-15T00:00:10+00:00",
                            stable_json(
                                {
                                    "task_id": "T-lineage",
                                    "dag_node_id": "dag-node:test:lineage-build",
                                    "predicted_files": ["src/app.py"],
                                    "predicted_symbols": [
                                        {
                                            "symbol_node_id": "symbol:src/app.py:main",
                                            "symbol_name": "main",
                                            "qualified_name": "src.app.main",
                                            "path": "src/app.py",
                                            "confidence": 0.96,
                                        }
                                    ],
                                }
                            ),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO worker_patches(
                            patch_id, worker_id, execution_group_id, status, manifest_path,
                            patch_path, changed_files_json, base_commit, leases_json,
                            validation_evidence_json, conflict_signature, created_at,
                            queued_at, integrated_at, payload_json
                        )
                        VALUES('patch:lineage', 'worker:lineage', 'execution-group:lineage',
                               'queued', 'target/manifest.json', 'target/changes.patch',
                               ?, '', '[]', '[]', '', ?, ?, '', '{}')
                        """,
                        (json.dumps(["src/app.py", "src/extra.py"]), now, now),
                    )
                    upsert_execution_dag_node(
                        conn,
                        node_id="dag-node:test:lineage-build",
                        task_id="T-lineage",
                        action_type="build",
                        status="done",
                        owner_role="builder",
                        confidence=0.92,
                        metadata={"paths": ["src/app.py"]},
                    )
                result = reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test")
                lineages = worker_patch_lineage_conn(conn, patch_id="patch:lineage")

            self.assertEqual(1, result["validation_node_count"])
            self.assertEqual(["src/app.py"], lineages[0]["predicted_files"])
            self.assertEqual(["src/app.py", "src/extra.py"], lineages[0]["actual_files"])
            self.assertLess(lineages[0]["prediction_accuracy"]["files"]["recall"], 1.0)
            self.assertTrue(lineages[0]["actual_symbols"])

    def test_patch_lineage_summary_reports_rates_and_wall_clock_savings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with closing(connect(database_path_for_target(target))) as conn:
                now = "2026-05-15T00:00:00+00:00"
                with conn:
                    for patch_id, worker_id in (("patch:ok", "worker:ok"), ("patch:retry", "worker:retry")):
                        conn.execute(
                            """
                            INSERT INTO worker_agents(worker_id, execution_group_id, run_id, mode, role, status, started_at, finished_at, payload_json)
                            VALUES(?, 'execution-group:lineage-wave', ?, 'write', 'builder', 'completed', ?, ?, '{}')
                            """,
                            (worker_id, worker_id, now, "2026-05-15T00:00:10+00:00"),
                        )
                        conn.execute(
                            """
                            INSERT INTO worker_patches(
                                patch_id, worker_id, execution_group_id, status, manifest_path,
                                patch_path, changed_files_json, base_commit, leases_json,
                                validation_evidence_json, conflict_signature, created_at,
                                queued_at, integrated_at, payload_json
                            )
                            VALUES(?, ?, 'execution-group:lineage-wave', 'queued',
                                   '', '', '[]', '', '[]', '[]', '', ?, ?, '', '{}')
                            """,
                            (patch_id, worker_id, now, now),
                        )
                    upsert_worker_patch_lineage_conn(
                        conn,
                        patch_id="patch:ok",
                        worker_id="worker:ok",
                        execution_group_id="execution-group:lineage-wave",
                        status="integrated",
                        predicted_files=["src/app.py"],
                        actual_files=["src/app.py"],
                        validations=[{"job_id": "job:ok", "status": "passed", "command": "test"}],
                        integration_result="integrated",
                        started_at="2026-05-15T00:00:00+00:00",
                        finished_at="2026-05-15T00:00:10+00:00",
                    )
                    upsert_worker_patch_lineage_conn(
                        conn,
                        patch_id="patch:retry",
                        worker_id="worker:retry",
                        execution_group_id="execution-group:lineage-wave",
                        status="repair_created",
                        predicted_files=["src/api.py"],
                        actual_files=["src/api.py", "tests/test_api.py"],
                        validations=[{"job_id": "job:retry", "status": "failed", "command": "test"}],
                        conflicts=[{"conflict_signature": "abc", "source": "test"}],
                        repair_node_ids=["dag-node:repair"],
                        integration_result="repair_required",
                        started_at="2026-05-15T00:00:00+00:00",
                        finished_at="2026-05-15T00:00:08+00:00",
                    )
                summary = patch_lineage_summary_conn(conn)

            self.assertEqual(2, summary["lineage_count"])
            self.assertEqual(0.5, summary["telemetry"]["conflict_rate"])
            self.assertEqual(0.5, summary["telemetry"]["validation_failure_rate"])
            self.assertEqual(0.5, summary["telemetry"]["retry_rate"])
            self.assertEqual(0.5, summary["telemetry"]["integration_success_rate"])
            self.assertEqual(8.0, summary["telemetry"]["wall_clock_savings_seconds"])
            self.assertGreater(summary["prediction_accuracy"]["average_file_f1"], 0)
            snapshot = state_snapshot(target)
            rendered = render_canonical_state_brief(snapshot, target=target)
            self.assertEqual(summary["prediction_accuracy"], snapshot["patch_prediction_accuracy"])
            self.assertEqual(summary["telemetry"], snapshot["patch_telemetry"])
            self.assertIn("patch_lineage:", rendered)

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

    def test_missing_required_projection_event_is_reconciled_by_snapshot_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            snapshot = state_snapshot(target)
            db = sqlite3.connect(snapshot["database"]["path"])
            try:
                db.execute(
                    "UPDATE projections SET event_id = ? WHERE name = ?",
                    (999999, AUTOMATION_ACTIVITY_PROJECTION_NAME),
                )
                db.commit()
            finally:
                db.close()

            validation = validate_state_database(target)
            projection_items = [
                item for item in validation["items"] if item.get("invariant") == "projections.event_id_exists"
            ]

            self.assertEqual("pass", validation["status"])
            self.assertEqual(1, len(projection_items))
            self.assertTrue(projection_items[0]["ok"])

    def test_state_snapshot_includes_invariant_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = state_snapshot(Path(tmp))
            invariant_names = {item["name"] for item in snapshot["invariant_results"]}

            self.assertEqual("pass", snapshot["state_health_summary"]["status"])
            self.assertIn("events.sequence_contiguous", invariant_names)
            self.assertIn("events.hash_chain", invariant_names)
            self.assertIn("projections.event_id_exists", invariant_names)

    def test_legacy_json_is_ignored_until_explicit_migration(self) -> None:
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

            ignored = load_conveyor_state(projection_path)
            pre_migration = state_snapshot(target)
            migration = import_legacy_target_state(target)
            loaded_again = load_conveyor_state(projection_path)
            post_migration = state_snapshot(target)

            self.assertEqual(0, ignored["cycles"])
            self.assertEqual(1, migration["conveyor_projection"])
            self.assertEqual(7, loaded_again["cycles"])
            self.assertLess(pre_migration["counts"]["events"], post_migration["counts"]["events"])
            self.assertEqual("migration.legacy_conveyor_json_imported", post_migration["last_event"]["event_type"])

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
            self.assertGreaterEqual(projection_count, 2)

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
            decision_machine = self._activity_machine(target)
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
            running_machine = self._activity_machine(target)
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
                "reason": "hardener completed; planner gets the next activity pass",
                "decided_at": "2026-05-12T23:11:51+00:00",
            }

            write_state(
                projection_path,
                state,
                event_type="conveyor.decision_recorded",
                actor_role="conveyor",
                phase="decision",
            )
            machine = self._activity_machine(target)

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
            machine = self._activity_machine(target)

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
            machine = self._activity_machine(target)
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
            machine = self._activity_machine(target)
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

    def test_task_markdown_projection_is_not_runtime_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            agentic = target / ".agentic"
            agentic.mkdir(parents=True)
            (agentic / "project_intake.json").write_text(
                json.dumps({"project_name": "Typed Control Demo", "campaign_mode": "ongoing"}),
                encoding="utf-8",
            )
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

    def test_ticket_progress_updates_ticket_campaign_control_from_ready_scaffold(self) -> None:
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
            self.assertEqual("T2 Ticket implementation", seeded["horizon"])
            self.assertEqual("ready", seeded["bootstrap_status"])

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
            self.assertEqual("stay", control["horizon_decision"])
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
                        {"id": "TICKET-001", "summary": "First increment", "status": "done", "evidence": ["accepted by integrator"]},
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
                        {"id": "TICKET-001", "summary": "First increment", "status": "done", "evidence": ["accepted by integrator"]},
                        {"id": "TICKET-002", "summary": "Second increment", "status": "done", "evidence": ["verified by hardener"]},
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
