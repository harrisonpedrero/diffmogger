from __future__ import annotations

from .common import *

def baseline_verification_snapshot(target: Path) -> dict[str, Any]:
    record = read_json(runtime_path(target, "target/baseline_verification.json"))
    if not record:
        return {
            "status": "not_recorded",
            "summary": "No clean-HEAD baseline verification ledger is recorded yet.",
            "next_action": "Run the integrator lane once to record baseline verification.",
        }
    status = clean_text(record.get("status") or "unknown", limit=80)
    root = clean_text(record.get("root_cause") or "No root cause recorded.", limit=300)
    next_action = clean_text(record.get("next_action") or "Inspect baseline verification before full-suite gates.", limit=300)
    return {
        "status": status,
        "category": clean_text(record.get("category") or "", limit=80),
        "root_cause": root,
        "failure_signature": clean_text(record.get("failure_signature") or "", limit=140),
        "head": clean_text(record.get("head") or "", limit=80),
        "last_seen_at": clean_text(record.get("last_seen_at") or "", limit=80),
        "repair_attempted": bool(record.get("repair_attempted")),
        "next_action": next_action,
        "summary": f"{status}: {root}",
    }

def classify_path(path: str) -> str:
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("templates/"):
        return "templates"
    if path.startswith("services/"):
        return "services"
    if path.startswith("scripts/"):
        return "scripts"
    if path.startswith("docs/") or path.endswith(".md"):
        return "docs"
    return "other"

def describe_path(path: str) -> str:
    if path.endswith("run_observatory.py"):
        return "observatory/review logic"
    if path.endswith("run_temporal_worker.sh") or path.endswith("orchestration_cli.py"):
        return "Temporal orchestration runner"
    if path.endswith("run_role_automation.sh"):
        return "role runner"
    if path.endswith("integrate_role_outputs.py"):
        return "integrator"
    if path.endswith("validate_starter_kit.sh"):
        return "starter-kit validation"
    if path.endswith("check_integration_safety.py"):
        return "integration safety checker"
    if path.endswith("check_required_files.py"):
        return "generated-target contract checker"
    if path.endswith("test_run_observatory.py"):
        return "observatory regression tests"
    if path.endswith("test_integrate_role_outputs.py"):
        return "integrator/runtime-state tests"
    if path.endswith("test_check_integration_safety.py"):
        return "safety checker tests"
    if path.endswith("test_check_required_files.py"):
        return "required-file contract tests"
    if "diffmogger/dashboard/shared" in path or path.endswith("dashboard_backend_cli.py"):
        return "dashboard backend surface"
    if "agentic-notifier" in path:
        return "notifier guardrails"
    if path.endswith("README.md"):
        return "public docs"
    if path.startswith("docs/"):
        return "operator docs"
    if path.startswith("templates/"):
        return "generated target mirror"
    return classify_path(path)

def run_git_output(target: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(target),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""

def commit_numstat(target: Path, commit_hash: str) -> list[dict[str, Any]]:
    output = run_git_output(target, ["show", "--format=", "--numstat", "--no-renames", commit_hash])
    files: list[dict[str, Any]] = []
    for raw in output.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        add_s, del_s, path = parts[0], parts[1], parts[2]
        additions = 0 if add_s == "-" else int(add_s or 0)
        deletions = 0 if del_s == "-" else int(del_s or 0)
        files.append(
            {
                "path": clean_text(path, limit=140),
                "additions": additions,
                "deletions": deletions,
                "area": classify_path(path),
                "label": describe_path(path),
            }
        )
    return sorted(files, key=lambda item: item["additions"] + item["deletions"], reverse=True)

def commit_summary_from_files(subject: str, files: list[dict[str, Any]]) -> str:
    paths = [str(item.get("path") or "") for item in files]
    joined = "\n".join(paths)
    if "check_required_files.py" in joined and "test_check_required_files.py" in joined:
        return "Generated-target contract checks changed, with validation coverage."
    if "check_integration_safety.py" in joined:
        return "Integration safety guardrails changed, with local regression coverage."
    if "diffmogger/dashboard/shared" in joined or "dashboard_backend_cli.py" in joined:
        return "Dashboard backend controls or status surfaces changed."
    if "run_role_automation.sh" in joined and "integrate_role_outputs.py" in joined:
        return "Runtime-state handoff changed so ignored automation state reaches main."
    if "run_temporal_worker.sh" in joined or "orchestration_cli.py" in joined:
        return "Temporal runner wiring changed."
    if "run_observatory.py" in joined and "test_run_observatory.py" in joined:
        return "Observatory reporting changed, with matching regression tests."
    if "orchestration/" in joined and "test_new_architecture.py" in joined:
        return "Orchestration behavior changed, with architecture smoke coverage."
    if paths and all(path.startswith("docs/") or path.endswith(".md") for path in paths):
        return "Operator documentation and durable planning state changed."
    return subject

def git_commits_snapshot(target: Path, *, max_count: int = 80) -> list[dict[str, Any]]:
    output = run_git_output(
        target,
        ["log", "--date=iso-strict", f"--max-count={max_count}", "--pretty=format:%h%x09%cI%x09%s"],
    )
    commits: list[dict[str, Any]] = []
    for raw in output.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) != 3:
            continue
        commit_hash, commit_time, subject = parts
        files = commit_numstat(target, commit_hash)
        additions = sum(int(item.get("additions") or 0) for item in files)
        deletions = sum(int(item.get("deletions") or 0) for item in files)
        role_match = re.search(r"\((planner|designer|builder|hardener|integrator|observatory|conveyor|dashboard|scaffold|safety|docs)\)", subject)
        commits.append(
            {
                "hash": commit_hash,
                "time": commit_time,
                "subject": clean_text(subject, limit=220),
                "semantic": bool(CONVENTIONAL_SUBJECT_RE.match(subject)),
                "role": role_match.group(1) if role_match else "commit",
                "files": files[:8],
                "file_count": len(files),
                "additions": additions,
                "deletions": deletions,
                "summary": commit_summary_from_files(subject, files),
            }
        )
    return commits

def git_snapshot(target: Path) -> dict[str, Any]:
    def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(target),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=3,
            check=False,
        )

    branch_result = run_git(["branch", "--show-current"])
    status_result = run_git(["status", "--short"])
    log_result = run_git(["log", "--oneline", "-5"])
    dirty_lines = [line for line in (status_result.stdout or "").splitlines() if line.strip()]
    return {
        "branch": clean_text(branch_result.stdout.strip() or "unknown", limit=80) if branch_result.returncode == 0 else "unknown",
        "dirty_count": len(dirty_lines) if status_result.returncode == 0 else 0,
        "recent_commits": [
            clean_text(line, limit=120)
            for line in (log_result.stdout or "").splitlines()
            if line.strip()
        ][:5]
        if log_result.returncode == 0
        else [],
        "commits": git_commits_snapshot(target),
    }

def log_snapshot(target: Path) -> list[dict[str, Any]]:
    log_dir = runtime_path(target, "target/automation_logs")
    if not log_dir.exists():
        return []
    files = sorted(
        [path for path in log_dir.glob("*.log") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    for path in files[:MAX_LOG_FILES]:
        text = read_tail_text(path)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        items.append(
            {
                "name": path.name,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                "tail": clean_text(lines[-1] if lines else "No log lines yet.", limit=MAX_LOG_LINE_CHARS),
            }
        )
    return items
