"""Worker helpers for Temporal-backed Diffmogger runs."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.runtime import LoggingConfig, Runtime, TelemetryConfig, TelemetryFilter
from temporalio.service import RetryConfig
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from diffmogger.contracts import SchedulerCycleRequest
from diffmogger.orchestration.activities import ACTIVITIES
from diffmogger.orchestration.workflows import CampaignWorkflow, WORKFLOWS


DEFAULT_TASK_QUEUE = "diffmogger-local"


async def run_worker_until_stopped(
    *,
    address: str = "localhost:7233",
    namespace: str = "default",
    task_queue: str = DEFAULT_TASK_QUEUE,
    stop_event: asyncio.Event | None = None,
) -> None:
    client = await Client.connect(address, namespace=namespace)
    async with Worker(client, task_queue=task_queue, workflows=WORKFLOWS, activities=ACTIVITIES):
        if stop_event is None:
            await asyncio.Event().wait()
        await stop_event.wait()


async def run_campaign_cycle_with_client(
    client: Client,
    *,
    target: Path,
    run_id: str,
    task_queue: str = DEFAULT_TASK_QUEUE,
    max_fanout: int = 3,
) -> dict[str, Any]:
    payload = SchedulerCycleRequest(
        target_path=str(target.expanduser().resolve()),
        run_id=run_id,
        max_fanout=max_fanout,
    ).model_dump(mode="json")
    return await client.execute_workflow(
        CampaignWorkflow.run,
        payload,
        id=f"diffmogger-campaign-{run_id}",
        task_queue=task_queue,
    )


async def run_local_temporal_scheduler_cycle(
    *,
    target: Path,
    run_id: str,
    task_queue: str = DEFAULT_TASK_QUEUE,
    max_fanout: int = 3,
    download_dest_dir: str | None = None,
) -> dict[str, Any]:
    runtime = Runtime(
        telemetry=TelemetryConfig(
            logging=LoggingConfig(filter=TelemetryFilter(core_level="ERROR", other_level="ERROR"))
        )
    )
    async with await WorkflowEnvironment.start_local(
        download_dest_dir=download_dest_dir,
        retry_config=RetryConfig(max_elapsed_time_millis=30000, max_retries=60),
        dev_server_log_level="error",
        runtime=runtime,
    ) as env:
        async with Worker(env.client, task_queue=task_queue, workflows=WORKFLOWS, activities=ACTIVITIES):
            return await run_campaign_cycle_with_client(
                env.client,
                target=target,
                run_id=run_id,
                task_queue=task_queue,
                max_fanout=max_fanout,
            )


def run_local_temporal_scheduler_cycle_sync(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(run_local_temporal_scheduler_cycle(**kwargs))
