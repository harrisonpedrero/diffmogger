from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from diffmogger.runtime.paths import target_path
from diffmogger.runtime.state_store import (
    acquire_resource_lease_conn,
    candidate_lanes_conn,
    compare_candidate_lanes_conn,
    connect,
    database_path_for_target,
    launch_read_only_execution_group_conn,
    launch_write_execution_group_conn,
    record_candidate_lane_conn,
    record_worker_report_disposition_conn,
    select_candidate_lane_conn,
    scope_evidence_records_conn,
    state_snapshot,
    worker_agents_conn,
    worker_contracts_conn,
    worker_patches_conn,
    write_ticket_run_state,
)


def write_text(target: Path, rel: str, text: str) -> None:
    path = target / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ReadOnlyWorkerFanoutTests(unittest.TestCase):
    def write_read_only_tickets(self, target: Path) -> None:
        write_ticket_run_state(
            target,
            {
                "run_id": "ticket-run",
                "campaign_mode": "bounded",
                "tickets": [
                    {
                        "id": "T1",
                        "summary": "Inspect src/auth.py for planning risks",
                        "status": "pending",
                        "action_kind": "read_only_analysis",
                        "execution_mode": "read_only",
                    },
                    {
                        "id": "T2",
                        "summary": "Review src/billing.py validation context",
                        "status": "pending",
                        "action_kind": "read_only_context_review",
                        "execution_mode": "read_only",
                    },
                ],
            },
            actor_role="test",
            event_type="ticket.run_test",
        )

    def proposed_read_only_group_id(self, target: Path) -> str:
        snapshot = state_snapshot(target)
        groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
        for group in groups:
            if isinstance(group, dict) and group.get("payload", {}).get("execution_mode") == "read_only":
                return str(group["execution_group_id"])
        self.fail(f"No read-only execution group proposed: {json.dumps(groups, sort_keys=True)}")

    def fake_success_runner(self, command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        run_id = command[command.index("--run-id") + 1]
        role = command[command.index("--role") + 1]
        report = target_path(cwd, "target/agent_runs") / run_id / f"worker_{role}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "\n".join(
                [
                    f"# Worker Report: {role}",
                    "",
                    "- status: PASS",
                    "",
                    "## Findings",
                    "",
                    f"- {role} found one reviewable gap.",
                    "",
                    "## Accepted Findings",
                    "",
                    f"- {role} accepted signal.",
                    "",
                    "## Rejected Findings",
                    "",
                    "- None.",
                    "",
                    "## Deferred Findings",
                    "",
                    "- Follow-up can wait.",
                    "",
                    "## Unresolved Risks",
                    "",
                    "- Validate the final integration path.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout=f"WORKER_REPORT path={report}\n", stderr="")

    def fake_unavailable_runner(self, command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 127, stdout="", stderr="codex command not found\n")

    def fake_scope_evidence_runner(self, command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        run_id = command[command.index("--run-id") + 1]
        role = command[command.index("--role") + 1]
        report = target_path(cwd, "target/agent_runs") / run_id / f"worker_{role}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "\n".join(
                [
                    f"# Worker Report: {role}",
                    "",
                    "## Scope Evidence",
                    "",
                    "```json",
                    json.dumps(
                        {
                            "scope_evidence_records": [
                                {
                                    "candidate_path": "src/auth.py",
                                    "confidence": 0.91,
                                    "likely_tests": [],
                                    "reasons": ["read-only inspection confirmed this path owns the requested behavior"],
                                }
                            ]
                        },
                        sort_keys=True,
                    ),
                    "```",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout=f"WORKER_REPORT path={report}\n", stderr="")

    def fake_legacy_path_runner(self, command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        run_id = command[command.index("--run-id") + 1]
        role = command[command.index("--role") + 1]
        legacy_role = "".join(char if char.isalnum() else "_" for char in role.lower()).strip("_")
        report = cwd / "target" / "agent_runs" / run_id / f"worker_{legacy_role}.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            "\n".join(
                [
                    f"# Worker Report: {legacy_role}",
                    "",
                    "- status: PASS",
                    "",
                    "## Findings",
                    "",
                    "- Legacy helper path was reported on stdout.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout=f"WORKER_REPORT path={report} run_id={run_id} role={legacy_role} mode=read-only\n", stderr="")

    def write_sidecar_manifest(self, target: Path) -> None:
        manifest = target / ".diffmogger" / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "layout": "sidecar_v1",
                    "path_aliases": {
                        ".agentic/project_intake.json": ".diffmogger/agentic/project_intake.json",
                        "target/agent_runs": ".diffmogger/runtime/agent_runs",
                        "target/orchestration.sqlite3": ".diffmogger/runtime/orchestration.sqlite3",
                    },
                }
            ),
            encoding="utf-8",
        )

    def setup_target(self, target: Path) -> str:
        intake = target / ".agentic" / "project_intake.json"
        intake.parent.mkdir(parents=True, exist_ok=True)
        intake.write_text(
            json.dumps(
                {
                    "project_name": "Worker Fanout Demo",
                    "product_goal": "Exercise read-only worker fanout.",
                    "target_user": "Automation maintainers",
                    "desired_first_demo": "Typed worker records exist.",
                    "worker_agents_allowed": True,
                    "write_worker_agents_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        write_text(target, "src/auth.py", "SECRET_SOURCE_BODY = 'hidden auth implementation'\n")
        write_text(target, "src/billing.py", "BILLING = True\n")
        self.write_read_only_tickets(target)
        return self.proposed_read_only_group_id(target)

    def setup_sidecar_target(self, target: Path) -> str:
        self.write_sidecar_manifest(target)
        intake = target / ".diffmogger" / "agentic" / "project_intake.json"
        intake.parent.mkdir(parents=True, exist_ok=True)
        intake.write_text(
            json.dumps(
                {
                    "project_name": "Sidecar Worker Fanout Demo",
                    "product_goal": "Exercise sidecar-aware read-only worker fanout.",
                    "target_user": "Automation maintainers",
                    "desired_first_demo": "Typed worker records exist.",
                    "worker_agents_allowed": True,
                    "write_worker_agents_allowed": False,
                }
            ),
            encoding="utf-8",
        )
        write_text(target, "src/auth.py", "AUTH = True\n")
        self.write_read_only_tickets(target)
        return self.proposed_read_only_group_id(target)

    def test_read_only_group_creates_worker_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_success_runner,
                )
                workers = worker_agents_conn(conn, mode="read_only")

            self.assertEqual("completed", result["status"])
            self.assertEqual(2, result["worker_count"])
            self.assertEqual(2, len([worker for worker in workers if worker["execution_group_id"] == group_id]))
            self.assertTrue(all(worker["report_artifact_id"] for worker in workers))

    def test_read_only_worker_report_records_structured_scope_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=self.fake_scope_evidence_runner,
                )
                records = scope_evidence_records_conn(conn)
                workers = worker_agents_conn(conn, mode="read_only")

            self.assertEqual("completed", result["status"])
            self.assertEqual(1, len(records))
            self.assertEqual("accepted", records[0]["status"])
            self.assertEqual("src/auth.py", records[0]["candidate_path"])
            self.assertEqual(1, workers[0]["payload"]["scope_evidence_ingest"]["accepted_count"])

    def test_sidecar_launch_accepts_reported_legacy_worker_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_sidecar_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=self.fake_legacy_path_runner,
                )
                workers = worker_agents_conn(conn, mode="read_only")

            self.assertEqual("completed", result["status"])
            self.assertEqual(1, result["worker_count"])
            worker = workers[0]
            report_path = Path(str(worker["payload"]["report_path"]))
            self.assertEqual((target / "target" / "agent_runs").resolve(), report_path.parents[1].resolve())
            self.assertTrue(report_path.exists())
            self.assertIn("_", report_path.name)
            self.assertFalse((target_path(target, "target/agent_runs") / result["run_id"] / report_path.name).exists())
            self.assertEqual("completed", worker["status"])

    def test_hyphenated_runtime_role_slug_is_passed_as_canonical_report_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_sidecar_target(target)
            commands: list[list[str]] = []

            def capture_runner(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                report = Path(command[command.index("--report-path") + 1])
                report.parent.mkdir(parents=True, exist_ok=True)
                report.write_text("- status: PASS\n\n## Findings\n\n- Canonical path honored.\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout=f"WORKER_REPORT path={report}\n", stderr="")

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=capture_runner,
                )
                workers = worker_agents_conn(conn, mode="read_only")

            self.assertEqual("completed", result["status"])
            self.assertTrue(commands)
            report_path = Path(commands[0][commands[0].index("--report-path") + 1])
            role = commands[0][commands[0].index("--role") + 1]
            self.assertIn("-", role)
            self.assertIn("-", report_path.name)
            self.assertNotIn("_", report_path.name.removeprefix("worker_").removesuffix(".md"))
            self.assertEqual(report_path, Path(str(workers[0]["payload"]["report_path"])))

    def test_dependent_read_only_tickets_do_not_share_parallel_wave(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            intake = target / ".agentic" / "project_intake.json"
            intake.parent.mkdir(parents=True, exist_ok=True)
            intake.write_text(
                json.dumps(
                    {
                        "project_name": "Worker Dependency Demo",
                        "product_goal": "Exercise dependent ticket parallel guards.",
                        "target_user": "Automation maintainers",
                        "desired_first_demo": "Dependent tickets are not launched together.",
                        "worker_agents_allowed": True,
                        "write_worker_agents_allowed": False,
                    }
                ),
                encoding="utf-8",
            )
            write_text(target, "src/auth.py", "AUTH = True\n")
            write_text(target, "src/billing.py", "BILLING = True\n")
            write_ticket_run_state(
                target,
                {
                    "run_id": "ticket-run",
                    "campaign_mode": "bounded",
                    "tickets": [
                        {
                            "id": "T1",
                            "summary": "Inspect src/auth.py first",
                            "status": "pending",
                            "action_kind": "read_only_analysis",
                            "execution_mode": "read_only",
                        },
                        {
                            "id": "T2",
                            "summary": "Inspect src/billing.py after auth context",
                            "status": "pending",
                            "action_kind": "read_only_context_review",
                            "execution_mode": "read_only",
                            "depends_on": ["T1"],
                        },
                    ],
                },
                actor_role="test",
                event_type="ticket.run_test",
            )

            snapshot = state_snapshot(target)
            dependency_edges = [
                edge
                for edge in snapshot["execution_dag"]["edges"]
                if edge["dependency_kind"] == "depends_on"
                and edge["dependency_mode"] == "hard"
                and "T2 waits for dependency T1" in edge["reason"]
            ]
            self.assertTrue(dependency_edges)
            groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                item_task_ids = {
                    str(item.get("task_id") or "")
                    for item in group.get("items", [])
                    if isinstance(item, dict)
                }
                self.assertFalse({"T1", "T2"}.issubset(item_task_ids), json.dumps(group, sort_keys=True))

    def test_read_only_workers_launch_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)
            lock = threading.Lock()
            all_started = threading.Event()
            started = 0
            active = 0
            max_active = 0

            def concurrent_runner(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                nonlocal active, max_active, started
                with lock:
                    active += 1
                    started += 1
                    max_active = max(max_active, active)
                    if started == 2:
                        all_started.set()
                try:
                    all_started.wait(1.0)
                    return self.fake_success_runner(command, cwd=cwd, timeout=timeout)
                finally:
                    with lock:
                        active -= 1

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=concurrent_runner,
                )

            self.assertEqual("completed", result["status"])
            self.assertGreaterEqual(max_active, 2)

    def test_codex_unavailable_creates_failure_report_but_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=self.fake_unavailable_runner,
                )
                workers = worker_agents_conn(conn, mode="read_only")

            self.assertEqual("failed", result["status"])
            self.assertEqual(1, result["failed_worker_count"])
            self.assertEqual("unavailable", workers[0]["status"])
            report_path = Path(str(workers[0]["payload"]["report_path"]))
            self.assertTrue(report_path.exists())
            self.assertIn("UNAVAILABLE", report_path.read_text(encoding="utf-8"))

    def test_worker_contract_forbids_writes_network_credentials_and_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=self.fake_success_runner,
                )
                contracts = worker_contracts_conn(conn)

            self.assertEqual(1, len(contracts))
            contract = contracts[0]
            self.assertTrue(contract["no_spawn_workers"])
            self.assertTrue(contract["no_network"])
            self.assertTrue(contract["no_credentials"])
            self.assertTrue(any("modify source" in action for action in contract["denied_actions"]))

    def test_read_only_worker_prompt_uses_symbol_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            intake = target / ".agentic" / "project_intake.json"
            intake.parent.mkdir(parents=True, exist_ok=True)
            intake.write_text(
                json.dumps({"worker_agents_allowed": True, "write_worker_agents_allowed": False}),
                encoding="utf-8",
            )
            write_text(target, "src/__init__.py", "")
            write_text(target, "src/auth.py", "class AuthService:\n    def refresh(self):\n        return True\n")
            write_text(target, "tests/test_auth.py", "from src.auth import AuthService\ndef test_auth():\n    assert AuthService()\n")
            write_ticket_run_state(
                target,
                {
                    "run_id": "ticket-run",
                    "tickets": [
                        {
                            "id": "T1",
                            "summary": "Review AuthService context",
                            "status": "pending",
                            "action_kind": "read_only_analysis",
                            "execution_mode": "read_only",
                        }
                    ],
                },
                actor_role="test",
                event_type="ticket.run_test",
            )
            group_id = self.proposed_read_only_group_id(target)
            prompts: list[str] = []

            def capture_runner(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                prompts.append(command[command.index("--prompt") + 1])
                return self.fake_success_runner(command, cwd=cwd, timeout=timeout)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=capture_runner,
                )
                workers = worker_agents_conn(conn, mode="read_only")
                contracts = worker_contracts_conn(conn)

            self.assertEqual("completed", result["status"])
            self.assertTrue(prompts)
            self.assertIn("Symbol-aware context:", prompts[0])
            self.assertIn("Direct symbols:", prompts[0])
            self.assertIn("AuthService", prompts[0])
            self.assertIn("Likely tests:", prompts[0])
            self.assertTrue(workers[0]["payload"]["symbol_context_available"])
            self.assertTrue(contracts[0]["payload"]["symbol_context_available"])

    def test_summary_is_generated_from_multiple_worker_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_success_runner,
                )

            summary_path = Path(str(result["summary_path"]))
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("## Finding Disposition", summary)
            self.assertIn("### Accepted Findings", summary)
            self.assertIn("### Rejected Findings", summary)
            self.assertIn("### Deferred Findings", summary)
            self.assertIn("### Unresolved Risks", summary)

    def test_worker_outputs_require_disposition_before_run_is_fully_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                launch_read_only_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_success_runner,
                )
                workers = worker_agents_conn(conn, mode="read_only")
            snapshot = state_snapshot(target)
            self.assertTrue(snapshot["worker_finding_disposition_required"])
            self.assertEqual(2, len(snapshot["completed_worker_reports"]))

            with closing(connect(database_path_for_target(target))) as conn:
                for worker in workers:
                    record_worker_report_disposition_conn(
                        conn,
                        str(worker["worker_id"]),
                        accepted_findings=["accepted"],
                        rejected_findings=[],
                        deferred_findings=[],
                        unresolved_risks=[],
                    )
            dispositioned = state_snapshot(target)
            self.assertFalse(dispositioned["worker_finding_disposition_required"])


