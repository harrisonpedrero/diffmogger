from __future__ import annotations

import tempfile

from .common import *

@dataclass
class GitIndexLockStatus:
    path: Path
    exists: bool
    age_seconds: float = 0.0
    stale_seconds: int = DEFAULT_GIT_INDEX_LOCK_STALE_SECONDS
    size: int = 0
    mtime_ns: int = 0
    inode: int = 0
    mode: int = 0
    open_processes: list[str] | None = None
    suspected_processes: list[str] | None = None
    probe_notes: list[str] | None = None
    probe_error: str = ""

    @property
    def is_regular_file(self) -> bool:
        return bool(self.mode and stat.S_ISREG(self.mode))

    @property
    def is_recent(self) -> bool:
        return self.age_seconds < self.stale_seconds

    @property
    def is_stale_unowned(self) -> bool:
        return (
            self.exists
            and self.is_regular_file
            and not self.is_recent
            and not self.open_processes
            and not self.suspected_processes
            and not self.probe_error
        )

    def active_detail(self) -> str:
        if not self.exists:
            return "no lock exists"
        details = [
            f"lock_path={self.path}",
            f"age_seconds={int(self.age_seconds)}",
            f"stale_threshold_seconds={self.stale_seconds}",
        ]
        if not self.is_regular_file:
            details.append("lock is not a regular file; refusing automatic removal")
        if self.is_recent:
            details.append("lock is recent")
        if self.open_processes:
            details.append("open_processes=" + " | ".join(self.open_processes[:5]))
        if self.suspected_processes:
            details.append("suspected_git_mutations=" + " | ".join(self.suspected_processes[:5]))
        if self.probe_error:
            details.append(f"probe_error={self.probe_error}")
        if self.probe_notes:
            details.append("probe_notes=" + " | ".join(self.probe_notes[:3]))
        return "; ".join(details)

class GitIndexLockBlocked(RuntimeError):
    def __init__(self, operation: str, status: GitIndexLockStatus):
        self.operation = operation
        self.status = status
        super().__init__(
            (
                f"Git index lock blocked `{operation}`. {status.active_detail()}. "
                "Manual action: wait for the Git operation to finish, or if no process is active, "
                f"remove `{status.path}` and rerun the integrator."
            )
        )

def git_index_lock_path(target: Path) -> Path:
    result = run(["git", "rev-parse", "--git-path", "index.lock"], cwd=target)
    raw = result.stdout.strip() if result.returncode == 0 else ""
    path = Path(raw) if raw else target / ".git" / "index.lock"
    return path if path.is_absolute() else target / path

def lsof_lock_processes(lock_path: Path) -> tuple[list[str], list[str], str]:
    lsof = shutil.which("lsof")
    if not lsof:
        return [], ["lsof unavailable; used process inspection fallback"], ""
    result = run([lsof, str(lock_path)], cwd=lock_path.parent)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    stderr = re.sub(r"\s+", " ", (result.stderr or "").strip())
    if result.returncode == 0 and len(lines) > 1:
        return lines[1:], ["lsof found lock holder(s)"], ""
    if result.returncode in {0, 1} and len(lines) <= 1 and not stderr:
        return [], ["lsof found no open file handle"], ""
    return [], ["lsof probe failed"], stderr[:300] or f"lsof exited {result.returncode}"

def proc_lock_processes(lock_path: Path) -> tuple[list[str], list[str]]:
    proc = Path("/proc")
    if not proc.exists():
        return [], ["proc fd scan unavailable"]
    try:
        lock_resolved = lock_path.resolve(strict=False)
    except OSError:
        lock_resolved = lock_path
    holders: list[str] = []
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        fd_dir = pid_dir / "fd"
        if not fd_dir.exists():
            continue
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = fd.resolve(strict=True)
            except OSError:
                continue
            if target != lock_resolved:
                continue
            cmdline = ""
            try:
                raw = (pid_dir / "cmdline").read_bytes()
                cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            except OSError:
                pass
            holders.append(f"pid={pid_dir.name} fd={fd.name} command={cmdline or '<unknown>'}"[:500])
            break
    return holders, ["proc fd scan checked lock handles"]

