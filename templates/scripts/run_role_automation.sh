#!/usr/bin/env bash
set -euo pipefail

export PATH="${CODEX_AUTOMATION_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

usage() {
  cat <<'EOF'
Usage: scripts/run_role_automation.sh --role planner|builder|hardener|integrator [--target PATH]

Run one optional multi-role automation role. Planner, builder, and hardener run
inside isolated git worktrees and queue patches. Integrator applies queued
patches in the main checkout.

Environment:
  TARGET                    Target project directory. Default: current repo
  CODEX_RUN_ID or RUN_ID    Run id. Generated if absent
  MULTI_ROLE_ALLOW_REMOTES  Set 1 to allow configured git remotes
EOF
}

target_dir="${TARGET:-$(cd "$(dirname "$0")/.." && pwd)}"
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
cd "$target_abs"

if [[ -n "${DIFFMOGGER_BROWSER_PATH:-}" && -z "${CHROME_PATH:-}" ]]; then
  export CHROME_PATH="$DIFFMOGGER_BROWSER_PATH"
elif [[ -z "${DIFFMOGGER_BROWSER_PATH:-}" && -z "${CHROME_PATH:-}" && -f "scripts/diffmogger_browser.py" ]]; then
  browser_env="$(python3 scripts/diffmogger_browser.py env 2>/dev/null || true)"
  if [[ -n "$browser_env" ]]; then
    eval "$browser_env"
  fi
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
  "/.agentic/" \
  "/AGENTS.md" \
  "/docs/AUTOMATION_SIGNALS.md" \
  "/docs/AUTONOMY_EXPERIMENT_LOG.md" \
  "/docs/CODEX_AUTOMATION_GUARDRAILS.md" \
  "/docs/CODEX_AUTOMATION_TASKS.md" \
  "/docs/DAILY_AUTOMATION_REVIEW.md" \
  "/docs/DEVELOPMENT.md" \
  "/docs/HUMAN_BRIDGE_SETUP.md" \
  "/docs/HUMAN_INBOX.md" \
  "/docs/HUMAN_OUTBOX.md" \
  "/docs/HUMAN_REQUESTS.md" \
  "/docs/HUMAN_RESPONSES_ARCHIVE.md" \
  "/docs/INITIAL_BOOTSTRAP_PROMPT.md" \
  "/docs/MULTI_ROLE_PROGRESS.md" \
  "/docs/PROJECT_CONTEXT.md" \
  "/docs/TICKET_RUN.md" \
  "/scripts/acquire_codex_lock.sh" \
  "/scripts/__pycache__/" \
  "/scripts/build_replay.py" \
  "/scripts/compact_agent_state.py" \
  "/scripts/diffmogger_browser.py" \
  "/scripts/integrate_role_outputs.py" \
  "/scripts/list_deferred_patches.py" \
  "/scripts/release_codex_lock.sh" \
  "/scripts/repair_environment.py" \
  "/scripts/run_codex_automation.sh" \
  "/scripts/run_conveyor_automation.py" \
  "/scripts/run_conveyor_automation.sh" \
  "/scripts/run_observatory.py" \
  "/scripts/run_role_automation.sh" \
  "/scripts/spawn_worker_agent.sh" \
  "/scripts/summarize_worker_outputs.py" \
  "/scripts/ticket_run.py" \
  "/scripts/update_automation_signals.py" \
  "/target/agent_runs/" \
  "/target/automation_conveyor.lock" \
  "/target/automation_conveyor_state.json" \
  "/target/baseline_verification.json" \
  "/target/automation_logs/" \
  "/target/automation_queue/" \
  "/target/automation_signals.json" \
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

prompt_path="$target_abs/.agentic/roles/$role.md"
if [[ ! -f "$prompt_path" ]]; then
  echo "Missing role prompt: $prompt_path" >&2
  exit 2
fi

