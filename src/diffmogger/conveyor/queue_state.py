from __future__ import annotations

from .state import *
from diffmogger.runtime.paths import load_manifest

def unhandled_human_inbox_count(target: Path) -> int:
    text = read_text(dpath(target, "docs/HUMAN_INBOX.md"))
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return len(re.findall(r"^\s*-\s*status:\s*unhandled\s*$", text, re.MULTILINE | re.IGNORECASE))

def target_has_multi_role(target: Path) -> bool:
    if not script_path(target, "scripts/run_role_automation.sh").exists():
        return False
    return all(dpath(target, f".agentic/roles/{role}.md").exists() for role in ROLES)


def target_role_profile(target: Path) -> str:
    manifest = load_manifest(target)
    features = manifest.get("features") if isinstance(manifest.get("features"), dict) else {}
    profile = str(features.get("automation_role_profile") or "").strip()
    if profile in {"single_lane", "planner_builder_hardener_integrator"}:
        return profile
    if "multi_role" in features:
        return "planner_builder_hardener_integrator" if features.get("multi_role") else "single_lane"

    for rel in [".agentic/project_intake.json", ".agentic/dashboard_state.json"]:
        data = read_json(dpath(target, rel))
        profile = str(data.get("automation_role_profile") or "").strip()
        if profile == "single_lane":
            return "single_lane"
        if profile == "planner_builder_hardener_integrator":
            return "planner_builder_hardener_integrator" if data.get("multi_role_automations_allowed", True) else "single_lane"
        if "multi_role_automations_allowed" in data:
            return "planner_builder_hardener_integrator" if data.get("multi_role_automations_allowed") else "single_lane"

    for rel in [".agentic/automation_prompt.md", "docs/CODEX_AUTOMATION_TASKS.md"]:
        text = read_text(dpath(target, rel))
        if "Role profile: `single_lane`" in text or "Multi-role automations allowed: false" in text:
            return "single_lane"
        if "Role profile: `planner_builder_hardener_integrator`" in text or "Multi-role automations allowed: true" in text:
            return "planner_builder_hardener_integrator"
    return ""