def lock_open_process_details(lock_path: Path) -> tuple[list[str], list[str], str]:
    lsof_holders, lsof_notes, lsof_error = lsof_lock_processes(lock_path)
    if lsof_holders:
        return lsof_holders, lsof_notes, ""
    proc_holders, proc_notes = proc_lock_processes(lock_path)
    if proc_holders:
        return proc_holders, [*lsof_notes, *proc_notes], ""
    return [], [*lsof_notes, *proc_notes], lsof_error

def ps_process_lines() -> list[tuple[int, str]]:
    commands = (
        ["ps", "-axo", "pid=,command="],
        ["ps", "-ef"],
    )
    for command in commands:
        result = run(command, cwd=Path("/"))
        if result.returncode != 0 or not result.stdout.strip():
            continue
        lines: list[tuple[int, str]] = []
        for raw in result.stdout.splitlines():
            line = raw.strip()
            if not line:
                continue
            if command == ["ps", "-ef"] and line.lower().startswith("uid "):
                continue
            parts = line.split(None, 7 if command == ["ps", "-ef"] else 1)
            try:
                pid = int(parts[1] if command == ["ps", "-ef"] else parts[0])
            except (IndexError, ValueError):
                continue
            cmd = parts[7] if command == ["ps", "-ef"] and len(parts) > 7 else (parts[1] if len(parts) > 1 else "")
            if cmd:
                lines.append((pid, cmd))
        return lines
    return []

def git_subcommand_from_process(command: str) -> tuple[str, list[str]]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for index, token in enumerate(tokens):
        if Path(token).name != "git":
            continue
        pos = index + 1
        while pos < len(tokens):
            item = tokens[pos]
            if item in {"-C", "-c", "--git-dir", "--work-tree"}:
                pos += 2
                continue
            if item.startswith(("--git-dir=", "--work-tree=")):
                pos += 1
                continue
            if item.startswith("-"):
                pos += 1
                continue
            return item, tokens[pos:]
    return "", []

def process_cwd_is_inside(pid: int, target: Path) -> bool:
    cwd_link = Path("/proc") / str(pid) / "cwd"
    if not cwd_link.exists():
        return False
    try:
        cwd = cwd_link.resolve(strict=True)
        cwd.relative_to(target.resolve())
    except (OSError, ValueError):
        return False
    return True

def command_references_repo(command: str, target: Path, git_dir: Path, lock_path: Path) -> bool:
    haystack = command.replace("\\ ", " ")
    needles = [target.as_posix(), git_dir.as_posix(), lock_path.as_posix()]
    return any(needle and needle in haystack for needle in needles)

def git_mutation_process_details(target: Path, lock_path: Path) -> list[str]:
    common_dir = run(["git", "rev-parse", "--git-common-dir"], cwd=target)
    git_dir = Path(common_dir.stdout.strip()) if common_dir.returncode == 0 and common_dir.stdout.strip() else target / ".git"
    if not git_dir.is_absolute():
        git_dir = target / git_dir
    suspects: list[str] = []
    current_pid = os.getpid()
    for pid, command in ps_process_lines():
        if pid == current_pid:
            continue
        subcommand, tokens = git_subcommand_from_process(command)
        if not subcommand or not git_args_mutate_main_checkout(tokens):
            continue
        if not (process_cwd_is_inside(pid, target) or command_references_repo(command, target, git_dir, lock_path)):
            continue
        compact = re.sub(r"\s+", " ", command).strip()
        suspects.append(f"pid={pid} command={compact[:420]}")
    return suspects

def git_index_lock_status(target: Path, stale_seconds: int) -> GitIndexLockStatus:
    lock_path = git_index_lock_path(target)
    try:
        info = lock_path.lstat()
    except FileNotFoundError:
        return GitIndexLockStatus(path=lock_path, exists=False, stale_seconds=stale_seconds)
    age = max(0.0, time.time() - info.st_mtime)
    open_processes, probe_notes, probe_error = lock_open_process_details(lock_path)
    suspected_processes = git_mutation_process_details(target, lock_path)
    return GitIndexLockStatus(
        path=lock_path,
        exists=True,
        age_seconds=age,
        stale_seconds=stale_seconds,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        inode=info.st_ino,
        mode=info.st_mode,
        open_processes=open_processes,
        suspected_processes=suspected_processes,
        probe_notes=probe_notes,
        probe_error=probe_error,
    )