class WriteWorkerFanoutTests(unittest.TestCase):
    def write_write_tickets(self, target: Path) -> None:
        write_ticket_run_state(
            target,
            {
                "run_id": "ticket-run",
                "campaign_mode": "bounded",
                "tickets": [
                    {"id": "T1", "summary": "Update src/auth.py", "status": "pending"},
                    {"id": "T2", "summary": "Update src/billing.py", "status": "pending"},
                ],
            },
            actor_role="test",
            event_type="ticket.run_test",
        )

    def write_intake(self, target: Path, *, write_enabled: bool, max_write_workers: int = 2) -> None:
        intake = target / ".agentic" / "project_intake.json"
        intake.parent.mkdir(parents=True, exist_ok=True)
        intake.write_text(
            json.dumps(
                {
                    "project_name": "Write Worker Fanout Demo",
                    "product_goal": "Exercise write-worker fanout.",
                    "target_user": "Automation maintainers",
                    "desired_first_demo": "Typed worker patches exist.",
                    "worker_agents_allowed": True,
                    "write_worker_agents_allowed": write_enabled,
                    "max_write_worker_count": max_write_workers,
                }
            ),
            encoding="utf-8",
        )

    def init_repo(self, target: Path) -> None:
        write_text(target, "src/auth.py", "AUTH = True\n")
        write_text(target, "src/billing.py", "BILLING = True\n")
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-q",
                "-m",
                "chore: base",
            ],
            cwd=target,
            check=True,
        )

    def setup_target(self, target: Path, *, write_enabled: bool = True, max_write_workers: int = 2) -> str:
        self.write_intake(target, write_enabled=write_enabled, max_write_workers=max_write_workers)
        self.init_repo(target)
        self.write_write_tickets(target)
        return self.proposed_write_group_id(target)

    def proposed_write_group(self, target: Path) -> dict[str, object]:
        snapshot = state_snapshot(target)
        groups = snapshot.get("proposed_execution_groups") if isinstance(snapshot.get("proposed_execution_groups"), list) else []
        for group in groups:
            if isinstance(group, dict) and group.get("payload", {}).get("execution_mode") == "write_workers":
                return group
        self.fail(f"No write-worker execution group proposed: {json.dumps(groups, sort_keys=True)}")

    def proposed_write_group_id(self, target: Path) -> str:
        return str(self.proposed_write_group(target)["execution_group_id"])

    def fake_write_runner(self, command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        ownership = command[command.index("--ownership") + 1]
        path = ownership.split(",", 1)[0].strip()
        if path:
            target_file = cwd / path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            current = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
            target_file.write_text(current + "# worker change\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="worker complete\n", stderr="")

    def test_write_worker_ignores_disabled_legacy_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target, write_enabled=False)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_write_runner,
                )

            self.assertEqual("completed", result["status"])
            self.assertEqual(2, result["queued_patch_count"])

    def test_write_worker_cannot_start_without_ownership_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_intake(target, write_enabled=True)
            self.init_repo(target)
            group = {
                "execution_group_id": "execution-group:test-no-scope",
                "payload": {"execution_mode": "write_workers"},
                "items": [
                    {
                        "item_id": "execution-group-item:no-scope",
                        "task_id": "T1",
                        "owner_role": "builder",
                        "action_kind": "implement_ready_ticket",
                        "required_leases": [],
                        "payload": {"execution_mode": "write_workers", "likely_touches": []},
                    }
                ],
            }

            with closing(connect(database_path_for_target(target))) as conn:
                state_snapshot(target)
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    group=group,
                    command_runner=self.fake_write_runner,
                )

            self.assertEqual("blocked", result["status"])
            self.assertEqual("ownership_scope_required", result["reason_kind"])

    def test_overlapping_lease_blocks_write_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)
            group = self.proposed_write_group(target)
            first_item = group["items"][0]
            first_lease = first_item["required_leases"][0]

            with closing(connect(database_path_for_target(target))) as conn:
                acquire_resource_lease_conn(
                    conn,
                    task_id="OTHER",
                    owner_role="builder",
                    run_id="other-run",
                    scope_kind=str(first_lease["scope_kind"]),
                    scope_node_id=str(first_lease["scope_node_id"]),
                )
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_write_runner,
                )

            self.assertEqual("blocked", result["status"])
            self.assertEqual("lease_conflict", result["reason_kind"])
            self.assertTrue(result["conflicts"])

    def test_disjoint_leases_allow_two_write_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_write_runner,
                )
                workers = worker_agents_conn(conn, mode="write")
                patches = worker_patches_conn(conn)
                contracts = worker_contracts_conn(conn)

            self.assertEqual("completed", result["status"])
            self.assertEqual(2, result["worker_count"])
            self.assertEqual(2, result["queued_patch_count"])
            self.assertEqual(2, len([worker for worker in workers if worker["status"] == "completed"]))
            self.assertEqual(2, len([patch for patch in patches if patch["status"] == "queued"]))
            self.assertTrue(all(contract["ownership_scope"] for contract in contracts))
            self.assertTrue(all(contract["integration_notes_required"] for contract in contracts))

    def test_write_workers_launch_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)
            lock = threading.Lock()
            all_started = threading.Event()
            started = 0
            active = 0
            max_active = 0

            def concurrent_runner(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                nonlocal active, max_active, started
                with lock:
                    active += 1
                    started += 1
                    max_active = max(max_active, active)
                    if started == 2:
                        all_started.set()
                try:
                    all_started.wait(1.0)
                    return self.fake_write_runner(command, cwd=cwd, timeout=timeout)
                finally:
                    with lock:
                        active -= 1

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=concurrent_runner,
                )

            self.assertEqual("completed", result["status"])
            self.assertEqual(2, result["queued_patch_count"])
            self.assertGreaterEqual(max_active, 2)

    def test_write_worker_prompt_uses_symbol_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.write_intake(target, write_enabled=True, max_write_workers=1)
            write_text(target, "src/__init__.py", "")
            write_text(target, "src/auth.py", "class AuthService:\n    pass\n")
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            subprocess.run(["git", "add", "."], cwd=target, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "chore: base",
                ],
                cwd=target,
                check=True,
            )
            write_ticket_run_state(
                target,
                {"run_id": "ticket-run", "tickets": [{"id": "T1", "summary": "Update AuthService behavior", "status": "pending"}]},
                actor_role="test",
                event_type="ticket.run_test",
            )
            group_id = self.proposed_write_group_id(target)
            prompts: list[str] = []

            def capture_runner(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                prompts.append(command[command.index("--prompt") + 1])
                return self.fake_write_runner(command, cwd=cwd, timeout=timeout)

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=capture_runner,
                )
                workers = worker_agents_conn(conn, mode="write")
                contracts = worker_contracts_conn(conn)

            self.assertEqual("completed", result["status"])
            self.assertTrue(prompts)
            self.assertIn("Symbol-aware context:", prompts[0])
            self.assertIn("Direct symbols:", prompts[0])
            self.assertIn("AuthService", prompts[0])
            self.assertTrue(workers[0]["payload"]["symbol_context_available"])
            self.assertTrue(contracts[0]["payload"]["symbol_context_available"])

    def test_worker_patch_is_queued_not_directly_committed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)
            head_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, text=True, capture_output=True, check=True).stdout.strip()

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    command_runner=self.fake_write_runner,
                )
            head_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, text=True, capture_output=True, check=True).stdout.strip()
            snapshot = state_snapshot(target)

            self.assertEqual(head_before, head_after)
            self.assertEqual("AUTH = True\n", (target / "src/auth.py").read_text(encoding="utf-8"))
            self.assertEqual(2, len(snapshot["queued_worker_patches"]))
            self.assertEqual(2, len(snapshot["integration_backlog_from_parallel_workers"]))
            for patch in result["patches"]:
                self.assertTrue((target / str(patch["manifest_path"])).exists())

    def test_failed_patch_creates_conflict_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            group_id = self.setup_target(target)

            def conflicting_runner(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
                ownership = command[command.index("--ownership") + 1]
                path = ownership.split(",", 1)[0].strip()
                result = self.fake_write_runner(command, cwd=cwd, timeout=timeout)
                if path:
                    (target / path).write_text("MAIN CHECKOUT DRIFTED\n", encoding="utf-8")
                return result

            with closing(connect(database_path_for_target(target))) as conn:
                result = launch_write_execution_group_conn(
                    conn,
                    target,
                    execution_group_id=group_id,
                    max_workers=1,
                    command_runner=conflicting_runner,
                )
                patches = worker_patches_conn(conn)

            self.assertEqual("failed", result["status"])
            self.assertEqual(1, result["conflict_count"])
            self.assertEqual("conflict", patches[0]["status"])
            self.assertTrue(patches[0]["conflict_signature"])


class SpeculativeCandidateLaneTests(unittest.TestCase):
    def init_repo(self, target: Path) -> None:
        write_text(target, "src/app.py", "VALUE = 'base'\n")
        subprocess.run(["git", "init", "-q"], cwd=target, check=True)
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-q",
                "-m",
                "chore: base",
            ],
            cwd=target,
            check=True,
        )

    def create_candidate_patch(
        self,
        conn,
        target: Path,
        *,
        run_id: str,
        worker_id: str,
        new_content: str,
    ) -> str:
        rel = "src/app.py"
        patch_id = f"worker-patch:{run_id}"
        queue_dir = target_path(target, f"target/automation_queue/builder/{run_id}")
        patch_path = queue_dir / "changes.patch"
        manifest_path = queue_dir / "manifest.json"
        summary_path = queue_dir / "summary.md"
        queue_dir.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(new_content, encoding="utf-8")
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--", rel],
            cwd=target,
            text=True,
            capture_output=True,
            check=True,
        )
        patch_path.write_text(diff.stdout, encoding="utf-8")
        subprocess.run(["git", "checkout", "--", rel], cwd=target, check=True, stdout=subprocess.DEVNULL)
        summary_path.write_text(f"# Candidate {run_id}\n", encoding="utf-8")
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, text=True, capture_output=True, check=True).stdout.strip()
        manifest = {
            "schema_version": 1,
            "role": "builder",
            "run_id": run_id,
            "status": "candidate",
            "source": "speculative_candidate_lane",
            "worker_id": worker_id,
            "base_commit": base_commit,
            "patch_path": f"target/automation_queue/builder/{run_id}/changes.patch",
            "summary_path": f"target/automation_queue/builder/{run_id}/summary.md",
            "changed_files": [rel],
            "checks_run": [],
            "validation_evidence": [{"status": "passed", "command": "candidate smoke"}],
            "created_at": "2026-05-14T00:00:00+00:00",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        conn.execute(
            """
            INSERT INTO worker_agents(
                worker_id, execution_group_id, run_id, mode, role, status,
                started_at, finished_at, payload_json
            )
            VALUES(?, 'execution-group:speculative-demo', ?, 'write', 'builder', 'completed',
                   '2026-05-14T00:00:00+00:00', '2026-05-14T00:00:01+00:00', '{}')
            """,
            (worker_id, run_id),
        )
        conn.execute(
            """
            INSERT INTO worker_patches(
                patch_id, worker_id, execution_group_id, status, manifest_path,
                patch_path, changed_files_json, base_commit, leases_json,
                validation_evidence_json, conflict_signature, created_at,
                queued_at, integrated_at, payload_json
            )
            VALUES(?, ?, 'execution-group:speculative-demo', 'candidate', ?, ?, ?,
                   ?, '[]', ?, '', '2026-05-14T00:00:00+00:00', '', '', ?)
            """,
            (
                patch_id,
                worker_id,
                f"target/automation_queue/builder/{run_id}/manifest.json",
                f"target/automation_queue/builder/{run_id}/changes.patch",
                json.dumps([rel]),
                base_commit,
                json.dumps([{"status": "passed", "command": "candidate smoke"}]),
                json.dumps({"schema_version": 1, "speculative_candidate": True}),
            ),
        )
        return patch_id

    def record_two_overlapping_lanes(self, target: Path) -> tuple[str, str]:
        with closing(connect(database_path_for_target(target))) as conn:
            patch_a = self.create_candidate_patch(
                conn,
                target,
                run_id="candidate-a",
                worker_id="worker:candidate-a",
                new_content="VALUE = 'candidate a'\n",
            )
            patch_b = self.create_candidate_patch(
                conn,
                target,
                run_id="candidate-b",
                worker_id="worker:candidate-b",
                new_content="VALUE = 'candidate b'\n",
            )
            lane_a = record_candidate_lane_conn(
                conn,
                target,
                candidate_id="candidate-lane:a",
                task_id="TICKET-ALT",
                execution_group_id="execution-group:speculative-demo",
                worker_id="worker:candidate-a",
                approach_summary="Small direct implementation.",
                status="validated",
                patch_id=patch_a,
                validation_summary={"status": "passed", "test_coverage": "focused smoke"},
            )
            lane_b = record_candidate_lane_conn(
                conn,
                target,
                candidate_id="candidate-lane:b",
                task_id="TICKET-ALT",
                execution_group_id="execution-group:speculative-demo",
                worker_id="worker:candidate-b",
                approach_summary="Alternative implementation.",
                status="validated",
                patch_id=patch_b,
                validation_summary={"status": "passed", "test_coverage": "focused smoke"},
            )
        return str(lane_a["candidate_id"]), str(lane_b["candidate_id"])

    def test_two_candidate_lanes_can_overlap_files_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.init_repo(target)
            self.record_two_overlapping_lanes(target)

            with closing(connect(database_path_for_target(target))) as conn:
                comparison = compare_candidate_lanes_conn(conn, "TICKET-ALT")
                patches = worker_patches_conn(conn)

            self.assertEqual(2, comparison["candidate_count"])
            self.assertEqual(["src/app.py"], comparison["overlapping_changed_files"])
            self.assertTrue(all(lane["comparison"]["overlap_allowed_in_speculative_mode"] for lane in comparison["lanes"]))
            self.assertEqual(0, len([patch for patch in patches if patch["status"] == "queued"]))
            self.assertEqual(2, len([patch for patch in patches if patch["status"] == "candidate"]))

    def test_only_selected_candidate_is_queued_for_integration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.init_repo(target)
            selected_id, _rejected_id = self.record_two_overlapping_lanes(target)

            with closing(connect(database_path_for_target(target))) as conn:
                result = select_candidate_lane_conn(
                    conn,
                    target,
                    selected_id,
                    selected_by="planner",
                    comparison_notes="Candidate A keeps the patch smaller.",
                )
                patches = worker_patches_conn(conn, limit=10)
                lanes = candidate_lanes_conn(conn, task_id="TICKET-ALT", include_patches=True)

            self.assertEqual("selected", result["status"])
            self.assertEqual(1, len([patch for patch in patches if patch["status"] == "queued"]))
            self.assertEqual(1, len([patch for patch in patches if patch["status"] == "superseded"]))
            self.assertEqual("selected", next(lane for lane in lanes if lane["candidate_id"] == selected_id)["status"])

    def test_rejected_candidate_is_superseded_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.init_repo(target)
            selected_id, rejected_id = self.record_two_overlapping_lanes(target)

            with closing(connect(database_path_for_target(target))) as conn:
                select_candidate_lane_conn(conn, target, selected_id, selected_by="planner")
                rejected = next(lane for lane in candidate_lanes_conn(conn, task_id="TICKET-ALT") if lane["candidate_id"] == rejected_id)

            self.assertEqual("superseded", rejected["status"])
            manifest = json.loads((target / "target/automation_queue/builder/candidate-b/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("superseded", manifest["status"])
            self.assertEqual(selected_id, manifest["superseded_by_candidate_id"])
            self.assertEqual("superseded_by_selected_candidate", manifest["deferral_reason"])

    def test_snapshot_exposes_candidate_lane_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.init_repo(target)
            self.record_two_overlapping_lanes(target)

            snapshot = state_snapshot(target)

            self.assertEqual(2, snapshot["candidate_lane_summary"]["candidate_count"])
            self.assertEqual(1, len(snapshot["candidate_lane_comparisons"]))
            self.assertEqual(["src/app.py"], snapshot["candidate_lane_comparisons"][0]["overlapping_changed_files"])


if __name__ == "__main__":
    unittest.main()
