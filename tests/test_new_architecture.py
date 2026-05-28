from __future__ import annotations

import json
import os
import sqlite3
import asyncio
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

import diffmogger.orchestration.activities as orchestration_activities
from diffmogger import supervision
from diffmogger.contracts import (
    CodeFact,
    DagEdge,
    DagNode,
    DesignContract,
    DesignReview,
    ExecutionGroup,
    NotificationPayload,
    OwnershipLease,
    SchedulerCandidate,
    SchedulerCycleRequest,
    TicketRecord,
    ValidationReceipt,
    WorkerOutput,
)
from diffmogger.notifications import send_notification
from diffmogger.orchestration.activities import (
    _mark_follow_up_recorded,
    _parse_owned_paths_from_text,
    _run_worker_command,
    run_campaign_cycle,
    run_scheduler_cycle,
)
from diffmogger.orchestration.scheduler_policy import choose_scheduler_record
from diffmogger.dashboard.ticket_generation import data_fidelity_detection, ticket_generation_quality_gate
from diffmogger.runtime import code_facts
from diffmogger.runtime.design import ensure_design_foundation_ticket, ui_detection_from_intake
from diffmogger.integrator.cli import integrate
from diffmogger.integrator.commits import filter_commit_paths, semantic_commit_message
from diffmogger.integrator.runtime_state import ticket_digest
from diffmogger.runtime.state_store import (
    default_conveyor_state,
    load_ticket_run_state,
    materialize_execution_dag_conn,
    state_snapshot,
    ticket_run_state_summary,
    write_ticket_run_state,
)
from diffmogger.state.db import (
    connect,
    database_path_for_target,
    insert_validation_receipt,
    insert_design_review,
    latest_design_contract,
    upsert_code_fact,
    upsert_dag_node,
    upsert_design_contract,
    upsert_execution_group,
    upsert_ownership_lease,
    upsert_ticket,
    upsert_worker_output,
)


def test_pydantic_contracts_forbid_ad_hoc_payload_fields() -> None:
    with pytest.raises(ValidationError):
        SchedulerCycleRequest.model_validate(
            {"target_path": ".", "run_id": "x", "surprise": "ad-hoc dicts are not contracts"}
        )
    schema = TicketRecord.model_json_schema()
    assert schema["properties"]["ticket_id"]["minLength"] == 1
    design_node = DagNode(node_id="design-1", action_type="design", owner_role="designer")
    assert design_node.action_type == "design"
    assert design_node.owner_role == "designer"
    with pytest.raises(ValidationError):
        SchedulerCandidate.model_validate({"candidate_id": "C1", "action_kind": "launch_work", "unexpected": True})