def remove_stale_git_index_lock(status: GitIndexLockStatus) -> bool:
    try:
        current = status.path.lstat()
    except FileNotFoundError:
        return True
    if (
        current.st_ino != status.inode
        or current.st_mtime_ns != status.mtime_ns
        or current.st_size != status.size
        or current.st_mode != status.mode
    ):
        return False
    if not stat.S_ISREG(current.st_mode):
        return False
    status.path.unlink()
    return True

def ensure_git_index_lock_clear(
    target: Path,
    operation: str,
    *,
    stale_seconds: int | None = None,
    wait_seconds: int | None = None,
    retry_seconds: int | None = None,
) -> None:
    stale = stale_seconds if stale_seconds is not None else env_int(
        "DIFFMOGGER_GIT_INDEX_LOCK_STALE_SECONDS",
        DEFAULT_GIT_INDEX_LOCK_STALE_SECONDS,
    )
    wait = wait_seconds if wait_seconds is not None else env_int(
        "DIFFMOGGER_GIT_INDEX_LOCK_WAIT_SECONDS",
        DEFAULT_GIT_INDEX_LOCK_WAIT_SECONDS,
    )
    retry = retry_seconds if retry_seconds is not None else env_int(
        "DIFFMOGGER_GIT_INDEX_LOCK_RETRY_SECONDS",
        DEFAULT_GIT_INDEX_LOCK_RETRY_SECONDS,
    )
    deadline = time.monotonic() + wait
    while True:
        status = git_index_lock_status(target, stale)
        if not status.exists:
            return
        if status.is_stale_unowned:
            if remove_stale_git_index_lock(status):
                print(
                    f"GIT_INDEX_LOCK_STALE_REMOVED operation={operation} "
                    f"path={status.path} age_seconds={int(status.age_seconds)}",
                    file=sys.stderr,
                )
                return
            print(
                f"GIT_INDEX_LOCK_CHANGED_DURING_PREFLIGHT operation={operation} path={status.path}; retrying",
                file=sys.stderr,
            )
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GitIndexLockBlocked(operation, status)
        sleep_for = min(max(1, retry), remaining)
        print(
            f"GIT_INDEX_LOCK_WAIT operation={operation}; {status.active_detail()}; "
            f"retry_in_seconds={sleep_for:.1f}",
            file=sys.stderr,
        )
        time.sleep(sleep_for)

def git_args_mutate_main_checkout(args: tuple[str, ...] | list[str]) -> bool:
    if not args:
        return False
    command = args[0]
    if command == "apply" and "--check" in args:
        return False
    if command == "reset" and "--soft" in args:
        return False
    return command in GIT_INDEX_LOCK_MUTATING_COMMANDS

def git_operation(args: tuple[str, ...] | list[str]) -> str:
    return "git " + " ".join(shlex.quote(str(arg)) for arg in args)

