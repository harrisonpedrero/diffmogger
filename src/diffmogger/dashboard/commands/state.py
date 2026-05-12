from __future__ import annotations

from ..errors import *
from ..target import *

from diffmogger.runtime.state_store import state_snapshot, validate_state_database, write_canonical_state_brief


def command_state_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return {
        "target": target_metadata(target),
        "state": state_snapshot(target),
    }


def command_state_validate(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    return {
        "target": target_metadata(target),
        "validation": validate_state_database(target),
    }


def command_state_brief(args: argparse.Namespace) -> dict[str, Any]:
    target = resolve_target(args.target)
    result = write_canonical_state_brief(target)
    return {
        "target": target_metadata(target),
        "brief": {
            "path": result["path"],
            "relative_path": result["relative_path"],
            "payload_sha256": result["payload_sha256"],
            "markdown": result["markdown"],
        },
    }