def queued_manifests(target: Path) -> list[Path]:
    queue_root = runtime_path(target, "target/automation_queue")
    manifests: list[Path] = []
    for path in sorted(queue_root.glob("*/*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "queued":
            manifests.append(path)
    return manifests

def role_manifest_records(target: Path, role: str, statuses: set[str] | None = None) -> list[tuple[Path, dict[str, Any]]]:
    queue_root = runtime_path(target, "target/automation_queue") / role
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(queue_root.glob("*/manifest.json")):
        data = read_json(path)
        if str(data.get("role") or role) != role:
            continue
        status = str(data.get("status") or "")
        if statuses is not None and status not in statuses:
            continue
        records.append((path, data))
    return sorted(
        records,
        key=lambda item: (
            str(item[1].get("integrated_at") or item[1].get("created_at") or ""),
            str(item[1].get("run_id") or item[0].parent.name),
        ),
    )

def manifest_file_list(manifest: dict[str, Any]) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for key in ("changed_files", "runtime_state_changed_files"):
        for item in manifest.get(key) or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                files.append(text)
    return files

def manifest_summary_line(manifest: dict[str, Any]) -> str:
    for raw in str(manifest.get("summary") or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip().lstrip("-*#> `")
        if line and not line.lower().startswith(("commit type:", "commit scope:", "commit subject:")):
            return line[:160]
    return ""

def format_file_list(files: list[str], limit: int = 4) -> str:
    if not files:
        return "unrecorded files"
    suffix = "" if len(files) <= limit else f", +{len(files) - limit} more"
    return ", ".join(files[:limit]) + suffix

def latest_applied_role_manifest_info(target: Path, role: str) -> dict[str, Any] | None:
    records = role_manifest_records(target, role, {"applied"})
    if not records:
        return None
    path, manifest = records[-1]
    return {
        "path": str(path),
        "run_id": str(manifest.get("run_id") or path.parent.name),
        "files": manifest_file_list(manifest),
        "summary": manifest_summary_line(manifest),
    }

def normalized_deferral_signature(manifest: dict[str, Any]) -> str:
    reason = str(manifest.get("deferral_reason") or "other")
    category = str(manifest.get("deferral_category") or "").strip().lower()
    if category:
        return f"{reason}:{category}"
    detail = re.sub(r"\s+", " ", str(manifest.get("deferral_detail") or "")).strip()
    lowered = detail.lower()
    if TYPESCRIPT_COMPILER_ERROR_RE.search(detail):
        detail_class = "typescript_compiler_error"
    elif "database_url" in lowered or re.search(r"\b[A-Z][A-Z0-9_]{2,}\b.*(?:not set|missing|required)", detail):
        detail_class = "missing_env_var"
    elif "no module named pytest" in lowered or "pytest: command not found" in lowered:
        detail_class = "missing_pytest"
    elif re.search(r"(command not found|not found:|could not determine executable)", lowered):
        detail_class = "missing_package_executable"
    elif any(marker in lowered for marker in ("relation does not exist", "no such table", "schema drift", "migration", "p2021", "p2022", "p3005")):
        detail_class = "db_schema_drift"
    elif any(marker in lowered for marker in ("gemini", "openai", "anthropic", "provider", "mock")):
        detail_class = "provider_mock_failure"
    elif any(marker in lowered for marker in ("assertionerror", "expected", "received", "failed")):
        detail_class = "test_assertion_failure"
    elif reason == "conflict":
        detail_class = "apply_conflict"
    elif reason == "staleness":
        detail_class = "stale_patch"
    else:
        detail_class = detail[:120] if detail else "no_detail"
    return f"{reason}:{detail_class}"

def deferred_equivalence_key(manifest: dict[str, Any]) -> str:
    role = str(manifest.get("role") or "role").strip().lower()
    changed_files = sorted(str(item).strip() for item in manifest.get("changed_files") or [] if str(item).strip())
    signature = normalized_deferral_signature(manifest)
    return json.dumps([role, changed_files, signature], sort_keys=True)

def manifest_ticket_tokens(manifest: dict[str, Any]) -> list[str]:
    values: list[str] = [
        str(manifest.get("summary") or ""),
        str(manifest.get("deferral_detail") or ""),
        str(manifest.get("deferral_root_cause") or ""),
        "\n".join(manifest_file_list(manifest)),
    ]
    for key in ("ticket_ids", "tickets", "ticket_cluster"):
        value = manifest.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif isinstance(value, str):
            values.append(value)
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in TICKET_TOKEN_RE.findall(value):
            normalized = token.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            tokens.append(token)
    return tokens

def hardener_guardrail_group_keys(manifest: dict[str, Any]) -> list[tuple[str, str, str]]:
    signature = normalized_deferral_signature(manifest)
    tokens = sorted(token.upper() for token in manifest_ticket_tokens(manifest))
    files = sorted(manifest_file_list(manifest))
    keys: list[tuple[str, str, str]] = []
    if tokens:
        keys.append(("ticket", ", ".join(tokens), json.dumps(["ticket", tokens, signature], sort_keys=True)))
    if files:
        keys.append(("files", format_file_list(files), json.dumps(["files", files, signature], sort_keys=True)))
    if not keys:
        keys.append(("signature", signature, json.dumps(["signature", signature], sort_keys=True)))
    return keys

def repeated_hardener_guardrail_deferral_info(target: Path) -> dict[str, Any] | None:
    queue_root = runtime_path(target, "target/automation_queue/hardener")
    groups: dict[str, dict[str, Any]] = {}
    if not queue_root.exists():
        return None
    for path in sorted(queue_root.glob("*/manifest.json")):
        manifest = read_json(path)
        if manifest.get("status") != "deferred":
            continue
        if str(manifest.get("deferral_reason") or "") != "guardrail_violation":
            continue
        for match_type, match_value, key in hardener_guardrail_group_keys(manifest):
            group = groups.setdefault(
                key,
                {
                    "match_type": match_type,
                    "match_value": match_value,
                    "items": [],
                },
            )
            manifest = dict(manifest)
            manifest["_manifest_path"] = str(path)
            group["items"].append(manifest)
    repeated = [group for group in groups.values() if len({item.get("run_id") for item in group["items"]}) > 1]
    if not repeated:
        return None
    repeated.sort(key=lambda group: len(group["items"]), reverse=True)
    group = repeated[0]
    newest = sorted(group["items"], key=lambda item: str(item.get("created_at") or ""))[-1]
    files = manifest_file_list(newest)
    root_cause = re.sub(r"\s+", " ", str(newest.get("deferral_root_cause") or "")).strip()
    detail = re.sub(r"\s+", " ", str(newest.get("deferral_detail") or "")).strip()
    return {
        "count": len(group["items"]),
        "run_id": str(newest.get("run_id") or "unknown"),
        "signature": normalized_deferral_signature(newest),
        "match_type": str(group["match_type"]),
        "match_value": str(group["match_value"]),
        "files": format_file_list(files),
        "root_cause": root_cause[:240] if root_cause else "No root cause recorded.",
        "detail": detail[:240] if detail else "No deferral detail recorded.",
    }

def duplicate_builder_deferral_info(target: Path) -> dict[str, Any] | None:
    queue_root = runtime_path(target, "target/automation_queue/builder")
    groups: dict[str, list[dict[str, Any]]] = {}
    if not queue_root.exists():
        return None
    for path in sorted(queue_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "deferred":
            continue
        key = deferred_equivalence_key(manifest)
        manifest["_manifest_path"] = str(path)
        groups.setdefault(key, []).append(manifest)
    duplicates = [items for items in groups.values() if len(items) >= 2]
    if not duplicates:
        return None
    duplicates.sort(key=len, reverse=True)
    group = duplicates[0]
    newest = sorted(group, key=lambda item: str(item.get("created_at") or ""))[-1]
    files = [str(item) for item in newest.get("changed_files") or [] if str(item).strip()]
    return {
        "count": len(group),
        "run_id": str(newest.get("run_id") or "unknown"),
        "signature": normalized_deferral_signature(newest),
        "files": ", ".join(files[:4]) if files else "unrecorded files",
    }

def builder_triage_followup_info(target: Path) -> dict[str, Any] | None:
    queue_root = runtime_path(target, "target/automation_queue/builder")
    if not queue_root.exists():
        return None
    candidates: list[dict[str, Any]] = []
    for path in sorted(queue_root.glob("*/manifest.json")):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "deferred":
            continue
        triage_status = str(manifest.get("deferral_triage_status") or "")
        if triage_status in {
            "replace-from-current-HEAD",
            "retryable",
            "retryable-after-environment-repair",
            "retryable-after-baseline-repair",
            "needs-triage",
        }:
            candidates.append(manifest)
    if not candidates:
        return None
    latest = sorted(candidates, key=lambda item: str(item.get("deferral_triaged_at") or item.get("created_at") or ""))[-1]
    return {
        "run_id": str(latest.get("run_id") or "unknown"),
        "triage_status": str(latest.get("deferral_triage_status") or "needs-triage"),
        "next_action": str(latest.get("deferral_next_action") or "Planner should decide whether to replace or retry this work."),
    }

def queue_snapshot(target: Path) -> dict[str, Any]:
    queue_root = runtime_path(target, "target/automation_queue")
    counts = {"queued": 0, "deferred": 0, "applied": 0, "failed": 0, "skipped": 0, "superseded": 0}
    applied_by_role = {role: 0 for role in QUEUE_ROLES}
    deferred_by_role = {role: 0 for role in QUEUE_ROLES}
    queued_by_role = {role: 0 for role in QUEUE_ROLES}
    deferred_signatures: dict[str, int] = {}
    deferred_signatures_by_role: dict[str, dict[str, int]] = {role: {} for role in QUEUE_ROLES}
    for path in sorted(queue_root.glob("*/*/manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("role") or "") not in QUEUE_ROLES:
            continue
        status = str(data.get("status") or "unknown")
        if status in counts:
            counts[status] += 1
        role = str(data.get("role") or "")
        if status == "queued" and role in queued_by_role:
            queued_by_role[role] += 1
        if status == "applied":
            if role in applied_by_role:
                applied_by_role[role] += 1
        if status == "deferred":
            if role in deferred_by_role:
                deferred_by_role[role] += 1
            signature = normalized_deferral_signature(data)
            deferred_signatures[signature] = deferred_signatures.get(signature, 0) + 1
            if role in deferred_signatures_by_role:
                role_signatures = deferred_signatures_by_role[role]
                role_signatures[signature] = role_signatures.get(signature, 0) + 1
    signature_parts = sorted(deferred_signatures)
    signature_by_role = {
        role: "|".join(sorted(signatures)) if signatures else "none"
        for role, signatures in deferred_signatures_by_role.items()
    }
    return {
        **counts,
        "applied_by_role": applied_by_role,
        "deferred_by_role": deferred_by_role,
        "queued_by_role": queued_by_role,
        "deferred_signature": "|".join(signature_parts) if signature_parts else "none",
        "deferred_signature_counts": deferred_signatures,
        "deferred_signature_by_role": signature_by_role,
        "deferred_signature_counts_by_role": deferred_signatures_by_role,
    }