def git(
    target: Path,
    *args: str,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    lock_stale_seconds: int | None = None,
    lock_wait_seconds: int | None = None,
    lock_retry_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if git_args_mutate_main_checkout(args):
        ensure_git_index_lock_clear(
            target,
            git_operation(args),
            stale_seconds=lock_stale_seconds,
            wait_seconds=lock_wait_seconds,
            retry_seconds=lock_retry_seconds,
        )
    return run(["git", *args], cwd=target, check=check, env=env, input_text=input_text)

def require_git_repo(target: Path) -> None:
    result = git(target, "rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise SystemExit(f"Multi-role integration requires an initialized git repo: {target}")

def ensure_local_only(target: Path) -> None:
    remotes = git(target, "remote", "-v").stdout.strip()
    if remotes and os.environ.get("MULTI_ROLE_ALLOW_REMOTES") != "1":
        print(
            "Multi-role automation is local-only and refuses to run with configured git remotes.",
            file=sys.stderr,
        )
        print(remotes, file=sys.stderr)
        print(
            "Set MULTI_ROLE_ALLOW_REMOTES=1 only if you intentionally allow local automation in a repo with remotes.",
            file=sys.stderr,
        )
        raise SystemExit(2)

def scan_push_hooks(target: Path) -> None:
    hooks_result = git(target, "rev-parse", "--git-path", "hooks")
    hooks_text = hooks_result.stdout.strip()
    hooks_dir = (target / hooks_text).resolve() if hooks_text else target / ".git" / "hooks"
    if not hooks_dir.exists():
        return
    offenders: list[Path] = []
    for hook in hooks_dir.iterdir():
        if hook.name.endswith(".sample"):
            continue
        if not hook.is_file() or not os.access(hook, os.X_OK):
            continue
        try:
            text = hook.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "git push" in text:
            offenders.append(hook)
    if offenders:
        print("Integrator refuses to run because executable git hooks contain `git push`:", file=sys.stderr)
        for hook in offenders:
            print(f"- {hook}", file=sys.stderr)
        raise SystemExit(2)

def update_info_exclude(target: Path, *, dry_run: bool) -> None:
    result = git(target, "rev-parse", "--git-path", "info/exclude")
    raw = result.stdout.strip() if result.returncode == 0 else ""
    exclude = Path(raw) if raw else target / ".git" / "info" / "exclude"
    if not exclude.is_absolute():
        exclude = target / exclude
    patterns = [
        "/.diffmogger/",
        "/.agentic/",
        "/.env",
        "/.env.development",
        "/.env.development.local",
        "/.env.local",
        "/apps/*/.env",
        "/apps/*/.env.development",
        "/apps/*/.env.development.local",
        "/apps/*/.env.local",
        "/AGENTS.md",
        "/docs/CODEX_AUTOMATION_GUARDRAILS.md",
        "/docs/CODEX_AUTOMATION_TASKS.md",
        "/docs/DEVELOPMENT.md",
        "/scripts/acquire_codex_lock.sh",
        "/scripts/__pycache__/",
        "/scripts/build_replay.py",
        "/scripts/compact_agent_state.py",
        "/scripts/diffmogger_browser.py",
        "/scripts/integrate_role_outputs.py",
        "/scripts/load_automation_env.py",
        "/scripts/list_deferred_patches.py",
        "/scripts/release_codex_lock.sh",
        "/scripts/repair_environment.py",
        "/scripts/run_observatory.py",
        "/scripts/run_temporal_worker.sh",
        "/scripts/run_role_automation.sh",
        "/scripts/spawn_worker_agent.sh",
        "/scripts/state_brief.py",
        "/scripts/summarize_worker_outputs.py",
        "/scripts/ticket_run.py",
        "/.diffmogger/lib/",
        "/target/agent_runs/",
        "/target/automation_logs/",
        "/target/codex_automation.lock",
        "/target/automation_venvs/",
        "/target/automation_queue/",
        "/target/automation_runner.json",
        "/target/automation_worktrees/",
        "/target/baseline_verification.json",
        "/target/canonical_state_brief.md",
        "/target/validation_jobs/",
        "/target/orchestration.sqlite3",
        "/target/orchestration.sqlite3-shm",
        "/target/orchestration.sqlite3-wal",
        "/target/prisma-cache/",
        "/target/ticket_run_completion.json",
        "/target/ticket_run_reports/",
        "/.pnpm-store/",
    ]
    manifest = load_manifest(target)
    if manifest.get("layout") == "sidecar_v1":
        for rel in manifest_path_list(manifest, "patch_exclude_paths"):
            patterns.append("/" + rel.rstrip("/") + ("/" if rel.endswith("/") else ""))
    if dry_run:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = existing.splitlines()
    changed = False
    if "# Diffmogger local automation scaffold/runtime" not in lines:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Diffmogger local automation scaffold/runtime")
        changed = True
    for pattern in patterns:
        if pattern not in lines:
            lines.append(pattern)
            changed = True
    if changed:
        exclude.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

def dirty_status(target: Path) -> str:
    return git(target, "status", "--porcelain").stdout.rstrip()

def head(target: Path) -> str:
    return git(target, "rev-parse", "HEAD", check=True).stdout.strip()

def path_exists_at_ref(target: Path, ref: str, rel_path: str) -> bool:
    result = git(target, "cat-file", "-e", f"{ref}:{rel_path}")
    return result.returncode == 0

def reset_to(target: Path, ref: str, manifests: list[dict[str, Any]], *, dry_run: bool) -> None:
    if dry_run:
        return
    git(target, "reset", "--hard", ref, check=True)
    for manifest in manifests:
        for rel in manifest.get("changed_files") or []:
            if not isinstance(rel, str) or not rel.strip():
                continue
            rel = rel.strip()
            if path_exists_at_ref(target, ref, rel):
                continue
            path = target / rel
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)

def apply_check(target: Path, patch: Path) -> subprocess.CompletedProcess[str]:
    return git(target, "apply", "--check", str(patch))

def reverse_apply_check(target: Path, patch: Path) -> subprocess.CompletedProcess[str]:
    return git(target, "apply", "--reverse", "--check", str(patch))

def apply_rebaseable_patch_file(target: Path, patch: Path, *, dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        return subprocess.CompletedProcess(["git", "apply", "--3way", str(patch)], 0, "", "")
    return git(target, "apply", "--3way", str(patch))

def apply_patch_file(target: Path, patch: Path, *, dry_run: bool) -> subprocess.CompletedProcess[str]:
    if dry_run:
        return subprocess.CompletedProcess(["git", "apply", str(patch)], 0, "", "")
    return git(target, "apply", str(patch))

def changed_since_base(target: Path, base_commit: str, current_head: str) -> set[str]:
    if not base_commit:
        return set()
    result = git(target, "diff", "--name-only", f"{base_commit}..{current_head}")
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}

INTEGRATION_RECONCILIATION_RESOLUTIONS = {
    "direct_apply",
    "already_applied",
    "rebaseable",
    "needs_reconciliation",
    "true_conflict",
}

@dataclass
class IntegrationReconciliation:
    resolution: str
    detail: str
    reason: str = ""
    apply_mode: str = "direct"
    patch_id: str = ""
    base_commit: str = ""
    head_commit: str = ""
    changed_since_base: list[str] | None = None

    @property
    def can_apply(self) -> bool:
        return self.resolution in {"direct_apply", "rebaseable"}

    @property
    def is_already_applied(self) -> bool:
        return self.resolution == "already_applied"

def commit_exists(target: Path, ref: str) -> bool:
    if not ref:
        return False
    return git(target, "cat-file", "-e", f"{ref}^{{commit}}").returncode == 0

def patch_id_from_text(target: Path, text: str) -> str:
    if not text.strip():
        return ""
    result = git(target, "patch-id", "--stable", input_text=text)
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts:
            return parts[0]
    return ""

def patch_id_for_patch(target: Path, patch: Path) -> str:
    try:
        text = patch.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return patch_id_from_text(target, text)

def patch_ids_from_log_range(target: Path, base_commit: str, current_head: str, changed_files: list[str]) -> set[str]:
    if not base_commit or base_commit == current_head:
        return set()
    args = ["log", "--format=commit %H", "--no-ext-diff", "--binary", "-p", f"{base_commit}..{current_head}"]
    if changed_files:
        args.extend(["--", *changed_files])
    log = git(target, *args)
    if log.returncode != 0 or not log.stdout.strip():
        return set()
    result = git(target, "patch-id", "--stable", input_text=log.stdout)
    if result.returncode != 0:
        return set()
    return {line.split()[0] for line in result.stdout.splitlines() if line.split()}

def aggregate_patch_id_for_range(target: Path, base_commit: str, current_head: str, changed_files: list[str]) -> str:
    if not base_commit or base_commit == current_head:
        return ""
    args = ["diff", "--binary", f"{base_commit}..{current_head}"]
    if changed_files:
        args.extend(["--", *changed_files])
    diff = git(target, *args)
    if diff.returncode != 0:
        return ""
    return patch_id_from_text(target, diff.stdout)

def patch_id_matches_head(
    target: Path,
    patch: Path,
    *,
    base_commit: str,
    current_head: str,
    changed_files: list[str],
) -> tuple[bool, str, str]:
    patch_id = patch_id_for_patch(target, patch)
    if not patch_id or not base_commit or base_commit == current_head:
        return False, patch_id, ""
    range_patch_ids = patch_ids_from_log_range(target, base_commit, current_head, changed_files)
    if patch_id in range_patch_ids:
        return True, patch_id, "stable patch-id matched a commit in base..HEAD"
    aggregate_patch_id = aggregate_patch_id_for_range(target, base_commit, current_head, changed_files)
    if aggregate_patch_id and aggregate_patch_id == patch_id:
        return True, patch_id, "stable patch-id matched the aggregate diff from base..HEAD"
    return False, patch_id, ""

def compact_git_failure(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    text = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part and part.strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1000] if text else fallback

def probe_rebaseable_with_temp_worktree(
    target: Path,
    patch: Path,
    *,
    base_commit: str,
    current_head: str,
) -> tuple[str, str]:
    temp_root = Path(tempfile.mkdtemp(prefix="diffmogger-reconcile-"))
    worktree = temp_root / "worktree"
    added = False
    try:
        add = git(target, "worktree", "add", "--detach", "--quiet", str(worktree), base_commit)
        if add.returncode != 0:
            return "needs_reconciliation", compact_git_failure(add, "could not create isolated base worktree")
        added = True
        base_check = git(worktree, "apply", "--check", str(patch))
        if base_check.returncode != 0:
            return (
                "needs_reconciliation",
                "Patch did not apply cleanly to its recorded base during isolated replay: "
                + compact_git_failure(base_check, "git apply --check failed at recorded base"),
            )
        base_apply = git(worktree, "apply", str(patch))
        if base_apply.returncode != 0:
            return (
                "needs_reconciliation",
                "Patch passed base check but failed while materializing the isolated replay: "
                + compact_git_failure(base_apply, "git apply failed at recorded base"),
            )
        if not dirty_status(worktree):
            return "already_applied", "Patch replay produced no worktree changes at its recorded base."
        git(worktree, "add", "-A", check=True)
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "Diffmogger Integrator",
                "GIT_AUTHOR_EMAIL": "diffmogger-integrator@example.invalid",
                "GIT_COMMITTER_NAME": "Diffmogger Integrator",
                "GIT_COMMITTER_EMAIL": "diffmogger-integrator@example.invalid",
            }
        )
        commit = git(worktree, "commit", "--no-verify", "-m", "diffmogger integration replay probe", env=env)
        if commit.returncode != 0:
            return "needs_reconciliation", compact_git_failure(commit, "could not commit isolated replay probe")
        replay_commit = head(worktree)
        reset = git(worktree, "reset", "--hard", current_head)
        if reset.returncode != 0:
            return "needs_reconciliation", compact_git_failure(reset, "could not reset isolated worktree to current HEAD")
        cherry = git(worktree, "cherry-pick", "--no-commit", replay_commit)
        if cherry.returncode == 0:
            return (
                "rebaseable",
                f"Patch base drifted from {base_commit} to {current_head}, but an isolated Git replay cherry-picked cleanly.",
            )
        return (
            "true_conflict",
            "Patch base drifted and isolated Git replay conflicted: "
            + compact_git_failure(cherry, "git cherry-pick --no-commit failed during isolated replay"),
        )
    finally:
        if added:
            run(["git", "worktree", "remove", "--force", str(worktree)], cwd=target)
        shutil.rmtree(temp_root, ignore_errors=True)