def test_supervision_uses_dependency_capable_python(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DIFFMOGGER_PYTHON", sys.executable)

    command = supervision.temporal_command(tmp_path, run_id="probe", max_fanout=2)
    environment = supervision.runner_environment(tmp_path, command[0])

    assert Path(command[0]).resolve() == Path(sys.executable).resolve()
    assert command[-2:] == ["--max-fanout", "2"]
    assert environment["DIFFMOGGER_PYTHON"] == command[0]
    assert "PYTHONPATH" in environment
    assert environment["DIFFMOGGER_WORKER_EXECUTION"] == "codex"


def test_design_capability_detection_preserves_backend_only_defaults() -> None:
    intake = {
        "ui_capability_mode": "auto",
        "product_goal": "Build a local CLI that processes CSV files.",
        "ticket_generation_scope_groups": [{"name": "CLI", "surfaces": ["argument parsing", "file IO"]}],
    }
    tickets = [
        {
            "id": "TICKET-001",
            "summary": "Implement CSV parser command",
            "acceptance_criteria": ["Command parses local files."],
            "verification_commands": ["python -m pytest"],
        }
    ]

    detection = ui_detection_from_intake(intake, tickets=tickets)
    with_design = ensure_design_foundation_ticket(tickets, intake)

    assert detection["designer_enabled"] is False
    assert with_design == tickets


def test_design_foundation_ticket_is_gated_for_ui_heavy_scope() -> None:
    intake = {
        "ui_capability_mode": "auto",
        "ui_validation_mode": "auto",
        "product_goal": "Build a React dashboard for reviewing local work.",
    }
    tickets = [
        {
            "id": "TICKET-001",
            "summary": "Build dashboard route and controls",
            "acceptance_criteria": ["Dashboard renders the primary workflow."],
            "verification_commands": ["npm test"],
        }
    ]

    with_design = ensure_design_foundation_ticket(tickets, intake)
    quality_gate = ticket_generation_quality_gate(with_design, intake=intake)

    assert with_design[0]["owner_role"] == "designer"
    assert with_design[0]["action_kind"] == "design"
    assert with_design[0]["design_contract_required"] is True
    assert with_design[1]["id"] == "TICKET-002"
    assert quality_gate["ui_detection"]["designer_enabled"] is True
    assert not any(item["type"] == "missing_design_foundation" for item in quality_gate["warnings"])
    assert any(item["type"] == "missing_ui_states" for item in quality_gate["warnings"])


def test_ui_capability_off_schedules_no_design_foundation() -> None:
    intake = {
        "ui_capability_mode": "off",
        "product_goal": "Build a web app only after the user opts in later.",
    }
    tickets = [
        {
            "id": "TICKET-001",
            "summary": "Build UI shell",
            "acceptance_criteria": ["Route renders locally."],
            "verification_commands": ["npm test"],
        }
    ]

    detection = ui_detection_from_intake(intake, tickets=tickets)
    with_design = ensure_design_foundation_ticket(tickets, intake)

    assert detection["designer_enabled"] is False
    assert with_design == tickets


def test_ticket_quality_gate_flags_fixture_only_real_data_scope() -> None:
    intake = {
        "product_goal": "Build a public data dashboard with official API imports.",
        "external_services": ["Official public API"],
    }
    tickets = [
        {
            "id": "TICKET-001",
            "summary": "Create fixture-backed dashboard rows",
            "acceptance_criteria": ["Dashboard renders mocked sample data."],
            "verification_commands": ["npm test"],
        }
    ]

    quality_gate = ticket_generation_quality_gate(tickets, intake=intake)
    warning_types = {item["type"] for item in quality_gate["warnings"]}

    assert quality_gate["passed"] is False
    assert quality_gate["data_fidelity_detection"]["real_data_scope"] is True
    assert "missing_data_source_strategy" in warning_types
    assert "fixture_only_without_real_data_path" in warning_types


def test_ticket_quality_gate_accepts_labeled_fallback_with_real_data_path() -> None:
    intake = {
        "product_goal": "Build a public data dashboard with official API imports.",
        "external_services": ["Official public API"],
    }
    tickets = [
        {
            "id": "TICKET-001",
            "summary": "Define source mode and public API adapter path",
            "acceptance_criteria": [
                "Source mode distinguishes fixture fallback, public cache, and live import states.",
                "Public API adapter records provenance, freshness, unavailable-source, and source status receipts.",
            ],
            "verification_commands": ["npm test"],
        }
    ]

    quality_gate = ticket_generation_quality_gate(tickets, intake=intake)
    detection = data_fidelity_detection(tickets, intake)
    warning_types = {item["type"] for item in quality_gate["warnings"]}

    assert detection["real_data_scope"] is True
    assert detection["data_mode_present"] is True
    assert detection["real_data_path_present"] is True
    assert "missing_data_source_strategy" not in warning_types
    assert "fixture_only_without_real_data_path" not in warning_types


def test_alembic_migration_creates_control_plane_tables(tmp_path: Path) -> None:
    with connect(tmp_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "alembic_version" in tables
        assert "scheduler_decisions" in tables
        assert "execution_groups" in tables
        assert "code_facts" in tables
        assert "design_contracts" in tables
        assert "design_reviews" in tables
        upsert_dag_node(conn, DagNode(node_id="node-1", paths=["src/app.py"]))
        upsert_execution_group(
            conn,
            ExecutionGroup(
                group_id="group-1",
                run_id="run-1",
                action_kind="work_wave",
                node_ids=["node-1"],
                paths=["src/app.py"],
            ),
        )
        upsert_code_fact(
            conn,
            CodeFact(
                fact_id="fact-1",
                file_path="src/app.py",
                language="python",
                kind="symbol",
                name="run",
            ),
        )
        insert_validation_receipt(
            conn,
            ValidationReceipt(
                receipt_id="receipt-1",
                node_id="node-1",
                command="pytest",
                status="failed",
            ),
        )
        upsert_design_contract(
            conn,
            DesignContract(
                contract_id="design-contract:active",
                version=1,
                ui_capability_mode="full",
                ui_validation_mode="local",
                ui_heavy=True,
                designer_enabled=True,
                audience="Operators",
                product_goal="Review local UI work.",
                product_posture="polished and task-focused",
            ),
        )
        insert_design_review(
            conn,
            DesignReview(
                review_id="review-1",
                contract_id="design-contract:active",
                node_id="node-1",
                status="passed",
                severity="low",
                findings=["Design contract followed."],
                evidence_paths=["target/screenshots/home.png"],
            ),
        )
        conn.commit()

    db_path = database_path_for_target(tmp_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM execution_dag_nodes").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM validation_receipts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM execution_groups").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM code_facts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM design_contracts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM design_reviews").fetchone()[0] == 1
    with connect(tmp_path) as conn:
        assert latest_design_contract(conn)["contract_id"] == "design-contract:active"


def test_alembic_migration_adopts_partially_created_initial_schema(tmp_path: Path) -> None:
    db_path = database_path_for_target(tmp_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(
            """
            CREATE TABLE execution_dag_nodes (
                node_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE TABLE execution_groups (group_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")

    with connect(tmp_path) as conn:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        projection_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(projections)").fetchall()
        }
        node_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(execution_dag_nodes)").fetchall()
        }
        receipt_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(validation_receipts)").fetchall()
        }

    assert version == "0006_design_runtime_surfaces"
    assert "execution_dag_nodes" in tables
    assert "legacy_execution_dag_nodes_pre_0002" in tables
    assert "scheduler_decisions" in tables
    assert "execution_groups" in tables
    assert "typed_execution_groups_pre_0005" in tables
    assert "integration_queue" in tables
    assert "design_contracts" in tables
    assert "design_reviews" in tables
    assert {"name", "payload_json", "payload_sha256", "event_id"}.issubset(projection_columns)
    assert {"task_id", "ticket_id", "paths_json", "payload_json"}.issubset(node_columns)
    assert {"work_item_id", "node_id", "required", "recorded_at"}.issubset(receipt_columns)


def test_scheduler_policy_converts_validation_failures_to_repair_work(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="policy",
        tickets=[TicketRecord(ticket_id="T1", title="Ready")],
        dag_nodes=[DagNode(node_id="node-1", paths=["src/app.py"])],
        validation_receipts=[
            ValidationReceipt(
                receipt_id="receipt-1",
                node_id="node-1",
                command="pytest",
                status="failed",
            )
        ],
    )

    assert record.selected.action_kind == "create_repair_work"
    assert record.selected.node_ids == ["node-1"]
    assert record.repair_work[0].action_type == "repair"


def test_scheduler_policy_routes_design_nodes_to_designer_lane(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="design-lane",
        tickets=[],
        dag_nodes=[DagNode(node_id="design-1", action_type="design", owner_role="designer", paths=[])],
        validation_receipts=[],
    )

    assert record.selected.action_kind == "launch_work"
    assert record.selected.owner_role == "designer"
    assert record.selected.execution_mode == "write"
    assert ".diffmogger/agentic/design_contract.md" in record.selected.paths


def test_scheduler_policy_turns_missing_ui_visual_tooling_into_setup_work(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="ui-visual-setup",
        tickets=[],
        dag_nodes=[DagNode(node_id="ui-check", paths=["src/App.tsx"])],
        validation_receipts=[
            ValidationReceipt(
                receipt_id="receipt-ui",
                node_id="ui-check",
                command="npm run browser-smoke",
                status="failed",
                required=True,
                payload={"classification": "ui_visual", "error": "playwright not installed"},
            )
        ],
    )

    assert record.selected.action_kind == "create_setup_work"
    assert record.selected.owner_role == "hardener"
    assert record.repair_work[0].action_type == "setup"


def test_scheduler_policy_groups_non_overlapping_ready_nodes(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="fanout",
        tickets=[],
        dag_nodes=[
            DagNode(node_id="a", paths=["src/a.py"]),
            DagNode(node_id="b", paths=["src/b.py"]),
            DagNode(node_id="overlap", paths=["src/a.py"]),
            DagNode(node_id="c", paths=["docs/c.md"]),
        ],
        validation_receipts=[],
        max_fanout=2,
    )

    assert record.selected.action_kind == "launch_work"
    assert record.selected.node_ids == ["a", "b"]
    assert record.selected.fanout == 2
    assert record.execution_group is not None
    assert record.execution_group.max_fanout == 2
    assert record.validation_group is not None


def test_scheduler_policy_scopes_multiple_ready_tickets(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="ticket-scope",
        tickets=[
            TicketRecord(ticket_id="T1", title="Scope first ticket", ownership_paths=["."]),
            TicketRecord(ticket_id="T2", title="Scope second ticket", ownership_paths=["."]),
            TicketRecord(ticket_id="T3", title="Scope later ticket", ownership_paths=["."]),
        ],
        dag_nodes=[],
        validation_receipts=[],
        max_fanout=2,
    )

    assert record.selected.action_kind == "launch_scope_work"
    assert record.selected.fanout == 2
    assert record.selected.ticket_ids == ["T1", "T2"]
    assert record.selected.telemetry["ticket_scope_wave"] is True
    assert record.selected.telemetry["configured_max_fanout"] == 2
    assert record.selected.telemetry["ready_scope_candidate_count"] == 3
    assert record.selected.telemetry["deferred_ticket_scope_candidate_ids"] == ["candidate:ticket-scope:ticket-T3"]
    assert record.scheduler_telemetry is not None
    assert record.scheduler_telemetry.max_fanout == 2
    assert record.scheduler_telemetry.selected_count == 2


def test_scheduler_policy_caps_large_ticket_scope_wave(tmp_path: Path) -> None:
    tickets = [
        TicketRecord(ticket_id=f"T{i:02d}", title=f"Scope ticket {i}", ownership_paths=[f"src/{i}.py"])
        for i in range(40)
    ]

    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="large-ticket-scope",
        tickets=tickets,
        dag_nodes=[],
        validation_receipts=[],
        max_fanout=32,
    )

    assert record.selected.action_kind == "launch_scope_work"
    assert record.selected.fanout == 32
    assert len(record.selected.ticket_ids) == 32
    assert record.selected.telemetry["ready_scope_candidate_count"] == 40
    assert len(record.selected.telemetry["deferred_ticket_scope_candidate_ids"]) == 8


def test_scheduler_policy_ticket_scope_wave_group_ids_include_ticket_set(tmp_path: Path) -> None:
    first = choose_scheduler_record(
        target_path=tmp_path,
        run_id="same-run",
        tickets=[
            TicketRecord(ticket_id="T1", title="Scope first ticket", ownership_paths=["."]),
            TicketRecord(ticket_id="T2", title="Scope second ticket", ownership_paths=["."]),
        ],
        dag_nodes=[],
        validation_receipts=[],
    )
    second = choose_scheduler_record(
        target_path=tmp_path,
        run_id="same-run",
        tickets=[
            TicketRecord(ticket_id="T3", title="Scope third ticket", ownership_paths=["."]),
            TicketRecord(ticket_id="T4", title="Scope fourth ticket", ownership_paths=["."]),
        ],
        dag_nodes=[],
        validation_receipts=[],
    )

    assert first.selected.candidate_id == second.selected.candidate_id
    assert first.selected.ticket_ids == ["T1", "T2"]
    assert second.selected.ticket_ids == ["T3", "T4"]
    assert first.execution_group is not None
    assert second.execution_group is not None
    assert first.execution_group.group_id != second.execution_group.group_id


def test_scheduler_policy_serializes_overlapping_ownership_with_telemetry(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="overlap",
        tickets=[],
        dag_nodes=[
            DagNode(node_id="a", paths=["src/app.py"]),
            DagNode(node_id="overlap", paths=["src"]),
            DagNode(node_id="b", paths=["docs/guide.md"]),
        ],
        validation_receipts=[],
        max_fanout=3,
    )

    assert record.selected.node_ids == ["a", "b"]
    assert any(conflict.conflict_type == "path_overlap" for conflict in record.conflicts)
    assert "path_overlap" in (record.scheduler_telemetry.reduced_fanout_reasons if record.scheduler_telemetry else [])


def test_scheduler_policy_serializes_root_owned_scoped_ticket_writes(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="root-owned",
        tickets=[],
        dag_nodes=[
            DagNode(node_id="T1-build", ticket_id="T1", paths=["."]),
            DagNode(node_id="T2-build", ticket_id="T2", paths=["."]),
        ],
        validation_receipts=[],
        max_fanout=2,
    )

    assert record.selected.action_kind == "launch_work"
    assert record.selected.node_ids == ["T1-build"]
    assert record.selected.fanout == 1
    assert any(conflict.conflict_type == "path_overlap" for conflict in record.conflicts)


def test_scheduler_policy_tree_sitter_imports_influence_wave(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import alpha\n\ndef beta():\n    return alpha()\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("def gamma():\n    return 3\n", encoding="utf-8")
    facts = [
        *code_facts.facts_for_file(tmp_path / "a.py"),
        *code_facts.facts_for_file(tmp_path / "b.py"),
        *code_facts.facts_for_file(tmp_path / "c.py"),
    ]

    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="facts",
        tickets=[],
        dag_nodes=[
            DagNode(node_id="a", paths=["a.py"]),
            DagNode(node_id="b", paths=["b.py"]),
            DagNode(node_id="c", paths=["c.py"]),
        ],
        validation_receipts=[],
        code_facts=facts,
        max_fanout=3,
    )

    assert record.selected.node_ids == ["a", "c"]
    assert any(conflict.conflict_type == "import_coupling" for conflict in record.conflicts)


def test_scheduler_policy_parser_fallback_uses_path_safety_without_freezing_work(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="parser",
        tickets=[],
        dag_nodes=[
            DagNode(node_id="ts", paths=["src/view.ts"]),
            DagNode(node_id="py", paths=["src/app.py"]),
        ],
        validation_receipts=[],
        code_facts=[
            CodeFact(
                fact_id="fact-parser",
                file_path=str(tmp_path / "src/view.ts"),
                language="typescript",
                kind="parser_unavailable",
                name="tree_sitter_parser_unavailable",
                source="fallback",
            )
        ],
        max_fanout=2,
    )

    assert record.selected.action_kind == "launch_work"
    assert record.selected.node_ids == ["ts", "py"]
    assert record.selected.telemetry["parser_unavailable_node_ids"] == ["ts"]
    assert any(item.startswith("parser_unavailable:") for item in record.selected.scope_evidence)
    assert not any(candidate.action_kind == "create_setup_work" for candidate in record.candidates)
    assert record.scheduler_telemetry is not None
    assert record.scheduler_telemetry.parser_fallbacks


def test_scheduler_policy_leases_and_low_confidence_reduce_fanout_without_idling(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="leases",
        tickets=[],
        dag_nodes=[
            DagNode(node_id="leased", paths=["src/a.py"]),
            DagNode(node_id="low", paths=["src/b.py"], confidence=0.25),
            DagNode(node_id="ready", paths=["src/c.py"]),
        ],
        validation_receipts=[],
        ownership_leases=[
            OwnershipLease(
                lease_id="lease-active",
                owner="builder",
                paths=["src/a.py"],
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            ),
            OwnershipLease(
                lease_id="lease-stale",
                owner="builder",
                paths=["src/c.py"],
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            ),
        ],
        max_fanout=3,
    )

    assert record.selected.action_kind == "launch_work"
    assert record.selected.node_ids == ["ready"]
    assert any(conflict.conflict_type == "lease_overlap" for conflict in record.conflicts)
    assert record.scheduler_telemetry is not None
    assert "lease-stale" in record.scheduler_telemetry.stale_lease_ids


def test_scheduler_policy_optional_validation_failure_is_telemetry_not_repair(tmp_path: Path) -> None:
    record = choose_scheduler_record(
        target_path=tmp_path,
        run_id="optional-validation",
        tickets=[],
        dag_nodes=[DagNode(node_id="node-1", paths=["src/app.py"])],
        validation_receipts=[
            ValidationReceipt(
                receipt_id="receipt-optional",
                node_id="node-1",
                command="playwright smoke",
                status="failed",
                required=False,
            )
        ],
    )

    assert record.selected.action_kind == "launch_work"
    assert record.repair_work == []
    assert record.telemetry["failed_optional_validation"] == 1


def test_temporal_activity_scheduler_cycle_persists_parallel_group_and_leases(tmp_path: Path) -> None:
    with connect(tmp_path) as conn:
        with conn:
            upsert_dag_node(conn, DagNode(node_id="a", paths=["src/a.py"]))
            upsert_dag_node(conn, DagNode(node_id="b", paths=["src/b.py"]))

    result = asyncio.run(
        run_scheduler_cycle(
            SchedulerCycleRequest(
                target_path=str(tmp_path),
                run_id="activity",
                max_fanout=2,
            ).model_dump(mode="json")
        )
    )

    assert result["decision"]["selected"]["node_ids"] == ["a", "b"]
    db_path = database_path_for_target(tmp_path)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM execution_groups").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='active'").fetchone()[0] == 2


def test_dashboard_snapshot_surfaces_typed_parallel_runtime_state(tmp_path: Path) -> None:
    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(conn, TicketRecord(ticket_id="T1", title="Build typed dashboard state", status="running"))
            upsert_dag_node(
                conn,
                DagNode(
                    node_id="node-1",
                    ticket_id="T1",
                    action_type="build",
                    status="running",
                    paths=["src/app.py"],
                ),
            )
            upsert_execution_group(
                conn,
                ExecutionGroup(
                    group_id="group-1",
                    run_id="run-typed",
                    action_kind="work_wave",
                    status="planned",
                    node_ids=["node-1"],
                    ticket_ids=["T1"],
                    paths=["src/app.py"],
                ),
            )
            upsert_ownership_lease(
                conn,
                OwnershipLease(
                    lease_id="lease-1",
                    owner="builder",
                    run_id="run-typed",
                    group_id="group-1",
                    node_id="node-1",
                    paths=["src/app.py"],
                    status="active",
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                ),
            )
            upsert_worker_output(
                conn,
                WorkerOutput(
                    output_id="worker-output-1",
                    run_id="run-typed",
                    group_id="group-1",
                    node_id="node-1",
                    worker_id="worker-1",
                    status="completed",
                    changed_paths=["src/app.py"],
                    summary="Worker completed.",
                    patch_path=".diffmogger/patches/worker-1.diff",
                ),
            )

    snapshot = state_snapshot(tmp_path)

    assert any(lease.get("source") == "ownership_leases" and lease.get("lease_id") == "lease-1" for lease in snapshot["active_leases"])
    assert any(
        group.get("group_id") == "group-1" and group.get("status") == "running"
        for group in snapshot["active_execution_groups"]
    )
    assert any(
        worker.get("source") == "ownership_leases" and worker.get("execution_group_id") == "group-1"
        for worker in snapshot["active_write_workers"]
    )
    assert any(
        worker.get("source") == "worker_runs" and worker.get("worker_id") == "worker-1"
        for worker in snapshot["completed_write_worker_reports"]
    )


def test_dashboard_snapshot_surfaces_ticket_specific_scope_worker_state(tmp_path: Path) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(conn, TicketRecord(ticket_id="T1", title="Scope first ticket", status="ready"))
            upsert_ticket(conn, TicketRecord(ticket_id="T2", title="Scope second ticket", status="ready"))
            upsert_execution_group(
                conn,
                ExecutionGroup(
                    group_id="group-scope",
                    run_id="run-scope",
                    action_kind="scope_wave",
                    status="running",
                    ticket_ids=["T1", "T2"],
                    paths=["."],
                ),
            )
            for ticket_id in ("T1", "T2"):
                upsert_ownership_lease(
                    conn,
                    OwnershipLease(
                        lease_id=f"lease-{ticket_id}",
                        owner="planner",
                        run_id="run-scope",
                        group_id="group-scope",
                        node_id="",
                        paths=["."],
                        mode="read",
                        status="active",
                        expires_at=expires_at,
                        payload={"ticket_id": ticket_id, "action_kind": "launch_scope_work"},
                    ),
                )

    snapshot = state_snapshot(tmp_path)

    scope_workers = [
        worker
        for worker in snapshot["active_read_only_workers"]
        if worker.get("execution_group_id") == "group-scope"
    ]
    assert {worker.get("ticket_id") for worker in scope_workers} == {"T1", "T2"}
    assert {worker.get("display_status") for worker in scope_workers} == {"scoping"}
    assert not any(
        worker.get("execution_group_id") == "group-scope"
        for worker in snapshot["active_write_workers"]
    )


def test_campaign_cycle_executes_follow_up_and_completes_ticket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "stub-success")

    result = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(
                target_path=str(tmp_path),
                run_id="campaign",
                max_fanout=2,
            ).model_dump(mode="json")
        )
    )

    assert result["cycle"]["decision"]["selected"]["action_kind"] == "launch_scope_work"
    assert result["follow_up"]["workers"][0]["activity"] == "execute_role_work"

    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM worker_runs WHERE status='completed'").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM tickets WHERE ticket_id='default-local-cycle'").fetchone()[0] == "done"
        assert conn.execute("SELECT status FROM execution_groups").fetchone()[0] == "completed"
        assert conn.execute("SELECT status FROM validation_groups").fetchone()[0] == "deferred"

    follow_up = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(
                target_path=str(tmp_path),
                run_id="campaign-idle",
            ).model_dump(mode="json")
        )
    )
    assert follow_up["cycle"]["decision"]["selected"]["action_kind"] == "idle_complete"


def test_default_stub_does_not_complete_write_without_material_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DIFFMOGGER_WORKER_EXECUTION", raising=False)
    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(conn, TicketRecord(ticket_id="T1", title="Implement real files", ownership_paths=["."]))
            upsert_dag_node(conn, DagNode(node_id="N1", ticket_id="T1", paths=["."]))

    result = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="no-material").model_dump(mode="json")
        )
    )

    assert result["cycle"]["decision"]["selected"]["action_kind"] == "launch_work"
    assert result["follow_up"]["workers"][0]["ok"] is False
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        assert conn.execute("SELECT status FROM tickets WHERE ticket_id='T1'").fetchone()[0] == "blocked"
        assert conn.execute("SELECT status FROM execution_groups").fetchone()[0] == "failed"
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='active'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='released' AND mode='write'").fetchone()[0] == 1


def test_design_contract_projection_changes_are_material_when_sidecar_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("/.diffmogger/\n", encoding="utf-8")
    helper_path = tmp_path / "scripts" / "spawn_worker_agent.sh"
    helper_path.parent.mkdir(parents=True)
    helper_path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
target=""
report_path=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      target="$2"
      shift 2
      ;;
    --report-path)
      report_path="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
mkdir -p "$target/.diffmogger/agentic" "$target/.diffmogger/runtime" "$(dirname "$report_path")"
printf '# Design Contract\\n\\nUpdated by test worker.\\n' > "$target/.diffmogger/agentic/design_contract.md"
printf '{"version":1,"source":"test"}\\n' > "$target/.diffmogger/agentic/design_contract.json"
printf '{"version":1,"source":"test"}\\n' > "$target/.diffmogger/runtime/design_contract.json"
printf 'updated design contract\\n' > "$report_path"
""",
        encoding="utf-8",
    )
    helper_path.chmod(0o755)
    subprocess.run(["git", "add", "scripts/spawn_worker_agent.sh"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "add worker helper"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    design_paths = [
        ".diffmogger/agentic/design_contract.md",
        ".diffmogger/agentic/design_contract.json",
        ".diffmogger/runtime/design_contract.json",
    ]
    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T1",
                    title="Create UI design foundation contract",
                    ownership_paths=design_paths,
                ),
            )
            upsert_dag_node(
                conn,
                DagNode(
                    node_id="N1",
                    ticket_id="T1",
                    owner_role="builder",
                    paths=design_paths,
                ),
            )

    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "codex")
    result = asyncio.run(
        orchestration_activities.execute_role_work(
            {
                "target_path": str(tmp_path),
                "run_id": "design-material",
                "group_id": "G1",
                "node_id": "N1",
                "ticket_id": "T1",
                "paths": design_paths,
            }
        )
    )

    assert result["ok"] is True
    output = result["output"]
    expected_material_paths = sorted(design_paths)
    assert output["status"] == "completed"
    assert output["changed_paths"] == expected_material_paths
    assert output["payload"]["material_changed_paths"] == expected_material_paths
    status_lines = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert status_lines == ["?? target/orchestration.sqlite3"]


def test_scope_ownership_paths_parser_handles_valid_invalid_and_missing_reports() -> None:
    paths, status, detail = _parse_owned_paths_from_text(
        "assignment\nOWNERSHIP_PATHS_JSON: [\"src/app.py\", \"tests/test_app.py\"]\nconfidence\n"
    )
    assert paths == ["src/app.py", "tests/test_app.py"]
    assert status == "parsed"
    assert detail == ""

    paths, status, detail = _parse_owned_paths_from_text("OWNERSHIP_PATHS_JSON: {not json}\n")
    assert paths == []
    assert status == "invalid"
    assert "invalid JSON" in detail

    paths, status, detail = _parse_owned_paths_from_text("assignment\nconfidence\n")
    assert paths == []
    assert status == "missing"
    assert "OWNERSHIP_PATHS_JSON" in detail


def test_scope_ownership_handoff_narrows_paths_and_falls_back_safely(tmp_path: Path) -> None:
    def complete_scope_follow_up(
        *,
        cycle: dict[str, object],
        ticket_id: str,
        owned_paths: list[str],
        owned_status: str,
        owned_detail: str = "",
    ) -> dict[str, object]:
        decision = cycle["decision"] if isinstance(cycle.get("decision"), dict) else {}
        group = decision.get("execution_group") if isinstance(decision.get("execution_group"), dict) else {}
        output = WorkerOutput(
            output_id=f"worker-output:{ticket_id}",
            run_id=str(cycle.get("run_id") or ""),
            group_id=str(group.get("group_id") or ""),
            node_id="",
            worker_id="test-scope-worker",
            status="completed",
            changed_paths=[".diffmogger/runtime/scoping.md"],
            summary="Scope complete.",
            payload={
                "input": {"ticket_id": ticket_id},
                "ticket_id": ticket_id,
                "owned_paths": owned_paths,
                "owned_paths_status": owned_status,
                "owned_paths_detail": owned_detail,
            },
        )
        return {
            "workers": [
                {
                    "ok": True,
                    "activity": "execute_role_work",
                    "output": output.model_dump(mode="json"),
                }
            ],
            "validation": {"ok": True},
        }

    narrow_target = tmp_path / "narrow"
    with connect(narrow_target) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T1",
                    title="Scope narrow implementation",
                    ownership_paths=["."],
                    payload={"source": "ticket_run_item"},
                ),
            )
    narrow_cycle = asyncio.run(
        run_scheduler_cycle(
            SchedulerCycleRequest(target_path=str(narrow_target), run_id="scope-narrow").model_dump(mode="json")
        )
    )
    _mark_follow_up_recorded(
        narrow_target,
        narrow_cycle,
        complete_scope_follow_up(
            cycle=narrow_cycle,
            ticket_id="T1",
            owned_paths=["src/narrow.py"],
            owned_status="parsed",
        ),
    )

    with sqlite3.connect(database_path_for_target(narrow_target)) as conn:
        assert json.loads(conn.execute("SELECT paths_json FROM execution_dag_nodes").fetchone()[0]) == ["src/narrow.py"]
        ticket_payload = json.loads(conn.execute("SELECT payload_json FROM tickets WHERE ticket_id='T1'").fetchone()[0])
        assert ticket_payload["payload"]["scope_owned_paths_status"] == "parsed"

    fallback_target = tmp_path / "fallback"
    with connect(fallback_target) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T2",
                    title="Scope fallback implementation",
                    ownership_paths=["docs/fallback.md"],
                    payload={"source": "ticket_run_item"},
                ),
            )
    fallback_cycle = asyncio.run(
        run_scheduler_cycle(
            SchedulerCycleRequest(target_path=str(fallback_target), run_id="scope-fallback").model_dump(mode="json")
        )
    )
    _mark_follow_up_recorded(
        fallback_target,
        fallback_cycle,
        complete_scope_follow_up(
            cycle=fallback_cycle,
            ticket_id="T2",
            owned_paths=[],
            owned_status="invalid",
            owned_detail="invalid JSON",
        ),
    )

    with sqlite3.connect(database_path_for_target(fallback_target)) as conn:
        assert json.loads(conn.execute("SELECT paths_json FROM execution_dag_nodes").fetchone()[0]) == [
            "docs/fallback.md"
        ]
        ticket_payload = json.loads(conn.execute("SELECT payload_json FROM tickets WHERE ticket_id='T2'").fetchone()[0])
        assert ticket_payload["payload"]["scope_owned_paths_status"] == "invalid"


