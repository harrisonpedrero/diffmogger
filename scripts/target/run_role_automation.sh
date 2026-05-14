#!/usr/bin/env bash
set -euo pipefail

export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

usage() {
  cat <<'EOF'
Usage: .diffmogger/scripts/run_role_automation.sh --role planner|builder|hardener|integrator [--target PATH]

Run one optional multi-role automation role. Planner, builder, and hardener run
inside isolated git worktrees and queue patches. Integrator applies queued
patches in the main checkout.

Environment:
  TARGET                    Target project directory. Default: current repo
  CODEX_RUN_ID or RUN_ID    Run id. Generated if absent
  MULTI_ROLE_ALLOW_REMOTES  Set 1 to allow configured git remotes
EOF
}

original_args=("$@")
runner_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
script_parent="$(cd "$runner_script_dir/.." && pwd)"
script_grandparent="$(cd "$script_parent/.." && pwd)"
runtime_script_dir="$runner_script_dir"
if [[ "$(basename "$script_parent")" == ".diffmogger" ]]; then
  default_target="$(cd "$script_parent/.." && pwd)"
elif [[ "$(basename "$runner_script_dir")" == "target" && "$(basename "$script_parent")" == "scripts" ]]; then
  default_target="$script_grandparent"
  runtime_script_dir="$script_parent/runtime"
else
  default_target="$script_parent"
fi
target_dir="${TARGET:-$default_target}"
role=""
run_id="${CODEX_RUN_ID:-${RUN_ID:-}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      target_dir="${2:?--target requires a path}"
      shift 2
      ;;
    --role)
      role="${2:?--role requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$role" ]]; then
  echo "--role is required" >&2
  usage >&2
  exit 2
fi

case "$role" in
  planner|builder|hardener|integrator)
    ;;
  *)
    echo "Invalid role: $role" >&2
    exit 2
    ;;
esac

if [[ -z "$run_id" ]]; then
  run_id="$(date -u +%Y%m%dT%H%M%SZ)-$role"
fi

target_abs="$(cd "$target_dir" && pwd)"
export DIFFMOGGER_TARGET_ROOT="$target_abs"
cd "$target_abs"

load_codex_automation_env() {
  if [[ "${CODEX_AUTOMATION_ENV_LOADED:-}" == "1" ]]; then
    return 0
  fi
  if [[ -f "$runtime_script_dir/load_automation_env.py" ]]; then
    exec python3 "$runtime_script_dir/load_automation_env.py" --target "$target_abs" -- "${BASH:-bash}" "$0" "${original_args[@]}"
  fi
  export CODEX_AUTOMATION_ENV_LOADED="1"
}

load_codex_automation_env

if [[ -n "${DIFFMOGGER_BROWSER_PATH:-}" && -z "${CHROME_PATH:-}" ]]; then
  export CHROME_PATH="$DIFFMOGGER_BROWSER_PATH"
elif [[ -z "${DIFFMOGGER_BROWSER_PATH:-}" && -z "${CHROME_PATH:-}" && -f "$runtime_script_dir/diffmogger_browser.py" ]]; then
  browser_env="$(python3 "$runtime_script_dir/diffmogger_browser.py" env 2>/dev/null || true)"
  if [[ -n "$browser_env" ]]; then
    eval "$browser_env"
  fi
fi
if [[ -n "${DIFFMOGGER_BROWSER_PATH:-}" ]]; then
  export PLAYWRIGHT_MCP_EXECUTABLE_PATH="${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-$DIFFMOGGER_BROWSER_PATH}"
elif [[ -n "${CHROME_PATH:-}" ]]; then
  export PLAYWRIGHT_MCP_EXECUTABLE_PATH="${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-$CHROME_PATH}"
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Multi-role automation requires an initialized git repo: $target_abs" >&2
  exit 2
fi

remotes="$(git remote -v || true)"
if [[ -n "$remotes" && "${MULTI_ROLE_ALLOW_REMOTES:-0}" != "1" ]]; then
  echo "Multi-role automation is local-only and refuses to run with configured git remotes." >&2
  echo "$remotes" >&2
  echo "Set MULTI_ROLE_ALLOW_REMOTES=1 only if you intentionally allow local automation in a repo with remotes." >&2
  exit 2
fi

exclude_path="$(git rev-parse --git-path info/exclude 2>/dev/null || printf '.git/info/exclude')"
mkdir -p "$(dirname "$exclude_path")"
touch "$exclude_path"
if ! grep -Fx "# Diffmogger local automation scaffold/runtime" "$exclude_path" >/dev/null 2>&1; then
  if [ -s "$exclude_path" ]; then
    printf '\n' >> "$exclude_path"
  fi
  printf '%s\n' "# Diffmogger local automation scaffold/runtime" >> "$exclude_path"
