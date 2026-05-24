"""Temporal workflows for Diffmogger campaign execution."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


ACTIVITY_TIMEOUT = timedelta(minutes=5)
ACTIVITY_RETRY = RetryPolicy(maximum_attempts=3)


async def _activity(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await workflow.execute_activity(
        name,
        payload,
        start_to_close_timeout=ACTIVITY_TIMEOUT,
        heartbeat_timeout=timedelta(minutes=1),
        retry_policy=ACTIVITY_RETRY,
    )


@workflow.defn
class SchedulerCycleWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await _activity("run_scheduler_cycle", payload)


@workflow.defn
class RoleWorkWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await _activity("execute_role_work", payload)


@workflow.defn
class ValidationGroupWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await _activity("run_validation_group", payload)


@workflow.defn
class IntegrationWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await _activity("integrate_ready_work", payload)


@workflow.defn
class RepairUnblockerWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await _activity("create_repair_or_unblocker_work", payload)


@workflow.defn
class CampaignWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        cycle = await _activity("run_scheduler_cycle", payload)
        selected = cycle.get("decision", {}).get("selected", {}) if isinstance(cycle.get("decision"), dict) else {}
        decision = cycle.get("decision", {}) if isinstance(cycle.get("decision"), dict) else {}
        group = decision.get("execution_group", {}) if isinstance(decision.get("execution_group"), dict) else {}
        validation_group = decision.get("validation_group", {}) if isinstance(decision.get("validation_group"), dict) else {}
        action_kind = selected.get("action_kind")
        follow_up: dict[str, Any] = {}
        follow_payload = {
            **payload,
            "group_id": group.get("group_id", ""),
            "paths": selected.get("paths", []),
            "validation_group_id": validation_group.get("validation_group_id", ""),
        }
        if action_kind in {"launch_work", "launch_scope_work"}:
            node_ids = selected.get("node_ids") if isinstance(selected.get("node_ids"), list) else []
            if not node_ids:
                node_ids = [""]
            worker_results = await asyncio.gather(
                *[
                    _activity("execute_role_work", {**follow_payload, "node_id": node_id})
                    for node_id in node_ids
                ]
            )
            validation_result = await _activity("run_validation_group", follow_payload)
            follow_up = {"workers": worker_results, "validation": validation_result}
            if action_kind == "launch_work":
                follow_up["integration"] = await _activity("integrate_ready_work", follow_payload)
        elif action_kind in {"create_repair_work", "create_setup_work"}:
            follow_up = await _activity(
                "create_repair_or_unblocker_work",
                {**follow_payload, "repair_work": decision.get("repair_work", [])},
            )
        elif action_kind == "integrate":
            follow_up = await _activity("integrate_ready_work", follow_payload)
        elif action_kind == "run_validation":
            follow_up = await _activity("run_validation_group", follow_payload)
        elif action_kind == "idle_complete":
            follow_up = {"ok": True, "activity": "idle_complete", "status": "idle"}
        await _activity(
            "record_follow_up_completion",
            {
                "target_path": payload.get("target_path") or payload.get("target"),
                "cycle": cycle,
                "follow_up": follow_up,
            },
        )
        return {"ok": True, "cycle": cycle, "follow_up": follow_up}


WORKFLOWS = [
    CampaignWorkflow,
    SchedulerCycleWorkflow,
    RoleWorkWorkflow,
    ValidationGroupWorkflow,
    IntegrationWorkflow,
    RepairUnblockerWorkflow,
]