def test_worker_command_runner_starts_subprocesses_concurrently(tmp_path: Path) -> None:
    script = (
        "import pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text(str(time.time()), encoding='utf-8'); "
        "time.sleep(0.6)"
    )

    async def run_pair() -> float:
        await asyncio.gather(
            _run_worker_command(
                [sys.executable, "-c", script, str(tmp_path / "one.start")],
                cwd=tmp_path,
                activity_log_path=tmp_path / "one.log",
                timeout=5,
            ),
            _run_worker_command(
                [sys.executable, "-c", script, str(tmp_path / "two.start")],
                cwd=tmp_path,
                activity_log_path=tmp_path / "two.log",
                timeout=5,
            ),
        )
        first = float((tmp_path / "one.start").read_text(encoding="utf-8"))
        second = float((tmp_path / "two.start").read_text(encoding="utf-8"))
        return abs(first - second)

    assert asyncio.run(run_pair()) < 0.5


def test_campaign_cycle_backfills_unlocked_work_before_slowest_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}

    async def fake_execute_role_work(payload: dict[str, object]) -> dict[str, object]:
        node_id = str(payload.get("node_id") or "")
        group_id = str(payload.get("group_id") or "")
        ticket_id = str(payload.get("ticket_id") or "")
        paths = [str(path) for path in payload.get("paths", [])] if isinstance(payload.get("paths"), list) else []
        starts[node_id] = time.monotonic()
        await asyncio.sleep({"A": 0.20, "B": 0.02, "C": 0.01}[node_id])
        finishes[node_id] = time.monotonic()
        output = WorkerOutput(
            output_id=f"worker-output:rolling:{group_id}:{node_id}",
            run_id="rolling",
            group_id=group_id,
            node_id=node_id,
            worker_id="fake-worker",
            status="completed",
            changed_paths=paths or [f"src/{node_id.lower()}.py"],
            summary="fake worker completed",
            payload={"input": dict(payload), "ticket_id": ticket_id},
        )
        with connect(tmp_path) as conn:
            with conn:
                upsert_worker_output(conn, output)
        return {"ok": True, "activity": "execute_role_work", "output": output.model_dump(mode="json")}

    monkeypatch.setattr(orchestration_activities, "execute_role_work", fake_execute_role_work)
    with connect(tmp_path) as conn:
        with conn:
            for ticket_id in ("T-A", "T-B", "T-C"):
                upsert_ticket(conn, TicketRecord(ticket_id=ticket_id, title=ticket_id, status="running"))
            upsert_dag_node(conn, DagNode(node_id="A", ticket_id="T-A", paths=["src/a.py"]))
            upsert_dag_node(conn, DagNode(node_id="B", ticket_id="T-B", paths=["src/b.py"]))
            upsert_dag_node(conn, DagNode(node_id="C", ticket_id="T-C", paths=["src/c.py"]))
            conn.execute(
                """
                INSERT INTO execution_dag_edges(edge_id, from_node_id, to_node_id, edge_type, payload_json)
                VALUES(?, ?, ?, ?, ?)
                """,
                ("edge:B:C", "B", "C", "depends_on", json.dumps(DagEdge(edge_id="edge:B:C", from_node_id="B", to_node_id="C").model_dump(mode="json"))),
            )

    result = asyncio.run(
        orchestration_activities.run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="rolling").model_dump(mode="json")
        )
    )

    assert set(starts) == {"A", "B", "C"}
    assert starts["C"] < finishes["A"]
    assert result["follow_up"]["backfill_cycles"][0]["decision"]["selected"]["node_ids"] == ["C"]
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        statuses = dict(conn.execute("SELECT node_id, status FROM execution_dag_nodes ORDER BY node_id").fetchall())
        assert statuses == {"A": "done", "B": "done", "C": "done"}
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='active'").fetchone()[0] == 0


