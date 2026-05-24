"""Typed runtime contracts for Diffmogger's local control plane."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TargetRef(StrictModel):
    target_path: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)


class OwnershipLease(StrictModel):
    lease_id: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    run_id: str = ""
    group_id: str = ""
    node_id: str = ""
    paths: list[str] = Field(default_factory=list)
    mode: Literal["read", "write", "validate", "integrate"] = "write"
    status: Literal["active", "released", "expired"] = "active"
    acquired_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TicketRecord(StrictModel):
    ticket_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    status: Literal["ready", "running", "done", "deferred", "blocked", "waiting"] = "ready"
    depends_on: list[str] = Field(default_factory=list)
    ownership_paths: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class DagNode(StrictModel):
    node_id: str = Field(..., min_length=1)
    ticket_id: str = ""
    action_type: Literal[
        "schedule",
        "scope",
        "build",
        "review",
        "validate",
        "integrate",
        "repair",
        "setup",
        "mock",
        "fixture",
        "defer",
        "split",
        "reframe",
        "document",
    ] = "build"
    status: Literal["ready", "running", "done", "failed", "deferred", "waiting"] = "ready"
    owner_role: str = "builder"
    paths: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float = Field(0.75, ge=0, le=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utc_now)


class DagEdge(StrictModel):
    edge_id: str = Field(..., min_length=1)
    from_node_id: str = Field(..., min_length=1)
    to_node_id: str = Field(..., min_length=1)
    edge_type: Literal["depends_on", "repairs", "validates", "integrates", "blocks"] = "depends_on"
    payload: dict[str, Any] = Field(default_factory=dict)


class ValidationReceipt(StrictModel):
    receipt_id: str = Field(..., min_length=1)
    node_id: str = ""
    command: str = Field(..., min_length=1)
    status: Literal["passed", "failed", "skipped", "deferred"] = "passed"
    required: bool = True
    exit_code: int | None = None
    evidence_path: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=utc_now)


class NotificationPayload(StrictModel):
    message_id: str = Field(..., min_length=1)
    event_kind: Literal["progress", "message", "review", "completion"] = "progress"
    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    expects_reply: bool = False
    apprise_urls: list[str] = Field(default_factory=list)
    dry_run: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class NotificationDelivery(StrictModel):
    ok: bool
    sent: bool = False
    dry_run: bool = True
    status: str
    detail: str = ""
    message_id: str = ""


class SchedulerCandidate(StrictModel):
    candidate_id: str = Field(..., min_length=1)
    action_kind: Literal[
        "launch_work",
        "launch_scope_work",
        "run_validation",
        "integrate",
        "create_repair_work",
        "create_setup_work",
        "idle_complete",
    ]
    execution_mode: Literal["write", "read_only_scope", "validate", "integrate", "repair", "setup", "idle"] = "write"
    owner_role: str = "builder"
    node_ids: list[str] = Field(default_factory=list)
    ticket_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    scope_evidence: list[str] = Field(default_factory=list)
    code_fact_refs: list[str] = Field(default_factory=list)
    required_lease_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    fanout: int = Field(1, ge=0, le=32)
    confidence: float = Field(0.75, ge=0, le=1)
    telemetry: dict[str, Any] = Field(default_factory=dict)


class ExecutionGroup(StrictModel):
    group_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    action_kind: Literal["work_wave", "scope_wave", "validation_group", "integration_gate", "repair_unblocker", "idle"]
    status: Literal["planned", "running", "completed", "deferred", "failed", "cancelled"] = "planned"
    execution_mode: Literal["write", "read_only_scope", "validate", "integrate", "repair", "setup", "idle"] = "write"
    owner_role: str = "builder"
    candidate_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    ticket_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    max_fanout: int = Field(1, ge=0, le=32)
    validation_group_id: str = ""
    integration_decision_id: str = ""
    reason: str = ""
    telemetry: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ConflictTelemetry(StrictModel):
    conflict_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    group_id: str = ""
    left_candidate_id: str = ""
    right_candidate_id: str = ""
    left_node_id: str = ""
    right_node_id: str = ""
    conflict_type: Literal[
        "path_overlap",
        "symbol_overlap",
        "import_coupling",
        "lease_overlap",
        "ambiguous_scope",
        "low_confidence",
        "stale_code_facts",
        "parser_unavailable",
        "validation_gate",
    ]
    severity: Literal["info", "fanout_reduced", "serialized", "safety_boundary"] = "fanout_reduced"
    paths: list[str] = Field(default_factory=list)
    detail: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class ValidationGate(StrictModel):
    gate_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    group_id: str = ""
    node_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    required: bool = True
    status: Literal["pending", "passed", "failed", "skipped", "deferred"] = "pending"
    failure_policy: Literal["repair", "setup", "harness", "mock", "defer", "alternate_validation"] = "repair"
    receipt_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ValidationGroup(StrictModel):
    validation_group_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    group_id: str = ""
    status: Literal["planned", "running", "passed", "failed", "deferred"] = "planned"
    gates: list[ValidationGate] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkerOutput(StrictModel):
    output_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    group_id: str = ""
    node_id: str = ""
    worker_id: str = ""
    status: Literal["planned", "running", "completed", "failed", "deferred"] = "completed"
    changed_paths: list[str] = Field(default_factory=list)
    validation_receipt_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    patch_path: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=utc_now)


class IntegrationDecision(StrictModel):
    decision_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    group_id: str = ""
    status: Literal["queued", "apply_serially", "defer_overlap", "accepted", "rejected", "repair"] = "queued"
    reason: str = ""
    paths: list[str] = Field(default_factory=list)
    worker_output_ids: list[str] = Field(default_factory=list)
    validation_group_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RepairUnblockerWork(StrictModel):
    work_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    source_kind: Literal["validation", "parser", "lease", "ownership", "ticket", "worker", "integration", "scheduler"]
    source_id: str = ""
    action_type: Literal[
        "repair",
        "setup",
        "harness",
        "mock",
        "fixture",
        "defer",
        "split",
        "reframe",
        "review",
        "document",
        "alternate_validation",
        "index_code_facts",
    ] = "repair"
    status: Literal["planned", "running", "done", "deferred"] = "planned"
    title: str = Field(..., min_length=1)
    node_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    reason: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SchedulerTelemetry(StrictModel):
    telemetry_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    selected_group_id: str = ""
    candidate_count: int = Field(0, ge=0)
    selected_count: int = Field(0, ge=0)
    max_fanout: int = Field(1, ge=1, le=32)
    reduced_fanout_reasons: list[str] = Field(default_factory=list)
    parser_fallbacks: list[str] = Field(default_factory=list)
    stale_lease_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SchedulerRecord(StrictModel):
    decision_id: str = Field(..., min_length=1)
    target_path: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    selected: SchedulerCandidate
    candidates: list[SchedulerCandidate] = Field(default_factory=list)
    execution_group: ExecutionGroup | None = None
    validation_group: ValidationGroup | None = None
    integration_decision: IntegrationDecision | None = None
    repair_work: list[RepairUnblockerWork] = Field(default_factory=list)
    conflicts: list[ConflictTelemetry] = Field(default_factory=list)
    scheduler_telemetry: SchedulerTelemetry | None = None
    telemetry: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class SchedulerCycleRequest(StrictModel):
    target_path: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    max_fanout: int = Field(3, ge=1, le=32)
    dry_run: bool = False

    @field_validator("target_path")
    @classmethod
    def target_is_not_empty(cls, value: str) -> str:
        return value.strip()


class SchedulerCycleResult(StrictModel):
    ok: bool = True
    run_id: str
    decision: SchedulerRecord
    evidence: list[str] = Field(default_factory=list)


class CodeFact(StrictModel):
    fact_id: str = Field(..., min_length=1)
    file_path: str = Field(..., min_length=1)
    language: str = Field(..., min_length=1)
    kind: Literal["symbol", "import", "parser_unavailable"] = "symbol"
    name: str = ""
    line: int = Field(0, ge=0)
    column: int = Field(0, ge=0)
    target: str = ""
    source: Literal["tree_sitter", "fallback"] = "tree_sitter"
    payload: dict[str, Any] = Field(default_factory=dict)
    extracted_at: datetime = Field(default_factory=utc_now)


def json_ready(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
