#!/usr/bin/env python3
"""Run Diffmogger Temporal orchestration helpers."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from diffmogger.contracts import SchedulerCycleRequest, json_ready
from diffmogger.orchestration.activities import run_campaign_cycle, run_scheduler_cycle
from diffmogger.orchestration.worker import run_local_temporal_scheduler_cycle_sync


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy-cycle", help="Run the scheduler policy outside Temporal.")
    policy.add_argument("--target", required=True)
    policy.add_argument("--run-id", default="policy-smoke")
    policy.add_argument("--max-fanout", type=int, default=3)
    policy.add_argument("--execute", action="store_true", help="Also execute the selected local follow-up activity.")

    campaign = sub.add_parser("campaign-cycle", help="Run one scheduler cycle and execute the selected local follow-up activity.")
    campaign.add_argument("--target", required=True)
    campaign.add_argument("--run-id", default="campaign-smoke")
    campaign.add_argument("--max-fanout", type=int, default=3)

    local = sub.add_parser("temporal-cycle", help="Run one scheduler cycle through a local Temporal dev server.")
    local.add_argument("--target", required=True)
    local.add_argument("--run-id", default="temporal-smoke")
    local.add_argument("--max-fanout", type=int, default=3)
    local.add_argument("--download-dest-dir", default="")

    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    if args.command == "policy-cycle":
        payload = SchedulerCycleRequest(
            target_path=str(target),
            run_id=args.run_id,
            max_fanout=args.max_fanout,
            dry_run=not args.execute,
        ).model_dump(mode="json")
        result = asyncio.run(run_campaign_cycle(payload) if args.execute else run_scheduler_cycle(payload))
    elif args.command == "campaign-cycle":
        payload = SchedulerCycleRequest(
            target_path=str(target),
            run_id=args.run_id,
            max_fanout=args.max_fanout,
            dry_run=False,
        ).model_dump(mode="json")
        result = asyncio.run(run_campaign_cycle(payload))
    else:
        result = run_local_temporal_scheduler_cycle_sync(
            target=target,
            run_id=args.run_id,
            max_fanout=args.max_fanout,
            download_dest_dir=args.download_dest_dir or None,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