if [[ "$role" == "integrator" ]]; then
  if [[ -f "$target_abs/scripts/update_automation_signals.py" && -f "$target_abs/docs/AUTOMATION_SIGNALS.md" ]]; then
    python3 "$target_abs/scripts/update_automation_signals.py" "$target_abs" --refresh --role integrator --summary || true
  fi
  python3 scripts/integrate_role_outputs.py "$target_abs" --run-id "$run_id"
  integrator_status=$?
  if [[ "$integrator_status" -eq 0 && -f "$target_abs/scripts/ticket_run.py" ]]; then
    python3 "$target_abs/scripts/ticket_run.py" "$target_abs" should-halt --finalize || true
  fi
  exit "$integrator_status"
fi

base_commit="$(git rev-parse HEAD)"
queue_dir="$target_abs/target/automation_queue/$role/$run_id"
worktree_dir="$target_abs/target/automation_worktrees/$role/$run_id"
log_dir="$target_abs/target/automation_logs"
mkdir -p "$queue_dir" "$(dirname "$worktree_dir")" "$log_dir"

summary_path="$queue_dir/summary.md"
worktree_summary_path="$worktree_dir/target/automation_queue/$role/$run_id/summary.md"
patch_path="$queue_dir/changes.patch"
manifest_path="$queue_dir/manifest.json"
raw_log="$queue_dir/codex.raw.log"
stdout_log="$log_dir/$role.stdout.log"
stderr_log="$log_dir/$role.stderr.log"
run_stdout="$queue_dir/codex.stdout.log"
run_stderr="$queue_dir/codex.stderr.log"
runtime_prompt_path="$queue_dir/runtime_prompt.md"
env_repair_path="$queue_dir/environment_repair.json"
rerun_stdout="$queue_dir/codex.rerun.stdout.log"
rerun_stderr="$queue_dir/codex.rerun.stderr.log"

git worktree add --detach "$worktree_dir" "$base_commit" >/dev/null
mkdir -p "$(dirname "$worktree_summary_path")"

if [[ -f "$target_abs/scripts/update_automation_signals.py" && -f "$target_abs/docs/AUTOMATION_SIGNALS.md" ]]; then
  python3 "$target_abs/scripts/update_automation_signals.py" "$target_abs" --refresh --role "$role" --summary || true
fi

context_paths=(
  ".agentic/automation_prompt.md"
  ".agentic/smoke_commands.txt"
  ".agentic/verification_commands.txt"
  ".agentic/roles"
  "docs/CODEX_AUTOMATION_TASKS.md"
  "docs/MULTI_ROLE_PROGRESS.md"
  "docs/CODEX_AUTOMATION_GUARDRAILS.md"
  "docs/PROJECT_CONTEXT.md"
  "docs/AUTOMATION_SIGNALS.md"
  "docs/AUTONOMY_EXPERIMENT_LOG.md"
  "docs/DAILY_AUTOMATION_REVIEW.md"
  "docs/HUMAN_BRIDGE_SETUP.md"
  "docs/HUMAN_INBOX.md"
  "docs/HUMAN_OUTBOX.md"
  "docs/HUMAN_REQUESTS.md"
  "docs/HUMAN_RESPONSES_ARCHIVE.md"
  "target/automation_signals.json"
  "target/baseline_verification.json"
)

runtime_state_paths_path="$queue_dir/runtime_state_paths.txt"
runtime_state_start_path="$queue_dir/runtime_state_start.json"
runtime_state_actions_path="$queue_dir/runtime_state_actions.json"
runtime_state_changed_files_path="$queue_dir/runtime_state_changed_files.txt"

