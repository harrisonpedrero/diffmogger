#!/usr/bin/env bash
set -euo pipefail

target="."
mode="campaign-cycle"
run_id="local-cycle"
max_fanout="${DIFFMOGGER_MAX_FANOUT:-3}"
download_dest_dir="${DIFFMOGGER_TEMPORAL_DOWNLOAD_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      target="${2:?missing --target value}"
      shift 2
      ;;
    --temporal)
      mode="temporal-cycle"
      shift
      ;;
    --run-id)
      run_id="${2:?missing --run-id value}"
      shift 2
      ;;
    --max-fanout)
      max_fanout="${2:?missing --max-fanout value}"
      shift 2
      ;;
    --download-dest-dir)
      download_dest_dir="${2:?missing --download-dest-dir value}"
      shift 2
      ;;
    --once|--policy)
      mode="policy-cycle"
      shift
      ;;
    --campaign)
      mode="campaign-cycle"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target_abs="$(cd "$target" && pwd)"
lib_dir="$target_abs/.diffmogger/lib"

if [[ -d "$lib_dir" ]]; then
  export PYTHONPATH="$lib_dir${PYTHONPATH:+:$PYTHONPATH}"
fi

candidate_pythons=()
if [[ -n "${DIFFMOGGER_PYTHON:-}" ]]; then
  candidate_pythons+=("$DIFFMOGGER_PYTHON")
fi
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  candidate_pythons+=("$VIRTUAL_ENV/bin/python")
fi
candidate_pythons+=(
  "$target_abs/.venv/bin/python"
  "$target_abs/.diffmogger/runtime/automation_venvs/diffmogger/bin/python"
  "$target_abs/.diffmogger/runtime/automation_venvs/root/bin/python"
  "python3"
)

python_bin=""
for candidate in "${candidate_pythons[@]}"; do
  if ! command -v "$candidate" >/dev/null 2>&1 && [[ ! -x "$candidate" ]]; then
    continue
  fi
  if "$candidate" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys
missing = [name for name in ("pydantic", "temporalio") if importlib.util.find_spec(name) is None]
raise SystemExit(1 if missing else 0)
PY
  then
    python_bin="$candidate"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  python_bin="${DIFFMOGGER_PYTHON:-python3}"
fi

args=("$mode" "--target" "$target_abs" "--run-id" "$run_id" "--max-fanout" "$max_fanout")
if [[ "$mode" == "temporal-cycle" && -n "$download_dest_dir" ]]; then
  args+=("--download-dest-dir" "$download_dest_dir")
fi
exec "$python_bin" -m diffmogger.orchestration.cli "${args[@]}"
