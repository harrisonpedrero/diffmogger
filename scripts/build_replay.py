#!/usr/bin/env python3
"""Build a standalone Diffmogger demo replay video from read-only history."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except ModuleNotFoundError:  # Pillow is only required when rendering video frames.
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]


DEFAULT_REPO = Path.cwd()
DEFAULT_OUT = Path("target/demo_replay")

WIDTH = 1920
HEIGHT = 1080
FPS = 24
INTRO_SECONDS = 3.0
OUTRO_SECONDS = 4.0

BG = (13, 17, 20)
PANEL = (29, 36, 41)
PANEL_DARK = (18, 23, 27)
PANEL_EDGE = (47, 56, 64)
TEXT = (244, 241, 235)
MUTED = (176, 181, 183)
SUBTLE = (121, 130, 135)
GREEN = (92, 214, 139)
GREEN_DARK = (31, 60, 45)
BLUE = (109, 165, 255)
BLUE_DARK = (28, 49, 82)
YELLOW = (236, 186, 77)
YELLOW_DARK = (73, 57, 26)
RED = (244, 107, 105)
CYAN = (79, 211, 223)
PURPLE = (168, 139, 250)

ROLE_COLORS = {
    "planner": (185, 193, 194),
    "builder": BLUE,
    "hardener": GREEN,
    "integrator": CYAN,
}

STATUS_COLORS = {
    "running": GREEN,
    "accepted": GREEN,
    "built": BLUE,
    "hardened": GREEN,
    "planned": (185, 193, 194),
    "deferred": YELLOW,
    "no progress": YELLOW,
    "retry": RED,
    "skipped": MUTED,
}

CONVENTIONAL_SUBJECT_RE = re.compile(
    r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([a-z0-9-]+\))?!?: .+"
)


@dataclass
class ReplayEvent:
    time: datetime
    role: str
    status: str
    title: str
    detail: str
    reason: str
    accepted_delta: int = 0
    deferred_delta: int = 0
    exit_code: int | None = None
    progress_success: bool | None = None
    accepted_by_role: dict[str, int] | None = None
    deferred_by_role: dict[str, int] | None = None
    run_id: str = ""

    def to_json(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["time"] = self.time.isoformat()
        return data


def parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def run_local_git(repo: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return ""


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if ImageFont is None:
        return None  # type: ignore[return-value]
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


FONT_REG = "/System/Library/Fonts/SFNS.ttf"
FONT_MONO = "/System/Library/Fonts/SFNSMono.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


class Fonts:
    title = load_font(FONT_BOLD, 64)
    h1 = load_font(FONT_BOLD, 42)
    h2 = load_font(FONT_BOLD, 28)
    h3 = load_font(FONT_BOLD, 22)
    body = load_font(FONT_REG, 24)
    body_bold = load_font(FONT_BOLD, 24)
    small = load_font(FONT_REG, 19)
    small_bold = load_font(FONT_BOLD, 19)
    tiny = load_font(FONT_REG, 15)
    mono = load_font(FONT_MONO, 18)
    number = load_font(FONT_BOLD, 54)
    huge = load_font(FONT_BOLD, 86)


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int, max_lines: int = 4) -> list[str]:
    words = text.replace("\n", " ").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_size(draw, candidate, font)[0] <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(word[: max(8, width // 12)])
            current = ""
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        joined = " ".join(lines)
        if len(joined) < len(text):
            lines[-1] = lines[-1].rstrip(" .,;:") + "..."
    return lines


def ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> str:
    if text_size(draw, text, font)[0] <= width:
        return text
    suffix = "..."
    clipped = text
    while clipped and text_size(draw, clipped.rstrip() + suffix, font)[0] > width:
        clipped = clipped[:-1]
    return clipped.rstrip(" .,;:") + suffix if clipped else suffix


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int] = TEXT,
    anchor: str | None = None,
) -> None:
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int = 18,
    fill: tuple[int, int, int] = PANEL,
    outline: tuple[int, int, int] = PANEL_EDGE,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    font: ImageFont.ImageFont = Fonts.small_bold,
) -> tuple[int, int, int, int]:
    tw, th = text_size(draw, text, font)
    pad_x, pad_y = 13, 6
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    bg = tuple(max(0, int(c * 0.24)) for c in color)
    draw.rounded_rectangle(box, radius=15, fill=bg, outline=color, width=1)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=color)
    return box


def draw_panel_header(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    x1, y1, x2, _ = box
    draw.rounded_rectangle((x1, y1, x2, y1 + 48), radius=18, fill=(34, 42, 48), outline=PANEL_EDGE)
    draw.rectangle((x1, y1 + 28, x2, y1 + 48), fill=(34, 42, 48))
    draw.text((x1 + 18, y1 + 15), title.upper(), font=Fonts.small_bold, fill=MUTED)


def extract_horizon_transitions(repo: Path) -> list[dict[str, str]]:
    path = repo / "docs" / "CODEX_AUTOMATION_TASKS.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    transitions = []
    pattern = re.compile(
        r"- (?P<ts>\d{4}-\d{2}-\d{2}T[0-9:+-]+): advanced from (?P<from>.+?) to (?P<to>.+?)\. Evidence: (?P<evidence>.*?)(?=\n- \d{4}|\n## |\Z)",
        re.S,
    )
    for match in pattern.finditer(text):
        evidence = " ".join(match.group("evidence").split())
        transitions.append(
            {
                "time": match.group("ts"),
                "from": match.group("from"),
                "to": match.group("to"),
                "evidence": evidence,
            }
        )
    return transitions


def parse_current_task_state(repo: Path) -> dict[str, str]:
    path = repo / "docs" / "CODEX_AUTOMATION_TASKS.md"
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    fields = {
        "current_horizon": "Autonomous local replay",
        "horizon_goal": "Show the automation making reviewable progress.",
        "suggested_task": "Keep converting local history into visible momentum.",
        "best_next_milestone": "Replay real role handoffs, integrations, and horizon advances.",
    }
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- Current horizon:"):
            fields["current_horizon"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("- Horizon goal:"):
            fields["horizon_goal"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("## Suggested Next Sprint-Sized Task"):
            current = "suggested_task"
        elif stripped.startswith("## Best Next Milestone"):
            current = "best_next_milestone"
        elif stripped.startswith("## "):
            current = None
        elif current and stripped and not stripped.startswith("-"):
            fields[current] = stripped
            current = None
    return fields


def load_conveyor_events(repo: Path) -> list[ReplayEvent]:
    state_path = repo / "target" / "automation_conveyor_state.json"
    if not state_path.exists():
        return []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    events: list[ReplayEvent] = []
    for item in state.get("history", []):
        role = item.get("role", "unknown")
        meta = item.get("metadata") or {}
        exit_code = item.get("exit_code")
        progress = item.get("progress_success")
        accepted_delta = int(meta.get("accepted_delta") or 0)
        deferred_delta = int(meta.get("deferred_delta") or 0)
        reason = item.get("reason") or ""
        if role == "integrator":
            if accepted_delta:
                status = "accepted"
                title = f"Integrator accepted {accepted_delta} patch" + ("" if accepted_delta == 1 else "es")
            elif deferred_delta:
                status = "deferred"
                title = f"Integrator deferred {deferred_delta} patch" + ("" if deferred_delta == 1 else "es")
            else:
                status = "no progress" if not progress else "accepted"
                title = "Integrator checked the queue"
        elif exit_code not in (0, None):
            status = "retry"
            title = f"{role.title()} needs retry"
        elif role == "builder":
            status = "built"
            title = "Builder produced a patch"
        elif role == "hardener":
            status = "hardened"
            title = "Hardener verified the lane"
        elif role == "planner":
            status = "planned"
            title = "Planner refreshed the plan"
        else:
            status = "skipped"
            title = f"{role.title()} completed"
        detail_parts = []
        if accepted_delta:
            by_role = meta.get("accepted_by_role") or {}
            winners = [f"{k}: {v}" for k, v in by_role.items() if v]
            if winners:
                detail_parts.append("accepted by role: " + ", ".join(winners))
        if deferred_delta:
            detail_parts.append("deferred: " + str(deferred_delta))
        if not detail_parts and reason:
            detail_parts.append(reason)
        events.append(
            ReplayEvent(
                time=parse_time(item.get("finished_at") or item.get("started_at")),
                role=role,
                status=status,
                title=title,
                detail="; ".join(detail_parts),
                reason=reason,
                accepted_delta=accepted_delta,
                deferred_delta=deferred_delta,
                exit_code=exit_code,
                progress_success=progress,
                accepted_by_role=meta.get("accepted_by_role") or {},
                deferred_by_role=meta.get("deferred_by_role") or {},
            )
        )
    active = state.get("active_role_run")
    if active:
        role = active.get("role", "unknown")
        events.append(
            ReplayEvent(
                time=parse_time(active.get("started_at")),
                role=role,
                status="running",
                title=f"{role.title()} is running now",
                detail=active.get("reason") or "active conveyor role",
                reason=active.get("reason") or "",
                run_id=active.get("run_id") or "",
            )
        )
    return sorted(events, key=lambda event: event.time)


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
    if path.endswith("run_conveyor_automation.py"):
        return "conveyor scheduler"
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
    if "agentic_dashboard/app.py" in path:
        return "dashboard app surface"
    if "agentic-notifier" in path:
        return "notifier guardrails"
    if path.endswith("README.md"):
        return "public docs"
    if path.startswith("docs/"):
        return "operator docs"
    if path.startswith("templates/"):
        return "generated target mirror"
    return classify_path(path)


def infer_commit_summary(subject: str, files: list[dict[str, Any]], symbols: list[str]) -> str:
    paths = [item["path"] for item in files]
    joined = "\n".join(paths)
    if "check_required_files.py" in joined and "test_check_required_files.py" in joined:
        return "Added generated-target contract checks and wired them into validation."
    if "check_integration_safety.py" in joined:
        return "Added local integration-safety guardrails with regression coverage."
    if "agentic_dashboard/app.py" in joined:
        return "Expanded dashboard controls/status around integration safety."
    if "run_role_automation.sh" in joined and "integrate_role_outputs.py" in joined:
        return "Patched runtime-state handoff so ignored automation state reaches main."
    if "run_observatory.py" in joined and "test_run_observatory.py" in joined:
        return "Expanded observatory self-review/reporting with matching tests."
    if "run_conveyor_automation.py" in joined and "test_run_conveyor_automation.py" in joined:
        return "Improved conveyor scheduling behavior and covered it with tests."
    if paths and all(path.startswith("docs/") or path.endswith(".md") for path in paths):
        return "Updated durable operator documentation and planning state."
    if symbols:
        return f"Introduced code paths: {', '.join(symbols[:3])}."
    return subject.replace("codex/integrator: ", "").replace("codex/hotfix: ", "").capitalize()


def semantic_headline(subject: str) -> str:
    if CONVENTIONAL_SUBJECT_RE.match(subject):
        return subject
    role_match = re.search(r"accept ([a-z]+) patch", subject)
    if role_match:
        return f"{role_match.group(1).title()} patch landed"
    if "hotfix" in subject:
        return "Live hotfix landed"
    return subject


def parse_numstat(repo: Path, commit_hash: str) -> list[dict[str, Any]]:
    output = run_local_git(repo, ["show", "--format=", "--numstat", "--no-renames", commit_hash])
    files: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_s, del_s, path = parts[0], parts[1], parts[2]
        additions = 0 if add_s == "-" else int(add_s or 0)
        deletions = 0 if del_s == "-" else int(del_s or 0)
        files.append(
            {
                "path": path,
                "additions": additions,
                "deletions": deletions,
                "area": classify_path(path),
                "label": describe_path(path),
            }
        )
    files.sort(key=lambda item: item["additions"] + item["deletions"], reverse=True)
    return files


def parse_added_symbols(repo: Path, commit_hash: str) -> list[str]:
    try:
        patch = run_local_git(repo, ["show", "--format=", "--unified=0", "--no-renames", commit_hash])
    except Exception:
        return []
    symbols: list[str] = []
    for line in patch.splitlines():
        if not line.startswith("+"):
            continue
        text = line[1:].strip()
        match = re.match(r"(def|class) ([A-Za-z_][A-Za-z0-9_]*)", text)
        if match:
            label = match.group(2)
            if label not in symbols:
                symbols.append(label)
        if len(symbols) >= 6:
            break
    return symbols


def load_commits(repo: Path) -> list[dict[str, Any]]:
    output = run_local_git(repo, ["log", "--date=iso-strict", "--pretty=format:%h%x09%cI%x09%s", "--max-count=120"])
    commits: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        commit_hash, commit_time, subject = parts
        files = parse_numstat(repo, commit_hash)
        symbols = parse_added_symbols(repo, commit_hash)
        run_match = re.search(r"(20\d{6}T\d{6}Z-conveyor-[a-z]+)", subject)
        role_match = re.search(r"accept ([a-z]+) patch", subject)
        additions = sum(item["additions"] for item in files)
        deletions = sum(item["deletions"] for item in files)
        commits.append(
            {
                "hash": commit_hash,
                "time": commit_time,
                "subject": subject,
                "headline": semantic_headline(subject),
                "run_id": run_match.group(1) if run_match else "",
                "role": role_match.group(1) if role_match else ("hotfix" if "hotfix" in subject else "commit"),
                "files": files,
                "file_count": len(files),
                "additions": additions,
                "deletions": deletions,
                "symbols": symbols,
                "summary": infer_commit_summary(subject, files, symbols),
            }
        )
    commits.reverse()
    return commits


def build_data(repo: Path) -> dict[str, Any]:
    events = load_conveyor_events(repo)
    if not events:
        events = [
            ReplayEvent(
                time=datetime.now(timezone.utc),
                role="conveyor",
                status="skipped",
                title="No conveyor events recorded yet",
                detail="Run the conveyor once to populate the replay timeline.",
                reason="No conveyor state file was found.",
            )
        ]
    commits = load_commits(repo)
    horizons = extract_horizon_transitions(repo)
    task_state = parse_current_task_state(repo)
    state_path = repo / "target" / "automation_conveyor_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    return {
        "repo": str(repo),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": [event.to_json() for event in events],
        "commits": commits,
        "horizons": horizons,
        "task_state": task_state,
        "cycles": state.get("cycles", len(events)),
        "active_role_run": state.get("active_role_run"),
        "role_counts": state.get("role_counts") or {},
    }


def event_state(data: dict[str, Any], index: int) -> dict[str, Any]:
    events = data["events"][: index + 1]
    role_runs = {role: 0 for role in ["planner", "builder", "hardener", "integrator"]}
    accepted_by_role = {role: 0 for role in ["planner", "builder", "hardener"]}
    deferred_by_role = {role: 0 for role in ["planner", "builder", "hardener"]}
    accepted_total = 0
    deferred_total = 0
    no_progress = 0
    for event in events:
        role = event["role"]
        if role in role_runs and event["status"] != "running":
            role_runs[role] += 1
        accepted_total += int(event.get("accepted_delta") or 0)
        deferred_total += int(event.get("deferred_delta") or 0)
        if event.get("status") == "no progress":
            no_progress += 1
        for key, value in (event.get("accepted_by_role") or {}).items():
            if key in accepted_by_role:
                accepted_by_role[key] += int(value or 0)
        for key, value in (event.get("deferred_by_role") or {}).items():
            if key in deferred_by_role:
                deferred_by_role[key] += int(value or 0)
    current = data["events"][index]
    now = parse_time(current["time"])
    commits = [commit for commit in data["commits"] if parse_time(commit["time"]) <= now]
    horizons = [h for h in data["horizons"] if parse_time(h["time"]) <= now]
    current_horizon = horizons[-1]["to"] if horizons else "H1 Runnable baseline"
    artifact_mix = {key: 0 for key in ["scripts", "tests", "docs", "templates", "services", "other"]}
    for commit in commits:
        subject = str(commit.get("subject", ""))
        if not (subject.startswith("codex/") or CONVENTIONAL_SUBJECT_RE.match(subject)):
            continue
        for file_info in commit.get("files") or []:
            area = file_info.get("area") or "other"
            artifact_mix[area if area in artifact_mix else "other"] += 1
    current_work = None
    for commit in reversed(commits):
        subject = str(commit.get("subject", ""))
        if subject.startswith("codex/") or CONVENTIONAL_SUBJECT_RE.match(subject):
            current_work = commit
            break
    return {
        "role_runs": role_runs,
        "accepted_by_role": accepted_by_role,
        "deferred_by_role": deferred_by_role,
        "accepted_total": accepted_total,
        "deferred_total": deferred_total,
        "no_progress": no_progress,
        "current": current,
        "commits": commits,
        "commit_count": len(
            [
                c
                for c in commits
                if c["subject"].startswith("codex/") or CONVENTIONAL_SUBJECT_RE.match(c["subject"])
            ]
        ),
        "current_horizon": current_horizon,
        "horizons": horizons,
        "cycle": min(data.get("cycles") or len(events), max(1, index + 1)),
        "artifact_mix": artifact_mix,
        "current_work": current_work,
    }


def background_base() -> Image.Image:
    cached = getattr(background_base, "_cached", None)
    if cached is not None:
        return cached.copy()
    image = Image.new("RGBA", (WIDTH, HEIGHT), BG + (255,))
    draw = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = y / HEIGHT
        r = int(BG[0] + 7 * t)
        g = int(BG[1] + 10 * t)
        b = int(BG[2] + 13 * t)
        draw.line((0, y, WIDTH, y), fill=(r, g, b, 255))
    background_base._cached = image
    return image.copy()


def draw_background(image: Image.Image, frame: int, total_frames: int) -> None:
    image.alpha_composite(background_base())
    pulse_x = int(120 + (WIDTH - 240) * (frame / max(1, total_frames - 1)))
    for radius, alpha in [(280, 24), (190, 24), (120, 32)]:
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse(
            (pulse_x - radius, 230 - radius, pulse_x + radius, 230 + radius),
            fill=(24, 112, 96, alpha),
        )
        image.alpha_composite(overlay)


def draw_intro(draw: ImageDraw.ImageDraw, alpha: float) -> None:
    title = "Diffmogger Autonomous Build Log"
    subtitle = "A real local automation run, reconstructed from conveyor history, manifests, git commits, and diff stats."
    draw.text((70, 46), title, font=Fonts.title, fill=TEXT)
    draw.text((74, 122), subtitle, font=Fonts.body, fill=MUTED)
    chip(draw, 1548, 64, "READ ONLY", GREEN)
    chip(draw, 1696, 64, "NO RESTART", BLUE)


def draw_mission_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], data: dict[str, Any], state: dict[str, Any]) -> None:
    rounded(draw, box)
    draw_panel_header(draw, box, "Mission State")
    x1, y1, x2, y2 = box
    y = y1 + 78
    chip(draw, x1 + 22, y, "ACTIVE", GREEN)
    chip(draw, x1 + 118, y, "LOCAL-FIRST", CYAN)
    y += 62
    draw.text((x1 + 24, y), "Current horizon", font=Fonts.small_bold, fill=TEXT)
    y += 34
    draw.text((x1 + 24, y), ellipsize(draw, state["current_horizon"], Fonts.h2, x2 - x1 - 48), font=Fonts.h2, fill=TEXT)
    y += 58
    draw.text((x1 + 24, y), "Mission", font=Fonts.small_bold, fill=TEXT)
    y += 33
    mission = data["task_state"].get("horizon_goal") or "Turn repeated Codex runs into compounding, reviewable local progress."
    for line in wrap(draw, mission, Fonts.body, x2 - x1 - 48, max_lines=4):
        draw.text((x1 + 24, y), line, font=Fonts.body, fill=MUTED)
        y += 31
    y += 22
    draw.text((x1 + 24, y), "Live counters", font=Fonts.small_bold, fill=TEXT)
    y += 34
    cards = [
        ("Cycles", str(state["cycle"]), CYAN),
        ("Accepted", str(state["accepted_total"]), GREEN),
        ("Commits", str(state["commit_count"]), BLUE),
        ("Deferred", str(state["deferred_total"]), YELLOW if state["deferred_total"] else MUTED),
    ]
    card_w = (x2 - x1 - 62) // 2
    for idx, (label, value, color) in enumerate(cards):
        cx = x1 + 24 + (idx % 2) * (card_w + 14)
        cy = y + (idx // 2) * 122
        rounded(draw, (cx, cy, cx + card_w, cy + 104), radius=12, fill=PANEL_DARK, outline=PANEL_EDGE)
        draw.text((cx + 16, cy + 15), value, font=Fonts.number, fill=color)
        draw.text((cx + 16, cy + 69), label, font=Fonts.small, fill=MUTED)


def draw_conveyor(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], state: dict[str, Any], frame: int) -> None:
    rounded(draw, box)
    draw_panel_header(draw, box, "Conveyor Belt")
    x1, y1, x2, y2 = box
    roles = ["planner", "builder", "hardener", "integrator"]
    current = state["current"]
    active_role = current["role"]
    card_gap = 18
    card_w = (x2 - x1 - 48 - card_gap * 3) // 4
    card_h = 180
    card_y = y1 + 78
    centers = []
    for idx, role in enumerate(roles):
        cx = x1 + 24 + idx * (card_w + card_gap)
        centers.append((cx + card_w // 2, card_y + card_h // 2))
        color = ROLE_COLORS[role]
        active = role == active_role
        outline = color if active else PANEL_EDGE
        fill = (18, 25, 24) if active else PANEL_DARK
        width = 3 if active else 1
        rounded(draw, (cx, card_y, cx + card_w, card_y + card_h), radius=16, fill=fill, outline=outline, width=width)
        draw.text((cx + 18, card_y + 22), role.title(), font=Fonts.h2, fill=TEXT)
        status = "RUNNING" if active and current["status"] == "running" else ("ACTIVE" if active else "STANDBY")
        chip(draw, cx + 18, card_y + 72, status, color if active else MUTED, Fonts.tiny)
        draw.text((cx + 18, card_y + 116), "runs", font=Fonts.tiny, fill=SUBTLE)
        draw.text((cx + 82, card_y + 116), str(state["role_runs"].get(role, 0)), font=Fonts.small_bold, fill=TEXT)
        if role != "integrator":
            draw.text((cx + 18, card_y + 146), "accepted", font=Fonts.tiny, fill=SUBTLE)
            draw.text((cx + 105, card_y + 146), str(state["accepted_by_role"].get(role, 0)), font=Fonts.small_bold, fill=GREEN)
        else:
            draw.text((cx + 18, card_y + 146), "landed", font=Fonts.tiny, fill=SUBTLE)
            draw.text((cx + 86, card_y + 146), str(state["accepted_total"]), font=Fonts.small_bold, fill=GREEN)
    line_y = card_y + card_h + 44
    draw.line((x1 + 58, line_y, x2 - 58, line_y), fill=(52, 70, 77), width=6)
    t = (frame % 96) / 96
    dot_x = int((x1 + 58) + (x2 - x1 - 116) * t)
    draw.ellipse((dot_x - 13, line_y - 13, dot_x + 13, line_y + 13), fill=GREEN, outline=(176, 255, 198), width=2)
    for c1, c2 in zip(centers, centers[1:]):
        ax = (c1[0] + c2[0]) // 2
        draw.polygon([(ax - 8, line_y - 14), (ax + 12, line_y), (ax - 8, line_y + 14)], fill=SUBTLE)
    run_box = (x1 + 24, y2 - 102, x2 - 24, y2 - 26)
    rounded(draw, run_box, radius=14, fill=(24, 44, 36), outline=(54, 97, 70))
    draw.text((run_box[0] + 18, run_box[1] + 15), "Running now" if current["status"] == "running" else "Latest role event", font=Fonts.small_bold, fill=GREEN)
    draw.text((run_box[0] + 18, run_box[1] + 43), current["title"], font=Fonts.body, fill=TEXT)
    detail = current["detail"] or current["reason"]
    detail_x = run_box[0] + 360
    detail_text = ellipsize(draw, detail, Fonts.small, run_box[2] - detail_x - 18)
    draw.text((detail_x, run_box[1] + 43), detail_text, font=Fonts.small, fill=MUTED)


def draw_story_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], data: dict[str, Any], state: dict[str, Any], event_index: int) -> None:
    rounded(draw, box)
    draw_panel_header(draw, box, "Progress Story")
    x1, y1, x2, y2 = box
    current = state["current"]
    color = STATUS_COLORS.get(current["status"], GREEN)
    y = y1 + 76
    draw.text((x1 + 24, y), current["title"], font=Fonts.h1, fill=TEXT)
    chip(draw, x2 - 172, y + 4, current["status"].upper(), color)
    y += 58
    for line in wrap(draw, current["detail"] or current["reason"], Fonts.body, x2 - x1 - 62, max_lines=3):
        draw.text((x1 + 24, y), line, font=Fonts.body, fill=MUTED)
        y += 31
    y += 20
    work = state.get("current_work")
    if work:
        draw.text((x1 + 24, y), "Latest landed work", font=Fonts.small_bold, fill=TEXT)
        chip_text = f"{work.get('file_count', 0)} files  +{work.get('additions', 0)} / -{work.get('deletions', 0)}"
        chip(draw, x2 - 230, y - 5, chip_text, BLUE, Fonts.tiny)
        y += 32
        for line in wrap(draw, work.get("headline") or "Commit landed", Fonts.h2, x2 - x1 - 70, max_lines=2):
            draw.text((x1 + 24, y), line, font=Fonts.h2, fill=TEXT)
            y += 32
        y += 6
        for line in wrap(draw, work.get("summary") or work.get("subject") or "", Fonts.small, x2 - x1 - 64, max_lines=2):
            draw.text((x1 + 24, y), line, font=Fonts.small, fill=MUTED)
            y += 25
        y += 6
        top_files = list(work.get("files") or [])[:3]
        for file_info in top_files:
            if y + 25 > y2 - 18:
                break
            stat = f"+{file_info.get('additions', 0)} / -{file_info.get('deletions', 0)}"
            label = file_info.get("label") or file_info.get("area") or "change"
            path = file_info.get("path") or ""
            draw.text((x1 + 36, y), stat, font=Fonts.mono, fill=GREEN)
            draw.text((x1 + 145, y), ellipsize(draw, label, Fonts.small_bold, 235), font=Fonts.small_bold, fill=TEXT)
            draw.text((x1 + 410, y), ellipsize(draw, Path(path).name, Fonts.tiny, x2 - x1 - 440), font=Fonts.tiny, fill=SUBTLE)
            y += 25
        y += 14

    milestones = data.get("horizons", [])
    if milestones and y + 92 <= y2 - 18:
        draw.text((x1 + 24, y), "Horizon advances", font=Fonts.small_bold, fill=TEXT)
        y += 34
        start_x = x1 + 28
        end_x = x2 - 28
        line_y = y + 18
        draw.line((start_x, line_y, end_x, line_y), fill=(48, 59, 66), width=4)
        visible = state["horizons"]
        for idx, h in enumerate(milestones):
            px = start_x + int((end_x - start_x) * ((idx + 1) / max(1, len(milestones))))
            done = h in visible
            c = GREEN if done else (62, 72, 78)
            draw.ellipse((px - 10, line_y - 10, px + 10, line_y + 10), fill=c)
            label = re.match(r"(H\d+)", h["to"])
            draw.text((px - 16, line_y + 18), label.group(1) if label else "H?", font=Fonts.tiny, fill=MUTED if done else SUBTLE)
        y += 58


def draw_feed(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], data: dict[str, Any], event_index: int) -> None:
    rounded(draw, box)
    draw_panel_header(draw, box, "Landed Work")
    x1, y1, x2, y2 = box
    state = event_state(data, event_index)
    feed = [
        commit
        for commit in state["commits"]
        if str(commit.get("subject", "")).startswith("codex/")
        or CONVENTIONAL_SUBJECT_RE.match(str(commit.get("subject", "")))
    ][-7:]
    y = y1 + 72
    for commit in reversed(feed):
        role = commit.get("role") or "commit"
        color = ROLE_COLORS.get(role, PURPLE if role == "hotfix" else BLUE)
        item_h = 112
        rounded(draw, (x1 + 18, y, x2 - 18, y + item_h), radius=13, fill=PANEL_DARK, outline=PANEL_EDGE)
        title_lines = wrap(draw, commit.get("headline") or "Commit landed", Fonts.small_bold, x2 - x1 - 68, max_lines=2)
        for idx, line in enumerate(title_lines):
            draw.text((x1 + 34, y + 13 + idx * 22), line, font=Fonts.small_bold, fill=TEXT)
        meta_y = y + 41 + max(0, len(title_lines) - 1) * 22
        chip(draw, x2 - 132, meta_y - 8, commit.get("hash", ""), color, Fonts.tiny)
        ts = parse_time(commit["time"]).strftime("%H:%M:%S UTC")
        draw.text((x1 + 34, meta_y), ts, font=Fonts.tiny, fill=SUBTLE)
        stats = f"{commit.get('file_count', 0)} files  +{commit.get('additions', 0)} / -{commit.get('deletions', 0)}"
        draw.text((x1 + 150, meta_y), stats, font=Fonts.small, fill=GREEN)
        files = commit.get("files") or []
        if files:
            top = files[0]
            detail = f"{top.get('label')}: {top.get('path')}"
        else:
            detail = commit.get("summary") or commit.get("subject") or ""
        draw.text((x1 + 34, meta_y + 26), ellipsize(draw, detail, Fonts.tiny, x2 - x1 - 68), font=Fonts.tiny, fill=MUTED)
        y += item_h + 13
        if y + item_h > y2 - 20:
            break


def draw_footer(draw: ImageDraw.ImageDraw, frame: int, total_frames: int, event_index: int, event_count: int) -> None:
    x1, y = 56, 1010
    x2 = WIDTH - 56
    draw.line((x1, y, x2, y), fill=(48, 58, 64), width=8)
    p = frame / max(1, total_frames - 1)
    draw.line((x1, y, int(x1 + (x2 - x1) * p), y), fill=GREEN, width=8)
    draw.ellipse((int(x1 + (x2 - x1) * p) - 9, y - 9, int(x1 + (x2 - x1) * p) + 9, y + 9), fill=TEXT)
    label = f"event {event_index + 1} / {event_count}"
    draw.text((x2, y + 18), label, font=Fonts.tiny, fill=SUBTLE, anchor="ra")


def render_frames(data: dict[str, Any], out_dir: Path, duration: float) -> int:
    frames_dir = out_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    event_count = max(1, len(data["events"]))
    total_frames = int(duration * FPS)
    intro_frames = int(INTRO_SECONDS * FPS)
    outro_frames = int(OUTRO_SECONDS * FPS)
    event_frames = max(1, total_frames - intro_frames - outro_frames)
    for frame in range(total_frames):
        image = Image.new("RGBA", (WIDTH, HEIGHT), BG + (255,))
        data["canvas"] = image
        draw_background(image, frame, total_frames)
        draw = ImageDraw.Draw(image)
        if frame < intro_frames:
            event_index = 0
        elif frame >= total_frames - outro_frames:
            event_index = event_count - 1
        else:
            p = (frame - intro_frames) / max(1, event_frames)
            event_index = min(event_count - 1, int(p * event_count))
        state = event_state(data, event_index)
        draw_intro(draw, 1.0)
        draw_mission_panel(draw, (56, 155, 510, 930), data, state)
        draw_conveyor(draw, (540, 155, 1396, 574), state, frame)
        draw_story_panel(draw, (540, 602, 1396, 930), data, state, event_index)
        draw_feed(draw, (1426, 155, 1866, 930), data, event_index)
        draw_footer(draw, frame, total_frames, event_index, event_count)
        image.convert("RGB").save(frames_dir / f"frame_{frame:05d}.jpg", quality=92, subsampling=0)
    return total_frames


def encode_video(out_dir: Path, fps: int = FPS) -> Path:
    video_path = out_dir / "diffmogger_demo_replay_detailed.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(out_dir / "frames" / "frame_%05d.jpg"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-movflags",
        "+faststart",
        str(video_path),
    ]
    subprocess.check_call(cmd)
    return video_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--duration", type=float, default=72.0)
    parser.add_argument("--skip-frames", action="store_true")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    data = build_data(args.repo)
    data_path = args.out / "replay-data.json"
    data_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    if not args.skip_frames:
        if Image is None:
            raise SystemExit("Pillow is required to render replay frames. Install pillow or run with --skip-frames.")
        total_frames = render_frames(data, args.out, args.duration)
        video = encode_video(args.out)
        print(f"events={len(data['events'])}")
        print(f"frames={total_frames}")
        print(f"data={data_path}")
        print(f"video={video}")
    else:
        print(f"events={len(data['events'])}")
        print(f"data={data_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