python3 - "$target_abs" "$runtime_state_paths_path" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1])
output = Path(sys.argv[2])
max_bytes = int(os.environ.get("RUNTIME_STATE_MAX_BYTES", "1048576"))
explicit_paths = [
    ".agentic/automation_prompt.md",
    ".agentic/smoke_commands.txt",
    ".agentic/verification_commands.txt",
    ".agentic/roles/planner.md",
    ".agentic/roles/builder.md",
    ".agentic/roles/hardener.md",
    ".agentic/roles/integrator.md",
    "docs/HUMAN_INBOX.md",
    "docs/HUMAN_RESPONSES_ARCHIVE.md",
    "docs/HUMAN_REQUESTS.md",
    "docs/HUMAN_OUTBOX.md",
    "docs/CODEX_AUTOMATION_TASKS.md",
    "docs/MULTI_ROLE_PROGRESS.md",
    "target/automation_signals.json",
]
scan_roots = [".agentic", "docs"]
allowed_prefixes = (".agentic/", "docs/")
deny_parts = {
    ".git",
    ".hg",
    ".svn",
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

{
  cat "$prompt_path"
  cat <<EOF

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

If you are the hardener and you remove obsolete tests or substantially rewrite brittle/stale tests, add:

\`\`\`text
Test change rationale: <one concise reason this preserves or improves meaningful coverage>
\`\`\`

Do not remove or weaken tests merely to make verification pass.
EOF
} >"$runtime_prompt_path"

set +e
codex exec --full-auto --skip-git-repo-check --add-dir "$HOME/.codex" -C "$worktree_dir" "$(cat "$runtime_prompt_path")" >"$run_stdout" 2>"$run_stderr"
codex_status=$?
set -e
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

if [[ "$codex_status" != "0" && "$critical_stop_detected" != "1" && -f "$target_abs/scripts/repair_environment.py" ]]; then
  repair_status=0
  python3 "$target_abs/scripts/repair_environment.py" "$target_abs" \
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
    codex exec --full-auto --skip-git-repo-check --add-dir "$HOME/.codex" -C "$worktree_dir" "$(cat "$runtime_prompt_path")" >"$rerun_stdout" 2>"$rerun_stderr"
    rerun_status=$?
    set -e
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

if [[ -f "$target_abs/scripts/update_automation_signals.py" && -f "$worktree_dir/target/automation_signals.json" ]]; then
  python3 "$target_abs/scripts/update_automation_signals.py" "$target_abs" --merge-state "$worktree_dir/target/automation_signals.json" --refresh --role "$role" --summary || true
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

(
  cd "$worktree_dir"
  git ls-files --others --exclude-standard -z -- . "${context_excludes[@]}" >"$queue_dir/untracked_files.z"
  if [[ -s "$queue_dir/untracked_files.z" ]]; then
    xargs -0 git add -N -- <"$queue_dir/untracked_files.z"
  fi
  git diff --binary "$base_commit" -- . "${context_excludes[@]}" >"$patch_path"
  git diff --name-only "$base_commit" -- . "${context_excludes[@]}" >"$queue_dir/changed_files.txt"
)

python3 - "$summary_path" "$role" "$run_id" "$base_commit" "$codex_status" "$target_abs" <<'PY'
import re
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
role = sys.argv[2]
run_id = sys.argv[3]
base_commit = sys.argv[4]
codex_status = sys.argv[5]
target = Path(sys.argv[6])

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
if original.strip():
    fallback.extend(["", "## Role Notes", original.strip()[:1600]])
summary_path.parent.mkdir(parents=True, exist_ok=True)
summary_path.write_text("\n".join(fallback).rstrip() + "\n", encoding="utf-8")
PY

python3 - "$manifest_path" "$role" "$run_id" "$base_commit" "$patch_path" "$summary_path" "$codex_status" "$queue_dir/changed_files.txt" "$runtime_state_actions_path" "$runtime_state_changed_files_path" <<'PY'
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

def summary_field(field_name: str) -> str:
    prefix = f"{field_name.lower()}:"
    for raw in summary.splitlines():
        line = re.sub(r"\s+", " ", raw.strip().lstrip("#>*- \t").strip("` "))
        if line.lower().startswith(prefix):
            return line[len(prefix):].strip(" `")
    return ""

verification_scope = summary_field("Verification scope").lower().replace("-", "_")
test_change_rationale = summary_field("Test change rationale")
patch_empty = not patch_path.exists() or patch_path.stat().st_size == 0
runtime_state_empty = not runtime_state_changed_files
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
    "runtime_state_changed_files": runtime_state_changed_files,
    "runtime_state_status": "pending" if runtime_state_changed_files else "none",
    "runtime_state_results": [],
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

if [[ "$codex_status" != "0" ]]; then
  manifest_status="failed"
elif [[ -s "$patch_path" || -s "$runtime_state_changed_files_path" ]]; then
  manifest_status="queued"
else
  manifest_status="skipped"
fi
printf 'ROLE_RUN role=%s run_id=%s status=%s manifest=%s\n' "$role" "$run_id" "$manifest_status" "$manifest_path"
exit "$codex_status"