fi
for pattern in \
  "/.env" \
  "/.env.development" \
  "/.env.development.local" \
  "/.env.local" \
  "/apps/*/.env" \
  "/apps/*/.env.development" \
  "/apps/*/.env.development.local" \
  "/apps/*/.env.local" \
  "/.agentic/" \
  "/AGENTS.md" \
  "/docs/AUTONOMY_EXPERIMENT_LOG.md" \
  "/docs/CODEX_AUTOMATION_GUARDRAILS.md" \
  "/docs/CODEX_AUTOMATION_TASKS.md" \
  "/docs/DAILY_AUTOMATION_REVIEW.md" \
  "/docs/DEVELOPMENT.md" \
  "/docs/HUMAN_BRIDGE_SETUP.md" \
  "/docs/INITIAL_BOOTSTRAP_PROMPT.md" \
  "/docs/MULTI_ROLE_PROGRESS.md" \
  "/docs/PROJECT_CONTEXT.md" \
  "/scripts/acquire_codex_lock.sh" \
  "/scripts/__pycache__/" \
  "/scripts/build_replay.py" \
  "/scripts/compact_agent_state.py" \
  "/scripts/diffmogger_browser.py" \
  "/scripts/integrate_role_outputs.py" \
  "/scripts/load_automation_env.py" \
  "/scripts/list_deferred_patches.py" \
  "/scripts/release_codex_lock.sh" \
  "/scripts/repair_environment.py" \
  "/scripts/run_codex_automation.sh" \
  "/scripts/run_conveyor_automation.py" \
  "/scripts/run_conveyor_automation.sh" \
  "/scripts/run_observatory.py" \
  "/scripts/run_role_automation.sh" \
  "/scripts/run_process_watchdog.py" \
  "/scripts/spawn_worker_agent.sh" \
  "/scripts/state_brief.py" \
  "/scripts/summarize_worker_outputs.py" \
  "/scripts/ticket_run.py" \
  "/target/agent_runs/" \
  "/target/automation_runner.json" \
  "/target/automation_conveyor.lock" \
  "/target/automation_conveyor_state.json" \
  "/target/baseline_verification.json" \
  "/target/canonical_state_brief.md" \
  "/target/orchestration.sqlite3" \
  "/target/orchestration.sqlite3-shm" \
  "/target/orchestration.sqlite3-wal" \
  "/target/automation_logs/" \
  "/target/automation_queue/" \
  "/target/automation_venvs/" \
  "/target/automation_worktrees/" \
  "/target/codex_automation.lock" \
  "/target/prisma-cache/" \
  "/target/ticket_run_completion.json" \
  "/target/ticket_run_reports/" \
  "/.pnpm-store/"; do
  if ! grep -Fx "$pattern" "$exclude_path" >/dev/null 2>&1; then
    printf '%s\n' "$pattern" >> "$exclude_path"
  fi
done

