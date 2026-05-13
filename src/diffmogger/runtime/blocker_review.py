from __future__ import annotations

import re
from typing import Any, Mapping


BLOCKER_REVIEW_SCHEMA_VERSION = 1

PM_DIAGNOSTIC_CODES = {
    "EBADENGINE",
    "ENOTSUP",
    "ERESOLVE",
    "ETARGET",
    "ELOCKVERIFY",
    "EINTEGRITY",
    "E404",
}

COMMON_ENV_NAMES = {"DATABASE_URL", "NODE_ENV", "PORT", "HOST", "CI"}
NONFATAL_WARNING_MARKERS = (
    " warn ",
    " warning",
    "deprecated",
    "deprecation",
    "unsupported engine",
)
SOURCE_FAILURE_MARKERS = (
    "assertionerror",
    "expected",
    "received",
    "error ts",
    "traceback",
    "exception",
    "failures:",
    "test failed",
    "tests failed",
)

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ENV_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9_]{1,}\b")


def clean_line(value: Any, *, limit: int = 280) -> str:
    text = ANSI_RE.sub("", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def blocker_review_id(kind: str, source_id: str) -> str:
    safe_kind = re.sub(r"[^A-Za-z0-9_.:-]+", "-", kind).strip("-") or "blocker"
    safe_source = re.sub(r"[^A-Za-z0-9_.:-]+", "-", source_id).strip("-") or "unknown"
    return f"blocker:{safe_kind}:{safe_source}"[:180]


def extract_env_name(text: str) -> str:
    match = re.search(r"environment variable [`'\"]?([A-Z][A-Z0-9_]{1,})[`'\"]?", text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    match = re.search(r"`([A-Z][A-Z0-9_]{1,})`", text)
    if match:
        return match.group(1)
    for match in ENV_NAME_RE.finditer(text):
        name = match.group(0)
        if "_" in name or name in COMMON_ENV_NAMES or name in PM_DIAGNOSTIC_CODES:
            return name
    return ""


def package_manager_diagnostic_line(line: str, code: str = "") -> bool:
    stripped = clean_line(line, limit=500)
    lowered = stripped.lower()
    if not stripped:
        return False
    if "unsupported engine" in lowered:
        return True
    if re.match(r"^(?:npm|pnpm)\s+(?:warn|warning|err!?|error)\s+e[a-z0-9_]+\b", lowered):
        return True
    if re.match(r"^yarn\s+(?:warning|error)\s+e[a-z0-9_]+\b", lowered):
        return True
    if code and re.search(rf"\b{re.escape(code)}\b", stripped):
        return bool(re.match(r"^(?:npm|pnpm|yarn)\b", lowered))
    return False


def package_manager_diagnostic_evidence(text: str, code: str) -> list[str]:
    if not code:
        return []
    evidence: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = clean_line(raw_line)
        if line and package_manager_diagnostic_line(line, code):
            evidence.append(line)
        if len(evidence) >= 4:
            break
    return evidence


def warning_evidence(text: str) -> list[str]:
    evidence: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = clean_line(raw_line)
        lowered = f" {line.lower()}"
        if line and (
            package_manager_diagnostic_line(line)
            or any(marker in lowered for marker in NONFATAL_WARNING_MARKERS)
        ):
            evidence.append(line)
        if len(evidence) >= 4:
            break
    return evidence


def source_failure_evidence(text: str) -> list[str]:
    evidence: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = clean_line(raw_line)
        lowered = line.lower()
        if not line or package_manager_diagnostic_line(line):
            continue
        if any(marker in lowered for marker in SOURCE_FAILURE_MARKERS):
            evidence.append(line)
        if len(evidence) >= 4:
            break
    return evidence


def command_exit_codes(detail: str) -> list[int]:
    codes: list[int] = []
    for match in re.finditer(r"(?m)^exit=(-?\d+)\b", str(detail or "")):
        try:
            codes.append(int(match.group(1)))
        except ValueError:
            continue
    return codes


def line_has_explicit_env_context(line: str, name: str) -> bool:
    lowered = line.lower()
    if not name or name not in line:
        return False
    return any(
        marker in lowered
        for marker in (
            "environment variable",
            "env var",
            "env variable",
            "process.env",
            "import.meta.env",
            "not set",
            "must be set",
            "missing",
            "undefined",
        )
    )


def env_context_evidence(text: str, name: str) -> list[str]:
    evidence: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = clean_line(raw_line)
        if line_has_explicit_env_context(line, name):
            evidence.append(line)
        if len(evidence) >= 4:
            break
    return evidence


def review_payload(
    *,
    source_kind: str,
    source_id: str,
    verdict: str,
    is_blocker: bool,
    summary: str,
    evidence: list[str],
    recommended_action: str,
    confidence: float,
    blocker_status: str,
    rerun_recommended: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": BLOCKER_REVIEW_SCHEMA_VERSION,
        "source_kind": source_kind,
        "source_id": source_id,
        "blocker_id": blocker_review_id(source_kind, source_id),
        "question": "Is this actually a blocker?",
        "verdict": verdict,
        "is_blocker": bool(is_blocker),
        "blocker_status": blocker_status,
        "summary": summary,
        "evidence": [clean_line(item) for item in evidence if clean_line(item)],
        "recommended_action": recommended_action,
        "confidence": float(confidence),
        "rerun_recommended": bool(rerun_recommended),
        "reasoning_guardrail": (
            "Use needs_human only when local evidence is insufficient and automatic continuation "
            "could hide a real unsafe blocker; nonfatal warnings and all-zero exits should not default to human review."
        ),
    }


def adjudicate_baseline_blocker(record: Mapping[str, Any] | None) -> dict[str, Any]:
    """Review a baseline ledger entry before promoting it to a live blocker."""

    baseline = dict(record or {})
    source_id = str(baseline.get("failure_signature") or baseline.get("head") or "baseline")
    status = str(baseline.get("status") or "").strip().lower()
    category = str(baseline.get("category") or "").strip().lower()
    root = clean_line(baseline.get("root_cause"), limit=500)
    detail = str(baseline.get("detail") or "")
    checks = baseline.get("checks_run") if isinstance(baseline.get("checks_run"), list) else []
    haystack = "\n".join([root, detail, *[str(item) for item in checks]])

    if not baseline or status in {"", "passing", "pass", "passed"}:
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="not_applicable",
            is_blocker=False,
            blocker_status="resolved",
            summary="No active baseline blocker is recorded.",
            evidence=[],
            recommended_action="No blocker action is needed.",
            confidence=1.0,
        )

    exits = command_exit_codes(detail)
    if status in {"blocked_environment", "blocked"} and exits and all(code == 0 for code in exits):
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="false_positive",
            is_blocker=False,
            blocker_status="superseded",
            summary="Baseline was marked blocked even though recorded command exits were successful.",
            evidence=[f"Recorded command exit codes: {', '.join(str(code) for code in exits)}"],
            recommended_action="Supersede this blocker and rerun baseline verification to refresh the receipt.",
            confidence=0.9,
            rerun_recommended=True,
        )

    name = extract_env_name(root)
    pm_evidence = package_manager_diagnostic_evidence(haystack, name)
    if status == "blocked_environment" and category == "missing_env_var" and pm_evidence:
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="false_positive",
            is_blocker=False,
            blocker_status="superseded",
            summary=f"`{name}` looks like a package-manager diagnostic code, not a required environment variable.",
            evidence=pm_evidence,
            recommended_action="Supersede this blocker and rerun baseline verification with current classification rules.",
            confidence=0.95,
            rerun_recommended=True,
        )

    if status == "blocked_environment" and category == "missing_env_var" and name:
        explicit_evidence = env_context_evidence(haystack, name)
        if explicit_evidence or "_" in name or name in COMMON_ENV_NAMES:
            return review_payload(
                source_kind="baseline_verification",
                source_id=source_id,
                verdict="confirmed_blocker",
                is_blocker=True,
                blocker_status="open",
                summary=f"Baseline requires environment value `{name}` before full-suite verification can pass.",
                evidence=explicit_evidence or [root],
                recommended_action="Keep the environment blocker open and request/provide only the missing variable name, never its value.",
                confidence=0.85,
            )
        warning_lines = warning_evidence(haystack)
        if warning_lines:
            return review_payload(
                source_kind="baseline_verification",
                source_id=source_id,
                verdict="downgrade_to_warning",
                is_blocker=False,
                blocker_status="superseded",
                summary=f"Baseline mentions `{name}`, but the evidence is non-fatal warning output rather than a missing environment value.",
                evidence=warning_lines,
                recommended_action="Supersede this environment blocker and rerun baseline verification to record a fresh warning or pass receipt.",
                confidence=0.78,
                rerun_recommended=True,
            )
        source_lines = source_failure_evidence(haystack)
        if source_lines:
            return review_payload(
                source_kind="baseline_verification",
                source_id=source_id,
                verdict="source_failure_not_environment",
                is_blocker=False,
                blocker_status="superseded",
                summary=f"Baseline labels `{name}` as an environment variable, but the evidence points to an ordinary source/test failure.",
                evidence=source_lines,
                recommended_action="Supersede this environment blocker and rerun baseline verification so normal repair routing can classify the failure.",
                confidence=0.74,
                rerun_recommended=True,
            )
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="needs_human",
            is_blocker=True,
            blocker_status="open",
            summary=f"Baseline reports `{name}` as missing, but evidence does not clearly prove it is an environment variable.",
            evidence=[root],
            recommended_action="Ask an agent to inspect the failing command output before treating this as an environment blocker.",
            confidence=0.55,
        )

    if status == "blocked_environment":
        warning_lines = warning_evidence(haystack)
        if warning_lines and (not exits or all(code == 0 for code in exits)):
            return review_payload(
                source_kind="baseline_verification",
                source_id=source_id,
                verdict="downgrade_to_warning",
                is_blocker=False,
                blocker_status="superseded",
                summary="Baseline was marked environment-blocked, but the available evidence is warning-only output.",
                evidence=warning_lines,
                recommended_action="Supersede this blocker and rerun baseline verification to refresh the receipt.",
                confidence=0.82,
                rerun_recommended=True,
            )
        source_lines = source_failure_evidence(haystack)
        if source_lines:
            return review_payload(
                source_kind="baseline_verification",
                source_id=source_id,
                verdict="source_failure_not_environment",
                is_blocker=False,
                blocker_status="superseded",
                summary="Baseline was marked environment-blocked, but the evidence matches a source or test failure.",
                evidence=source_lines,
                recommended_action="Supersede this blocker and rerun baseline verification so normal repair routing can classify the failure.",
                confidence=0.72,
                rerun_recommended=True,
            )
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="confirmed_blocker",
            is_blocker=True,
            blocker_status="open",
            summary=f"Baseline verification is blocked by the local environment: {root or 'No root cause recorded.'}",
            evidence=[root],
            recommended_action="Keep the blocker open unless a rerun or agent review proves the environment classification is stale.",
            confidence=0.7,
        )

    if status in {"failing_source", "missing_config", "repairable_local_service"}:
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="confirmed_blocker",
            is_blocker=True,
            blocker_status="open",
            summary=f"Baseline verification needs project repair: {root or status}",
            evidence=[root or status],
            recommended_action=str(baseline.get("next_action") or "Route a baseline repair patch with verification evidence."),
            confidence=0.8,
        )

    warning_lines = warning_evidence(haystack)
    if warning_lines and (not exits or all(code == 0 for code in exits)):
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="downgrade_to_warning",
            is_blocker=False,
            blocker_status="superseded",
            summary=f"Baseline status `{status}` has warning-only evidence, not a confirmed blocker.",
            evidence=warning_lines,
            recommended_action="Rerun baseline verification to refresh the receipt before escalating.",
            confidence=0.76,
            rerun_recommended=True,
        )
    source_lines = source_failure_evidence(haystack)
    if source_lines:
        return review_payload(
            source_kind="baseline_verification",
            source_id=source_id,
            verdict="source_failure_not_environment",
            is_blocker=False,
            blocker_status="superseded",
            summary=f"Baseline status `{status}` should be reclassified through normal source-failure routing.",
            evidence=source_lines,
            recommended_action="Rerun baseline verification with current classification rules.",
            confidence=0.68,
            rerun_recommended=True,
        )

    return review_payload(
        source_kind="baseline_verification",
        source_id=source_id,
        verdict="needs_human",
        is_blocker=True,
        blocker_status="open",
        summary=f"Baseline blocker status `{status}` needs review.",
        evidence=[root or status],
        recommended_action="Ask an agent to adjudicate this blocker before stopping automation.",
        confidence=0.5,
    )


def baseline_review_requests_rerun(record: Mapping[str, Any] | None) -> bool:
    return bool(adjudicate_baseline_blocker(record).get("rerun_recommended"))


def baseline_review_allows_progress(record: Mapping[str, Any] | None) -> bool:
    review = adjudicate_baseline_blocker(record)
    return not bool(review.get("is_blocker"))
