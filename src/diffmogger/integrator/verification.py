from __future__ import annotations

from .common import *
from .git_safety import git
from .queue import manifest_list

@dataclass
class VerificationResult:
    ok: bool
    checks_run: list[str]
    detail: str
    reason: str = ""
    category: str = ""
    root_cause: str = ""

@dataclass
class VerificationRepair:
    attempted: bool
    detail: str
    final_command: str | None = None
    final_result: subprocess.CompletedProcess[str] | None = None

def load_environment_repair_module() -> Any | None:
    module_path = Path(__file__).resolve().parents[1] / "runtime" / "repair_environment.py"
    if not module_path.exists():
        module_path = Path(__file__).with_name("repair_environment.py")
    if not module_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("diffmogger_repair_environment", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def clean_command_line(raw: str) -> str:
    line = raw.strip()
    line = line.removeprefix("- ").strip()
    return line

def load_command_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    commands: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = clean_command_line(raw)
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("add project-specific"):
            continue
        commands.append(line)
    return commands

def normalize_command_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_lines = [str(item) for item in value]
    elif isinstance(value, str):
        raw_lines = value.splitlines()
    else:
        return []
    commands: list[str] = []
    for raw in raw_lines:
        line = clean_command_line(raw)
        if line and not line.startswith("#"):
            commands.append(line)
    return commands

def dedupe_commands(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for command in commands:
        normalized = re.sub(r"\s+", " ", command).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(command)
    return unique

def load_full_verification_commands(target: Path) -> list[str]:
    return load_command_file(dpath(target, ".agentic/verification_commands.txt"))

def manifest_verification_scope(manifest: dict[str, Any]) -> str:
    scope = str(manifest.get("verification_scope") or manifest.get("verification_policy") or "").strip().lower()
    return scope.replace("-", "_")

def manifest_is_baseline_repair(manifest: dict[str, Any]) -> bool:
    return manifest_verification_scope(manifest) in {"baseline_repair", "baseline-repair"}

def manifest_declared_verification_commands(manifests: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for manifest in manifests:
        for field in (
            "verification_commands",
            "focused_verification_commands",
            "patch_verification_commands",
            "smoke_commands",
        ):
            commands.extend(normalize_command_list(manifest.get(field)))
    return dedupe_commands(commands)

def manifest_requires_full_verification(manifest: dict[str, Any]) -> bool:
    role = str(manifest.get("role") or "").strip().lower()
    scope = manifest_verification_scope(manifest)
    if role == "hardener" or scope == "baseline_repair":
        return True
    for field in ("requires_full_verification", "full_suite_required"):
        value = manifest.get(field)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "required"}:
            return True
    return scope in {"full", "full_suite", "required", "finalization"}

def command_selector_matches(selector: str, role: str, changed_files: list[str]) -> bool:
    selector = selector.strip()
    if not selector:
        return False
    lowered = selector.lower()
    if lowered in {"all", "*"}:
        return True
    if lowered in {"planner", "builder", "hardener"}:
        return lowered == role
    if lowered.startswith(("role:", "role=")):
        return lowered.split(":", 1)[-1].split("=", 1)[-1].strip() == role
    if lowered.startswith(("path:", "path=", "file:", "file=", "changed:", "changed=")):
        pattern = selector.split(":", 1)[-1].split("=", 1)[-1].strip()
        return any(fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("/")) for path in changed_files)
    return False

def parse_smoke_command_line(line: str, role: str, changed_files: list[str]) -> str | None:
    if "|" not in line:
        return line
    selector_text, command = line.split("|", 1)
    command = command.strip()
    selectors = [item.strip() for item in selector_text.split(",") if item.strip()]
    if command and any(command_selector_matches(selector, role, changed_files) for selector in selectors):
        return command
    return None

def load_smoke_verification_commands(target: Path, manifests: list[dict[str, Any]]) -> list[str]:
    lines = load_command_file(dpath(target, ".agentic/smoke_commands.txt"))
    if not lines or not manifests:
        return []
    commands: list[str] = []
    for manifest in manifests:
        role = str(manifest.get("role") or "").strip().lower()
        changed_files = [str(item) for item in manifest.get("changed_files") or [] if isinstance(item, str)]
        for line in lines:
            command = parse_smoke_command_line(line, role, changed_files)
            if command:
                commands.append(command)
    return dedupe_commands(commands)

def verification_plan(
    target: Path,
    manifests: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    scoped_manifests = manifest_list(manifests)
    full_commands = load_full_verification_commands(target)
    declared = manifest_declared_verification_commands(scoped_manifests)
    smoke = load_smoke_verification_commands(target, scoped_manifests)
    requires_full = manifests is None or any(manifest_requires_full_verification(manifest) for manifest in scoped_manifests)
    commands = [*declared, *smoke]
    notes: list[str] = []
    if requires_full:
        commands.extend(full_commands)
        if full_commands:
            notes.append(
                "Full-suite verification required for this role or manifest."
                if manifests is not None
                else "Full-suite verification requested directly."
            )
        else:
            notes.append("Full-suite verification was required, but .agentic/verification_commands.txt is empty or missing.")
    elif full_commands:
        roles = ", ".join(sorted({str(item.get("role") or "role") for item in scoped_manifests})) or "unspecified role"
        notes.append(
            f"Full-suite verification configured in .agentic/verification_commands.txt but not required for {roles}; using patch-scoped checks only."
        )

    commands = dedupe_commands(commands)
    if commands:
        return commands, notes
    if notes:
        return [], notes + ["No patch-scoped verification commands matched this patch."]
    return [], ["No patch-scoped verification commands configured; treated as pass."]

def root_cause_line(output: str, keywords: tuple[str, ...] = ()) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in output.splitlines()]
    lines = [line for line in lines if line]
    lowered_keywords = tuple(keyword.lower() for keyword in keywords if keyword)
    if lowered_keywords:
        for line in lines:
            lowered = line.lower()
            if any(keyword in lowered for keyword in lowered_keywords):
                return line[:400]
    for line in lines:
        if not line.startswith("$ ") and not line.startswith("exit="):
            return line[:400]
    return (lines[0] if lines else "No failure detail recorded.")[:400]

def missing_verification_config_text(output: str) -> bool:
    lowered = output.lower()
    # Patch-scoped verification can legitimately note that the full-suite file
    # exists but is not required. That note must not masquerade as missing config.
    lowered = re.sub(
        r"full-suite verification configured in\s+\.agentic/verification_commands\.txt\s+but\s+not\s+required[^\n]*",
        "",
        lowered,
    )
    config_marker = (
        ".agentic/verification_commands.txt" in lowered
        or "verification_commands.txt" in lowered
        or "verification config" in lowered
        or "verification configuration" in lowered
    )
    if not config_marker:
        return False
    config_subject = r"(?:\.agentic/verification_commands\.txt|verification_commands\.txt|verification config(?:uration)?)"
    missing_state = r"(?:empty|missing|required[- ]but[- ](?:empty|missing))"
    return bool(
        re.search(fr"{config_subject}[^\n]{{0,240}}{missing_state}", lowered)
        or re.search(fr"{missing_state}[^\n]{{0,240}}{config_subject}", lowered)
        or re.search(r"\bmissing verification config(?:uration)?\b", lowered)
    )

def classify_failure_text(command: str, output: str) -> tuple[str, str]:
    lowered = output.lower()
    if missing_verification_config_text(output):
        return "missing_verification_config", ".agentic/verification_commands.txt is required but empty or missing."
    if TYPESCRIPT_COMPILER_ERROR_RE.search(output):
        return "typescript_compiler_error", root_cause_line(output, ("error ts", "ts"))
    if local_database_unavailable_text(command, output):
        return "missing_local_database", root_cause_line(
            output,
            ("can't reach database", "connection refused", "econnrefused", "p1001", "postgres", "database"),
        )
    env_var_match = re.search(
        r"\b([A-Z][A-Z0-9_]{2,})\b[^\n]{0,100}(?:not set|missing|required|undefined|not found)",
        output,
    ) or re.search(
        r"(?:missing|required|undefined|not found)[^\n]{0,100}\b([A-Z][A-Z0-9_]{2,})\b",
        output,
        re.IGNORECASE,
    )
    if env_var_match and env_var_match.group(1) != env_var_match.group(1).upper():
        env_var_match = None
    if env_var_match:
        name = env_var_match.group(1)
        return "missing_env_var", f"Missing required environment variable `{name}`."
    if "database_url" in lowered:
        return "missing_env_var", "Missing required environment variable `DATABASE_URL`."
    if any(marker in lowered for marker in ("no module named pytest", "pytest: command not found", "pytest: not found")):
        return "missing_pytest", "Missing pytest in the verification environment."
    if re.search(r"(command not found|not found:|no such file or directory|could not determine executable)", lowered):
        return "missing_package_executable", root_cause_line(output, ("command not found", "not found", "executable"))
    if any(
        marker in lowered
        for marker in (
            "relation does not exist",
            "no such table",
            "schema drift",
            "database schema",
            "migration",
            "prisma migrate",
            "p2021",
            "p2022",
            "p3005",
        )
    ):
        return "db_schema_drift", root_cause_line(output, ("schema", "relation", "table", "migration", "prisma"))
    if any(marker in lowered for marker in ("gemini", "openai", "anthropic", "provider", "mock")):
        return "provider_mock_failure", root_cause_line(output, ("gemini", "openai", "anthropic", "provider", "mock"))
    if any(marker in lowered for marker in ("assertionerror", "expected", "received", "failed", "failures:")):
        return "test_assertion_failure", root_cause_line(output, ("assert", "expected", "received", "failed"))
    if "git apply" in lowered or "patch failed" in lowered:
        return "apply_conflict", root_cause_line(output, ("git apply", "patch failed", "conflict"))
    return "other", root_cause_line(output)

def classify_deferral_cause(reason: str, detail: str) -> tuple[str, str]:
    if reason == "staleness":
        return "stale_patch", root_cause_line(detail, ("no longer matches", "stale", "base"))
    if reason == "conflict":
        return "apply_conflict", root_cause_line(detail, ("conflict", "patch failed", "git apply"))
    if reason == "guardrail_violation":
        return "guardrail_violation", root_cause_line(detail, ("guardrail", "unsafe", "rejected"))
    category, root_cause = classify_failure_text("", detail)
    return category, root_cause

def local_database_unavailable_text(command: str, output: str) -> bool:
    text = f"{command}\n{output}".lower()
    database_markers = (
        "can't reach database server",
        "cannot reach database server",
        "could not connect to server",
        "connection refused",
        "econnrefused",
        "p1001",
        "is the server running",
        "server closed the connection unexpectedly",
    )
    if not any(marker in text for marker in database_markers):
        return False
    return any(marker in text for marker in ("postgres", "postgresql", "prisma", "database_url", "localhost", "127.0.0.1"))

def verification_reason_for_category(category: str) -> str:
    return "verification_environment_failure" if category in ENVIRONMENT_FAILURE_CATEGORIES else "verification_failure"

def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout + "\n" + result.stderr).strip()