if [[ -f "$target_abs/.diffmogger/manifest.json" ]]; then
  while IFS= read -r pattern; do
    if [[ -n "$pattern" ]] && ! grep -Fx "$pattern" "$exclude_path" >/dev/null 2>&1; then
      printf '%s\n' "$pattern" >> "$exclude_path"
    fi
  done < <(python3 - "$target_abs" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
try:
    manifest = json.loads((target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8"))
except Exception:
    manifest = {}
def normalize_rel(value: str) -> str:
    rel = str(value).strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")
for rel in manifest.get("patch_exclude_paths") or []:
    rel = normalize_rel(str(rel))
    if rel:
        print("/" + rel.rstrip("/") + ("/" if rel.endswith("/") else ""))
PY
  )
fi

eval "$(
  python3 - "$target_abs" "$role" "$run_id" <<'PY'
import json
import shlex
import sys
from pathlib import Path

target = Path(sys.argv[1])
role = sys.argv[2]
run_id = sys.argv[3]
try:
    manifest = json.loads((target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8"))
except Exception:
    manifest = {}
sidecar = manifest.get("layout") == "sidecar_v1"
aliases = manifest.get("path_aliases") if isinstance(manifest.get("path_aliases"), dict) else {}

def normalize_rel(value: str) -> str:
    rel = str(value).strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")

def rel(path: str) -> str:
    if not sidecar:
        return path
    if path in aliases:
        return normalize_rel(str(aliases[path]))
    for old, new in sorted(aliases.items(), key=lambda item: len(str(item[0])), reverse=True):
        old = normalize_rel(str(old)).rstrip("/")
        new = normalize_rel(str(new)).rstrip("/")
        if old and path.startswith(old + "/"):
            return new + path[len(old):]
    return normalize_rel(path)

values = {
    "prompt_path": target / rel(f".agentic/roles/{role}.md"),
    "queue_dir": target / rel(f"target/automation_queue/{role}/{run_id}"),
    "worktree_dir": target / rel(f"target/automation_worktrees/{role}/{run_id}"),
    "log_dir": target / rel("target/automation_logs"),
    "worktree_summary_rel": rel(f"target/automation_queue/{role}/{run_id}/summary.md"),
    "worktree_ticket_state_actions_rel": rel(f"target/automation_queue/{role}/{run_id}/ticket_state_actions.json"),
    "worktree_ticket_state_snapshot_rel": rel(f"target/automation_queue/{role}/{run_id}/ticket_state_snapshot.json"),
    "state_brief_path": target / rel("target/canonical_state_brief.md"),
    "state_brief_rel": rel("target/canonical_state_brief.md"),
    "mcp_config_rel": rel(".codex/config.toml"),
    "playwright_mcp_rel": rel("scripts/run_playwright_mcp.sh"),
    "playwright_artifact_rel": rel(f"docs/backlog/ui_artifacts/{run_id}"),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

if [[ ! -f "$prompt_path" ]]; then
  echo "Missing role prompt: $prompt_path" >&2
  exit 2
fi

regenerate_state_brief() {
  if [[ -f "$runtime_script_dir/state_brief.py" ]]; then
    python3 "$runtime_script_dir/state_brief.py" --target "$target_abs" --quiet || {
      printf 'WARN: failed to regenerate canonical state brief at %s\n' "$state_brief_path" >&2
    }
  fi
}

regenerate_state_brief

if [[ "$role" == "integrator" ]]; then
  python3 "$runtime_script_dir/integrate_role_outputs.py" "$target_abs" --run-id "$run_id"
  integrator_status=$?
  if [[ "$integrator_status" -eq 0 && -f "$runtime_script_dir/ticket_run.py" ]]; then
    python3 "$runtime_script_dir/ticket_run.py" "$target_abs" should-halt --finalize || true
  fi
  exit "$integrator_status"
fi

base_commit="$(git rev-parse HEAD)"
mkdir -p "$queue_dir" "$(dirname "$worktree_dir")" "$log_dir"

summary_path="$queue_dir/summary.md"
worktree_summary_path="$worktree_dir/$worktree_summary_rel"
ticket_state_actions_path="$queue_dir/ticket_state_actions.json"
worktree_ticket_state_actions_path="$worktree_dir/$worktree_ticket_state_actions_rel"
ticket_state_snapshot_path="$queue_dir/ticket_state_snapshot.json"
worktree_ticket_state_snapshot_path="$worktree_dir/$worktree_ticket_state_snapshot_rel"
ticket_claim_path="$queue_dir/ticket_claim.json"
ticket_claim_stderr_path="$queue_dir/ticket_claim.stderr.log"
patch_path="$queue_dir/changes.patch"
manifest_path="$queue_dir/manifest.json"
raw_log="$queue_dir/codex.raw.log"
stdout_log="$log_dir/$role.stdout.log"
stderr_log="$log_dir/$role.stderr.log"
run_stdout="$queue_dir/codex.stdout.log"
run_stderr="$queue_dir/codex.stderr.log"
watchdog_status_path="$queue_dir/codex.watchdog.json"
runtime_prompt_path="$queue_dir/runtime_prompt.md"
hardener_deferred_context_path="$queue_dir/hardener_deferred_context.md"
env_repair_path="$queue_dir/environment_repair.json"
rerun_stdout="$queue_dir/codex.rerun.stdout.log"
rerun_stderr="$queue_dir/codex.rerun.stderr.log"
rerun_watchdog_status_path="$queue_dir/codex.rerun.watchdog.json"
final_watchdog_status_path="$watchdog_status_path"
hardener_queue_root="$(dirname "$(dirname "$queue_dir")")/hardener"

if [[ "$role" == "builder" && -f "$runtime_script_dir/ticket_run.py" ]]; then
  DIFFMOGGER_TICKET_STATE_DIRECT=1 python3 "$runtime_script_dir/ticket_run.py" "$target_abs" claim-next \
    --role "$role" \
    --run-id "$run_id" \
    --json >"$ticket_claim_path" 2>"$ticket_claim_stderr_path" || {
      printf 'WARN: failed to claim next ticket for %s run %s; continuing with role execution.\n' "$role" "$run_id" >&2
      if [[ -s "$ticket_claim_stderr_path" ]]; then
        cat "$ticket_claim_stderr_path" >&2
      fi
    }
  regenerate_state_brief
fi

git worktree add --detach "$worktree_dir" "$base_commit" >/dev/null
mkdir -p "$(dirname "$worktree_summary_path")"

context_paths=(
  ".agentic/automation_prompt.md"
  ".agentic/smoke_commands.txt"
  ".agentic/verification_commands.txt"
  ".agentic/roles"
  ".codex/config.toml"
  "docs/CODEX_AUTOMATION_TASKS.md"
  "docs/MULTI_ROLE_PROGRESS.md"
  "docs/CODEX_AUTOMATION_GUARDRAILS.md"
  "docs/PROJECT_CONTEXT.md"
  "docs/AUTONOMY_EXPERIMENT_LOG.md"
  "docs/DAILY_AUTOMATION_REVIEW.md"
  "docs/HUMAN_BRIDGE_SETUP.md"
  "docs/backlog/README.md"
  "scripts/acquire_codex_lock.sh"
  "scripts/build_replay.py"
  "scripts/compact_agent_state.py"
  "scripts/diffmogger_browser.py"
  "scripts/integrate_role_outputs.py"
  "scripts/load_automation_env.py"
  "scripts/list_deferred_patches.py"
  "scripts/release_codex_lock.sh"
  "scripts/repair_environment.py"
  "scripts/run_codex_automation.sh"
  "scripts/run_conveyor_automation.py"
  "scripts/run_conveyor_automation.sh"
  "scripts/run_observatory.py"
  "scripts/run_playwright_mcp.sh"
  "scripts/run_process_watchdog.py"
  "scripts/run_role_automation.sh"
  "scripts/spawn_worker_agent.sh"
  "scripts/state_brief.py"
  "scripts/summarize_worker_outputs.py"
  "scripts/ticket_run.py"
  "target/automation_runner.json"
  "target/canonical_state_brief.md"
  "target/baseline_verification.json"
)

if [[ -f "$target_abs/.diffmogger/manifest.json" ]]; then
  context_paths=()
  while IFS= read -r rel; do
    if [[ -n "$rel" ]]; then
      context_paths+=("$rel")
    fi
  done < <(python3 - "$target_abs" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
try:
    manifest = json.loads((target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8"))
except Exception:
    manifest = {}
def normalize_rel(value: str) -> str:
    rel = str(value).strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.lstrip("/")
for rel in manifest.get("worktree_seed_paths") or []:
    rel = normalize_rel(str(rel))
    if rel:
        print(rel)
PY
  )
fi

runtime_state_paths_path="$queue_dir/runtime_state_paths.txt"
runtime_state_start_path="$queue_dir/runtime_state_start.json"
runtime_state_actions_path="$queue_dir/runtime_state_actions.json"
runtime_state_changed_files_path="$queue_dir/runtime_state_changed_files.txt"

python3 - "$target_abs" "$runtime_state_paths_path" <<'PY'
import os
import json
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1])
output = Path(sys.argv[2])
max_bytes = int(os.environ.get("RUNTIME_STATE_MAX_BYTES", "1048576"))
try:
    manifest = json.loads((target / ".diffmogger" / "manifest.json").read_text(encoding="utf-8"))
except Exception:
    manifest = {}
if manifest.get("layout") == "sidecar_v1":
    explicit_paths = [
        str(item).strip()
        for item in (manifest.get("worktree_seed_paths") or [])
        if str(item).strip().startswith((".diffmogger/agentic/", ".diffmogger/state/"))
    ]
    scan_roots = [".diffmogger/agentic", ".diffmogger/state"]
    allowed_prefixes = (".diffmogger/agentic/", ".diffmogger/state/")
else:
    explicit_paths = [
        ".agentic/automation_prompt.md",
        ".agentic/smoke_commands.txt",
        ".agentic/verification_commands.txt",
      ".agentic/roles/planner.md",
      ".agentic/roles/builder.md",
      ".agentic/roles/hardener.md",
      ".agentic/roles/integrator.md",
      ".codex/config.toml",
        "docs/CODEX_AUTOMATION_TASKS.md",
        "docs/MULTI_ROLE_PROGRESS.md",
        "target/automation_runner.json",
    ]
    scan_roots = [".agentic", "docs"]
    allowed_prefixes = (".agentic/", "docs/")
deny_parts = {
    ".git",
    ".hg",
    ".svn",
    ".codex",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "automation_queue",
    "automation_worktrees",
    "automation_logs",
    "automation_venvs",
}
deny_names = {".DS_Store", "codex_automation.lock", "automation_conveyor.lock"}
deny_suffixes = (
    ".7z",
    ".db",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".lock",
    ".log",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".tar",
    ".tgz",
    ".zip",
)

def git_ignored(rel):
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=target,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0

def safe_rel(rel):
    rel_path = Path(rel)
    if rel_path.is_absolute():
        return False
    parts = rel_path.parts
    if any(part in {"", ".", ".."} for part in parts):
        return False
    lowered_parts = {part.lower() for part in parts}
    if lowered_parts & {"secrets", ".ssh"}:
        return False
    if any(part in deny_parts for part in parts):
        return False
    name = rel_path.name
    if name == ".env" or name.startswith(".env."):
        return False
    if name in deny_names or name.endswith(deny_suffixes):
        return False
    return True

def text_file(path):
    if not path.exists() or not path.is_file() or path.is_symlink():
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) > max_bytes:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True

def allowed_runtime_path(rel):
    if not safe_rel(rel):
        return False
    if rel in explicit_paths:
        return True
    if not rel.startswith(allowed_prefixes):
        return False
    return git_ignored(rel)

seen = set()
paths = []

def add(rel):
    if rel in seen or not allowed_runtime_path(rel):
        return
    if not text_file(target / rel):
        return
    seen.add(rel)
    paths.append(rel)

for rel in explicit_paths:
    add(rel)

for root in scan_roots:
    root_path = target / root
    if not root_path.exists():
        continue
    for current, dirs, files in os.walk(root_path):
        dirs[:] = [item for item in dirs if item not in deny_parts and item.lower() not in {"secrets", ".ssh"}]
        for name in files:
            rel = (Path(current) / name).relative_to(target).as_posix()
            add(rel)

output.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
PY

runtime_state_paths=()
while IFS= read -r rel; do
  if [[ -n "$rel" ]]; then
    runtime_state_paths+=("$rel")
  fi
done <"$runtime_state_paths_path"

context_excludes=()
for rel in "${context_paths[@]}"; do
  context_excludes+=(":(exclude)$rel")
done
for rel in "${runtime_state_paths[@]}"; do
  context_excludes+=(":(exclude)$rel")
done
context_excludes+=(":(exclude)$worktree_ticket_state_actions_rel")
context_excludes+=(":(exclude)$worktree_ticket_state_snapshot_rel")

seed_context_path() {
  local rel="$1"
  local src="$target_abs/$rel"
  local dst="$worktree_dir/$rel"
  if [[ ! -e "$src" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  rm -rf "$dst"
  if [[ -d "$src" ]]; then
    cp -R "$src" "$dst"
  else
    cp "$src" "$dst"
  fi
}

for rel in "${context_paths[@]}"; do
  seed_context_path "$rel"
done
for rel in "${runtime_state_paths[@]}"; do
  seed_context_path "$rel"
done

if [[ -f "$runtime_script_dir/ticket_run.py" ]]; then
  mkdir -p "$(dirname "$worktree_ticket_state_snapshot_path")"
  if DIFFMOGGER_TICKET_STATE_DIRECT=1 python3 "$runtime_script_dir/ticket_run.py" "$target_abs" snapshot --json >"$worktree_ticket_state_snapshot_path"; then
    cp "$worktree_ticket_state_snapshot_path" "$ticket_state_snapshot_path"
  else
    printf 'WARN: failed to write ticket-state readonly snapshot for %s run %s; role may fall back to canonical state reads.\n' "$role" "$run_id" >&2
    rm -f "$worktree_ticket_state_snapshot_path"
  fi
fi

export PLAYWRIGHT_MCP_OUTPUT_DIR="${PLAYWRIGHT_MCP_OUTPUT_DIR:-$worktree_dir/$playwright_artifact_rel}"
export DIFFMOGGER_TICKET_STATE_ACTIONS_PATH="$worktree_ticket_state_actions_path"
export DIFFMOGGER_TICKET_STATE_READONLY_SNAPSHOT="$worktree_ticket_state_snapshot_path"

CODEX_ROLE_ARGS=(--add-dir "$HOME/.codex")
toml_quote() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '"%s"' "$value"
}

append_context7_mcp_args() {
  CODEX_ROLE_ARGS+=(
    -c 'mcp_servers.context7.command="npx"'
    -c 'mcp_servers.context7.args=["-y","@upstash/context7-mcp"]'
    -c 'mcp_servers.context7.enabled=true'
    -c 'mcp_servers.context7.required=false'
    -c 'mcp_servers.context7.startup_timeout_sec=20'
    -c 'mcp_servers.context7.tool_timeout_sec=60'
    -c 'mcp_servers.context7.env_vars=["CONTEXT7_API_KEY"]'
  )
}

append_playwright_mcp_args() {
  CODEX_ROLE_ARGS+=(
    -c 'mcp_servers.playwright.command="bash"'
    -c "mcp_servers.playwright.args=[$(toml_quote "$playwright_mcp_rel")]"
    -c 'mcp_servers.playwright.enabled=true'
    -c 'mcp_servers.playwright.required=false'
    -c 'mcp_servers.playwright.disabled_tools=["browser_run_code_unsafe","browser_file_upload"]'
    -c 'mcp_servers.playwright.startup_timeout_sec=20'
    -c 'mcp_servers.playwright.tool_timeout_sec=60'
    -c "mcp_servers.playwright.env.PLAYWRIGHT_MCP_OUTPUT_DIR=$(toml_quote "$PLAYWRIGHT_MCP_OUTPUT_DIR")"
  )
  if [[ -n "${PLAYWRIGHT_MCP_EXECUTABLE_PATH:-}" ]]; then
    CODEX_ROLE_ARGS+=(
      -c "mcp_servers.playwright.env.PLAYWRIGHT_MCP_EXECUTABLE_PATH=$(toml_quote "$PLAYWRIGHT_MCP_EXECUTABLE_PATH")"
    )
  fi
}

if [[ -f "$worktree_dir/$mcp_config_rel" ]]; then
  CODEX_ROLE_ARGS+=(
    -c 'mcp_servers.context7.enabled=false'
    -c 'mcp_servers.playwright.enabled=false'
  )
  if [[ "$role" == "planner" || "$role" == "builder" ]] && grep -q "mcp_servers.context7" "$worktree_dir/$mcp_config_rel"; then
    append_context7_mcp_args
  fi
  if [[ "$role" == "hardener" || "$role" == "integrator" ]] && grep -q "mcp_servers.playwright" "$worktree_dir/$mcp_config_rel"; then
    append_playwright_mcp_args
  fi
fi

python3 - "$target_abs" "$runtime_state_start_path" "${runtime_state_paths[@]}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
output = Path(sys.argv[2])
paths = sys.argv[3:]

def sha256(path: Path):
    if not path.exists() or not path.is_file() or path.is_symlink():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

snapshot = {"schema_version": 1, "files": {}}
for rel in paths:
    path = target / rel
    snapshot["files"][rel] = {
        "exists": path.exists() and path.is_file() and not path.is_symlink(),
        "sha256": sha256(path),
    }
output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

if [[ "$role" == "hardener" ]]; then
  python3 - "$target_abs" "$hardener_deferred_context_path" "$hardener_queue_root" "${CONVEYOR_DECISION_REASON:-}" <<'PY'
import json
import re
import sys
from pathlib import Path
from typing import Any

target = Path(sys.argv[1])
output = Path(sys.argv[2])
queue = Path(sys.argv[3])
decision_reason = sys.argv[4] if len(sys.argv) > 4 else ""

TICKET_RE = re.compile(r"(?<![\w-])#\d+\b|\b[A-Z][A-Z0-9]{0,12}-\d+\b")
TEST_RATIONALE_RE = re.compile(r"test\s+change\s+rationale", re.IGNORECASE)


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def clean(value: Any, *, limit: int = 480) -> str:
    text = " ".join(str(value or "").split())
    if str(target):
        text = text.replace(str(target), "<target>")
    if len(text) > limit:
        return text[: max(0, limit - 3)].rstrip() + "..."
    return text


def changed_files(manifest: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    files: list[str] = []
    for key in ("changed_files", "runtime_state_changed_files"):
        raw = manifest.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                files.append(text)
    return files


def ticket_tokens(*values: Any) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in TICKET_RE.findall(str(value or "")):
            normalized = token.upper()
            if normalized not in seen:
                seen.add(normalized)
                tokens.append(token)
    return tokens


def field(manifest: dict[str, Any], name: str) -> str:
    return clean(manifest.get(name), limit=700)


records: list[dict[str, Any]] = []
for path in sorted(queue.glob("*/manifest.json")):
    manifest = load_json(path)
    if not manifest or manifest.get("status") != "deferred":
        continue
    if str(manifest.get("role") or "hardener") != "hardener":
        continue
    files = changed_files(manifest)
    haystack = "\n".join(
        [
            str(manifest.get("summary") or ""),
            str(manifest.get("deferral_detail") or ""),
            str(manifest.get("deferral_root_cause") or ""),
            "\n".join(files),
        ]
    )
    tokens = ticket_tokens(haystack)
    lowered_reason = decision_reason.lower()
    matches_decision = any(token.lower() in lowered_reason for token in tokens)
    matches_decision = matches_decision or any(file_name.lower() in lowered_reason for file_name in files)
    matches_decision = matches_decision or any(Path(file_name).name.lower() in lowered_reason for file_name in files)
    records.append(
        {
            "path": path,
            "manifest": manifest,
            "files": files,
            "tokens": tokens,
            "matches_decision": matches_decision,
            "created_at": str(manifest.get("created_at") or ""),
            "run_id": str(manifest.get("run_id") or path.parent.name),
        }
    )

records.sort(key=lambda item: (item["matches_decision"], item["created_at"], item["run_id"]), reverse=True)
records = records[:8]
matching = [item for item in records if item["matches_decision"]]
missing_rationale = any(
    TEST_RATIONALE_RE.search(
        "\n".join(
            [
                str(item["manifest"].get("deferral_detail") or ""),
                str(item["manifest"].get("deferral_root_cause") or ""),
                str(item["manifest"].get("summary") or ""),
            ]
        )
    )
    for item in records
)

lines = [
    "## Recent Deferred Hardener Patch Context",
    "",
    f"- current_conveyor_reason: {clean(decision_reason, limit=700) or 'not provided'}",
    f"- deferred_hardener_patches_considered: {len(records)}",
    f"- matching_current_ticket_or_files: {'yes' if matching else 'no'}",
]

if not records:
    lines.extend(
        [
            "- retry_context: No recent deferred hardener patches found.",
            "",
        ]
    )
else:
    lines.extend(
        [
            "- retry_context: Review these deferrals before choosing hardener work. If the current ticket, cluster, or files overlap a deferral, repair the deferral reason first or explicitly skip/defer that ticket with a concise blocker.",
        ]
    )
    if missing_rationale:
        lines.extend(
            [
                "- required_summary_line_when_touching_tests: `Test change rationale: <one concise reason this preserves or improves meaningful coverage>`",
                "- missing_test_change_rationale_deferral_detected: yes; include that exact summary line in `summary.md` whenever this hardener run touches tests.",
            ]
        )
    lines.append("")
    for index, item in enumerate(records, start=1):
        manifest = item["manifest"]
        reason = field(manifest, "deferral_reason") or "other"
        root_cause = field(manifest, "deferral_root_cause") or "not recorded"
        detail = field(manifest, "deferral_detail") or "not recorded"
        files = item["files"]
        tokens = item["tokens"]
        lines.extend(
            [
                f"### Deferred hardener patch {index}: {clean(item['run_id'], limit=120)}",
                "",
                f"- matches_current_ticket_or_files: {'yes' if item['matches_decision'] else 'no'}",
                f"- manifest_path: {clean(item['path'].relative_to(target).as_posix(), limit=240)}",
                f"- deferral_reason: {reason}",
                f"- deferral_root_cause: {root_cause}",
                f"- deferral_detail: {detail}",
                f"- changed_files: {clean(', '.join(files) if files else 'none recorded', limit=500)}",
                f"- ticket_or_cluster_tokens: {clean(', '.join(tokens) if tokens else 'none recorded', limit=240)}",
                "- hardener_retry_instruction: Correct the deferral reason before making another normal attempt on overlapping work; otherwise skip/defer the ticket with a concise blocker.",
                "",
            ]
        )

output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
fi

{
  cat "$prompt_path"
  if [[ "$role" == "hardener" && -s "$hardener_deferred_context_path" ]]; then
    printf '\n'
    cat "$hardener_deferred_context_path"
  fi
  cat <<EOF

## Canonical State Brief

Before changing files, read this generated SQLite-derived brief:

\`\`\`text
$state_brief_rel
\`\`\`

Treat it as a bounded generated view, not editable authority. If it conflicts with Markdown or JSON projections, reconcile through the target-local Diffmogger typed state APIs.

## Runtime Summary Contract

Before your final response, write a concise Markdown summary to this exact file:

\`\`\`text
$worktree_summary_path
\`\`\`

Start the file with this exact commit-intent block so the integrator can create useful semantic commits:

\`\`\`text
Commit type: <feat|fix|docs|test|refactor|chore|build|ci|perf|style>
Commit scope: <short-kebab-case-scope>
Commit subject: <imperative subject without type/scope, 72 chars or less>
\`\`\`

Then add short \`## Summary\` and \`## Checks\` sections. The commit subject must describe the actual user-visible, code, test, validation, or docs change. Do not use generic subjects such as \`integrate $role work\`, \`document automation progress\`, \`update files\`, or \`changes\`.

When this work intentionally repairs a failing clean-HEAD full-suite baseline, add:

\`\`\`text
Verification scope: baseline_repair
\`\`\`

If you are the hardener and you add, remove, substantially rewrite, broaden, or otherwise touch tests, add:

\`\`\`text
Test change rationale: <one concise reason this preserves or improves meaningful coverage>
\`\`\`

Do not remove or weaken tests merely to make verification pass.
EOF
} >"$runtime_prompt_path"

watchdog_helper="$runtime_script_dir/run_process_watchdog.py"

run_with_watchdog() {
  local stdout_file="$1"
  local stderr_file="$2"
  local status_file="$3"
  shift 3
  python3 "$watchdog_helper" \
    --stdout-file "$stdout_file" \
    --stderr-file "$stderr_file" \
    --status-file "$status_file" \
    -- "$@"
}

append_watchdog_status() {
  local status_file="$1"
  local log_file="$2"
  if [[ -f "$status_file" ]]; then
    {
      printf '\n=== process watchdog status ===\n'
      cat "$status_file"
    } >>"$log_file"
  fi
}

set +e
regenerate_state_brief
seed_context_path "$state_brief_rel"
run_with_watchdog "$run_stdout" "$run_stderr" "$watchdog_status_path" \
  codex exec --full-auto --skip-git-repo-check "${CODEX_ROLE_ARGS[@]}" -C "$worktree_dir" "$(cat "$runtime_prompt_path")"
codex_status=$?
set -e
append_watchdog_status "$watchdog_status_path" "$run_stderr"
critical_stop_detected=0
detect_critical_stop() {
  python3 - "$1" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
try:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
except OSError:
    raise SystemExit(1)

seen = 0
for raw in lines:
    line = raw.strip()
    if not line:
        continue
    cleaned = line.lstrip("#>*- `\t_").strip("*_` ")
    if re.match(r"^CRITICAL_STOP(?:\b|[^\w])", cleaned):
        raise SystemExit(0)
    seen += 1
    if seen >= 20:
        break
raise SystemExit(1)
PY
}
if detect_critical_stop "$run_stdout" || detect_critical_stop "$run_stderr"; then
  critical_stop_detected=1
  if [[ "$codex_status" == "0" ]]; then
    codex_status=90
  fi
fi

if [[ "$codex_status" != "0" && "$codex_status" != "124" && "$critical_stop_detected" != "1" && -f "$runtime_script_dir/repair_environment.py" ]]; then
  repair_status=0
  python3 "$runtime_script_dir/repair_environment.py" "$target_abs" \
    --command "codex exec role $role" \
    --exit-code "$codex_status" \
    --stdout-file "$run_stdout" \
    --stderr-file "$run_stderr" \
    --status-file "$env_repair_path" >/dev/null 2>&1 || repair_status=$?
  if python3 - "$env_repair_path" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
if data.get("repair_performed"):
    raise SystemExit(0)
raise SystemExit(1)
PY
  then
    while IFS= read -r path_item; do
      if [[ -n "$path_item" ]]; then
        export PATH="$path_item:$PATH"
      fi
    done < <(python3 - "$env_repair_path" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in data.get("path_prepend") or []:
    print(item)
PY
)
    set +e
    regenerate_state_brief
    seed_context_path "$state_brief_rel"
    run_with_watchdog "$rerun_stdout" "$rerun_stderr" "$rerun_watchdog_status_path" \
      codex exec --full-auto --skip-git-repo-check "${CODEX_ROLE_ARGS[@]}" -C "$worktree_dir" "$(cat "$runtime_prompt_path")"
    rerun_status=$?
    set -e
    append_watchdog_status "$rerun_watchdog_status_path" "$rerun_stderr"
    final_watchdog_status_path="$rerun_watchdog_status_path"
    {
      printf '\n=== environment repair attempted; repair_status=%s ===\n' "$repair_status"
      cat "$env_repair_path"
      printf '\n=== rerun after environment repair exit=%s ===\n' "$rerun_status"
      cat "$rerun_stdout"
    } >>"$run_stdout"
    {
      printf '\n=== environment repair attempted; repair_status=%s ===\n' "$repair_status"
      cat "$env_repair_path"
      printf '\n=== rerun after environment repair exit=%s ===\n' "$rerun_status"
      cat "$rerun_stderr"
    } >>"$run_stderr"
    codex_status="$rerun_status"
    if detect_critical_stop "$rerun_stdout" || detect_critical_stop "$rerun_stderr"; then
      critical_stop_detected=1
      if [[ "$codex_status" == "0" ]]; then
        codex_status=90
      fi
    fi
  fi
fi

{
  printf '\n=== %s role run %s started from %s ===\n' "$role" "$run_id" "$base_commit"
  cat "$run_stdout"
  if [[ "$critical_stop_detected" == "1" ]]; then
    printf '\n=== %s role run %s detected CRITICAL_STOP; status=%s ===\n' "$role" "$run_id" "$codex_status"
  fi
  printf '\n=== %s role run %s exit=%s ===\n' "$role" "$run_id" "$codex_status"
} >>"$stdout_log"
{
  printf '\n=== %s role run %s started from %s ===\n' "$role" "$run_id" "$base_commit"
  cat "$run_stderr"
  if [[ "$critical_stop_detected" == "1" ]]; then
    printf '\n=== %s role run %s detected CRITICAL_STOP; status=%s ===\n' "$role" "$run_id" "$codex_status"
  fi
  printf '\n=== %s role run %s exit=%s ===\n' "$role" "$run_id" "$codex_status"
} >>"$stderr_log"
{
  cat "$run_stdout"
  cat "$run_stderr"
} >"$raw_log"

if [[ -s "$worktree_summary_path" ]]; then
  cp "$worktree_summary_path" "$summary_path"
fi

python3 - "$worktree_dir" "$runtime_state_start_path" "$runtime_state_actions_path" "$runtime_state_changed_files_path" "${runtime_state_paths[@]}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

worktree = Path(sys.argv[1])
start_path = Path(sys.argv[2])
actions_path = Path(sys.argv[3])
changed_path = Path(sys.argv[4])
paths = sys.argv[5:]

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

try:
    start = json.loads(start_path.read_text(encoding="utf-8"))
except Exception:
    start = {"files": {}}
start_files = start.get("files") if isinstance(start.get("files"), dict) else {}

actions = []
changed = []
for rel in paths:
    file_info = start_files.get(rel) if isinstance(start_files.get(rel), dict) else {}
    start_hash = file_info.get("sha256")
    path = worktree / rel
    if not path.exists() or not path.is_file() or path.is_symlink():
        continue
    data = path.read_bytes()
    end_hash = sha256_bytes(data)
    if end_hash == start_hash:
        continue
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        continue
    actions.append(
        {
            "action": "replace_file",
            "path": rel,
            "start_hash": start_hash,
            "end_hash": end_hash,
            "content": content,
        }
    )
    changed.append(rel)

actions_path.write_text(
    json.dumps({"schema_version": 1, "actions": actions}, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
changed_path.write_text("\n".join(changed) + ("\n" if changed else ""), encoding="utf-8")
PY

python3 - "$runtime_state_actions_path" "$worktree_ticket_state_actions_path" "$ticket_state_actions_path" <<'PY'
import json
import sys
from pathlib import Path

runtime_actions_path = Path(sys.argv[1])
worktree_ticket_actions_path = Path(sys.argv[2])
queue_ticket_actions_path = Path(sys.argv[3])

def load_actions(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = payload.get("actions") if isinstance(payload, dict) else None
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

runtime_actions = load_actions(runtime_actions_path)
ticket_actions = load_actions(worktree_ticket_actions_path)
if ticket_actions:
    queue_ticket_actions_path.write_text(
        json.dumps({"schema_version": 1, "actions": ticket_actions}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    runtime_actions.extend(ticket_actions)
    runtime_actions_path.write_text(
        json.dumps({"schema_version": 1, "actions": runtime_actions}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
PY

(
  cd "$worktree_dir"
  git ls-files --others --exclude-standard -z -- . "${context_excludes[@]}" >"$queue_dir/untracked_files.z"
  if [[ -s "$queue_dir/untracked_files.z" ]]; then
    xargs -0 git add -N -- <"$queue_dir/untracked_files.z"
  fi
  git diff --binary "$base_commit" -- . "${context_excludes[@]}" >"$patch_path"
  git diff --name-only "$base_commit" -- . "${context_excludes[@]}" >"$queue_dir/changed_files.txt"
)

python3 - "$summary_path" "$role" "$run_id" "$base_commit" "$codex_status" "$target_abs" "$final_watchdog_status_path" <<'PY'
import json
import re
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
role = sys.argv[2]
run_id = sys.argv[3]
base_commit = sys.argv[4]
codex_status = sys.argv[5]
target = Path(sys.argv[6])
watchdog_status_path = Path(sys.argv[7])

def scrub(text: str) -> str:
    replacements = {
        str(target): "<target>",
        str(Path.home()): "<home>",
    }
    for old, new in replacements.items():
        if old:
            text = text.replace(old, new)
    text = re.sub(r"(?<![\w.])/(?:Users|private/tmp|tmp|var/folders)/[^\s`'\"<>)]*", "<local-path>", text)
    return text

def has_commit_intent(text: str) -> bool:
    lowered = text.lower()
    return all(marker in lowered for marker in ("commit type:", "commit scope:", "commit subject:"))

if summary_path.exists():
    original = scrub(summary_path.read_text(encoding="utf-8", errors="replace"))
else:
    original = ""

if has_commit_intent(original):
    summary_path.write_text(original.rstrip() + "\n", encoding="utf-8")
    raise SystemExit(0)

subject = f"capture {role} automation output"
fallback = [
    "Commit type: chore",
    f"Commit scope: {role}",
    f"Commit subject: {subject}",
    "",
    "## Summary",
    f"- {role} role run `{run_id}` produced queue output for integrator review.",
    "",
    "## Checks",
    f"- Codex exit code: {codex_status}",
    f"- Base commit: {base_commit[:12]}",
]
try:
    watchdog = json.loads(watchdog_status_path.read_text(encoding="utf-8"))
except Exception:
    watchdog = {}
if watchdog:
    fallback.extend(
        [
            f"- Watchdog timed out: {str(bool(watchdog.get('timed_out'))).lower()}",
            f"- Watchdog terminated process group: {str(bool(watchdog.get('terminated'))).lower()}",
            f"- Watchdog status file: {scrub(str(watchdog_status_path))}",
        ]
    )
if original.strip():
    fallback.extend(["", "## Role Notes", original.strip()[:1600]])
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text("\n".join(fallback).rstrip() + "\n", encoding="utf-8")
PY

python3 - "$manifest_path" "$role" "$run_id" "$base_commit" "$patch_path" "$summary_path" "$codex_status" "$queue_dir/changed_files.txt" "$runtime_state_actions_path" "$runtime_state_changed_files_path" "$ticket_state_actions_path" "$final_watchdog_status_path" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path = Path(sys.argv[1])
role = sys.argv[2]
run_id = sys.argv[3]
base_commit = sys.argv[4]
patch_path = Path(sys.argv[5])
summary_path = Path(sys.argv[6])
exit_code = int(sys.argv[7])
changed_files_path = Path(sys.argv[8])
runtime_state_actions_path = Path(sys.argv[9])
runtime_state_changed_files_path = Path(sys.argv[10])
ticket_state_actions_path = Path(sys.argv[11])
watchdog_status_path = Path(sys.argv[12])
changed_files = [
    line.strip()
    for line in changed_files_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
] if changed_files_path.exists() else []
runtime_state_changed_files = [
    line.strip()
    for line in runtime_state_changed_files_path.read_text(encoding="utf-8").splitlines()
    if line.strip()
] if runtime_state_changed_files_path.exists() else []
summary = summary_path.read_text(encoding="utf-8", errors="replace")[:2000] if summary_path.exists() else ""
try:
    watchdog_status = json.loads(watchdog_status_path.read_text(encoding="utf-8"))
except Exception:
    watchdog_status = {}

def summary_field(field_name: str) -> str:
    prefix = f"{field_name.lower()}:"
    for raw in summary.splitlines():
        line = re.sub(r"\s+", " ", raw.strip().lstrip("#>*- \t").strip("` "))
        if line.lower().startswith(prefix):
            return line[len(prefix):].strip(" `")
    return ""

verification_scope = summary_field("Verification scope").lower().replace("-", "_")
test_change_rationale = summary_field("Test change rationale")
try:
    runtime_actions_payload = json.loads(runtime_state_actions_path.read_text(encoding="utf-8"))
except Exception:
    runtime_actions_payload = {}
runtime_state_action_count = len(
    [item for item in runtime_actions_payload.get("actions", []) if isinstance(item, dict)]
) if isinstance(runtime_actions_payload, dict) else 0
patch_empty = not patch_path.exists() or patch_path.stat().st_size == 0
runtime_state_empty = not runtime_state_changed_files and runtime_state_action_count == 0
status = "failed" if exit_code != 0 else ("skipped" if patch_empty and runtime_state_empty else "queued")
manifest = {
    "role": role,
    "run_id": run_id,
    "base_commit": base_commit,
    "head_before_integration": None,
    "status": status,
    "deferral_reason": None,
    "deferral_detail": "",
    "patch_path": str(patch_path),
    "changed_files": changed_files,
    "runtime_state_actions_path": str(runtime_state_actions_path),
    "ticket_state_actions_path": str(ticket_state_actions_path),
    "runtime_state_action_count": runtime_state_action_count,
    "runtime_state_changed_files": runtime_state_changed_files,
    "runtime_state_status": "pending" if not runtime_state_empty else "none",
    "runtime_state_results": [],
    "watchdog_status_path": str(watchdog_status_path),
    "watchdog_timed_out": bool(watchdog_status.get("timed_out")),
    "watchdog_idle_timed_out": bool(watchdog_status.get("idle_timed_out")),
    "watchdog_terminated": bool(watchdog_status.get("terminated")),
    "watchdog_killed": bool(watchdog_status.get("killed")),
    "watchdog_exit_code": watchdog_status.get("exit_code"),
    "watchdog_duration_seconds": watchdog_status.get("duration_seconds"),
    "checks_run": [],
    "verification_scope": verification_scope,
    "test_change_rationale": test_change_rationale,
    "summary": summary,
    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "integrated_at": None,
    "checkpoint_commit": None,
    "accepted_commit": None,
}
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

runtime_state_action_count="$(
  python3 - "$runtime_state_actions_path" <<'PY'
import json
import sys
from pathlib import Path
try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    payload = {}
raw = payload.get("actions") if isinstance(payload, dict) else None
print(len([item for item in raw if isinstance(item, dict)]) if isinstance(raw, list) else 0)
PY
)"
if [[ "$codex_status" != "0" ]]; then
  manifest_status="failed"
elif [[ -s "$patch_path" || -s "$runtime_state_changed_files_path" || "$runtime_state_action_count" != "0" ]]; then
  manifest_status="queued"
else
  manifest_status="skipped"
fi
printf 'ROLE_RUN role=%s run_id=%s status=%s manifest=%s\n' "$role" "$run_id" "$manifest_status" "$manifest_path"
exit "$codex_status"
