from __future__ import annotations

from .common import *
from .verification import (
    VerificationResult,
    load_smoke_verification_commands,
    manifest_declared_verification_commands,
    manifest_is_baseline_repair,
    root_cause_line,
    run_verification,
    verification_reason_for_category,
)
from diffmogger.runtime.blocker_review import (
    adjudicate_baseline_blocker,
    baseline_review_allows_progress,
    baseline_review_requests_rerun,
)

def baseline_verification_path(target: Path) -> Path:
    return dpath(target, BASELINE_VERIFICATION_RELATIVE)

def verification_config_hash(target: Path) -> str:
    config = dpath(target, ".agentic/verification_commands.txt")
    if not config.exists() or not config.is_file() or config.is_symlink():
        return "missing"
    digest = file_sha256(config)
    return digest or "unreadable"

def verification_failure_signature(result: VerificationResult) -> str:
    if result.ok:
        return "passing"
    category = result.category or "other"
    reason = result.reason or verification_reason_for_category(category)
    root = result.root_cause or root_cause_line(result.detail)
    normalized = re.sub(r"\s+", " ", root).strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{reason}:{category}:{digest}"

def iter_project_files_named(target: Path, filename: str, *, limit: int = 40) -> list[Path]:
    matches: list[Path] = []
    for root, dirs, files in os.walk(target):
        root_path = Path(root)
        try:
            relative = root_path.relative_to(target)
        except ValueError:
            continue
        parts = set(relative.parts)
        dirs[:] = [
            item
            for item in dirs
            if item not in RUNTIME_STATE_DENY_PARTS
            and item not in {"dist", "build", ".next", ".turbo", "coverage"}
            and not item.startswith(".git")
        ]
        if parts.intersection(RUNTIME_STATE_DENY_PARTS):
            dirs[:] = []
            continue
        if filename in files:
            matches.append(root_path / filename)
            if len(matches) >= limit:
                break
    return matches

def read_small_text(path: Path, *, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""

def target_has_postgres_prisma_schema(target: Path) -> bool:
    for schema in iter_project_files_named(target, "schema.prisma"):
        text = read_small_text(schema).lower()
        if 'provider = "postgresql"' in text or "provider = 'postgresql'" in text:
            return True
    return False

def target_has_local_database_example(target: Path) -> bool:
    local_markers = ("127.0.0.1", "localhost", "@postgres:", "@db:", ":5432")
    for root, dirs, files in os.walk(target):
        root_path = Path(root)
        try:
            relative = root_path.relative_to(target)
        except ValueError:
            continue
        dirs[:] = [
            item
            for item in dirs
            if item not in RUNTIME_STATE_DENY_PARTS
            and item not in {"dist", "build", ".next", ".turbo", "coverage"}
            and not item.startswith(".git")
        ]
        if set(relative.parts).intersection(RUNTIME_STATE_DENY_PARTS):
            dirs[:] = []
            continue
        for name in files:
            lowered = name.lower()
            if not (lowered.endswith(".example") or lowered.endswith(".sample") or lowered.endswith(".template")):
                continue
            if ".env" not in lowered and "env" not in lowered:
                continue
            text = read_small_text(root_path / name).lower()
            if "database_url" in text and any(marker in text for marker in local_markers):
                return True
    return False

def verification_mentions_database_url(result: VerificationResult) -> bool:
    text = "\n".join([result.root_cause or "", result.detail or "", *[str(item) for item in result.checks_run]]).lower()
    return any(marker in text for marker in ("database_url", "postgres", "postgresql", "prisma", "localhost:5432", "127.0.0.1:5432"))

def result_is_repairable_local_service(target: Path | None, result: VerificationResult) -> bool:
    if target is None or result.ok:
        return False
    if result.category not in REPAIRABLE_LOCAL_SERVICE_CATEGORIES:
        return False
    if not verification_mentions_database_url(result):
        return False
    if result.category == "missing_local_database":
        return target_has_postgres_prisma_schema(target)
    return target_has_postgres_prisma_schema(target) and target_has_local_database_example(target)

def baseline_status_for_result(result: VerificationResult, target: Path | None = None) -> str:
    if result.ok:
        return "passing"
    if result.category == "missing_verification_config":
        return "missing_config"
    if result_is_repairable_local_service(target, result):
        return "repairable_local_service"
    if result.reason == "verification_environment_failure" or result.category in ENVIRONMENT_FAILURE_CATEGORIES:
        return "blocked_environment"
    if result.reason == "verification_failure":
        return "failing_source"
    return "unknown"

def baseline_next_action(status: str, result: VerificationResult) -> str:
    if status == "passing":
        return "Full-suite baseline is passing; normal full-suite integration may proceed."
    if status == "missing_config":
        return "Create .agentic/verification_commands.txt with explicit full-suite commands before hardener/finalization gates."
    if status == "repairable_local_service":
        return (
            "Route a baseline repair patch to create or wire a safe local service harness "
            "for the failing verification command, then rerun the full suite."
        )
    if status == "blocked_environment":
        return "Safe local repair was not available or did not clear the environment issue; create setup, harness, mock, fixture, or deferred validation work before requiring full-suite integration."
    if status == "failing_source":
        return "Route a baseline repair patch through planner/builder/hardener with verification_scope baseline_repair; use designer only for UI design baseline issues."
    return result.root_cause or "Inspect baseline verification output before running full-suite-required integration."

def sanitize_baseline_payload(value: Any, target: Path) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_baseline_payload(item, target) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_baseline_payload(item, target) for item in value]
    if isinstance(value, str):
        return progress_inline(value, target, limit=500)
    return value