def test_campaign_cycle_does_not_backfill_active_lease_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    starts: dict[str, float] = {}

    async def fake_execute_role_work(payload: dict[str, object]) -> dict[str, object]:
        node_id = str(payload.get("node_id") or "")
        group_id = str(payload.get("group_id") or "")
        ticket_id = str(payload.get("ticket_id") or "")
        paths = [str(path) for path in payload.get("paths", [])] if isinstance(payload.get("paths"), list) else []
        starts[node_id] = time.monotonic()
        await asyncio.sleep({"A": 0.20, "B": 0.02}[node_id])
        output = WorkerOutput(
            output_id=f"worker-output:lease-backfill:{group_id}:{node_id}",
            run_id="lease-backfill",
            group_id=group_id,
            node_id=node_id,
            worker_id="fake-worker",
            status="completed",
            changed_paths=paths or [f"src/{node_id.lower()}.py"],
            summary="fake worker completed",
            payload={"input": dict(payload), "ticket_id": ticket_id},
        )
        with connect(tmp_path) as conn:
            with conn:
                upsert_worker_output(conn, output)
        return {"ok": True, "activity": "execute_role_work", "output": output.model_dump(mode="json")}

    monkeypatch.setattr(orchestration_activities, "execute_role_work", fake_execute_role_work)
    with connect(tmp_path) as conn:
        with conn:
            for ticket_id in ("T-A", "T-B", "T-C"):
                upsert_ticket(conn, TicketRecord(ticket_id=ticket_id, title=ticket_id, status="running"))
            upsert_dag_node(conn, DagNode(node_id="A", ticket_id="T-A", paths=["src/shared.py"]))
            upsert_dag_node(conn, DagNode(node_id="B", ticket_id="T-B", paths=["src/b.py"]))
            upsert_dag_node(conn, DagNode(node_id="C", ticket_id="T-C", paths=["src/shared.py"]))
            conn.execute(
                """
                INSERT INTO execution_dag_edges(edge_id, from_node_id, to_node_id, edge_type, payload_json)
                VALUES(?, ?, ?, ?, ?)
                """,
                ("edge:B:C", "B", "C", "depends_on", json.dumps(DagEdge(edge_id="edge:B:C", from_node_id="B", to_node_id="C").model_dump(mode="json"))),
            )

    asyncio.run(
        orchestration_activities.run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="lease-backfill").model_dump(mode="json")
        )
    )

    assert set(starts) == {"A", "B"}
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        assert conn.execute("SELECT status FROM execution_dag_nodes WHERE node_id='C'").fetchone()[0] == "ready"
        assert conn.execute("SELECT COUNT(*) FROM conflict_telemetry WHERE conflict_type='lease_overlap'").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='active'").fetchone()[0] == 0


