from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.conveyor import runner as conveyor_runner
from diffmogger.conveyor.scheduler import DAG_RUNNER_ACTIONS
from diffmogger.runtime.state_store import (
    connect,
    create_repair_nodes_for_failed_validation_conn,
    database_path_for_target,
    execution_dag_edges_conn,
    execution_dag_read_model,
    latest_scheduler_decision_conn,
    launch_read_only_execution_group_conn,
    reconcile_worker_results_into_execution_dag_conn,
    record_validation_group_result_on_execution_dag_conn,
    scope_fanout_outcomes_conn,
    stable_json,
    state_snapshot,
    update_execution_dag_node_status_conn,
    update_execution_group_dag_nodes_conn,
    upsert_execution_dag_node,
    worker_patches_conn,
    write_ticket_run_state,
)


CONVEYOR_PATHS = [
    ROOT / "src" / "diffmogger" / "runtime" / "run_conveyor_automation.py",
]


def load_conveyor(path: Path):
    module_name = "conveyor_under_test_" + path.relative_to(ROOT).as_posix().replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DagSchedulerRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = [(path, load_conveyor(path)) for path in CONVEYOR_PATHS]

    def write_text(self, root: Path, relative: str, content: str, *, executable: bool = False) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        if executable:
            path.chmod(0o755)
        return path

    def seed_target(self, target: Path) -> None:
        self.write_text(
            target,
            "docs/CODEX_AUTOMATION_TASKS.md",
            """
            # Codex Automation Tasks

            AUTOMATION_STATUS: ACTIVE
            """,
        )
        self.write_text(
            target,
            "scripts/run_role_automation.sh",
            """
            #!/usr/bin/env bash
            exit 0
            """,
            executable=True,
        )

    def latest_candidate(self, target: Path) -> dict[str, object]:
        with closing(connect(database_path_for_target(target))) as conn:
            decision = latest_scheduler_decision_conn(conn)
        selected = decision.get("selected_candidate") if isinstance(decision.get("selected_candidate"), dict) else {}
        return dict(selected)

    def ready_build_node(self, target: Path, *, node_id: str = "dag-node:test:build") -> None:
        with closing(connect(database_path_for_target(target))) as conn:
            with conn:
                upsert_execution_dag_node(
                    conn,
                    node_id=node_id,
                    task_id="T1",
                    action_type="build",
                    status="ready",
                    owner_role="builder",
                    confidence=0.9,
                    metadata={
                        "source": "test.dag_scheduler",
                        "summary": "Update src/app.py",
                        "paths": ["src/app.py"],
                    },
                )

    def seed_worker_patch(
        self,
        target: Path,
        *,
        patch_id: str = "patch:test-worker",
        worker_id: str = "worker:test",
        execution_group_id: str = "execution-group:test",
        run_id: str = "run:test",
        source_node_id: str = "dag-node:test:worker-build",
        task_id: str = "T1",
        changed_files: list[str] | None = None,
        status: str = "queued",
    ) -> None:
        changed_files = changed_files or ["src/app.py"]
        now = "2026-05-15T00:00:00+00:00"
        with closing(connect(database_path_for_target(target))) as conn:
            with conn:
                upsert_execution_dag_node(
                    conn,
                    node_id=source_node_id,
                    task_id=task_id,
                    action_type="build",
                    status="done",
                    owner_role="builder",
                    confidence=0.9,
                    metadata={
                        "source": "test.dag_scheduler",
                        "summary": f"Worker build for {task_id}",
                        "paths": changed_files,
                    },
                )
                conn.execute(
                    """
                    INSERT INTO worker_agents(
                        worker_id, execution_group_id, run_id, mode, role, status,
                        context_pack_id, started_at, finished_at, payload_json
                    )
                    VALUES(?, ?, ?, 'write', 'builder', 'completed', '', ?, ?, ?)
                    """,
                    (
                        worker_id,
                        execution_group_id,
                        run_id,
                        now,
                        now,
                        stable_json({"task_id": task_id, "dag_node_id": source_node_id}),
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
                    VALUES(?, ?, ?, ?, ?, ?, ?, '', '[]', '[]', '', ?, ?, '', '{}')
                    """,
                    (
                        patch_id,
                        worker_id,
                        execution_group_id,
                        status,
                        f"target/automation_queue/builder/{run_id}/manifest.json",
                        f"target/automation_queue/builder/{run_id}/changes.patch",
                        json.dumps(changed_files),
                        now,
                        now,
                    ),
                )

    def seed_queued_role_manifest(
        self,
        target: Path,
        *,
        role: str = "builder",
        run_id: str = "serial-builder",
        ticket_id: str = "TICKET-001",
        changed_files: list[str] | None = None,
    ) -> Path:
        changed_files = changed_files or ["src/app.py"]
        queue_dir = target / "target" / "automation_queue" / role / run_id
        queue_dir.mkdir(parents=True, exist_ok=True)
        patch_path = queue_dir / "changes.patch"
        summary_path = queue_dir / "summary.md"
        ticket_actions_path = queue_dir / "ticket_state_actions.json"
        patch_path.write_text(
            "diff --git a/src/app.py b/src/app.py\n"
            "new file mode 100644\n"
            "index 0000000..8baef1b\n"
            "--- /dev/null\n"
            "+++ b/src/app.py\n"
            "@@ -0,0 +1 @@\n"
            "+VALUE = 1\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            f"Commit type: chore\nCommit scope: layout\nCommit subject: update {ticket_id}\n\n## Summary\n- Completed {ticket_id}.\n",
            encoding="utf-8",
        )
        ticket_actions_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "actions": [
                        {
                            "action": "update_ticket",
                            "ticket_id": ticket_id,
                            "ticket": {
                                "id": ticket_id,
                                "summary": "Create local project directory layout",
                                "status": "candidate_done",
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest = {
            "role": role,
            "run_id": run_id,
            "base_commit": "base-commit",
            "status": "queued",
            "patch_path": str(patch_path),
            "changed_files": changed_files,
            "ticket_state_actions_path": str(ticket_actions_path),
            "runtime_state_action_count": 1,
            "runtime_state_status": "pending",
            "checks_run": ["python3 -m py_compile src/app.py"],
            "summary": summary_path.read_text(encoding="utf-8"),
            "created_at": "2026-05-15T00:00:00+00:00",
            "integrated_at": None,
        }
        manifest_path = queue_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    def dag_nodes_by_action(self, target: Path, action_type: str) -> list[dict[str, object]]:
        with closing(connect(database_path_for_target(target))) as conn:
            model = execution_dag_read_model(conn)
        return [
            dict(item)
            for item in model["nodes"]
            if isinstance(item, dict) and item.get("action_type") == action_type
        ]

    def run_fake_review_action(self, target: Path, candidate: dict[str, object]) -> int:
        original_launch = conveyor_runner.launch_read_only_execution_group_conn

        def fake_launch(conn, target_arg, *, execution_group_id: str = "", selected_by: str = ""):
            return {"status": "completed", "execution_group_id": execution_group_id, "target": str(target_arg)}

        try:
            conveyor_runner.launch_read_only_execution_group_conn = fake_launch
            return conveyor_runner.run_scheduler_action(target, candidate, False)
        finally:
            conveyor_runner.launch_read_only_execution_group_conn = original_launch

    def fake_scope_report_without_promotable_evidence(self, command: list[str], *, cwd: Path, timeout: int):
        report_path = Path(command[command.index("--report-path") + 1])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "\n".join(
                [
                    "# Read-only Scope Report",
                    "",
                    "Worker found possible ownership, but no normalized write owner cleared the threshold.",
                    "",
                    "```json",
                    json.dumps(
                        {
                            "scope_evidence_records": [
                                {
                                    "candidate_symbol": "AmbiguousOwner",
                                    "confidence": 0.62,
                                    "reasons": ["symbol was not resolved to a unique current owner"],
                                }
                            ]
                        },
                        sort_keys=True,
                    ),
                    "```",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout=f"WORKER_REPORT path={report_path}\n", stderr="")

    def test_declares_required_dag_runner_actions(self) -> None:
        self.assertTrue(
            {
                "launch_scope_group",
                "launch_write_group",
                "launch_validation_group",
                "launch_review_group",
                "run_serial_integration",
                "reconcile_worker_results",
                "create_repair_nodes",
                "refresh_index",
                "run_serial_role",
            }.issubset(DAG_RUNNER_ACTIONS)
        )

    def test_dependency_ready_ticket_uses_scope_fanout_before_serial_role_fallback(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    write_ticket_run_state(
                        target,
                        {
                            "run_id": "ticket-run",
                            "halt_when_complete": True,
                            "notify_on_complete": False,
                            "tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Create local project directory layout",
                                    "status": "pending",
                                    "depends_on": [],
                                }
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_test",
                    )

                    role, reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)

                    self.assertEqual("planner", role)
                    self.assertFalse(stop)
                    self.assertIn("read-only workers", reason)
                    self.assertEqual("launch_scope_group", candidate["action_kind"])
                    self.assertEqual("TICKET-001", candidate["task_id"])
                    self.assertTrue(candidate["scope_evidence_required"])
                    self.assertEqual([], candidate["required_leases"])
                    self.assertTrue(candidate["execution_group_id"])
                    with closing(connect(database_path_for_target(target))) as conn:
                        item = conn.execute(
                            """
                            SELECT action_kind, required_leases_json, payload_json
                            FROM execution_group_items
                            WHERE execution_group_id = ?
                            LIMIT 1
                            """,
                            (str(candidate["execution_group_id"]),),
                        ).fetchone()
                    self.assertIsNotNone(item)
                    item_payload = json.loads(item["payload_json"])
                    self.assertEqual("scope_execution", item["action_kind"])
                    self.assertEqual([], json.loads(item["required_leases_json"]))
                    self.assertEqual("scope", item_payload["canonical_action_type"])
                    self.assertTrue(item_payload["scope_evidence_required"])

                    exit_code = self.run_fake_review_action(target, candidate)
                    self.assertEqual(0, exit_code)

    def test_scope_fanout_exhaustion_falls_back_to_serial_role(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    write_ticket_run_state(
                        target,
                        {
                            "run_id": "ticket-run",
                            "halt_when_complete": True,
                            "notify_on_complete": False,
                            "tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Create local project directory layout",
                                    "status": "pending",
                                    "depends_on": [],
                                }
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_test",
                    )

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    first = self.latest_candidate(target)
                    self.assertEqual("planner", role)
                    self.assertFalse(stop)
                    self.assertEqual("launch_scope_group", first["action_kind"])

                    with closing(connect(database_path_for_target(target))) as conn:
                        result = launch_read_only_execution_group_conn(
                            conn,
                            target,
                            execution_group_id=str(first["execution_group_id"]),
                            max_workers=1,
                            command_runner=self.fake_scope_report_without_promotable_evidence,
                        )
                        self.assertEqual("completed", result["status"])
                        update_execution_group_dag_nodes_conn(
                            conn,
                            str(first["execution_group_id"]),
                            status="done",
                            selected_by="test.scope_fanout",
                        )
                        outcomes = scope_fanout_outcomes_conn(conn, task_id="TICKET-001")
                    self.assertEqual("exhausted", outcomes[0]["status"])
                    self.assertEqual(1, outcomes[0]["attempt_count"])
                    snapshot = state_snapshot(target)
                    self.assertTrue(snapshot["exhausted_scope_fanout_outcomes"])
                    rendered_reasons = [
                        group["reason_kind"]
                        for group in snapshot["why_not_parallel"]["reason_groups"]
                        if isinstance(group, dict)
                    ]
                    self.assertIn("serial_fallback", rendered_reasons)
                    raw_reason_kinds = [
                        raw
                        for group in snapshot["why_not_parallel"]["reason_groups"]
                        if isinstance(group, dict)
                        for raw in group.get("raw_reason_kinds", [])
                    ]
                    self.assertIn("scope_fanout_exhausted", raw_reason_kinds)

                    role, reason, stop = module.choose_next(target, {}, 2)
                    second = self.latest_candidate(target)

                    self.assertEqual("builder", role)
                    self.assertFalse(stop)
                    self.assertEqual("run_serial_role", second["action_kind"])
                    self.assertEqual("TICKET-001", second["task_id"])
                    self.assertEqual("scope_fanout_exhausted", second["parallel_block_reason_kind"])
                    self.assertEqual("serial_fallback", second["parallel_block_display_reason_kind"])
                    self.assertIn("serial_fallback", reason)

    def test_queued_serial_role_manifest_reconciles_into_dag_handoff(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/app.py", "VALUE = 0\n")
                    self.seed_queued_role_manifest(target)
                    with closing(connect(database_path_for_target(target))) as conn:
                        with conn:
                            upsert_execution_dag_node(
                                conn,
                                node_id="dag-node:test:serial-build",
                                task_id="TICKET-001",
                                action_type="build",
                                status="running",
                                owner_role="builder",
                                confidence=0.9,
                                metadata={"source": "test.serial_role", "paths": ["src/app.py"]},
                            )

                    role, reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)

                    self.assertEqual("integrator", role)
                    self.assertFalse(stop)
                    self.assertIn("queued worker patch", reason)
                    self.assertEqual("reconcile_worker_results", candidate["action_kind"])
                    with closing(connect(database_path_for_target(target))) as conn:
                        patches = worker_patches_conn(conn, statuses={"queued"}, limit=5)
                        build_node = conn.execute(
                            "SELECT status FROM execution_dag_nodes WHERE node_id = ?",
                            ("dag-node:test:serial-build",),
                        ).fetchone()
                    self.assertEqual(1, len(patches))
                    self.assertTrue(patches[0]["patch_id"].startswith("role-patch:"))
                    self.assertEqual("TICKET-001", patches[0]["payload"]["task_id"])
                    self.assertEqual("done", build_node["status"])

                    self.assertEqual(0, conveyor_runner.run_scheduler_action(target, candidate, False))
                    with closing(connect(database_path_for_target(target))) as conn:
                        model = execution_dag_read_model(conn)
                    self.assertIn("review", {item["action_type"] for item in model["ready_nodes"]})
                    self.assertIn("integrate", {item["action_type"] for item in model["blocked_nodes"]})

    def test_serial_builder_patch_handoff_survives_in_progress_ticket_materialization(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/app.py", "VALUE = 0\n")
                    write_ticket_run_state(
                        target,
                        {
                            "run_id": "ticket-run",
                            "tickets": [
                                {
                                    "id": "TICKET-001",
                                    "summary": "Create local project directory layout",
                                    "status": "in_progress",
                                    "depends_on": [],
                                }
                            ],
                        },
                        actor_role="test",
                        event_type="ticket.run_test",
                    )
                    self.seed_queued_role_manifest(target)

                    role, reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)

                    self.assertEqual("integrator", role)
                    self.assertFalse(stop)
                    self.assertIn("queued worker patch", reason)
                    self.assertEqual("reconcile_worker_results", candidate["action_kind"])
                    self.assertEqual(0, conveyor_runner.run_scheduler_action(target, candidate, False))

                    role, reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)

                    self.assertEqual("hardener", role)
                    self.assertFalse(stop)
                    self.assertNotIn("no DAG-ready scheduler action", reason)
                    self.assertIn("queued worker patch", reason)
                    self.assertEqual("launch_review_group", candidate["action_kind"])
                    with closing(connect(database_path_for_target(target))) as conn:
                        ticket = conn.execute(
                            "SELECT status FROM ticket_items WHERE ticket_id = 'TICKET-001'",
                        ).fetchone()
                        build = conn.execute(
                            "SELECT status FROM execution_dag_nodes WHERE task_id = 'TICKET-001' AND action_type = 'build'",
                        ).fetchone()
                    self.assertEqual("in_progress", ticket["status"])
                    self.assertEqual("done", build["status"])

    def test_dag_ready_write_node_launches_through_runner_action(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.write_text(target, "src/app.py", "VALUE = 1\n")
                    self.ready_build_node(target)

                    role, reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)

                    self.assertEqual("builder", role)
                    self.assertFalse(stop)
                    self.assertIn("ready DAG write nodes", reason)
                    self.assertEqual("launch_write_group", candidate["action_kind"])
                    self.assertTrue(str(candidate["execution_group_id"]).startswith("execution-group:"))

                    launched: list[dict[str, str]] = []
                    original_launch = conveyor_runner.launch_write_execution_group_conn
                    original_reconcile = conveyor_runner.reconcile_worker_results_into_execution_dag_conn

                    def fake_launch(conn, target_arg, *, execution_group_id: str = "", selected_by: str = ""):
                        launched.append({"execution_group_id": execution_group_id, "selected_by": selected_by})
                        return {"status": "completed", "execution_group_id": execution_group_id, "target": str(target_arg)}

                    def fake_reconcile(conn, *, target: Path | None = None, selected_by: str = "dag_scheduler", limit: int = 50):
                        return {"status": "skipped", "selected_by": selected_by, "limit": limit}

                    try:
                        conveyor_runner.launch_write_execution_group_conn = fake_launch
                        conveyor_runner.reconcile_worker_results_into_execution_dag_conn = fake_reconcile
                        exit_code = conveyor_runner.run_scheduler_action(target, candidate, False)
                    finally:
                        conveyor_runner.launch_write_execution_group_conn = original_launch
                        conveyor_runner.reconcile_worker_results_into_execution_dag_conn = original_reconcile

                    self.assertEqual(0, exit_code)
                    self.assertEqual(candidate["execution_group_id"], launched[0]["execution_group_id"])
                    with closing(connect(database_path_for_target(target))) as conn:
                        model = execution_dag_read_model(conn)
                    node = next(item for item in model["terminal_nodes"] if item["node_id"] == "dag-node:test:build")
                    self.assertEqual("done", node["status"])

    def test_worker_patches_flow_through_review_validation_before_serial_integration(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    patch_id = "patch:test-worker"
                    source_node_id = "dag-node:test:worker-build"
                    self.seed_worker_patch(target, patch_id=patch_id, source_node_id=source_node_id)

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)
                    self.assertEqual("integrator", role)
                    self.assertFalse(stop)
                    self.assertEqual("reconcile_worker_results", candidate["action_kind"])
                    self.assertEqual(0, conveyor_runner.run_scheduler_action(target, candidate, False))

                    with closing(connect(database_path_for_target(target))) as conn:
                        model = execution_dag_read_model(conn)
                        edges = execution_dag_edges_conn(conn)
                    ready_actions = {item["action_type"] for item in model["ready_nodes"]}
                    blocked_actions = {item["action_type"] for item in model["blocked_nodes"]}
                    self.assertIn("review", ready_actions)
                    self.assertIn("validate", blocked_actions)
                    self.assertIn("integrate", blocked_actions)
                    self.assertIn(
                        (source_node_id, "reviews"),
                        {(edge["source"], edge["dependency_kind"]) for edge in edges},
                    )
                    review_edge = next(edge for edge in edges if edge["source"] == source_node_id and edge["dependency_kind"] == "reviews")
                    validation_edge = next(edge for edge in edges if edge["source"].startswith("dag-node:worker-review:") and edge["dependency_kind"] == "validates")
                    self.assertEqual("advisory", review_edge["dependency_mode"])
                    self.assertEqual("hard", validation_edge["dependency_mode"])

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)
                    self.assertEqual("hardener", role)
                    self.assertFalse(stop)
                    self.assertEqual("launch_review_group", candidate["action_kind"])
                    self.assertEqual(0, self.run_fake_review_action(target, candidate))

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)
                    self.assertEqual("hardener", role)
                    self.assertFalse(stop)
                    self.assertEqual("launch_validation_group", candidate["action_kind"])

                    original_validation = conveyor_runner.run_parallel_validation_conn

                    def fake_validation(conn, target_arg, commands=None, *, selected_by: str = "", plan_id: str = ""):
                        return {
                            "status": "passed",
                            "execution_group_id": "validation-group:test",
                            "plan_id": plan_id,
                            "jobs": [],
                            "validation_job_summary": {"aggregate_status": "passed"},
                        }

                    try:
                        conveyor_runner.run_parallel_validation_conn = fake_validation
                        self.assertEqual(0, conveyor_runner.run_scheduler_action(target, candidate, False))
                    finally:
                        conveyor_runner.run_parallel_validation_conn = original_validation

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)
                    self.assertEqual("integrator", role)
                    self.assertFalse(stop)
                    self.assertEqual("run_serial_integration", candidate["action_kind"])

                    original_run_role = conveyor_runner.run_role
                    try:
                        conveyor_runner.run_role = lambda *args, **kwargs: 0
                        self.assertEqual(0, conveyor_runner.run_scheduler_action(target, candidate, False))
                    finally:
                        conveyor_runner.run_role = original_run_role

                    with closing(connect(database_path_for_target(target))) as conn:
                        patch = conn.execute("SELECT status, integrated_at FROM worker_patches WHERE patch_id = ?", (patch_id,)).fetchone()
                        model = execution_dag_read_model(conn)
                    integration_node_id = next(
                        item["node_id"]
                        for item in model["terminal_nodes"]
                        if item["action_type"] == "integrate" and item["task_id"] == "T1"
                    )
                    self.assertEqual("integrated", patch["status"])
                    self.assertTrue(patch["integrated_at"])
                    self.assertTrue(integration_node_id.startswith("dag-node:worker-integration:"))

    def test_scheduler_uses_preflight_safe_patch_subset_for_serial_integration(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.seed_worker_patch(
                        target,
                        patch_id="patch:a-ready",
                        worker_id="worker:a-ready",
                        run_id="run:a-ready",
                        source_node_id="dag-node:test:build-ready",
                        task_id="T1",
                        changed_files=["src/shared.py"],
                    )
                    self.seed_worker_patch(
                        target,
                        patch_id="patch:z-conflict",
                        worker_id="worker:z-conflict",
                        run_id="run:z-conflict",
                        source_node_id="dag-node:test:build-conflict",
                        task_id="T2",
                        changed_files=["src/shared.py"],
                    )
                    with closing(connect(database_path_for_target(target))) as conn:
                        reconcile_worker_results_into_execution_dag_conn(conn, target=target, selected_by="test.preflight")
                        ready_row = conn.execute(
                            "SELECT node_id FROM execution_dag_nodes WHERE action_type = 'integrate' AND patch_id = 'patch:a-ready'",
                        ).fetchone()
                        self.assertIsNotNone(ready_row)
                        dependency_ids = [
                            str(row["source_node_id"])
                            for row in conn.execute(
                                "SELECT source_node_id FROM execution_dag_edges WHERE target_node_id = ?",
                                (ready_row["node_id"],),
                            ).fetchall()
                            if str(row["source_node_id"])
                        ]
                        for dependency_id in dependency_ids:
                            update_execution_dag_node_status_conn(
                                conn,
                                dependency_id,
                                status="done",
                                selected_by="test.preflight",
                            )
                            for upstream in conn.execute(
                                "SELECT source_node_id FROM execution_dag_edges WHERE target_node_id = ?",
                                (dependency_id,),
                            ).fetchall():
                                update_execution_dag_node_status_conn(
                                    conn,
                                    str(upstream["source_node_id"]),
                                    status="done",
                                    selected_by="test.preflight",
                                )
                        update_execution_dag_node_status_conn(
                            conn,
                            ready_row["node_id"],
                            status="ready",
                            selected_by="test.preflight",
                        )

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)

                    self.assertEqual("integrator", role)
                    self.assertFalse(stop)
                    self.assertEqual("run_serial_integration", candidate["action_kind"])
                    self.assertEqual(["patch:a-ready"], candidate["patch_ids"])
                    self.assertEqual(["patch:a-ready"], candidate["integration_preflight"]["safe_patch_ids"])
                    self.assertEqual(0, candidate["integration_preflight"]["likely_conflict_count"])
                    self.assertEqual(1, candidate["integration_preflight"]["reconcilable_overlap_count"])

    def test_multi_builder_wave_converges_into_compatible_review_node(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    self.seed_worker_patch(
                        target,
                        patch_id="patch:test-a",
                        worker_id="worker:test-a",
                        run_id="run:test-a",
                        source_node_id="dag-node:test:build-a",
                        task_id="T1",
                        changed_files=["src/app.py"],
                    )
                    self.seed_worker_patch(
                        target,
                        patch_id="patch:test-b",
                        worker_id="worker:test-b",
                        run_id="run:test-b",
                        source_node_id="dag-node:test:build-b",
                        task_id="T2",
                        changed_files=["src/util.py"],
                    )

                    role, _reason, stop = module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)
                    self.assertEqual("integrator", role)
                    self.assertFalse(stop)
                    self.assertEqual("reconcile_worker_results", candidate["action_kind"])
                    self.assertEqual(0, conveyor_runner.run_scheduler_action(target, candidate, False))

                    with closing(connect(database_path_for_target(target))) as conn:
                        model = execution_dag_read_model(conn)
                    compatibility_task_ids = {"task:conveyor", "task:automation"}
                    review_nodes = [
                        item
                        for item in model["nodes"]
                        if item["action_type"] == "review" and item["task_id"] not in compatibility_task_ids
                    ]
                    validation_nodes = [
                        item
                        for item in model["nodes"]
                        if item["action_type"] == "validate" and item["task_id"] not in compatibility_task_ids
                    ]
                    integration_nodes = [
                        item
                        for item in model["nodes"]
                        if item["action_type"] == "integrate" and item["task_id"] not in compatibility_task_ids
                    ]
                    self.assertEqual(1, len(review_nodes))
                    self.assertEqual(1, len(validation_nodes))
                    self.assertEqual(2, len(integration_nodes))
                    review = review_nodes[0]
                    review_metadata = review["metadata"]
                    self.assertEqual(["patch:test-a", "patch:test-b"], review_metadata["patch_ids"])
                    self.assertEqual(
                        ["dag-node:test:build-a", "dag-node:test:build-b"],
                        review_metadata["covered_builder_node_ids"],
                    )
                    self.assertEqual(["src/app.py", "src/util.py"], review_metadata["paths"])
                    self.assertEqual(review["node_id"], validation_nodes[0]["metadata"]["review_node_id"])

    def test_failed_validation_creates_targeted_repair_node_from_receipt(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    patch_id = "patch:test-worker"
                    source_node_id = "dag-node:test:worker-build"
                    self.seed_worker_patch(target, patch_id=patch_id, source_node_id=source_node_id)

                    module.choose_next(target, {}, 2)
                    self.assertEqual(0, conveyor_runner.run_scheduler_action(target, self.latest_candidate(target), False))

                    module.choose_next(target, {}, 2)
                    self.assertEqual(0, self.run_fake_review_action(target, self.latest_candidate(target)))

                    module.choose_next(target, {}, 2)
                    candidate = self.latest_candidate(target)
                    self.assertEqual("launch_validation_group", candidate["action_kind"])

                    original_validation = conveyor_runner.run_parallel_validation_conn

                    def fake_failed_validation(conn, target_arg, commands=None, *, selected_by: str = "", plan_id: str = ""):
                        now = "2026-05-15T00:00:00+00:00"
                        job = {
                            "job_id": "validation-job:test",
                            "execution_group_id": "validation-group:test",
                            "plan_id": plan_id,
                            "gate_id": "T1",
                            "command": "python -m pytest",
                            "cwd": "",
                            "status": "failed",
                            "started_at": now,
                            "finished_at": now,
                            "exit_code": 1,
                            "log_artifact_id": "log:validation-job:test",
                            "resource_profile": "cpu",
                            "payload": {"required": True},
                        }
                        conn.execute(
                            """
                            INSERT INTO validation_jobs(
                                job_id, execution_group_id, plan_id, gate_id, command, cwd,
                                status, started_at, finished_at, exit_code, log_artifact_id,
                                resource_profile, payload_json
                            )
                            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                job["job_id"],
                                job["execution_group_id"],
                                job["plan_id"],
                                job["gate_id"],
                                job["command"],
                                job["cwd"],
                                job["status"],
                                job["started_at"],
                                job["finished_at"],
                                job["exit_code"],
                                job["log_artifact_id"],
                                job["resource_profile"],
                                stable_json(job["payload"]),
                            ),
                        )
                        return {
                            "status": "failed",
                            "execution_group_id": "validation-group:test",
                            "plan_id": plan_id,
                            "jobs": [job],
                            "validation_job_summary": {"aggregate_status": "failed"},
                        }

                    try:
                        conveyor_runner.run_parallel_validation_conn = fake_failed_validation
                        conveyor_runner.run_scheduler_action(target, candidate, False)
                    finally:
                        conveyor_runner.run_parallel_validation_conn = original_validation

                    with closing(connect(database_path_for_target(target))) as conn:
                        model = execution_dag_read_model(conn)
                        edges = execution_dag_edges_conn(conn)
                    repair = next(item for item in model["ready_nodes"] if item["action_type"] == "repair")
                    self.assertEqual("T1", repair["task_id"])
                    self.assertIn("failed validation", repair["blocker_reason"])
                    self.assertIn("receipt:validation-job:test", repair["validation_receipt_refs"])
                    repair_metadata = next(
                        item["metadata"]
                        for item in model["nodes"]
                        if item["node_id"] == repair["node_id"]
                    )
                    self.assertEqual([source_node_id], repair_metadata["failed_work_node_ids"])
                    self.assertEqual(["src/app.py"], repair_metadata["paths"])
                    self.assertTrue(repair_metadata["validation_node_ids"])
                    self.assertIn(
                        ("dag-node:test:worker-build", repair["node_id"], "repairs"),
                        {(edge["source"], edge["target"], edge["dependency_kind"]) for edge in edges},
                    )

                    module.choose_next(target, {}, 2)
                    self.assertNotEqual("create_repair_nodes", self.latest_candidate(target).get("action_kind"))

    def test_repeated_validation_failures_create_explicit_blocker_after_retry_limit(self) -> None:
        for path, _module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                with tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp)
                    self.seed_target(target)
                    now = "2026-05-15T00:00:00+00:00"
                    group_id = "execution-group:test-validation"
                    validation_node_id = "dag-node:test:validation"
                    with closing(connect(database_path_for_target(target))) as conn:
                        with conn:
                            upsert_execution_dag_node(
                                conn,
                                node_id="dag-node:test:builder",
                                task_id="T1",
                                action_type="build",
                                status="done",
                                owner_role="builder",
                                confidence=0.9,
                                metadata={"paths": ["src/app.py"]},
                            )
                            upsert_execution_dag_node(
                                conn,
                                node_id=validation_node_id,
                                task_id="T1",
                                action_type="validate",
                                status="ready",
                                owner_role="hardener",
                                confidence=0.88,
                                metadata={
                                    "retry_limit": 1,
                                    "covered_builder_node_ids": ["dag-node:test:builder"],
                                    "review_node_id": "dag-node:test:review",
                                    "paths": ["src/app.py"],
                                },
                            )
                            conn.execute(
                                """
                                INSERT INTO execution_groups(
                                    execution_group_id, status, mode, created_at, selected_by, reason, payload_json
                                )
                                VALUES(?, 'proposed', 'dry_run', ?, 'test', 'validation test', '{}')
                                """,
                                (group_id, now),
                            )
                            conn.execute(
                                """
                                INSERT INTO execution_group_items(
                                    item_id, execution_group_id, task_id, graph_task_node_id,
                                    owner_role, action_kind, status, reason, payload_json
                                )
                                VALUES('execution-group-item:test-validation', ?, 'T1', ?, 'hardener',
                                       'validation_execution', 'proposed', 'test validation', ?)
                                """,
                                (
                                    group_id,
                                    validation_node_id,
                                    stable_json({"dag_node_id": validation_node_id, "action_type": "validate"}),
                                ),
                            )
                            conn.execute(
                                """
                                INSERT INTO validation_jobs(
                                    job_id, execution_group_id, plan_id, gate_id, command, cwd,
                                    status, started_at, finished_at, exit_code, log_artifact_id,
                                    resource_profile, payload_json
                                )
                                VALUES('validation-job:retry-limit', 'validation-group:test', ?, 'T1',
                                       'python -m pytest', '', 'failed', ?, ?, 1,
                                       'log:validation-job:retry-limit', 'cpu', ?)
                                """,
                                (group_id, now, now, stable_json({"required": True})),
                            )
                            result = {
                                "status": "failed",
                                "jobs": [
                                    {
                                        "job_id": "validation-job:retry-limit",
                                        "plan_id": group_id,
                                        "gate_id": "T1",
                                        "command": "python -m pytest",
                                        "status": "failed",
                                        "payload": {"required": True},
                                    }
                                ],
                            }
                            record_validation_group_result_on_execution_dag_conn(conn, group_id, result, selected_by="test")
                            created = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                            skipped = create_repair_nodes_for_failed_validation_conn(conn, selected_by="test")
                            model = execution_dag_read_model(conn)
                            edges = execution_dag_edges_conn(conn)

                    self.assertEqual(0, created["repair_node_count"])
                    self.assertEqual(1, created["blocker_node_count"])
                    self.assertEqual("skipped", skipped["status"])
                    blocker = next(item for item in model["blocked_nodes"] if item["action_type"] == "blocker")
                    self.assertIn("retry limit exhausted", blocker["blocker_reason"])
                    self.assertIn("receipt:validation-job:retry-limit", blocker["validation_receipt_refs"])
                    self.assertIn(
                        (blocker["node_id"], validation_node_id, "blocks"),
                        {(edge["source"], edge["target"], edge["dependency_kind"]) for edge in edges},
                    )

    def test_scheduler_decision_does_not_fall_back_to_stage_rotation(self) -> None:
        for path, module in self.modules:
            with self.subTest(path=path.relative_to(ROOT)):
                for last_completed_role in ("", "planner", "builder", "hardener", "integrator"):
                    with tempfile.TemporaryDirectory() as tmp:
                        target = Path(tmp)
                        self.seed_target(target)
                        state = {"last_completed_role": last_completed_role}

                        role, reason, stop = module.choose_next(target, state, 2)
                        queue = module.conveyor_decision_queue(target, state, role, reason, 2)
                        with closing(connect(database_path_for_target(target))) as conn:
                            decision = latest_scheduler_decision_conn(conn)

                        self.assertIsNone(role)
                        self.assertFalse(stop)
                        self.assertIn("no DAG-ready scheduler action", reason)
                        self.assertFalse(decision["scheduler_fallback_used"])
                        self.assertFalse(decision["legacy_result"])
                        self.assertEqual("idle", decision["selected_candidate"]["action_kind"])
                        self.assertEqual("idle", queue[0]["role"])
                        self.assertEqual("idle", queue[0]["action_kind"])


if __name__ == "__main__":
    unittest.main()