def baseline_record_from_result(
    target: Path,
    result: VerificationResult,
    *,
    head_value: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    now = utc_now().isoformat(timespec="seconds")
    signature = verification_failure_signature(result)
    status = baseline_status_for_result(result, target)
    previous_signature = str(previous.get("failure_signature") or "")
    first_seen = str(previous.get("first_seen_at") or now) if previous_signature == signature else now
    root_cause = result.root_cause or root_cause_line(result.detail)
    repair_attempted = any("repair" in str(item).lower() for item in result.checks_run) or "repair" in result.detail.lower()
    review_input = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "head": head_value,
        "verification_config_hash": verification_config_hash(target),
        "status": status,
        "category": result.category or "",
        "root_cause": root_cause,
        "failure_signature": signature,
        "checks_run": result.checks_run,
        "detail": result.detail,
    }
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "head": head_value,
        "verification_config_hash": verification_config_hash(target),
        "status": status,
        "category": result.category or "",
        "root_cause": progress_inline(root_cause, target, limit=300),
        "failure_signature": signature,
        "checks_run": [progress_inline(str(item), target, limit=300) for item in result.checks_run],
        "detail": progress_inline(result.detail, target, limit=1200),
        "repair_attempted": repair_attempted,
        "next_action": baseline_next_action(status, result),
        "blocker_review": sanitize_baseline_payload(adjudicate_baseline_blocker(review_input), target),
        "first_seen_at": first_seen,
        "last_seen_at": now,
    }

def write_baseline_record(target: Path, record: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path = baseline_verification_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def read_baseline_record(target: Path) -> dict[str, Any]:
    return read_json(baseline_verification_path(target))

def baseline_record_is_current(target: Path, record: dict[str, Any], head_value: str) -> bool:
    return (
        bool(record)
        and int(record.get("schema_version") or 0) == BASELINE_SCHEMA_VERSION
        and str(record.get("head") or "") == head_value
        and str(record.get("verification_config_hash") or "") == verification_config_hash(target)
        and not baseline_review_requests_rerun(record)
    )

def run_baseline_verification(
    target: Path,
    *,
    head_value: str,
    dry_run: bool,
    force: bool = False,
) -> dict[str, Any]:
    previous = read_baseline_record(target)
    if not force and baseline_record_is_current(target, previous, head_value):
        return previous
    result = run_verification(target, None)
    record = baseline_record_from_result(target, result, head_value=head_value, previous=previous)
    write_baseline_record(target, record, dry_run=dry_run)
    return record

def baseline_record_blocks_full_suite(record: dict[str, Any] | None) -> bool:
    return bool(record) and str(record.get("status") or "unknown") != "passing" and not baseline_review_allows_progress(record)

def attach_baseline_fields(manifest: dict[str, Any], baseline: dict[str, Any] | None) -> None:
    if not baseline:
        return
    manifest["baseline_status"] = str(baseline.get("status") or "unknown")
    manifest["baseline_failure_signature"] = str(baseline.get("failure_signature") or "")

def baseline_blocker_detail(target: Path, baseline: dict[str, Any]) -> str:
    status = str(baseline.get("status") or "unknown")
    root_cause = str(baseline.get("root_cause") or "No baseline root cause recorded.")
    next_action = str(baseline.get("next_action") or "Repair the baseline before retrying full-suite-required work.")
    return scrub_local_references(
        f"Baseline full-suite verification is {status}: {root_cause} Next action: {next_action}",
        target,
    )

def baseline_repair_has_focused_evidence(target: Path, manifest: dict[str, Any], verification: VerificationResult) -> bool:
    declared = manifest_declared_verification_commands([manifest])
    smoke = load_smoke_verification_commands(target, [manifest])
    if not declared and not smoke:
        return False
    detail = verification.detail
    return all(command in detail or command in verification.checks_run for command in [*declared, *smoke])

def baseline_repair_accepts_failure(
    target: Path,
    manifest: dict[str, Any],
    baseline: dict[str, Any] | None,
    verification: VerificationResult,
) -> bool:
    if not manifest_is_baseline_repair(manifest) or verification.ok:
        return verification.ok
    if not baseline_record_blocks_full_suite(baseline):
        return False
    old_signature = str((baseline or {}).get("failure_signature") or "")
    new_signature = verification_failure_signature(verification)
    manifest["baseline_status"] = baseline_status_for_result(verification, target)
    manifest["baseline_failure_signature"] = new_signature
    if new_signature and new_signature != old_signature:
        manifest["baseline_repair_result"] = "accepted_changed_failure_signature"
        return True
    if str((baseline or {}).get("status") or "") in {"blocked_environment", "repairable_local_service"} and (
        baseline_repair_has_focused_evidence(target, manifest, verification)
    ):
        manifest["baseline_repair_result"] = "accepted_with_focused_evidence"
        return True
    return False