def test_campaign_cycle_scopes_independent_tickets_then_writes_parallel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "stub-success")
    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T1",
                    title="Implement first independent slice",
                    ownership_paths=["src/first.py"],
                    payload={"source": "ticket_run_item"},
                ),
            )
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T2",
                    title="Implement second independent slice",
                    ownership_paths=["docs/second.md"],
                    payload={"source": "ticket_run_item"},
                ),
            )

    first = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="parallel-scope", max_fanout=2).model_dump(mode="json")
        )
    )

    assert first["cycle"]["decision"]["selected"]["action_kind"] == "launch_scope_work"
    assert first["cycle"]["decision"]["selected"]["fanout"] == 2
    assert set(first["cycle"]["decision"]["selected"]["ticket_ids"]) == {"T1", "T2"}
    assert len(first["follow_up"]["workers"]) == 2

    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        node_rows = conn.execute(
            "SELECT ticket_id, paths_json FROM execution_dag_nodes WHERE payload_json LIKE '%scope_follow_up%' ORDER BY ticket_id"
        ).fetchall()
        assert [(row[0], json.loads(row[1])) for row in node_rows] == [
            ("T1", ["src/first.py"]),
            ("T2", ["docs/second.md"]),
        ]

    second = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="parallel-write", max_fanout=2).model_dump(mode="json")
        )
    )

    assert second["cycle"]["decision"]["selected"]["action_kind"] == "launch_work"
    assert second["cycle"]["decision"]["selected"]["fanout"] == 2
    assert set(second["cycle"]["decision"]["selected"]["ticket_ids"]) == {"T1", "T2"}
    assert len(second["follow_up"]["workers"]) == 2
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        statuses = dict(conn.execute("SELECT ticket_id, status FROM tickets ORDER BY ticket_id").fetchall())
        assert statuses == {"T1": "done", "T2": "done"}
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='released' AND mode='write'").fetchone()[0] == 2


