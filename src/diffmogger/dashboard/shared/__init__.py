"""Shared backend helpers for the native Diffmogger dashboard."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, MutableMapping

from diffmogger.runtime.paths import existing_or_target_path, preferred_target_path, sidecar_rel, target_path


def find_kit_root() -> Path:
    override = os.environ.get("DIFFMOGGER_KIT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "templates").is_dir() and (parent / "scripts").is_dir():
            return parent
    return Path(__file__).resolve().parents[4]


ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KIT_ROOT = find_kit_root()
SCRIPTS_DIR = KIT_ROOT / "scripts"
RUNTIME_SCRIPTS_DIR = SCRIPTS_DIR / "runtime"
SCAFFOLD_SCRIPT = SCRIPTS_DIR / "scaffold_project_docs.py"
CHECK_REQUIRED_SCRIPT = SCRIPTS_DIR / "check_required_files.py"
OBSERVATORY_SCRIPT = RUNTIME_SCRIPTS_DIR / "run_observatory.py"
INTEGRATION_SAFETY_SCRIPT = SCRIPTS_DIR / "check_integration_safety.py"
DEFAULT_REVIEW_BUNDLE_DIR = Path("/tmp/Diffmogger-review")
INTEGRATION_SAFETY_RECORD_RELATIVE = Path("target/integration_safety_check.json")
STARTABLE_STATUSES = {
    "ACTIVE",
    "ACTIVE_WITH_PENDING_USER_INPUT",
    "BLOCKED_ON_USER",
    "BLOCKED_ON_ENVIRONMENT",
}
MAX_WRITE_WORKER_COUNT = 10
DEFAULT_WRITE_WORKER_COUNT = 3
DEFAULT_AUTOMATION_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
MULTI_ROLE_PROFILE = "planner_builder_hardener_integrator"
MULTI_ROLE_ROLES = ("planner", "designer", "builder", "hardener", "integrator")
OPTIONAL_MCP_SERVERS = ("context7", "playwright")
DEFAULT_OPTIONAL_MCP_SERVERS = list(OPTIONAL_MCP_SERVERS)
OPTIONAL_DESIGN_SERVICES = (
    "figma_mcp",
    "v0",
    "builder_visual_copilot",
    "storybook_chromatic",
    "percy",
    "applitools",
)
ENV_ACCESS_PROJECT_COMMANDS_ONLY = "project_commands_only"
ENV_ACCESS_DIRECT = "direct_env_files_allowed"
ENV_ACCESS_LABELS = {
    ENV_ACCESS_PROJECT_COMMANDS_ONLY: "Project commands only",
    ENV_ACCESS_DIRECT: "Allow direct .env reads",
}
ENV_ACCESS_BY_LABEL = {label: key for key, label in ENV_ACCESS_LABELS.items()}
DASHBOARD_STATE_FILE = sidecar_rel(".agentic/dashboard_state.json")
WORKER_STRATEGY_NAMES = {"NO_WORKERS", "READ_ONLY_REPORTS", "WRITE_WORKERS", "INTEGRATION_ONLY"}
WORKER_REPORT_STRATEGIES = {"READ_ONLY_REPORTS", "WRITE_WORKERS"}

DOC_CHOICES = {
    "Automation Tasks": sidecar_rel("docs/CODEX_AUTOMATION_TASKS.md"),
    "Automation Prompt": sidecar_rel(".agentic/automation_prompt.md"),
}

HUMAN_DOC_CHOICES: dict[str, str] = {}

INTENT_CHOICES = {
    "General note": "info",
    "Done / completed": "done",
    "Skip this request": "skip",
    "Approved": "approve",
    "Rejected": "reject",
    "Not sure": "unknown",
}


def _strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
    return value.rstrip()


def _parse_double_quoted(value: str) -> str:
    result: list[str] = []
    escaped = False
    escapes = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "$": "$", "`": "`"}
    for char in value:
        if escaped:
            result.append(escapes.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def _parse_dotenv_value(raw: str) -> str:
    value = _strip_inline_comment(raw.strip())
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _parse_double_quoted(value[1:-1])
    return value


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export") and len(line) > len("export") and line[len("export")].isspace():
            line = line[len("export") :].lstrip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if not ENV_NAME_RE.fullmatch(name):
            continue
        values[name] = _parse_dotenv_value(value)
    return values


def load_dotenv_file(path: Path, env: MutableMapping[str, str] | None = None) -> int:
    if not path.exists() or not path.is_file():
        return 0
    target_env = os.environ if env is None else env
    protected = set(target_env)
    loaded = 0
    for name, value in _parse_dotenv_file(path).items():
        if name in protected:
            continue
        target_env[name] = value
        loaded += 1
    return loaded


def load_repo_dotenv(repo_root: Path = KIT_ROOT, env: MutableMapping[str, str] | None = None) -> int:
    return load_dotenv_file(repo_root / ".env", env)


@dataclass(frozen=True)
class PrerequisiteItem:
    name: str
    ok: bool
    required: bool
    detail: str


@dataclass(frozen=True)
class ContextRecord:
    rel_path: str
    original_name: str
    size_bytes: int


def load_scaffold_module() -> Any:
    try:
        return importlib.import_module("diffmogger.kit.scaffold_project_docs")
    except Exception as exc:
        raise RuntimeError("Could not import diffmogger.kit.scaffold_project_docs") from exc


def load_observatory_module() -> Any:
    spec = importlib.util.spec_from_file_location("diffmogger_observatory", OBSERVATORY_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load observatory script at {OBSERVATORY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def split_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        lines.append(line)
    return lines


def nearest_existing_parent(path: Path) -> Path:
    current = path.expanduser()
    if current.exists():
        return current if current.is_dir() else current.parent
    for parent in current.parents:
        if parent.exists():
            return parent
    return Path.cwd()


def path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.expanduser().resolve().relative_to(parent.expanduser().resolve())
        return True
    except ValueError:
        return False
    except OSError:
        return False


def command_detail(command: str, args: list[str] | None = None, timeout: int = 4) -> tuple[bool, str]:
    path = shutil.which(command)
    if not path:
        return False, f"`{command}` not found on PATH."
    if not args:
        return True, path
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return True, f"{path}; version check failed: {exc}"
    output = (result.stdout or result.stderr).strip().splitlines()
    suffix = output[0] if output else "installed"
    return True, f"{path}; {suffix}"


def env_access_policy_from_value(value: Any) -> str:
    text = str(value or "").strip()
    if text in ENV_ACCESS_LABELS:
        return text
    if text in ENV_ACCESS_BY_LABEL:
        return ENV_ACCESS_BY_LABEL[text]
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in {"direct_env_files_allowed", "allow_direct_env_files", "allow_env_files"}:
        return ENV_ACCESS_DIRECT
    return ENV_ACCESS_PROJECT_COMMANDS_ONLY


def write_worker_count_from_text(value: Any, *, enabled: bool) -> int:
    if not enabled:
        return 0
    text = str(value or "").strip()
    match = re.search(r"\d+", text)
    count = int(match.group(0)) if match else DEFAULT_WRITE_WORKER_COUNT
    return min(MAX_WRITE_WORKER_COUNT, max(1, count))


def bool_from_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def optional_mcp_servers_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else re.split(r"[\n,]+", str(value))
    enabled: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = re.sub(r"^[-*]\s+", "", str(item).strip().lower())
        if not text:
            continue
        normalized = text.replace("-", "_").replace(" ", "_")
        names: list[str] = []
        if "context7" in normalized or normalized in {"context_7", "context"}:
            names.append("context7")
        if "playwright" in normalized:
            names.append("playwright")
        if normalized in OPTIONAL_MCP_SERVERS:
            names.append(normalized)
        for name in names:
            if name not in seen:
                seen.add(name)
                enabled.append(name)
    return enabled


def optional_mcp_servers_from_sources(*sources: Any) -> list[str]:
    """Resolve MCPs from ordered intake/dashboard sources.

    A missing field means the current default, all supported MCPs. An explicit
    empty field in the first source is an opt-out. Existing non-empty secondary
    sources can repair stale missing primary projections by unioning values.
    """
    enabled: list[str] = []
    seen: set[str] = set()
    saw_field = False
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or "optional_mcp_servers" not in source:
            continue
        saw_field = True
        normalized = optional_mcp_servers_from_value(source.get("optional_mcp_servers"))
        if not normalized and index == 0:
            return []
        for name in normalized:
            if name not in seen:
                seen.add(name)
                enabled.append(name)
    if enabled:
        ordered = [name for name in OPTIONAL_MCP_SERVERS if name in seen]
        extras = [name for name in enabled if name not in ordered]
        return [*ordered, *extras]
    if saw_field:
        return []
    return list(DEFAULT_OPTIONAL_MCP_SERVERS)


def target_script_path(target: Path, legacy_rel: str) -> Path:
    return existing_or_target_path(target.expanduser().resolve(), legacy_rel)


def dashboard_state_path(target: Path) -> Path:
    return preferred_target_path(target.expanduser().resolve(), ".agentic/dashboard_state.json")


def default_browser_cache_dir() -> Path:
    configured = os.environ.get("DIFFMOGGER_BROWSER_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "diffmogger" / "browsers"


def managed_browser_path() -> str | None:
    cache_dir = default_browser_cache_dir()
    if not cache_dir.exists():
        return None
    names = {"chrome-headless-shell", "chrome", "Google Chrome for Testing", "Chromium"}
    candidates = [
        path
        for path in cache_dir.rglob("*")
        if path.is_file() and path.name in names and os.access(path, os.X_OK) and "Crashpad" not in path.parts
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return str(candidates[0]) if candidates else None


def automation_environment(target: Path, *, allow_remotes: bool = False) -> dict[str, str]:
    environment = {
        "TARGET": str(target),
        "PATH": DEFAULT_AUTOMATION_PATH,
        "HOME": str(Path.home()),
        "DIFFMOGGER_BROWSER_CACHE": str(default_browser_cache_dir()),
    }
    env_browser = os.environ.get("DIFFMOGGER_BROWSER_PATH", "").strip() or os.environ.get("CHROME_PATH", "").strip()
    browser_path = env_browser or managed_browser_path()
    if browser_path:
        environment["DIFFMOGGER_BROWSER_PATH"] = browser_path
        environment["CHROME_PATH"] = browser_path
        environment["PLAYWRIGHT_MCP_EXECUTABLE_PATH"] = browser_path
    if allow_remotes:
        environment["MULTI_ROLE_ALLOW_REMOTES"] = "1"
    return environment


def target_has_initial_commit(target: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def fetch_notifier_health(timeout: float = 0.6) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        payload = json.loads(body)
        configured = payload.get("target_repo_configured")
        apprise = payload.get("apprise_configured")
        return True, (
            "agentic-notifier is reachable; "
            f"target_repo_configured={configured}; apprise_configured={apprise}."
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return False, f"agentic-notifier is not reachable on 127.0.0.1:8765 ({exc})."


def codex_mcp_detail(expected_servers: list[str], target: Path) -> tuple[bool, str]:
    codex_path = shutil.which("codex")
    if not codex_path:
        return False, "`codex` not found; MCP readiness cannot be checked."
    cwd = target if target.is_dir() else nearest_existing_parent(target)
    try:
        result = subprocess.run(
            [codex_path, "mcp", "list", "--json"],
            capture_output=True,
            text=True,
            cwd=cwd if cwd.exists() else None,
            timeout=6,
            check=False,
        )
    except Exception as exc:
        return False, f"`codex mcp list --json` failed: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "`codex mcp list --json` returned a non-zero exit code."
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return False, "`codex mcp list --json` returned invalid JSON."
    names = {
        str(item.get("name") or "")
        for item in data
        if isinstance(item, dict)
    }
    missing = [name for name in expected_servers if name not in names]
    if missing:
        return False, "Not registered in current Codex MCP list yet: " + ", ".join(missing) + ". Project-scoped config will be generated; missing MCP remains advisory."
    return True, "Configured MCP servers visible to Codex: " + ", ".join(expected_servers)


def check_prerequisites(target: Path, human_bridge_mode: str, optional_mcp_servers: list[str] | None = None) -> list[PrerequisiteItem]:
    items: list[PrerequisiteItem] = []
    optional_mcp_servers = optional_mcp_servers or []

    py_ok = sys.version_info >= (3, 10)
    items.append(
        PrerequisiteItem(
            "Python 3.10+",
            py_ok,
            True,
            f"Running {sys.version.split()[0]}.",
        )
    )
    codex_ok, codex_detail = command_detail("codex", ["--version"])
    items.append(
        PrerequisiteItem(
            "Codex CLI installed and signed in",
            codex_ok,
            True,
            codex_detail if codex_ok else codex_detail + " Install and run `codex` once before starting automation.",
        )
    )

    bash_ok, bash_detail = command_detail("bash", ["--version"])
    items.append(PrerequisiteItem("bash available", bash_ok, True, bash_detail))

    git_ok, git_detail = command_detail("git", ["--version"])
    items.append(PrerequisiteItem("git available", git_ok, True, git_detail))

    parent = nearest_existing_parent(target)
    writable = parent.exists() and os.access(parent, os.W_OK)
    items.append(
        PrerequisiteItem(
            "Target parent directory writable",
            writable,
            True,
            f"Nearest existing parent: {parent}",
        )
    )

    codex_home = Path.home() / ".codex"
    items.append(
        PrerequisiteItem(
            "Codex home accessible for nested workers",
            codex_home.exists(),
            False,
            f"{codex_home} exists." if codex_home.exists() else f"{codex_home} does not exist yet; run `codex` interactively once if workers fail.",
        )
    )

    if optional_mcp_servers:
        node_ok, node_detail = command_detail("node", ["--version"])
        items.append(PrerequisiteItem("Optional MCP Node runtime", node_ok, False, node_detail))
        npx_ok, npx_detail = command_detail("npx", ["--version"])
        items.append(PrerequisiteItem("Optional MCP npx runtime", npx_ok, False, npx_detail))
        mcp_ok, mcp_detail = codex_mcp_detail(optional_mcp_servers, target)
        items.append(PrerequisiteItem("Optional Codex MCP config", mcp_ok, False, mcp_detail))
        if "context7" in optional_mcp_servers:
            context7_key_set = bool(os.environ.get("CONTEXT7_API_KEY"))
            items.append(
                PrerequisiteItem(
                    "Optional Context7 API key",
                    context7_key_set,
                    False,
                    (
                        "CONTEXT7_API_KEY is visible to the dashboard process."
                        if context7_key_set
                        else "CONTEXT7_API_KEY is not visible; Context7 remains optional but may be unauthenticated or rate-limited. Export it in the environment before launching continuous automation."
                    ),
                )
            )
        if "playwright" in optional_mcp_servers:
            browser_path = managed_browser_path()
            items.append(
                PrerequisiteItem(
                    "Optional Playwright MCP browser",
                    bool(browser_path),
                    False,
                    browser_path or "No managed browser found yet; run `.diffmogger/scripts/diffmogger_browser.py install` in the generated target or use system browser fallback manually.",
                )
            )

    if sys.platform == "darwin" and path_is_under(target, Path.home() / "Documents"):
        items.append(
            PrerequisiteItem(
                "macOS Documents permission note",
                False,
                False,
                "Targets under ~/Documents may need Full Disk Access for /bin/bash and the Node executable used by Codex during continuous automation.",
            )
        )
    else:
        items.append(
            PrerequisiteItem(
                "macOS Documents permission note",
                True,
                False,
                "No Documents-folder advisory for the selected target.",
            )
        )

    if human_bridge_mode in {"local_notifier", "apprise_notifier"}:
        notifier_ok, notifier_detail = fetch_notifier_health()
        items.append(
            PrerequisiteItem(
                "Optional local notifier reachable",
                notifier_ok,
                False,
                notifier_detail + " File-only handoff remains available if notifier setup is incomplete.",
            )
        )

    return items


def format_prerequisites(items: list[PrerequisiteItem]) -> str:
    required = [item for item in items if item.required]
    optional = [item for item in items if not item.required]
    lines = ["Required before starting automation:"]
    for item in required:
        marker = "OK" if item.ok else "MISSING"
        lines.append(f"- [{marker}] {item.name}: {item.detail}")
    lines.append("")
    lines.append("Advisory and optional checks:")
    for item in optional:
        marker = "OK" if item.ok else "CHECK"
        lines.append(f"- [{marker}] {item.name}: {item.detail}")
    return "\n".join(lines)


def required_failures(items: list[PrerequisiteItem]) -> list[PrerequisiteItem]:
    return [item for item in items if item.required and not item.ok]


def has_integration_safety_tree(target: Path) -> bool:
    target = target.expanduser()
    return (
        (target / "scripts" / "check_integration_safety.py").is_file()
        and (target / "services" / "agentic-notifier").is_dir()
    )


def resolve_integration_safety_target(target: Path) -> Path:
    target = target.expanduser()
    if has_integration_safety_tree(target):
        return target.resolve()
    return KIT_ROOT


def integration_safety_command(target: Path) -> list[str]:
    return [
        sys.executable,
        str(INTEGRATION_SAFETY_SCRIPT),
        str(resolve_integration_safety_target(target)),
    ]


def integration_safety_record_path(target: Path) -> Path:
    return target_path(target.expanduser().resolve(), INTEGRATION_SAFETY_RECORD_RELATIVE)


def write_integration_safety_record(
    selected_target: Path,
    checked_target: Path,
    command: list[str],
    exit_code: int,
) -> Path:
    selected_target = selected_target.expanduser().resolve()
    checked_target = checked_target.expanduser().resolve()
    status = "pass" if exit_code == 0 else "fail"
    status_word = "passed" if status == "pass" else "failed"
    checked_label = "the Diffmogger kit source" if checked_target == KIT_ROOT else str(checked_target)
    selected_label = selected_target.name or str(selected_target)
    if selected_target == checked_target:
        summary = f"Dashboard Run Safety Check {status_word} for {checked_label}."
    else:
        summary = (
            f"Dashboard Run Safety Check {status_word} against {checked_label} "
            f"for selected target {selected_label}."
        )
    record = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "dashboard_run_safety_check",
        "status": status,
        "exit_code": exit_code,
        "command": shlex.join(str(part) for part in command),
        "selected_target": str(selected_target),
        "checked_target": str(checked_target),
        "summary": summary,
    }
    record_path = integration_safety_record_path(selected_target)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record_path


def review_bundle_command(target: Path, review_dir: Path = DEFAULT_REVIEW_BUNDLE_DIR) -> list[str]:
    return [
        sys.executable,
        str(OBSERVATORY_SCRIPT),
        "--target",
        str(target.expanduser().resolve()),
        "--review-dir",
        str(review_dir),
    ]


def compact_dashboard_text(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def dashboard_run_id(prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-") or "dashboard"
    return f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def dashboard_worker_strategy(target: Path) -> dict[str, Any]:
    module = load_observatory_module()
    snapshot = module.build_snapshot(target.expanduser().resolve())
    strategy = snapshot.get("worker_strategy") if isinstance(snapshot, dict) else {}
    if not isinstance(strategy, dict):
        return {}
    name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    if name not in WORKER_STRATEGY_NAMES:
        strategy = dict(strategy)
        strategy["strategy"] = "NO_WORKERS"
    return strategy


def worker_strategy_summary(strategy: dict[str, Any]) -> str:
    if not strategy:
        return "Next worker strategy: unavailable until the observatory can read target state."
    name = compact_dashboard_text(strategy.get("strategy") or "NO_WORKERS", limit=80)
    try:
        budget = int(strategy.get("parallelism_budget") or 0)
    except (TypeError, ValueError):
        budget = 0
    lane = compact_dashboard_text(strategy.get("action_lane") or "local", limit=80)
    summary = compact_dashboard_text(
        strategy.get("summary") or "No next-run worker strategy summary recorded.",
        limit=360,
    )
    return f"Next worker strategy: {name} / budget {budget} / lane {lane}. {summary}"


def worker_summary_command(target: Path, run_id: str) -> list[str]:
    target = target.expanduser().resolve()
    return [
        sys.executable,
        str(target_script_path(target, "scripts/summarize_worker_outputs.py")),
        str(target),
        "--run-id",
        run_id,
    ]


def latest_worker_result(target: Path) -> dict[str, Any]:
    target = target.expanduser().resolve()
    runs_dir = target_path(target, "target/agent_runs")
    result: dict[str, Any] = {
        "label": "Latest worker result: none yet.",
        "run_id": None,
        "report_count": 0,
        "summary_path": None,
        "summary_exists": False,
    }
    if not runs_dir.exists():
        return result

    run_dirs = [
        path
        for path in runs_dir.iterdir()
        if path.is_dir()
        and any(
            child.name.startswith("worker_")
            and child.name != "worker_summary.md"
            and child.suffix == ".md"
            for child in path.iterdir()
        )
    ]
    if not run_dirs:
        return result

    def newest_child_mtime(path: Path) -> float:
        children = [child for child in path.iterdir() if child.is_file()]
        if not children:
            return path.stat().st_mtime
        return max(child.stat().st_mtime for child in children)

    latest = max(run_dirs, key=newest_child_mtime)
    reports = sorted(
        path
        for path in latest.glob("worker_*.md")
        if path.name != "worker_summary.md"
    )
    summary_path = latest / "summary.md"
    report_word = "report" if len(reports) == 1 else "reports"
    if summary_path.exists():
        result["label"] = (
            f"Latest worker result: {latest.name} / {len(reports)} {report_word} / "
            f"summary ready at {summary_path.relative_to(target)}."
        )
        result["summary_path"] = str(summary_path)
        result["summary_exists"] = True
    else:
        result["label"] = (
            f"Latest worker result: {latest.name} / {len(reports)} {report_word} / "
            "summary not generated yet."
        )
    result["run_id"] = latest.name
    result["report_count"] = len(reports)
    return result


def worker_role_from_strategy(strategy: dict[str, Any]) -> str:
    lane = compact_dashboard_text(strategy.get("action_lane") or "review", limit=40).lower()
    if lane in {"planner", "designer", "builder", "hardener", "integrator"}:
        return f"{lane}_strategy"
    name = compact_dashboard_text(strategy.get("strategy") or "review", limit=40).lower()
    return f"{name}_strategy"


def worker_assignment_prompt(strategy: dict[str, Any], *, mode: str) -> str:
    summary = compact_dashboard_text(strategy.get("summary") or "", limit=600)
    reasons = [
        compact_dashboard_text(item, limit=300)
        for item in list(strategy.get("reasons") or [])
        if item
    ][:4]
    next_steps = [
        compact_dashboard_text(item, limit=360)
        for item in list(strategy.get("next_steps") or [])
        if item
    ][:5]
    lines = [
        f"Use the dashboard-observed next-run worker strategy `{compact_dashboard_text(strategy.get('strategy') or 'NO_WORKERS', limit=80)}`.",
        f"Action lane: `{compact_dashboard_text(strategy.get('action_lane') or 'local', limit=80)}`.",
    ]
    if summary:
        lines.append(f"Strategy summary: {summary}")
    if reasons:
        lines.append("Reasons:")
        lines.extend(f"- {reason}" for reason in reasons)
    if next_steps:
        lines.append("Suggested next steps:")
        lines.extend(f"- {step}" for step in next_steps)
    if mode == "write":
        lines.extend(
            [
                "",
                "Implement exactly one bounded slice inside the supplied ownership scope.",
                "Keep the main agent responsible for reviewing, integrating, and verifying your output.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Produce a concise read-only report that helps the next main automation run decide whether to follow this strategy, narrow it, or avoid it.",
            ]
        )
    return "\n".join(lines)


def normalize_worker_ownership_scope(ownership_scope: str) -> str:
    scope = re.sub(r"\s+", " ", str(ownership_scope or "").strip())
    if not scope:
        raise ValueError("write workers require a non-empty ownership scope")
    return scope


def read_only_worker_command(target: Path, strategy: dict[str, Any], *, run_id: str | None = None) -> list[str]:
    target = target.expanduser().resolve()
    return [
        "bash",
        str(target_script_path(target, "scripts/spawn_worker_agent.sh")),
        "--target",
        str(target),
        "--run-id",
        run_id or dashboard_run_id("dashboard-worker-report"),
        "--role",
        worker_role_from_strategy(strategy),
        "--read-only",
        "--prompt",
        worker_assignment_prompt(strategy, mode="read-only"),
    ]


def write_worker_command(
    target: Path,
    strategy: dict[str, Any],
    ownership_scope: str,
    *,
    run_id: str | None = None,
) -> list[str]:
    target = target.expanduser().resolve()
    ownership_scope = normalize_worker_ownership_scope(ownership_scope)
    return [
        "bash",
        str(target_script_path(target, "scripts/spawn_worker_agent.sh")),
        "--target",
        str(target),
        "--run-id",
        run_id or dashboard_run_id("dashboard-write-worker"),
        "--role",
        worker_role_from_strategy(strategy),
        "--write",
        "--ownership",
        ownership_scope,
        "--prompt",
        worker_assignment_prompt(strategy, mode="write"),
    ]


def integration_only_command(target: Path, *, run_id: str | None = None) -> list[str]:
    target = target.expanduser().resolve()
    return [
        "env",
        f"CODEX_RUN_ID={run_id or dashboard_run_id('dashboard-integrator')}",
        "bash",
        str(target_script_path(target, "scripts/run_role_automation.sh")),
        "--target",
        str(target),
        "--role",
        "integrator",
    ]


def safe_context_filename(name: str) -> str:
    source = Path(name)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem).strip(".-") or "context"
    suffix = re.sub(r"[^A-Za-z0-9.]+", "", source.suffix)
    return f"{stem}{suffix}"


def copy_context_files(
    target: Path,
    context_paths: list[Path],
    log: Callable[[str], None],
) -> list[ContextRecord]:
    if not context_paths:
        return []

    context_dir = target / ".diffmogger" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    records: list[ContextRecord] = []
    used_names: set[str] = set()

    for source in context_paths:
        source = source.expanduser().resolve()
        if not source.exists() or not source.is_file():
            log(f"Skipping missing context file: {source}")
            continue
        base_name = safe_context_filename(source.name)
        candidate = base_name
        counter = 2
        while candidate in used_names or (context_dir / candidate).exists():
            stem = Path(base_name).stem
            suffix = Path(base_name).suffix
            candidate = f"{stem}-{counter}{suffix}"
            counter += 1
        used_names.add(candidate)
        dest = context_dir / candidate
        if source == dest.resolve():
            log(f"Context file already in target: {dest}")
        else:
            shutil.copy2(source, dest)
            log(f"Copied context file: {source.name} -> .diffmogger/context/{candidate}")
        records.append(
            ContextRecord(
                rel_path=f".diffmogger/context/{candidate}",
                original_name=source.name,
                size_bytes=dest.stat().st_size,
            )
        )

    return records


def next_inbox_id(inbox_path: Path, now: datetime) -> str:
    date_prefix = now.strftime("%Y-%m-%d")
    if inbox_path.exists():
        text = inbox_path.read_text(encoding="utf-8")
    else:
        text = ""
    pattern = re.compile(rf"^## INBOX-{re.escape(date_prefix)}-(\d{{3,}})", re.MULTILINE)
    existing = [int(match.group(1)) for match in pattern.finditer(text)]
    return f"INBOX-{date_prefix}-{max(existing, default=0) + 1:03d}"


def append_manual_inbox_entry(
    target: Path,
    body: str,
    *,
    request_id: str,
    parsed_intent: str,
) -> str:
    from diffmogger.runtime.state_store import record_human_message

    record = record_human_message(
        target,
        kind="note",
        body=body,
        request_id=request_id.strip() or "unknown",
        intent=parsed_intent.strip() or "info",
        status="unhandled",
        channel="manual-dashboard",
    )
    return str(record.get("id") or "")


def smoke_check() -> int:
    problems: list[str] = []
    for path in [SCAFFOLD_SCRIPT, CHECK_REQUIRED_SCRIPT, OBSERVATORY_SCRIPT, INTEGRATION_SAFETY_SCRIPT]:
        if not path.exists():
            problems.append(f"Missing required script: {path}")
    if "--review-dir" not in " ".join(review_bundle_command(KIT_ROOT)):
        problems.append("Review bundle command is not wired to --review-dir.")
    smoke_strategy = {"strategy": "READ_ONLY_REPORTS", "parallelism_budget": 1, "action_lane": "builder"}
    if "--read-only" not in read_only_worker_command(KIT_ROOT, smoke_strategy, run_id="dashboard-smoke"):
        problems.append("Dashboard read-only worker command is not wired to --read-only.")
    if "--write" not in write_worker_command(KIT_ROOT, {"strategy": "WRITE_WORKERS", "action_lane": "builder"}, "docs/** only", run_id="dashboard-smoke"):
        problems.append("Dashboard write-worker command is not wired to --write.")
    if "summarize_worker_outputs.py" not in " ".join(worker_summary_command(KIT_ROOT, "dashboard-smoke")):
        problems.append("Dashboard worker summary command is not wired to summarize_worker_outputs.py.")
    if "--role" not in integration_only_command(KIT_ROOT, run_id="dashboard-smoke"):
        problems.append("Dashboard integration-only command is not wired to run_role_automation.sh.")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print("OK: dashboard backend helper smoke check passed")
    return 0