def classify_patch_reconciliation(
    target: Path,
    patch: Path,
    manifest: dict[str, Any],
    *,
    current_head: str,
    apply_check_result: subprocess.CompletedProcess[str] | None = None,
) -> IntegrationReconciliation:
    base_commit = str(manifest.get("base_commit") or "").strip()
    changed_files = sorted({str(item).strip() for item in manifest.get("changed_files") or [] if str(item).strip()})
    changed = sorted(changed_since_base(target, base_commit, current_head) & set(changed_files)) if base_commit else []

    reverse = reverse_apply_check(target, patch)
    if reverse.returncode == 0:
        return IntegrationReconciliation(
            resolution="already_applied",
            detail=f"git apply --reverse --check succeeded at HEAD {current_head}; patch content is already present.",
            apply_mode="none",
            base_commit=base_commit,
            head_commit=current_head,
            changed_since_base=changed,
        )

    matched, patch_id, match_detail = patch_id_matches_head(
        target,
        patch,
        base_commit=base_commit,
        current_head=current_head,
        changed_files=changed_files,
    )
    if matched:
        return IntegrationReconciliation(
            resolution="already_applied",
            detail=f"{match_detail}; patch content is already represented in HEAD {current_head}.",
            apply_mode="none",
            patch_id=patch_id,
            base_commit=base_commit,
            head_commit=current_head,
            changed_since_base=changed,
        )

    check = apply_check_result if apply_check_result is not None else apply_check(target, patch)
    if check.returncode == 0:
        resolution = "rebaseable" if changed else "direct_apply"
        drift = f" Base drift touched: {', '.join(changed)}." if changed else ""
        replay = " Patch can be replayed directly on current HEAD." if changed else ""
        return IntegrationReconciliation(
            resolution=resolution,
            detail=f"git apply --check succeeded at HEAD {current_head}.{drift}{replay}",
            apply_mode="direct",
            patch_id=patch_id,
            base_commit=base_commit,
            head_commit=current_head,
            changed_since_base=changed,
        )

    if not base_commit:
        return IntegrationReconciliation(
            resolution="needs_reconciliation",
            reason="staleness",
            apply_mode="none",
            detail="Patch failed git apply --check and did not record a base_commit. " + compact_git_failure(check, "git apply --check failed"),
            patch_id=patch_id,
            base_commit=base_commit,
            head_commit=current_head,
            changed_since_base=changed,
        )
    if not commit_exists(target, base_commit):
        return IntegrationReconciliation(
            resolution="needs_reconciliation",
            reason="staleness",
            apply_mode="none",
            detail=f"Patch failed git apply --check and recorded base_commit {base_commit} is not available in this repository. "
            + compact_git_failure(check, "git apply --check failed"),
            patch_id=patch_id,
            base_commit=base_commit,
            head_commit=current_head,
            changed_since_base=changed,
        )
    if base_commit == current_head:
        return IntegrationReconciliation(
            resolution="true_conflict",
            reason="conflict",
            apply_mode="none",
            detail="Patch failed git apply --check at its recorded base/current HEAD. "
            + compact_git_failure(check, "git apply --check failed"),
            patch_id=patch_id,
            base_commit=base_commit,
            head_commit=current_head,
            changed_since_base=changed,
        )

    replay_resolution, replay_detail = probe_rebaseable_with_temp_worktree(
        target,
        patch,
        base_commit=base_commit,
        current_head=current_head,
    )
    reason = "conflict" if replay_resolution == "true_conflict" else "staleness"
    if replay_resolution == "already_applied":
        reason = ""
    return IntegrationReconciliation(
        resolution=replay_resolution if replay_resolution in INTEGRATION_RECONCILIATION_RESOLUTIONS else "needs_reconciliation",
        reason=reason,
        apply_mode="three_way" if replay_resolution == "rebaseable" else "none",
        detail=replay_detail,
        patch_id=patch_id,
        base_commit=base_commit,
        head_commit=current_head,
        changed_since_base=changed,
    )

def classify_apply_failure(target: Path, manifest: dict[str, Any], current_head: str, stderr: str) -> tuple[str, str]:
    base_commit = str(manifest.get("base_commit") or "")
    changed_files = {str(item) for item in manifest.get("changed_files") or []}
    if base_commit and base_commit != current_head and changed_files & changed_since_base(target, base_commit, current_head):
        return "staleness", f"Patch base {base_commit} no longer matches HEAD {current_head}; touched files changed since base. {stderr.strip()}"
    return "conflict", stderr.strip() or "git apply --check failed"