def command_uses_pytest(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    if "pytest" in command:
        return True
    return any(token == "pytest" for token in tokens)

def missing_pytest_failure(command: str, output: str) -> bool:
    if not command_uses_pytest(command) and "pytest" not in output:
        return False
    lowered = output.lower()
    return any(
        marker in lowered
        for marker in [
            "no module named pytest",
            "no module named 'pytest'",
            "pytest: command not found",
            "pytest: not found",
        ]
    )

def quote_command(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)

def pytest_args_from_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    if not tokens:
        return []
    if Path(tokens[0]).name == "pytest":
        return tokens[1:]
    for index, token in enumerate(tokens[:-1]):
        if token == "-m" and tokens[index + 1] == "pytest":
            return tokens[index + 2 :]
    return []

def pytest_command_for_python(target: Path, python_path: Path, original_command: str) -> str:
    args = pytest_args_from_command(original_command)
    notifier_dir = target / "services" / "agentic-notifier"
    if not args and notifier_dir.exists() and "agentic-notifier" in python_path.as_posix():
        args = ["services/agentic-notifier"]
    return quote_command([str(python_path), "-m", "pytest", *args])

def python_can_import(python_path: Path, module: str) -> bool:
    result = run([str(python_path), "-c", f"import {module}"], cwd=python_path.parent)
    return result.returncode == 0

def existing_venv_pythons(target: Path) -> list[Path]:
    candidates: list[Path] = [
        target / "services" / "agentic-notifier" / ".venv" / "bin" / "python",
        target / ".venv" / "bin" / "python",
    ]
    services_dir = target / "services"
    if services_dir.exists():
        candidates.extend(sorted(services_dir.glob("*/.venv/bin/python")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve() if candidate.exists() else candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(candidate)
    return unique

def git_ignores_path(target: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(target)
    except ValueError:
        return False
    result = git(target, "check-ignore", "-q", "--", rel.as_posix())
    return result.returncode == 0

def requirements_for_pytest_repair(target: Path) -> list[tuple[Path, Path]]:
    candidates: list[tuple[Path, Path]] = []
    notifier_requirements = target / "services" / "agentic-notifier" / "requirements.txt"
    if notifier_requirements.exists():
        candidates.append((notifier_requirements, notifier_requirements.parent / ".venv"))
    root_requirements = target / "requirements.txt"
    if root_requirements.exists():
        candidates.append((root_requirements, runtime_path(target, "target/automation_venvs") / "root"))
    services_dir = target / "services"
    if services_dir.exists():
        for requirements in sorted(services_dir.glob("*/requirements.txt")):
            item = (requirements, requirements.parent / ".venv")
            if item not in candidates:
                candidates.append(item)
    return candidates

def create_ignored_venv(target: Path) -> tuple[Path | None, str]:
    notes: list[str] = []
    for requirements, venv_dir in requirements_for_pytest_repair(target):
        if not git_ignores_path(target, venv_dir):
            notes.append(f"skipped {venv_dir.relative_to(target)} because it is not ignored by repo policy")
            continue
        python_path = venv_dir / "bin" / "python"
        if python_path.exists() and python_can_import(python_path, "pytest"):
            notes.append(f"using existing local ignored venv at {venv_dir.relative_to(target)}")
            return python_path, "; ".join(notes)
        if not python_path.exists():
            create = run([sys.executable, "-m", "venv", str(venv_dir)], cwd=target)
            if create.returncode != 0:
                notes.append(f"venv creation failed for {venv_dir.relative_to(target)}: {combined_output(create)}")
                continue
        install = run([str(python_path), "-m", "pip", "install", "-r", str(requirements)], cwd=target)
        if install.returncode != 0:
            notes.append(
                f"dependency install failed for {requirements.relative_to(target)}: {combined_output(install)}"
            )
            continue
        if python_can_import(python_path, "pytest"):
            notes.append(f"created local ignored venv from {requirements.relative_to(target)}")
            return python_path, "; ".join(notes)
        notes.append(f"installed {requirements.relative_to(target)} but pytest is still unavailable")
    return None, "; ".join(notes) if notes else "no requirements file with an ignored local venv location was found"

def attempt_verification_repair(
    target: Path,
    command: str,
    result: subprocess.CompletedProcess[str],
) -> VerificationRepair | None:
    output = combined_output(result)
    if not missing_pytest_failure(command, output):
        return None

    notes = ["detected missing pytest in the verification environment"]
    for python_path in existing_venv_pythons(target):
        if not python_path.exists() or not os.access(python_path, os.X_OK):
            continue
        if not python_can_import(python_path, "pytest"):
            notes.append(f"{python_path.relative_to(target)} exists but cannot import pytest")
            continue
        final_command = pytest_command_for_python(target, python_path, command)
        final_result = run(["/bin/bash", "-lc", final_command], cwd=target)
        notes.append(f"reran verification with existing local venv {python_path.relative_to(target)}")
        return VerificationRepair(
            attempted=True,
            detail="; ".join(notes),
            final_command=final_command,
            final_result=final_result,
        )

    python_path, create_detail = create_ignored_venv(target)
    notes.append(create_detail)
    if python_path is None:
        return VerificationRepair(attempted=True, detail="; ".join(note for note in notes if note))
    final_command = pytest_command_for_python(target, python_path, command)
    final_result = run(["/bin/bash", "-lc", final_command], cwd=target)
    notes.append(f"reran verification with local ignored venv {python_path.relative_to(target)}")
    return VerificationRepair(
        attempted=True,
        detail="; ".join(note for note in notes if note),
        final_command=final_command,
        final_result=final_result,
    )

def run_verification(
    target: Path,
    manifests: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> VerificationResult:
    commands, plan_notes = verification_plan(target, manifests)
    if any(note.startswith("Full-suite verification was required") for note in plan_notes):
        detail = "\n".join(plan_notes)
        return VerificationResult(
            ok=False,
            checks_run=plan_notes,
            detail=detail,
            reason="verification_environment_failure",
            category="missing_verification_config",
            root_cause=".agentic/verification_commands.txt is required for this role but is empty or missing.",
        )
    if not commands:
        return VerificationResult(
            ok=True,
            checks_run=plan_notes,
            detail="\n".join(plan_notes),
        )
    repair_module = load_environment_repair_module()
    if repair_module is not None:
        checks_run: list[str] = [*plan_notes]
        details: list[str] = [*plan_notes]
        for command in commands:
            outcome = repair_module.run_command_with_repair(target, command)
            checks_run.extend(str(item) for item in outcome.checks_run())
            details.append(outcome.detail())
            if not outcome.ok:
                detail = "\n\n".join(details)
                category, root_cause = classify_failure_text(command, detail)
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail=detail,
                    reason=verification_reason_for_category(category),
                    category=category,
                    root_cause=root_cause,
                )
        return VerificationResult(ok=True, checks_run=checks_run, detail="\n\n".join(details))

    checks_run: list[str] = [*plan_notes]
    details: list[str] = [*plan_notes]
    for command in commands:
        result = run(["/bin/bash", "-lc", command], cwd=target)
        checks_run.append(command)
        output = combined_output(result)
        details.append(f"$ {command}\nexit={result.returncode}\n{output}".strip())
        if result.returncode != 0:
            repair = attempt_verification_repair(target, command, result)
            if repair is None:
                detail = "\n\n".join(details)
                category, root_cause = classify_failure_text(command, detail)
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail=detail,
                    reason=verification_reason_for_category(category),
                    category=category,
                    root_cause=root_cause,
                )
            checks_run.append(f"verification repair: {repair.detail}")
            details.append(f"verification repair: {repair.detail}")
            if repair.final_command is None or repair.final_result is None:
                detail = "\n\n".join(details)
                category, root_cause = classify_failure_text(command, detail)
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail=detail,
                    reason=verification_reason_for_category(category),
                    category=category,
                    root_cause=root_cause,
                )
            checks_run.append(repair.final_command)
            final_output = combined_output(repair.final_result)
            details.append(
                f"$ {repair.final_command}\nexit={repair.final_result.returncode}\n{final_output}".strip()
            )
            if repair.final_result.returncode != 0:
                detail = "\n\n".join(details)
                category, root_cause = classify_failure_text(repair.final_command, detail)
                return VerificationResult(
                    ok=False,
                    checks_run=checks_run,
                    detail=detail,
                    reason=verification_reason_for_category(category),
                    category=category,
                    root_cause=root_cause,
                )
    return VerificationResult(ok=True, checks_run=checks_run, detail="\n\n".join(details))