def test_ongoing_campaign_drafts_one_next_ticket_without_churning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "stub-success")

    state_dir = tmp_path / ".agentic"
    state_dir.mkdir()
    (state_dir / "dashboard_state.json").write_text(
        json.dumps(
            {
                "campaign_mode": "ongoing",
                "project_name": "Demo target",
                "brief_draft_intake": {
                    "product_goal": "Build a local-first planning workspace.",
                    "desired_first_demo": "A user can capture goals, generate a weekly plan, and review progress.",
                },
            }
        ),
        encoding="utf-8",
    )

    first = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="ongoing-first").model_dump(mode="json")
        )
    )
    assert first["cycle"]["decision"]["selected"]["ticket_ids"] == ["default-local-cycle"]

    second = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="ongoing-second").model_dump(mode="json")
        )
    )
    assert second["cycle"]["decision"]["selected"]["action_kind"] == "launch_scope_work"
    assert second["cycle"]["decision"]["selected"]["ticket_ids"] == ["ongoing-ticket-001"]

    third = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="ongoing-third").model_dump(mode="json")
        )
    )
    assert third["cycle"]["decision"]["selected"]["action_kind"] == "launch_work"
    assert third["cycle"]["decision"]["selected"]["ticket_ids"] == ["ongoing-ticket-001"]

    fourth = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="ongoing-fourth").model_dump(mode="json")
        )
    )
    assert fourth["cycle"]["decision"]["selected"]["action_kind"] == "launch_scope_work"
    assert fourth["cycle"]["decision"]["selected"]["ticket_ids"] == ["ongoing-ticket-002"]

    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        rows = conn.execute(
            "SELECT ticket_id, title, status, payload_json FROM tickets ORDER BY ticket_id"
        ).fetchall()
        statuses = {row[0]: row[2] for row in rows}
        payloads = {row[0]: json.loads(row[3])["payload"] for row in rows}
        assert statuses["default-local-cycle"] == "done"
        assert statuses["ongoing-ticket-001"] == "done"
        assert statuses["ongoing-ticket-002"] == "running"
        assert payloads["ongoing-ticket-001"]["source"] == "ongoing_campaign_draft"
        assert payloads["ongoing-ticket-001"]["follow_up_node_id"]
        assert conn.execute(
            "SELECT COUNT(*) FROM execution_dag_nodes WHERE ticket_id='ongoing-ticket-001' AND status='done'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE ticket_id LIKE 'ongoing-ticket-%'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM ownership_leases WHERE status='active'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM ownership_leases WHERE status='released' AND mode='write'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM runtime_events WHERE event_type='campaign.ticket_drafted'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM runtime_events WHERE event_type='campaign.scope_follow_up_created'"
        ).fetchone()[0] == 2


def test_scoped_running_ticket_without_node_is_recovered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "stub-success")

    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T-scoped",
                    title="Scoped ticket",
                    status="running",
                    ownership_paths=["."],
                    payload={
                        "source": "ongoing_campaign_draft",
                        "last_action_kind": "launch_scope_work",
                        "last_execution_group_id": "group:scope",
                    },
                ),
            )

    result = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="recover-scoped").model_dump(mode="json")
        )
    )

    assert result["cycle"]["decision"]["selected"]["action_kind"] == "launch_work"
    assert result["cycle"]["decision"]["selected"]["ticket_ids"] == ["T-scoped"]
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM execution_dag_nodes WHERE ticket_id='T-scoped' AND status='done'"
        ).fetchone()[0] == 1
        payload = json.loads(
            conn.execute("SELECT payload_json FROM tickets WHERE ticket_id='T-scoped'").fetchone()[0]
        )["payload"]
        assert payload["follow_up_node_id"]
        assert payload["last_build_node_id"] == payload["follow_up_node_id"]
        assert conn.execute("SELECT status FROM tickets WHERE ticket_id='T-scoped'").fetchone()[0] == "done"
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='active'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='released' AND mode='write'").fetchone()[0] == 1


@pytest.mark.parametrize("follow_up_status", ["done", "failed"])
def test_setup_only_follow_up_node_is_reopened(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, follow_up_status: str
) -> None:
    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "stub-success")

    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T-parser",
                    title="Recover parser setup ticket",
                    status="running",
                    ownership_paths=["src/app.ts"],
                    payload={
                        "source": "ticket_run_item",
                        "last_action_kind": "create_setup_work",
                        "last_execution_group_id": "group:parser-setup",
                        "follow_up_node_id": "node:parser-follow-up",
                    },
                ),
            )
            upsert_dag_node(
                conn,
                DagNode(
                    node_id="node:parser-follow-up",
                    ticket_id="T-parser",
                    action_type="build",
                    status=follow_up_status,  # type: ignore[arg-type]
                    paths=["src/app.ts"],
                    payload={
                        "source": "scope_follow_up",
                        "failure_reason": "worker helper exited with code 1" if follow_up_status == "failed" else "",
                    },
                ),
            )

    result = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="recover-parser").model_dump(mode="json")
        )
    )

    assert result["cycle"]["decision"]["selected"]["action_kind"] == "launch_work"
    assert result["cycle"]["decision"]["selected"]["node_ids"] == ["node:parser-follow-up"]
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        ticket_row = conn.execute(
            "SELECT status, payload_json FROM tickets WHERE ticket_id='T-parser'"
        ).fetchone()
        node_row = conn.execute(
            "SELECT status, payload_json FROM execution_dag_nodes WHERE node_id='node:parser-follow-up'"
        ).fetchone()
        assert ticket_row[0] == "done"
        assert node_row[0] == "done"
        ticket_payload = json.loads(ticket_row[1])["payload"]
        node_payload = json.loads(node_row[1])["payload"]
        assert ticket_payload["setup_only_follow_up_reopened_at"]
        assert ticket_payload["last_build_node_id"] == "node:parser-follow-up"
        assert node_payload["recovered_from_setup_only_action"] is True
        if follow_up_status == "failed":
            assert node_payload["recovered_from_failed_setup_only_action"] is True
        assert conn.execute(
            "SELECT COUNT(*) FROM runtime_events WHERE event_type='campaign.setup_only_follow_up_reopened'"
        ).fetchone()[0] == 1


def test_campaign_runtime_write_group_creates_checkpoint_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def git_run(*args: str) -> str:
        env = {
            **dict(os.environ),
            "GIT_AUTHOR_NAME": "Diffmogger Test",
            "GIT_AUTHOR_EMAIL": "diffmogger-test@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Test",
            "GIT_COMMITTER_EMAIL": "diffmogger-test@example.invalid",
        }
        result = subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=False, env=env)
        assert result.returncode == 0, result.stderr or result.stdout
        return result.stdout.strip()

    git_run("init", "-q")
    (tmp_path / "README.md").write_text("# Runtime checkpoint\n", encoding="utf-8")
    git_run("add", "README.md")
    git_run("commit", "-m", "chore: scaffold")
    base_commit = git_run("rev-parse", "HEAD")

    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="T-runtime",
                    title="Build runtime commit surface",
                    status="ready",
                    ownership_paths=["src/app.py"],
                ),
            )
            upsert_dag_node(
                conn,
                DagNode(
                    node_id="node:runtime",
                    ticket_id="T-runtime",
                    action_type="build",
                    status="ready",
                    paths=["src/app.py"],
                    summary="Build runtime commit surface",
                ),
            )

    async def fake_execute_role_work(payload: dict[str, object]) -> dict[str, object]:
        src = tmp_path / "src"
        src.mkdir(exist_ok=True)
        (src / "app.py").write_text("def app():\n    return 'ok'\n", encoding="utf-8")
        output = WorkerOutput(
            output_id="worker-output:runtime-checkpoint",
            run_id=str(payload.get("run_id") or "runtime-checkpoint"),
            group_id=str(payload.get("group_id") or ""),
            node_id=str(payload.get("node_id") or ""),
            worker_id="test-worker",
            status="completed",
            changed_paths=["src/app.py"],
            summary="Created app runtime surface.",
            payload={
                "input": {
                    "node_id": str(payload.get("node_id") or ""),
                    "ticket_id": str(payload.get("ticket_id") or ""),
                },
                "ticket_id": str(payload.get("ticket_id") or ""),
            },
        )
        return {"ok": True, "activity": "execute_role_work", "output": output.model_dump(mode="json")}

    monkeypatch.setattr(orchestration_activities, "execute_role_work", fake_execute_role_work)

    result = asyncio.run(
        orchestration_activities.run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="runtime-checkpoint").model_dump(mode="json")
        )
    )

    checkpoint = result["follow_up"]["integration"]["checkpoint"]
    head_commit = git_run("rev-parse", "HEAD")
    commit_body = git_run("log", "-1", "--format=%B")
    tree_paths = set(git_run("ls-tree", "-r", "--name-only", "HEAD").splitlines())

    assert checkpoint["status"] == "committed"
    assert checkpoint["commit_hash"] == head_commit
    assert head_commit != base_commit
    assert "feat(builder): build runtime commit surface" in commit_body
    assert "Diffmogger-Checkpoint: runtime-work" in commit_body
    assert "Diffmogger-Ticket: T-runtime" in commit_body
    assert "src/app.py" in tree_paths
    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        ticket_payload = json.loads(
            conn.execute("SELECT payload_json FROM tickets WHERE ticket_id='T-runtime'").fetchone()[0]
        )["payload"]
        assert ticket_payload["related_commits"] == [head_commit]


def test_spawn_worker_prompt_escapes_env_rule_heredoc() -> None:
    repo = Path(__file__).resolve().parents[1]
    for rel in ("scripts/target/spawn_worker_agent.sh", "templates/scripts/spawn_worker_agent.sh"):
        text = (repo / rel).read_text(encoding="utf-8")
        assert 'worker_env_access_rule_for_heredoc="$(escape_heredoc_text "$worker_env_access_rule")"' in text
        assert "- $worker_env_access_rule\n" not in text
        assert "- $worker_env_access_rule_for_heredoc\n" in text


