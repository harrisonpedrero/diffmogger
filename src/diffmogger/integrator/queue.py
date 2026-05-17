from __future__ import annotations

from .common import *
from .git_safety import head

def manifest_path_for(target: Path, role: str, run_id: str) -> Path:
    return runtime_path(target, "target/automation_queue") / role / run_id / "manifest.json"

def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def write_manifest(path: Path, manifest: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def resolve_patch_path(target: Path, manifest: dict[str, Any]) -> Path:
    patch = Path(str(manifest.get("patch_path") or ""))
    if patch.is_absolute():
        return patch
    return target / patch

def resolve_runtime_state_actions_path(target: Path, manifest: dict[str, Any]) -> Path | None:
    raw = str(manifest.get("runtime_state_actions_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return target / path

def resolve_ticket_state_actions_path(target: Path, manifest: dict[str, Any]) -> Path | None:
    raw = str(manifest.get("ticket_state_actions_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        return path
    return target / path

def parse_created_at(manifest: dict[str, Any], fallback: float) -> float:
    raw = str(manifest.get("created_at") or "")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback

def _target_relative_manifest_path(target: Path, path: Path) -> str:
    try:
        return path.expanduser().resolve().relative_to(target.expanduser().resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()

def manifest_patch_id(target: Path, path: Path, manifest: dict[str, Any]) -> str:
    patch_id = str(manifest.get("patch_id") or "").strip()
    if patch_id:
        return patch_id
    run_id = str(manifest.get("run_id") or path.parent.name).strip()
    worker_id = str(manifest.get("worker_id") or "").strip()
    if worker_id:
        return f"worker-patch:{hashlib.sha256((worker_id + ':' + run_id).encode('utf-8')).hexdigest()[:20]}"
    rel = _target_relative_manifest_path(target, path)
    return f"role-patch:{hashlib.sha256(rel.encode('utf-8')).hexdigest()[:20]}"

def selected_patch_id_set(values: list[str] | None = None) -> set[str]:
    selected: set[str] = set()
    raw_values = list(values or [])
    env_value = os.environ.get("DIFFMOGGER_SELECTED_PATCH_IDS", "")
    if env_value:
        raw_values.extend(re.split(r"[,\s]+", env_value))
    for value in raw_values:
        text = str(value or "").strip()
        if text:
            selected.add(text)
    return selected

def load_queued_manifests(target: Path, *, patch_ids: list[str] | set[str] | None = None) -> list[tuple[Path, dict[str, Any]]]:
    queue_root = runtime_path(target, "target/automation_queue")
    selected = selected_patch_id_set([str(item) for item in patch_ids or []])
    items: list[tuple[Path, dict[str, Any]]] = []
    for role in QUEUE_ROLES:
        role_root = queue_root / role
        if not role_root.exists():
            continue
        for path in role_root.glob("*/manifest.json"):
            try:
                manifest = read_manifest(path)
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") == "queued":
                manifest_id = manifest_patch_id(target, path, manifest)
                if selected and manifest_id not in selected:
                    continue
                if not str(manifest.get("patch_id") or "").strip():
                    manifest = {**manifest, "patch_id": manifest_id}
                items.append((path, manifest))
    items.sort(key=lambda item: (parse_created_at(item[1], item[0].stat().st_mtime), str(item[0])))
    return items

def all_role_manifests(target: Path) -> list[tuple[Path, dict[str, Any]]]:
    queue_root = runtime_path(target, "target/automation_queue")
    items: list[tuple[Path, dict[str, Any]]] = []
    for role in ALL_ROLES:
        role_root = queue_root / role
        if not role_root.exists():
            continue
        for path in role_root.glob("*/manifest.json"):
            try:
                items.append((path, read_manifest(path)))
            except (OSError, json.JSONDecodeError):
                continue
    return items

def manifest_list(manifests: list[dict[str, Any]] | dict[str, Any] | None) -> list[dict[str, Any]]:
    if manifests is None:
        return []
    if isinstance(manifests, dict):
        return [manifests]
    return [item for item in manifests if isinstance(item, dict)]

def _normalize_mcp_servers(value: Any) -> list[str]:
    supported = ["context7", "playwright"]
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else re.split(r"[\n,]+", str(value))
    enabled: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        normalized = re.sub(r"^[-*]\s+", "", str(item).strip().lower()).replace("-", "_").replace(" ", "_")
        names: list[str] = []
        if "context7" in normalized or normalized in {"context_7", "context"}:
            names.append("context7")
        if "playwright" in normalized:
            names.append("playwright")
        if normalized in supported:
            names.append(normalized)
        for name in names:
            if name not in seen:
                seen.add(name)
                enabled.append(name)
    return [name for name in supported if name in seen] + [name for name in enabled if name not in supported]

def _integrator_mcp_manifest_fields(target: Path) -> dict[str, Any]:
    manifest = load_manifest(target)
    features = manifest.get("features") if isinstance(manifest.get("features"), dict) else {}
    if "optional_mcp_servers" in manifest:
        enabled = _normalize_mcp_servers(manifest.get("optional_mcp_servers"))
    elif "optional_mcp_servers" in features:
        enabled = _normalize_mcp_servers(features.get("optional_mcp_servers"))
    else:
        enabled = ["context7", "playwright"]
    requested = ["playwright"] if "playwright" in enabled else []
    skipped = []
    if "context7" not in enabled:
        skipped.append({"server": "context7", "reason": "disabled by optional_mcp_servers"})
    else:
        skipped.append({"server": "context7", "reason": "not relevant for integrator script role"})
    if "playwright" not in enabled:
        skipped.append({"server": "playwright", "reason": "disabled by optional_mcp_servers"})
    return {
        "mcp_supported_servers": ["context7", "playwright"],
        "mcp_enabled_servers": enabled,
        "mcp_requested_servers": requested,
        "mcp_mounted_servers": [],
        "mcp_skipped_servers": skipped,
        "mcp_required": {"context7": False, "playwright": False},
        "mcp_usage_outcome": {
            "context7": {"outcome": "skipped", "reason": "not relevant for integrator script role"},
            "playwright": (
                {"outcome": "skipped", "reason": "integrator script runs serialized local verification; browser validation must be recorded by checks or blocker"}
                if "playwright" in enabled
                else {"outcome": "disabled", "reason": "disabled by optional_mcp_servers"}
            ),
        },
        "mcp_usage_note": "",
    }

def create_integrator_manifest(
    target: Path,
    *,
    run_id: str,
    status: str,
    head_before: str | None,
    checkpoint_commit: str | None,
    summary: str,
    dry_run: bool,
) -> None:
    path = manifest_path_for(target, "integrator", run_id)
    manifest = {
        "role": "integrator",
        "run_id": run_id,
        "base_commit": head_before or "",
        "head_before_integration": head_before,
        "status": status,
        "deferral_reason": None if status == "applied" else "other",
        "deferral_detail": "" if status == "applied" else summary,
        "patch_path": "",
        "changed_files": [],
        "checks_run": [],
        "summary": summary,
        "created_at": utc_now().isoformat(timespec="seconds"),
        "integrated_at": utc_now().isoformat(timespec="seconds"),
        "checkpoint_commit": checkpoint_commit,
        "accepted_commit": head(target) if status == "applied" and not dry_run else None,
        **_integrator_mcp_manifest_fields(target),
    }
    write_manifest(path, manifest, dry_run=dry_run)
