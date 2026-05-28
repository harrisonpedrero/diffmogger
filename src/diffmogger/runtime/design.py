"""Local-first design capability helpers for generated Diffmogger targets."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping


UI_CAPABILITY_MODES = ("auto", "off", "light", "full")
DESIGN_SOURCES = ("generated_contract", "figma", "existing_code")
UI_VALIDATION_MODES = ("auto", "off", "local", "external_optional")
OPTIONAL_DESIGN_SERVICES = (
    "figma_mcp",
    "v0",
    "builder_visual_copilot",
    "storybook_chromatic",
    "percy",
    "applitools",
)

UI_SCOPE_TERMS = {
    "app shell",
    "browser",
    "canvas",
    "client",
    "component",
    "css",
    "dashboard",
    "demo path",
    "dom",
    "frontend",
    "front-end",
    "html",
    "interface",
    "jsx",
    "landing page",
    "mobile",
    "next.js",
    "page",
    "react",
    "responsive",
    "route",
    "screen",
    "storybook",
    "svelte",
    "tailwind",
    "tsx",
    "ui",
    "ux",
    "view",
    "visual",
    "vue",
    "web app",
}

UI_PACKAGE_TERMS = {
    "@vitejs/plugin-react",
    "astro",
    "chakra-ui",
    "daisyui",
    "framer-motion",
    "lucide-react",
    '"next"',
    "playwright",
    "react",
    "remix",
    "storybook",
    "svelte",
    "tailwindcss",
    "vite",
    "vue",
}

UI_PATH_PATTERNS = (
    r"(^|/)(app|components|pages|routes|screens|styles|ui)(/|$)",
    r"\.(css|scss|sass|html|jsx|tsx|vue|svelte)$",
)

UI_STATE_REQUIREMENTS = (
    "loading",
    "empty",
    "error",
    "focus",
    "disabled",
    "responsive",
    "representative data density",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or default).strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in allowed else default


def normalize_design_service(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "figma": "figma_mcp",
        "figma_mcp_server": "figma_mcp",
        "builder": "builder_visual_copilot",
        "builder_io": "builder_visual_copilot",
        "builderio": "builder_visual_copilot",
        "chromatic": "storybook_chromatic",
        "storybook": "storybook_chromatic",
    }
    return aliases.get(text, text)


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = re.split(r"[\n,;|]+", value)
    else:
        raw_items = []
    items: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = re.sub(r"^[-*]\s+", "", str(raw).strip())
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items


def normalize_optional_design_services(value: Any) -> list[str]:
    enabled: list[str] = []
    seen: set[str] = set()
    for item in normalize_string_list(value):
        name = normalize_design_service(item)
        if name in {"none", "disabled", "disable", "off", "false", "no"}:
            continue
        if name in OPTIONAL_DESIGN_SERVICES and name not in seen:
            seen.add(name)
            enabled.append(name)
    return enabled


def design_settings(intake: Mapping[str, Any] | None) -> dict[str, Any]:
    data = intake or {}
    return {
        "ui_capability_mode": normalize_enum(data.get("ui_capability_mode"), UI_CAPABILITY_MODES, "auto"),
        "design_source": normalize_enum(data.get("design_source"), DESIGN_SOURCES, "generated_contract"),
        "design_reference_files": normalize_string_list(data.get("design_reference_files")),
        "design_reference_urls": normalize_string_list(data.get("design_reference_urls")),
        "ui_validation_mode": normalize_enum(data.get("ui_validation_mode"), UI_VALIDATION_MODES, "auto"),
        "optional_design_services": normalize_optional_design_services(data.get("optional_design_services")),
    }


def _text_blob(value: Any, *, limit: int = 50000) -> str:
    try:
        text = json.dumps(value, sort_keys=True)
    except TypeError:
        text = str(value)
    return text[:limit].lower()


def _has_term(text: str, terms: set[str]) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) for term in terms)


def _ticket_text(ticket: Mapping[str, Any]) -> str:
    values: list[str] = []
    for key in ("id", "summary", "title", "description", "blocker", "owner_role", "action_kind"):
        values.append(str(ticket.get(key) or ""))
    for key in ("acceptance_criteria", "verification_commands", "evidence", "paths", "changed_files"):
        raw = ticket.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        else:
            values.append(str(raw or ""))
    return "\n".join(values).lower()


def ticket_is_ui_scoped(ticket: Mapping[str, Any]) -> bool:
    text = _ticket_text(ticket)
    if _has_term(text, UI_SCOPE_TERMS):
        return True
    return any(re.search(pattern, text) for pattern in UI_PATH_PATTERNS)


def ui_detection_from_intake(
    intake: Mapping[str, Any] | None,
    *,
    tickets: list[Mapping[str, Any]] | None = None,
    file_summaries: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    data = intake or {}
    settings = design_settings(data)
    mode = settings["ui_capability_mode"]
    validation_mode = settings["ui_validation_mode"]
    reasons: list[str] = []

    if mode == "off":
        return {
            **settings,
            "ui_heavy": False,
            "designer_enabled": False,
            "ui_validation_enabled": False,
            "reasons": ["ui_capability_mode=off"],
        }

    intake_text = _text_blob(
        {
            key: data.get(key)
            for key in (
                "project_name",
                "product_goal",
                "target_user",
                "desired_first_demo",
                "tech_preferences",
                "ticket_generation_decomposition_brief",
                "ticket_generation_scope_groups",
            )
        }
    )
    if _has_term(intake_text, UI_SCOPE_TERMS):
        reasons.append("intake mentions UI/browser/frontend scope")

    ticket_count = 0
    ui_ticket_count = 0
    for ticket in tickets or []:
        ticket_count += 1
        if ticket_is_ui_scoped(ticket):
            ui_ticket_count += 1
    if ui_ticket_count:
        reasons.append(f"{ui_ticket_count} UI-scoped ticket(s)")

    package_terms: set[str] = set()
    path_terms = 0
    for summary in file_summaries or []:
        path = str(summary.get("path") or "")
        excerpt = _text_blob(summary, limit=12000)
        for package in UI_PACKAGE_TERMS:
            if package in excerpt:
                package_terms.add(package)
        if any(re.search(pattern, path.lower()) for pattern in UI_PATH_PATTERNS):
            path_terms += 1
    if package_terms:
        reasons.append("frontend package cues: " + ", ".join(sorted(package_terms)[:5]))
    if path_terms:
        reasons.append(f"{path_terms} UI path cue(s)")

    ui_heavy = bool(reasons)
    if mode == "full":
        ui_heavy = True
        reasons.insert(0, "ui_capability_mode=full")
    elif mode == "light":
        reasons.insert(0, "ui_capability_mode=light")

    designer_enabled = mode == "full" or (mode == "auto" and ui_heavy)
    validation_enabled = validation_mode in {"local", "external_optional"} or (
        validation_mode == "auto" and (ui_heavy or mode in {"full", "light"})
    )
    if validation_mode == "off":
        validation_enabled = False

    return {
        **settings,
        "ui_heavy": ui_heavy,
        "designer_enabled": designer_enabled,
        "ui_validation_enabled": validation_enabled,
        "ui_ticket_count": ui_ticket_count,
        "ticket_count": ticket_count,
        "reasons": reasons or ["no UI-heavy signal detected"],
    }


def _first_line(value: Any, fallback: str) -> str:
    for raw in normalize_string_list(value):
        text = re.sub(r"\s+", " ", raw).strip()
        if text:
            return text
    return fallback


def build_design_contract_payload(
    intake: Mapping[str, Any] | None,
    *,
    target_name: str = "",
    tickets: list[Mapping[str, Any]] | None = None,
    file_summaries: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    data = intake or {}
    detection = ui_detection_from_intake(data, tickets=tickets, file_summaries=file_summaries)
    target_user = _first_line(data.get("target_user"), "The primary user described in the intake brief.")
    product_goal = _first_line(data.get("product_goal"), "Build a useful local-first product from the intake brief.")
    demo = _first_line(data.get("desired_first_demo"), "A runnable local demo that proves the core workflow.")
    source = str(detection["design_source"])
    posture = "quiet, functional, local-first, and reviewable"
    if detection["ui_heavy"]:
        posture = "polished, consistent, task-focused, and responsive"
    workflows = [
        demo,
        "A first-run path with representative local data.",
        "A recovery path for empty, loading, error, disabled, and offline/local-fallback states.",
    ]
    return {
        "schema_version": 1,
        "contract_id": "design-contract:active",
        "version": 1,
        "status": "active",
        "source": source,
        "ui_capability_mode": detection["ui_capability_mode"],
        "ui_validation_mode": detection["ui_validation_mode"],
        "ui_heavy": detection["ui_heavy"],
        "designer_enabled": detection["designer_enabled"],
        "audience": target_user,
        "product_goal": product_goal,
        "product_posture": posture,
        "workflows": workflows,
        "information_architecture": [
            "Expose the primary workflow immediately instead of a marketing splash.",
            "Keep navigation predictable and reusable across screens.",
            "Make setup, review, and recovery paths discoverable without explanatory clutter.",
            "Keep the primary decision surface visible in the first viewport on desktop and tablet when the product is an operational dashboard.",
            "Move component galleries, validation catalogs, and implementation-state showcases to secondary developer/review routes rather than mixing them into the default product route.",
        ],
        "layout_principles": [
            "Prefer dense, scan-friendly layouts for operational tools and generous breathing room only where comprehension benefits.",
            "Use stable dimensions for boards, controls, lists, and panels so dynamic content does not shift the layout.",
            "Design mobile and desktop states deliberately; do not rely on viewport-scaled typography.",
            "Prevent clipped, overlapping, or awkwardly wrapped text with explicit min-width, max-width, overflow, and responsive wrapping rules.",
            "Avoid nested cards, beveled piles of panels, and repeated one-off borders when a simpler section, table, or rail communicates the same information.",
        ],
        "tokens": {
            "color": [
                "Define semantic surface, text, border, accent, success, warning, and danger tokens before one-off colors.",
                "Avoid one-note palettes and heavy decorative gradients unless the product domain explicitly calls for them.",
            ],
            "type": [
                "Use clear hierarchy with compact headings inside panels and hero-scale type only for true hero surfaces.",
                "Keep letter spacing at 0 unless an existing design system says otherwise.",
            ],
            "space": [
                "Use a small spacing scale and align controls to predictable grid or flex tracks.",
            ],
            "radius": [
                "Use 8px radius or less for cards and controls unless the existing design system already differs.",
            ],
        },
        "component_inventory": [
            "App shell/navigation",
            "Primary action controls",
            "Form fields and validation messages",
            "List/table/card item display",
            "Modal or detail panel when needed",
            "Loading, empty, error, focus, disabled, and success states",
        ],
        "state_matrix": list(UI_STATE_REQUIREMENTS),
        "accessibility_expectations": [
            "Keyboard focus is visible and ordered.",
            "Interactive controls have accessible names.",
            "Color contrast remains usable in normal and error states.",
            "Responsive layouts avoid clipped or overlapping text.",
        ],
        "visual_do": [
            "Reuse existing components, tokens, and interaction patterns before adding new styles.",
            "Validate UI changes with local screenshots, console checks, focus checks, and responsive viewports when tooling exists.",
            "Use representative content density rather than empty demo-only data.",
            "Preserve clear source labels when content is fixture, mock, generated, cached, imported, or live data.",
            "Iterate after viewing screenshots for desktop, tablet, and mobile states when UI polish is part of the ticket.",
        ],
        "visual_dont": [
            "Do not invent one-off styling for every ticket.",
            "Do not mark UI work clean without design review, UI visual receipt, or explicit deferred validation/setup work.",
            "Do not require external paid services or credentials for unattended local design validation.",
            "Do not let debug/state-gallery surfaces crowd the primary user workflow.",
            "Do not present fixture, mock, or synthetic content as real source-backed data.",
        ],
        "references": {
            "files": detection["design_reference_files"],
            "urls": detection["design_reference_urls"],
            "optional_services": detection["optional_design_services"],
        },
        "validation_expectations": [
            "Prefer deterministic project scripts such as npm run browser-smoke or Playwright Test when available.",
            "Use Playwright MCP as local inspection evidence when mounted.",
            "Record ui_visual validation receipts with routes, viewports, screenshots, console status, focus/interaction notes, and overflow/overlap notes.",
            "For dashboard-like products, assert that the primary work surface is reachable in the first viewport at representative desktop and tablet sizes, or document an intentional exception.",
            "When browser tooling is missing, create setup, harness, alternate-validation, or deferred-QA DAG work instead of passing silently.",
        ],
        "detection": detection,
        "updated_at": utc_now(),
    }


def design_contract_markdown(contract: Mapping[str, Any]) -> str:
    refs = contract.get("references") if isinstance(contract.get("references"), Mapping) else {}

    def bullets(items: Any) -> str:
        values = normalize_string_list(items)
        return "\n".join(f"- {item}" for item in values) if values else "- None."

    tokens = contract.get("tokens") if isinstance(contract.get("tokens"), Mapping) else {}
    token_lines: list[str] = []
    for name, values in tokens.items():
        token_lines.append(f"- {name}:")
        for value in normalize_string_list(values):
            token_lines.append(f"  - {value}")
    if not token_lines:
        token_lines.append("- None.")

    return "\n".join(
        [
            "# Design Contract",
            "",
            f"- contract_id: {contract.get('contract_id') or 'design-contract:active'}",
            f"- version: {contract.get('version') or 1}",
            f"- status: {contract.get('status') or 'active'}",
            f"- source: {contract.get('source') or 'generated_contract'}",
            f"- ui_capability_mode: {contract.get('ui_capability_mode') or 'auto'}",
            f"- ui_validation_mode: {contract.get('ui_validation_mode') or 'auto'}",
            f"- designer_enabled: {str(bool(contract.get('designer_enabled'))).lower()}",
            "",
            "## Audience And Posture",
            "",
            f"- audience: {contract.get('audience') or 'The primary user described in the intake brief.'}",
            f"- product_goal: {contract.get('product_goal') or 'Build a useful local-first product.'}",
            f"- product_posture: {contract.get('product_posture') or 'quiet, functional, local-first, and reviewable'}",
            "",
            "## Workflows",
            "",
            bullets(contract.get("workflows")),
            "",
            "## Information Architecture",
            "",
            bullets(contract.get("information_architecture")),
            "",
            "## Layout Principles",
            "",
            bullets(contract.get("layout_principles")),
            "",
            "## Tokens",
            "",
            "\n".join(token_lines),
            "",
            "## Component Inventory",
            "",
            bullets(contract.get("component_inventory")),
            "",
            "## State Matrix",
            "",
            bullets(contract.get("state_matrix")),
            "",
            "## Accessibility Expectations",
            "",
            bullets(contract.get("accessibility_expectations")),
            "",
            "## Visual Do",
            "",
            bullets(contract.get("visual_do")),
            "",
            "## Visual Do Not",
            "",
            bullets(contract.get("visual_dont")),
            "",
            "## References",
            "",
            "- files:",
            *(f"  - {item}" for item in normalize_string_list(refs.get("files"))),
            "- urls:",
            *(f"  - {item}" for item in normalize_string_list(refs.get("urls"))),
            "- optional_services:",
            *(f"  - {item}" for item in normalize_string_list(refs.get("optional_services"))),
            "",
            "## Validation Expectations",
            "",
            bullets(contract.get("validation_expectations")),
            "",
        ]
    ).rstrip() + "\n"


def ticket_state_coverage(ticket: Mapping[str, Any]) -> set[str]:
    text = _ticket_text(ticket)
    covered: set[str] = set()
    for state in UI_STATE_REQUIREMENTS:
        if state in text:
            covered.add(state)
    return covered


def ui_ticket_quality_warnings(
    tickets: list[Mapping[str, Any]],
    intake: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    detection = ui_detection_from_intake(intake, tickets=tickets)
    if not detection["ui_heavy"]:
        return []
    warnings: list[dict[str, str]] = []
    corpus = "\n".join(_ticket_text(ticket) for ticket in tickets)
    has_design_foundation = any(
        phrase in corpus
        for phrase in (
            "design contract",
            "design foundation",
            "design system",
            "tokens",
            "component inventory",
            "visual baseline",
        )
    )
    has_validation = any(
        phrase in corpus
        for phrase in ("browser-smoke", "playwright", "screenshot", "ui visual", "visual validation")
    )
    if not has_design_foundation:
        warnings.append(
            {
                "ticket_id": "",
                "type": "missing_design_foundation",
                "detail": "UI-heavy scope should include early design contract, token, and reusable component foundation work.",
            }
        )
    if not has_validation:
        warnings.append(
            {
                "ticket_id": "",
                "type": "missing_ui_validation",
                "detail": "UI-heavy scope should include browser, screenshot, or explicit deferred UI validation work.",
            }
        )
    for ticket in tickets:
        if not ticket_is_ui_scoped(ticket):
            continue
        missing = [state for state in UI_STATE_REQUIREMENTS if state not in ticket_state_coverage(ticket)]
        if missing:
            warnings.append(
                {
                    "ticket_id": str(ticket.get("id") or ""),
                    "type": "missing_ui_states",
                    "detail": "UI ticket should name expected states: " + ", ".join(missing[:7]) + ".",
                }
            )
    return warnings


def design_foundation_ticket(intake: Mapping[str, Any] | None = None) -> dict[str, Any]:
    contract = build_design_contract_payload(intake)
    validation_expectation = (
        "Record design review notes and create ui_visual validation/deferred-QA work if browser tooling is unavailable."
    )
    return {
        "id": "TICKET-001",
        "summary": "Create design foundation contract, tokens, reusable UI states, and validation guidance",
        "status": "pending",
        "depends_on": [],
        "owner_role": "designer",
        "action_kind": "design",
        "acceptance_criteria": [
            "An active design contract projection exists for the UI scope.",
            "Reusable component, token, layout, accessibility, and visual do/don't rules are documented.",
            "Loading, empty, error, focus, disabled, responsive, and representative data-density expectations are covered.",
            "First-viewport priority, product-route versus developer-state-gallery separation, and text overflow/overlap rules are covered.",
            validation_expectation,
        ],
        "verification_commands": [
            "Inspect .diffmogger/agentic/design_contract.md and .diffmogger/agentic/design_contract.json.",
        ],
        "evidence": [],
        "related_commits": [],
        "blocker": "",
        "design_contract_required": True,
        "payload": {
            "classification": "design_foundation",
            "contract_id": contract.get("contract_id"),
            "contract_version": contract.get("version"),
        },
    }


def ensure_design_foundation_ticket(
    tickets: list[Mapping[str, Any]],
    intake: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    detection = ui_detection_from_intake(intake, tickets=tickets)
    normalized = [dict(ticket) for ticket in tickets]
    if not detection["designer_enabled"]:
        return normalized
    if any(
        str(ticket.get("owner_role") or ticket.get("role") or "").strip().lower() == "designer"
        or str(ticket.get("action_kind") or ticket.get("kind") or "").strip().lower() == "design"
        or "design contract" in _ticket_text(ticket)
        or "design foundation" in _ticket_text(ticket)
        for ticket in normalized
    ):
        return normalized
    foundation = design_foundation_ticket(intake)
    remapped: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}
    for index, ticket in enumerate(normalized, start=2):
        old_id = str(ticket.get("id") or f"TICKET-{index - 1:03d}")
        new_id = f"TICKET-{index:03d}"
        id_map[old_id] = new_id
        updated = dict(ticket)
        updated["id"] = new_id
        deps = normalize_string_list(updated.get("depends_on"))
        updated["depends_on"] = [id_map.get(dep, dep) for dep in deps]
        if ticket_is_ui_scoped(updated) and foundation["id"] not in updated["depends_on"]:
            updated["depends_on"] = [foundation["id"], *updated["depends_on"]]
        remapped.append(updated)
    return [foundation, *remapped]