def test_bounded_ticket_items_are_synced_into_scheduler_tickets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DIFFMOGGER_WORKER_EXECUTION", "stub-success")

    with connect(tmp_path) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE ticket_items (
                    ticket_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    blocker TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO ticket_items(ticket_id, run_id, position, summary, status, blocker, updated_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TICKET-001",
                    "bounded-run",
                    0,
                    "Build the first bounded ticket.",
                    "pending",
                    "",
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(
                        {
                            "id": "TICKET-001",
                            "summary": "Build the first bounded ticket.",
                            "status": "pending",
                            "depends_on": [],
                            "acceptance_criteria": ["Work is scoped."],
                            "verification_commands": ["pytest"],
                            "evidence": [],
                            "related_commits": [],
                            "blocker": "",
                        }
                    ),
                ),
            )
            conn.execute(
                """
                INSERT INTO ticket_items(ticket_id, run_id, position, summary, status, blocker, updated_at, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TICKET-002",
                    "bounded-run",
                    1,
                    "Wait for the first bounded ticket.",
                    "pending",
                    "",
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(
                        {
                            "id": "TICKET-002",
                            "summary": "Wait for the first bounded ticket.",
                            "status": "pending",
                            "depends_on": ["TICKET-001"],
                            "acceptance_criteria": ["Dependency is respected."],
                            "verification_commands": ["pytest"],
                            "evidence": [],
                            "related_commits": [],
                            "blocker": "",
                        }
                    ),
                ),
            )

    first = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="bounded-first").model_dump(mode="json")
        )
    )
    assert first["cycle"]["decision"]["selected"]["action_kind"] == "launch_scope_work"
    assert first["cycle"]["decision"]["selected"]["ticket_ids"] == ["TICKET-001"]

    second = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="bounded-second").model_dump(mode="json")
        )
    )
    assert second["cycle"]["decision"]["selected"]["action_kind"] == "launch_work"
    assert second["cycle"]["decision"]["selected"]["ticket_ids"] == ["TICKET-001"]

    third = asyncio.run(
        run_campaign_cycle(
            SchedulerCycleRequest(target_path=str(tmp_path), run_id="bounded-third").model_dump(mode="json")
        )
    )
    assert third["cycle"]["decision"]["selected"]["action_kind"] == "launch_scope_work"
    assert third["cycle"]["decision"]["selected"]["ticket_ids"] == ["TICKET-002"]

    with sqlite3.connect(database_path_for_target(tmp_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tickets WHERE ticket_id='default-local-cycle'").fetchone()[0] == 0
        rows = {
            row[0]: row
            for row in conn.execute("SELECT ticket_id, status, payload_json FROM tickets ORDER BY ticket_id").fetchall()
        }
        assert rows["TICKET-001"][1] == "done"
        assert rows["TICKET-002"][1] == "running"
        payload = json.loads(rows["TICKET-001"][2])["payload"]
        assert payload["source"] == "ticket_run_item"
        assert payload["follow_up_node_id"]
        assert conn.execute(
            "SELECT COUNT(*) FROM execution_dag_nodes WHERE ticket_id='TICKET-001' AND status='done'"
        ).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='active'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ownership_leases WHERE status='released' AND mode='write'").fetchone()[0] == 1


def test_tree_sitter_code_facts_extract_python_symbols_and_imports(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "import json\n\nclass Runner:\n    pass\n\ndef run_cycle():\n    return json.dumps({})\n",
        encoding="utf-8",
    )

    facts = code_facts.facts_for_file(source)
    names = {(fact.kind, fact.name) for fact in facts}

    assert ("symbol", "Runner") in names
    assert ("symbol", "run_cycle") in names
    assert any(fact.kind == "import" and fact.target == "json" for fact in facts)


def test_tree_sitter_parser_unavailable_fallback(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(code_facts, "_language_for", lambda _path: ("python", None))

    facts = code_facts.facts_for_file(source)

    assert facts[0].kind == "parser_unavailable"
    assert facts[0].source == "fallback"


def test_apprise_dry_run_delivery_is_typed() -> None:
    result = send_notification(
        NotificationPayload(
            message_id="message-1",
            title="Dry run",
            body="No outbound delivery.",
            apprise_urls=["json://127.0.0.1:9"],
            dry_run=True,
        )
    )

    assert result.ok is True
    assert result.sent is False
    assert result.status == "dry_run"


def test_integrator_commit_messages_use_intent_metadata_and_safe_paths(tmp_path: Path) -> None:
    manifest = {
        "role": "builder",
        "run_id": "worker-run",
        "task_id": "TICKET-123",
        "changed_files": ["src/backend.py", "tests/test_backend.py"],
        "checks_run": ["python3 -m py_compile src/backend.py"],
        "summary": "\n".join(
            [
                "Commit type: feat",
                "Commit scope: api",
                "Commit subject: Add customer endpoint",
                "",
                "## Summary",
                "Adds the endpoint.",
            ]
        ),
    }

    message = semantic_commit_message(manifest, tmp_path, "integrator-run")
    allowed, skipped = filter_commit_paths(
        [
            "src/backend.py",
            "tests/test_backend.py",
            "docs/guide.md",
            "package-lock.json",
            ".env",
            ".env.local",
            ".env.example",
            "node_modules/pkg/index.js",
            ".diffmogger/runtime/automation_logs/raw.log",
            "target/automation_queue/builder/run/manifest.json",
            "dist/app.js",
            ".DS_Store",
        ]
    )

    assert message.splitlines()[0] == "feat(api): add customer endpoint"
    assert "Diffmogger-Run: integrator-run" in message
    assert "Diffmogger-Ticket: TICKET-123" in message
    assert "Diffmogger-Role: builder" in message
    assert "Diffmogger-Patch-Run: worker-run" in message
    assert "Validation: python3 -m py_compile src/backend.py" in message
    assert allowed == ["src/backend.py", "tests/test_backend.py", "docs/guide.md", "package-lock.json", ".env.example"]
    assert {item["path"] for item in skipped} == {
        ".env",
        ".env.local",
        "node_modules/pkg/index.js",
        ".diffmogger/runtime/automation_logs/raw.log",
        "target/automation_queue/builder/run/manifest.json",
        "dist/app.js",
        ".DS_Store",
    }


def test_ticket_run_state_overlays_typed_ticket_statuses_on_stale_projection(tmp_path: Path) -> None:
    stale_tickets = [
        {
            "id": "TICKET-001",
            "summary": "Build first slice.",
            "status": "pending",
            "depends_on": [],
            "acceptance_criteria": ["First slice works."],
            "verification_commands": ["python3 -m py_compile src/first.py"],
            "evidence": [],
            "related_commits": [],
            "blocker": "",
        },
        {
            "id": "TICKET-002",
            "summary": "Build second slice.",
            "status": "pending",
            "depends_on": ["TICKET-001"],
            "acceptance_criteria": ["Second slice works."],
            "verification_commands": [],
            "evidence": [],
            "related_commits": [],
            "blocker": "",
        },
        {
            "id": "TICKET-003",
            "summary": "Wait for follow-up.",
            "status": "pending",
            "depends_on": ["TICKET-002"],
            "acceptance_criteria": [],
            "verification_commands": [],
            "evidence": [],
            "related_commits": [],
            "blocker": "",
        },
    ]
    write_ticket_run_state(
        tmp_path,
        {
            "run_id": "demo-run",
            "halt_when_complete": True,
            "notify_on_complete": False,
            "tickets": stale_tickets,
        },
        actor_role="test",
        event_type="ticket.test_seeded",
    )

    with connect(tmp_path) as conn:
        with conn:
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="TICKET-001",
                    title="Build first slice.",
                    status="done",
                    evidence=["worker_output:first-slice"],
                    payload={"ticket_run_id": "demo-run", "position": 0, "ticket_item": stale_tickets[0]},
                ),
            )
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="TICKET-002",
                    title="Build second slice.",
                    status="running",
                    depends_on=["TICKET-001"],
                    payload={"ticket_run_id": "demo-run", "position": 1, "ticket_item": stale_tickets[1]},
                ),
            )
            upsert_ticket(
                conn,
                TicketRecord(
                    ticket_id="TICKET-003",
                    title="Wait for follow-up.",
                    status="waiting",
                    depends_on=["TICKET-002"],
                    payload={"ticket_run_id": "demo-run", "position": 2, "ticket_item": stale_tickets[2]},
                ),
            )

    ticket_state = load_ticket_run_state(tmp_path)
    assert ticket_state is not None
    assert [ticket["status"] for ticket in ticket_state["tickets"]] == ["done", "in_progress", "pending"]
    assert ticket_state["tickets"][0]["evidence"] == ["worker_output:first-slice"]
    assert ticket_state["tickets"][0]["acceptance_criteria"] == ["First slice works."]
    assert ticket_state["tickets"][1]["depends_on"] == ["TICKET-001"]

    summary = ticket_run_state_summary(tmp_path)
    assert summary["total"] == 3
    assert summary["counts"]["done"] == 1
    assert summary["counts"]["in_progress"] == 1
    assert summary["counts"]["pending"] == 1

    with connect(tmp_path) as conn:
        with conn:
            dag = materialize_execution_dag_conn(conn, tmp_path, default_conveyor_state())
    completion_nodes = [
        node
        for node in dag["nodes"]
        if node.get("task_id") == "TICKET-001" and node.get("action_type") == "completion"
    ]
    assert completion_nodes
    assert completion_nodes[0]["status"] == "complete"
    assert completion_nodes[0]["blocker_reason"] == ""


def test_integrator_creates_checkpoint_commit_and_records_ticket_state(tmp_path: Path) -> None:
    def git_run(*args: str, input_text: str | None = None) -> str:
        env = {
            **dict(os.environ),
            "GIT_AUTHOR_NAME": "Diffmogger Test",
            "GIT_AUTHOR_EMAIL": "diffmogger-test@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Test",
            "GIT_COMMITTER_EMAIL": "diffmogger-test@example.invalid",
        }
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return result.stdout.strip()

    git_run("init", "-q")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    git_run("add", "README.md")
    git_run("commit", "-m", "chore: scaffold")
    base_commit = git_run("rev-parse", "HEAD")

    initial_ticket = {
        "id": "TICKET-001",
        "summary": "Build backend core.",
        "status": "in_progress",
        "depends_on": [],
        "acceptance_criteria": ["Backend module exists."],
        "verification_commands": ["python3 -m py_compile src/backend.py"],
        "evidence": [],
        "related_commits": [],
        "blocker": "",
    }
    write_ticket_run_state(
        tmp_path,
        {
            "run_id": "demo-run",
            "halt_when_complete": True,
            "notify_on_complete": False,
            "tickets": [initial_ticket],
        },
        actor_role="test",
        event_type="ticket.test_seeded",
    )

    (tmp_path / "src").mkdir()
    backend = tmp_path / "src" / "backend.py"
    backend.write_text("def handler():\n    return 'ok'\n", encoding="utf-8")
    git_run("add", "-N", "src/backend.py")
    patch_text = git_run("diff", "--binary", base_commit, "--", "src/backend.py")
    git_run("reset", "-q")
    backend.unlink()
    (tmp_path / "src").rmdir()

    desired_ticket = {
        **initial_ticket,
        "status": "candidate_done",
        "evidence": ["python3 -m py_compile src/backend.py passed."],
    }
    queue_dir = tmp_path / "target" / "automation_queue" / "builder" / "worker-run"
    queue_dir.mkdir(parents=True)
    (queue_dir / "changes.patch").write_text(patch_text + "\n", encoding="utf-8")
    (queue_dir / "ticket_state_actions.json").write_text(
        json.dumps(
            {
                "actions": [
                    {
                        "action": "update_ticket",
                        "ticket_id": "TICKET-001",
                        "ticket": desired_ticket,
                        "start_hash": ticket_digest(initial_ticket),
                        "end_hash": ticket_digest(desired_ticket),
                    }
                ]
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (queue_dir / "manifest.json").write_text(
        json.dumps(
            {
                "role": "builder",
                "run_id": "worker-run",
                "patch_id": "patch-backend-core",
                "base_commit": base_commit,
                "status": "queued",
                "patch_path": "target/automation_queue/builder/worker-run/changes.patch",
                "ticket_state_actions_path": "target/automation_queue/builder/worker-run/ticket_state_actions.json",
                "changed_files": ["src/backend.py"],
                "verification_commands": ["python3 -m py_compile src/backend.py"],
                "summary": "\n".join(
                    [
                        "Commit type: feat",
                        "Commit scope: backend",
                        "Commit subject: Add backend core",
                        "",
                        "## Checks",
                        "python3 -m py_compile src/backend.py",
                    ]
                ),
                "created_at": "2026-05-26T00:00:00+00:00",
                "checkpoint_commit": None,
                "accepted_commit": None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (tmp_path / ".env").write_text("SECRET_VALUE=do-not-commit\n", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}\n", encoding="utf-8")
    (tmp_path / "target" / "automation_logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "target" / "automation_logs" / "raw.log").write_text("raw agent log\n", encoding="utf-8")

    assert integrate(tmp_path, "integrator-run", dry_run=False) == 0

    head_commit = git_run("rev-parse", "HEAD")
    log_subjects = git_run("log", "--format=%s").splitlines()
    commit_body = git_run("log", "-1", "--format=%B")
    tree_paths = set(git_run("ls-tree", "-r", "--name-only", "HEAD").splitlines())
    manifest = json.loads((queue_dir / "manifest.json").read_text(encoding="utf-8"))
    ticket_state = load_ticket_run_state(tmp_path)
    status_json = subprocess.run(
        [sys.executable, "-m", "diffmogger.runtime.ticket_run", str(tmp_path), "status", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**dict(os.environ), "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    assert status_json.returncode == 0
    status_payload = json.loads(status_json.stdout)
    recorded_ticket = ticket_state["tickets"][0]

    assert head_commit != base_commit
    assert log_subjects[0] == "feat(backend): add backend core"
    assert "Diffmogger-Run: integrator-run" in commit_body
    assert "Diffmogger-Ticket: TICKET-001" in commit_body
    assert "Diffmogger-Role: builder" in commit_body
    assert "Validation: python3 -m py_compile src/backend.py" in commit_body
    assert "src/backend.py" in tree_paths
    assert ".env" not in tree_paths
    assert not any(path.startswith("node_modules/") for path in tree_paths)
    assert not any(path.startswith("target/automation_logs/") for path in tree_paths)
    assert manifest["status"] == "applied"
    assert manifest["accepted_commit"] == head_commit
    assert recorded_ticket["related_commits"] == [head_commit]
    assert recorded_ticket["status"] == "candidate_done"
    assert status_payload["tickets"][0]["related_commits"] == [head_commit]


def test_integrator_respects_disabled_checkpoint_commits(tmp_path: Path) -> None:
    def git_run(*args: str) -> str:
        env = {
            **dict(os.environ),
            "GIT_AUTHOR_NAME": "Diffmogger Test",
            "GIT_AUTHOR_EMAIL": "diffmogger-test@example.invalid",
            "GIT_COMMITTER_NAME": "Diffmogger Test",
            "GIT_COMMITTER_EMAIL": "diffmogger-test@example.invalid",
        }
        result = subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=False, env=env)
        assert result.returncode == 0, result.stderr or result.stdout
        return result.stdout.strip()

    git_run("init", "-q")
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    git_run("add", "README.md")
    git_run("commit", "-m", "chore: scaffold")
    base_commit = git_run("rev-parse", "HEAD")
    (tmp_path / ".agentic").mkdir()
    (tmp_path / ".agentic" / "project_intake.json").write_text(
        json.dumps({"automation_checkpoint_commits": False}) + "\n",
        encoding="utf-8",
    )

    (tmp_path / "src").mkdir()
    app = tmp_path / "src" / "app.py"
    app.write_text("print('demo')\n", encoding="utf-8")
    git_run("add", "-N", "src/app.py")
    patch_text = git_run("diff", "--binary", base_commit, "--", "src/app.py")
    git_run("reset", "-q")
    app.unlink()
    (tmp_path / "src").rmdir()

    queue_dir = tmp_path / "target" / "automation_queue" / "builder" / "disabled-run"
    queue_dir.mkdir(parents=True)
    (queue_dir / "changes.patch").write_text(patch_text + "\n", encoding="utf-8")
    (queue_dir / "manifest.json").write_text(
        json.dumps(
            {
                "role": "builder",
                "run_id": "disabled-run",
                "patch_id": "patch-disabled-commit",
                "base_commit": base_commit,
                "status": "queued",
                "patch_path": "target/automation_queue/builder/disabled-run/changes.patch",
                "changed_files": ["src/app.py"],
                "summary": "Commit subject: Add app shell",
                "created_at": "2026-05-26T00:00:00+00:00",
                "checkpoint_commit": None,
                "accepted_commit": None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    assert integrate(tmp_path, "integrator-disabled-run", dry_run=False) == 0

    manifest = json.loads((queue_dir / "manifest.json").read_text(encoding="utf-8"))
    assert git_run("rev-parse", "HEAD") == base_commit
    assert (tmp_path / "src" / "app.py").exists()
    assert manifest["status"] == "applied"
    assert manifest["accepted_commit"] is None
