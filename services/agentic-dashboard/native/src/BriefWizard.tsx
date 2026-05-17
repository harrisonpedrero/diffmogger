import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  FilePlus2,
  FolderOpen,
  Hammer,
  Loader2,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  WandSparkles,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  BackendEnvelope,
  BackendLogEvent,
  PickedContextFile,
  ProjectSnapshot,
  RecentTarget,
  listenBackendLogs,
  runBackendCommand,
  runBackendCommandStreamed,
  selectContextFiles,
} from "./api/backend";
import { TicketFields } from "./TicketFields";
import diffmoggerIcon from "./assets/diffmogger-icon.png";
import {
  defaultImportMode,
  emptyTicket,
  issueLabel,
  localTicketIssues,
  normalizeTicket,
  normalizeTickets,
  parseTicketImportText,
  parseTicketJson,
  ticketImportExample,
  ticketToJson,
  type Ticket,
  type TicketImportFormat,
} from "./ticketModel";

export type BriefRoute =
  | "Home"
  | "Brief"
  | "Run"
  | "Observatory"
  | "Inbox"
  | "Review"
  | "Advanced";

type StepKey =
  | "project"
  | "goal"
  | "stack"
  | "mode"
  | "guardrails"
  | "context"
  | "review";

export type IntakeDraft = {
  project_name: string;
  project_mode: "fresh_project" | "existing_project";
  product_goal: string;
  target_user: string;
  desired_first_demo: string;
  tech_preferences: string[];
  hard_constraints: string[];
  safety_constraints: string[];
  automation_must_never_do: string[];
  external_services: string[];
  env_access_policy: "project_commands_only" | "direct_env_files_allowed";
  verification_commands: string[];
  human_bridge_enabled: boolean;
  human_bridge_mode: "disabled" | "file_only" | "local_notifier" | "discord_notifier";
  human_requested_text_responses: boolean;
  local_notifications_enabled: boolean;
  worker_agents_allowed: boolean;
  codex_cli_workers_expected_on_broad_runs: boolean;
  write_worker_agents_allowed: boolean;
  max_write_worker_count: number;
  write_worker_guidance: string;
  parallel_execution_mode: "conservative" | "aggressive";
  symbol_graph_languages: string[];
  parallel_write_min_confidence: number;
  parallel_write_direct_confidence: number;
  max_parallel_write_workers: number;
  max_parallel_scope_workers: number;
  multi_role_automations_allowed: boolean;
  automation_role_profile: "planner_builder_hardener_integrator";
  automation_checkpoint_commits: boolean;
  multi_role_allow_remotes: boolean;
  optional_mcp_servers: string[];
  campaign_mode: "bounded" | "ongoing";
  ticket_run_file: string;
  ticket_run_seed_tickets: Ticket[];
  ticket_completion_notify: boolean;
  meaningful_deliverable: string;
  beyond_mvp: string;
  assumptions: string[];
  additional_context_files: string[];
  overwrite_existing_scaffold_files: boolean;
};

export type AutomationScope = "ongoing" | "bounded";

type ContextUiFile = PickedContextFile & {
  relPath?: string;
  importStatus: "selected" | "imported" | "failed";
};

type ContextImportRecord = {
  rel_path: string;
  original_name: string;
  size_bytes: number;
};

type ContextImportResponse = {
  records: ContextImportRecord[];
  imported_count: number;
  project_context_path?: string;
  log?: string[];
};

type ScaffoldResponse = {
  written_count: number;
  written_files: string[];
  required_files: { status?: string; exit_code?: number };
  codex: { status?: string; reason?: string };
  native_next_state: {
    state: "FIRST_REVIEW_NEEDED" | "READY_TO_RUN" | string;
    reason?: string;
    first_review_status?: string;
    task_status?: string;
  };
  preflight?: ScaffoldPreviewResponse;
  log?: BackendLogEvent[];
  log_excerpt?: BackendLogEvent[];
};

export type SetupRunState = {
  enabled: boolean;
  bootstrapCompleted: boolean;
  reason: string;
  status: string;
};

export type ScaffoldPreviewFile = {
  rel_path: string;
  action: "create" | "overwrite" | "skip_existing" | "managed_section_update" | "update_local_exclude" | string;
  exists: boolean;
  managed_section: boolean;
  detail: string;
};

type ScaffoldPreviewWarning = {
  type: string;
  level: "info" | "warning" | "error" | string;
  message: string;
};

type ScaffoldPreviewResponse = {
  files: ScaffoldPreviewFile[];
  summary: Record<string, number>;
  warnings: ScaffoldPreviewWarning[];
  prerequisites: {
    status: "pass" | "fail" | string;
    required_failures: Array<{ name: string; detail: string }>;
    advisory_warnings: Array<{ name: string; detail: string }>;
  };
};

type ScaffoldFailure = {
  message: string;
  errorType?: string;
  details?: Record<string, unknown>;
};

type GeneratedIntakeResponse = {
  intake?: Record<string, unknown>;
  ticket_count?: number;
  ticket_generation_complexity?: string;
  ticket_generation_decomposition_brief?: string;
  ticket_generation_scope_groups?: unknown[];
  ticket_generation_quality_warnings?: unknown[];
  ticket_generation_refinement_needed?: boolean;
  ticket_generation_refinement_passed?: boolean;
  ticket_generation_scope_surface_floor?: number;
  automation_role_profile?: IntakeDraft["automation_role_profile"];
  ticket_run_file?: string;
};

const steps: Array<{ key: StepKey; label: string }> = [
  { key: "project", label: "Project" },
  { key: "goal", label: "Goal" },
  { key: "stack", label: "Stack" },
  { key: "mode", label: "Run" },
  { key: "guardrails", label: "Guardrails" },
  { key: "context", label: "Context" },
  { key: "review", label: "Review" },
];

const defaultDraft: IntakeDraft = {
  project_name: "New Project",
  project_mode: "fresh_project",
  product_goal:
    "Build a local-first workspace that helps solo builders turn project goals into weekly boards, daily focus plans, and review summaries.",
  target_user: "Solo founders, engineers, and creative builders managing one to three active projects.",
  desired_first_demo:
    "A user can create a project, capture goals, generate a weekly plan, and review progress from the local dashboard.",
  tech_preferences: ["Use a simple, well-supported stack.", "Prefer local-first storage and clear validation commands."],
  hard_constraints: ["Keep the generated project target-agnostic.", "Preserve existing project conventions when integrating into a repo."],
  safety_constraints: ["Do not store secrets in generated docs.", "Keep destructive operations explicit and human-approved."],
  automation_must_never_do: ["Never push to remotes without direct human instruction.", "Never modify credentials or production data."],
  external_services: ["None required for local execution."],
  env_access_policy: "project_commands_only",
  verification_commands: ["Run the project test suite.", "Run lint/typecheck/build commands when present."],
  human_bridge_enabled: true,
  human_bridge_mode: "file_only",
  human_requested_text_responses: true,
  local_notifications_enabled: true,
  worker_agents_allowed: true,
  codex_cli_workers_expected_on_broad_runs: true,
  write_worker_agents_allowed: true,
  max_write_worker_count: 3,
  write_worker_guidance:
    "Use write workers as optional bounded acceleration when work splits into reviewable ownership scopes.",
  parallel_execution_mode: "aggressive",
  symbol_graph_languages: ["python", "typescript", "javascript"],
  parallel_write_min_confidence: 0.75,
  parallel_write_direct_confidence: 0.75,
  max_parallel_write_workers: 3,
  max_parallel_scope_workers: 2,
  multi_role_automations_allowed: true,
  automation_role_profile: "planner_builder_hardener_integrator",
  automation_checkpoint_commits: true,
  multi_role_allow_remotes: false,
  optional_mcp_servers: [],
  campaign_mode: "ongoing",
  ticket_run_file: "",
  ticket_run_seed_tickets: [],
  ticket_completion_notify: true,
  meaningful_deliverable: "A runnable, verified change that improves the product or developer workflow.",
  beyond_mvp: "Continue improving core value, demo quality, integrations, and run reliability.",
  assumptions: ["Ask through the inbox when a decision is ambiguous."],
  additional_context_files: [],
  overwrite_existing_scaffold_files: false,
};

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function boolValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function numberValue(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function listValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === "string") {
    return value
      .split(/\r?\n/)
      .map((line) => line.trim().replace(/^[-*]\s*/, ""))
      .filter(Boolean);
  }
  return [];
}

function enumValue<T extends string>(value: unknown, valid: readonly T[], fallback: T): T {
  return valid.includes(value as T) ? (value as T) : fallback;
}

function roleProfileValues(): Pick<IntakeDraft, "multi_role_automations_allowed" | "automation_role_profile"> {
  return {
    multi_role_automations_allowed: true,
    automation_role_profile: "planner_builder_hardener_integrator",
  };
}

export function automationScopeForDraft(
  draft: Pick<IntakeDraft, "campaign_mode"> | { campaign_mode?: unknown; automation_run_mode?: unknown },
): AutomationScope {
  const raw = "campaign_mode" in draft && draft.campaign_mode !== undefined ? draft.campaign_mode : draft.automation_run_mode;
  const text = String(raw || "ongoing").trim().toLowerCase().replace(/[-\s]+/g, "_");
  return text === "bounded" || text === "ticket_campaign" ? "bounded" : "ongoing";
}

export function applyAutomationScope(draft: IntakeDraft, scope: AutomationScope): IntakeDraft {
  return {
    ...draft,
    campaign_mode: scope,
  };
}

function draftFromSource(source: Record<string, unknown>, targetName: string): IntakeDraft {
  const optionalMcp = listValue(source.optional_mcp_servers).filter((item) =>
    ["context7", "playwright"].includes(item),
  );
  const roleProfile = roleProfileValues();
  return {
    ...defaultDraft,
    project_name: stringValue(source.project_name, targetName),
    project_mode: enumValue(source.project_mode, ["fresh_project", "existing_project"], defaultDraft.project_mode),
    product_goal: stringValue(source.product_goal, defaultDraft.product_goal),
    target_user: stringValue(source.target_user, defaultDraft.target_user),
    desired_first_demo: stringValue(source.desired_first_demo, defaultDraft.desired_first_demo),
    tech_preferences: listValue(source.tech_preferences).length ? listValue(source.tech_preferences) : defaultDraft.tech_preferences,
    hard_constraints: listValue(source.hard_constraints).length ? listValue(source.hard_constraints) : defaultDraft.hard_constraints,
    safety_constraints: listValue(source.safety_constraints).length ? listValue(source.safety_constraints) : defaultDraft.safety_constraints,
    automation_must_never_do: listValue(source.automation_must_never_do).length
      ? listValue(source.automation_must_never_do)
      : defaultDraft.automation_must_never_do,
    external_services: listValue(source.external_services).length ? listValue(source.external_services) : defaultDraft.external_services,
    env_access_policy: enumValue(
      source.env_access_policy,
      ["project_commands_only", "direct_env_files_allowed"],
      defaultDraft.env_access_policy,
    ),
    verification_commands: listValue(source.verification_commands).length
      ? listValue(source.verification_commands)
      : defaultDraft.verification_commands,
    human_bridge_enabled: boolValue(source.human_bridge_enabled, defaultDraft.human_bridge_enabled),
    human_bridge_mode: enumValue(
      source.human_bridge_mode,
      ["disabled", "file_only", "local_notifier", "discord_notifier"],
      defaultDraft.human_bridge_mode,
    ),
    human_requested_text_responses: boolValue(
      source.human_requested_text_responses,
      defaultDraft.human_requested_text_responses,
    ),
    local_notifications_enabled: boolValue(source.local_notifications_enabled, defaultDraft.local_notifications_enabled),
    worker_agents_allowed: boolValue(source.worker_agents_allowed, defaultDraft.worker_agents_allowed),
    codex_cli_workers_expected_on_broad_runs: boolValue(
      source.codex_cli_workers_expected_on_broad_runs,
      defaultDraft.codex_cli_workers_expected_on_broad_runs,
    ),
    write_worker_agents_allowed: true,
    max_write_worker_count: Math.max(1, Math.min(10, numberValue(source.max_write_worker_count, defaultDraft.max_write_worker_count))),
    write_worker_guidance: stringValue(source.write_worker_guidance, defaultDraft.write_worker_guidance),
    parallel_execution_mode: enumValue(
      source.parallel_execution_mode,
      ["conservative", "aggressive"],
      defaultDraft.parallel_execution_mode,
    ),
    symbol_graph_languages: listValue(source.symbol_graph_languages).length
      ? listValue(source.symbol_graph_languages)
      : defaultDraft.symbol_graph_languages,
    parallel_write_min_confidence: numberValue(
      source.parallel_write_min_confidence,
      defaultDraft.parallel_write_min_confidence,
    ),
    parallel_write_direct_confidence: numberValue(
      source.parallel_write_direct_confidence,
      defaultDraft.parallel_write_direct_confidence,
    ),
    max_parallel_write_workers: numberValue(source.max_parallel_write_workers, defaultDraft.max_parallel_write_workers),
    max_parallel_scope_workers: numberValue(source.max_parallel_scope_workers, defaultDraft.max_parallel_scope_workers),
    multi_role_automations_allowed: roleProfile.multi_role_automations_allowed,
    automation_role_profile: roleProfile.automation_role_profile,
    automation_checkpoint_commits: boolValue(source.automation_checkpoint_commits, defaultDraft.automation_checkpoint_commits),
    multi_role_allow_remotes: boolValue(source.multi_role_allow_remotes, defaultDraft.multi_role_allow_remotes),
    optional_mcp_servers: optionalMcp,
    campaign_mode: automationScopeForDraft({
      campaign_mode: source.campaign_mode,
      automation_run_mode: source.automation_run_mode,
    }),
    ticket_run_file: stringValue(source.ticket_run_file, defaultDraft.ticket_run_file),
    ticket_run_seed_tickets: normalizeTickets(source.ticket_run_seed_tickets),
    ticket_completion_notify: boolValue(source.ticket_completion_notify, defaultDraft.ticket_completion_notify),
    meaningful_deliverable: stringValue(source.meaningful_deliverable, defaultDraft.meaningful_deliverable),
    beyond_mvp: stringValue(source.beyond_mvp, defaultDraft.beyond_mvp),
    assumptions: listValue(source.assumptions).length ? listValue(source.assumptions) : defaultDraft.assumptions,
    additional_context_files: listValue(source.additional_context_files),
    overwrite_existing_scaffold_files: boolValue(
      source.overwrite_existing_scaffold_files,
      defaultDraft.overwrite_existing_scaffold_files,
    ),
  };
}

function mergeDraft(snapshot: ProjectSnapshot | null): IntakeDraft {
  const source = {
    ...asRecord(snapshot?.brief?.intake),
    ...asRecord(snapshot?.brief?.draft_intake),
    ...asRecord(snapshot?.brief?.dashboard_state),
  };
  return draftFromSource(source, snapshot?.target.name || defaultDraft.project_name);
}

export function lowCortisolDraftFromGeneratedIntake(
  source: Record<string, unknown>,
  current: IntakeDraft,
  targetName = defaultDraft.project_name,
): IntakeDraft {
  const generated = draftFromSource(source, targetName);
  const generatedTickets = normalizeTickets(source.ticket_run_seed_tickets ?? source.tickets);
  const generatedContext = listValue(source.additional_context_files);
  return {
    ...generated,
    human_bridge_enabled: true,
    human_bridge_mode: "file_only",
    optional_mcp_servers: [],
    campaign_mode: "bounded",
    ticket_run_file: defaultDraft.ticket_run_file,
    ticket_run_seed_tickets: generatedTickets,
    additional_context_files: generatedContext.length ? generatedContext : current.additional_context_files,
    overwrite_existing_scaffold_files: false,
  };
}

function serializeDraft(draft: IntakeDraft): Record<string, unknown> {
  const scope = automationScopeForDraft(draft);
  const roleProfile = roleProfileValues();
  const payload: Record<string, unknown> = {
    ...draft,
    multi_role_automations_allowed: roleProfile.multi_role_automations_allowed,
    automation_role_profile: roleProfile.automation_role_profile,
    campaign_mode: scope,
    ticket_run_seed_tickets: draft.ticket_run_seed_tickets.map((ticket) => normalizeTicket(ticket)),
    human_bridge_mode: draft.human_bridge_enabled ? draft.human_bridge_mode : "disabled",
    write_worker_agents_allowed: true,
    max_write_worker_count: Math.max(1, Math.min(10, draft.max_write_worker_count || 3)),
    parallel_write_min_confidence: Math.max(0, Math.min(1, draft.parallel_write_min_confidence)),
    parallel_write_direct_confidence: Math.max(0, Math.min(1, draft.parallel_write_direct_confidence)),
    max_parallel_write_workers: Math.max(1, Math.min(10, Math.round(draft.max_parallel_write_workers))),
    max_parallel_scope_workers: Math.max(1, Math.min(10, Math.round(draft.max_parallel_scope_workers))),
  };
  return payload;
}

function listToText(values: string[]): string {
  return values.map((value) => `- ${value}`).join("\n");
}

function bytesLabel(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 102.4) / 10} KB`;
  return `${Math.round(size / 1024 / 102.4) / 10} MB`;
}

function commandLabel(detected: Record<string, unknown>): string {
  const scripts = asRecord(detected.package_scripts);
  const scriptNames = Object.keys(scripts);
  if (!scriptNames.length) return "No package scripts detected yet.";
  return scriptNames.map((name) => `${name}: ${String(scripts[name])}`).join("\n");
}

function targetStatus(snapshot: ProjectSnapshot | null): string {
  if (!snapshot) return "No target selected";
  if (snapshot.target.is_diffmogger_project) return "Diffmogger state detected";
  if (snapshot.target.project_intake_exists) return "Project intake exists";
  return "Not configured yet";
}

function actionLabel(action: string): string {
  if (action === "managed_section_update") return "Managed section";
  if (action === "skip_existing") return "Not overwritten";
  if (action === "update_local_exclude") return "Local exclude";
  return action.replace(/_/g, " ");
}

export function visibleScaffoldPreviewFiles(files: ScaffoldPreviewFile[]): ScaffoldPreviewFile[] {
  return files.filter((file) => file.action !== "skip_existing");
}

const pendingBootstrapStatuses = new Set(["", "unknown", "pending", "not_bootstrapped", "not bootstrapped"]);

function normalizedStatus(value: string): string {
  return value.trim().toLowerCase().replace(/-/g, "_");
}

export function setupRunState(
  snapshot: ProjectSnapshot | null,
  options: {
    scaffoldResultPresent?: boolean;
    draftDirty?: boolean;
    saveState?: "idle" | "saving" | "saved" | "error";
    busy?: boolean;
    ticketIssueCount?: number;
  } = {},
): SetupRunState {
  if (!snapshot) {
    return {
      enabled: false,
      bootstrapCompleted: false,
      reason: "Choose a target folder before running.",
      status: "Choose a target",
    };
  }
  const task = asRecord(snapshot.run.task);
  const dashboard = asRecord(snapshot.brief.dashboard_state);
  const dashboardPassed =
    normalizedStatus(stringValue(dashboard.initial_bootstrap_status, "")) === "pass" ||
    Boolean(String(dashboard.initial_bootstrap_completed_at ?? "").trim());
  const scaffolded = snapshot.target.automation_task_exists || Boolean(options.scaffoldResultPresent);
  const bootstrapStatus = normalizedStatus(stringValue(task.bootstrap_status, scaffolded ? "pending" : "unknown"));
  const completed = dashboardPassed || (scaffolded && !pendingBootstrapStatuses.has(bootstrapStatus));
  if (!scaffolded) {
    return {
      enabled: false,
      bootstrapCompleted: false,
      reason: "Run Scaffold before opening Run.",
      status: "Scaffold first",
    };
  }
  if (options.busy) {
    return {
      enabled: false,
      bootstrapCompleted: completed,
      reason: "Setup is already running.",
      status: "Setup running",
    };
  }
  if (options.saveState === "saving") {
    return {
      enabled: false,
      bootstrapCompleted: completed,
      reason: "Wait for the setup draft to finish saving.",
      status: "Saving",
    };
  }
  if (options.saveState === "error") {
    return {
      enabled: false,
      bootstrapCompleted: completed,
      reason: "Resolve the setup draft save error before running.",
      status: "Save error",
    };
  }
  if (options.draftDirty) {
    return {
      enabled: false,
      bootstrapCompleted: completed,
      reason: "Scaffold the latest setup changes before running.",
      status: "Scaffold latest changes",
    };
  }
  if ((options.ticketIssueCount ?? 0) > 0) {
    return {
      enabled: false,
      bootstrapCompleted: completed,
      reason: "Resolve ticket issues before running.",
      status: "Resolve ticket issues",
    };
  }
  return {
    enabled: true,
    bootstrapCompleted: completed,
    reason: completed ? "Open Run." : "Open Run; the first Start will prepare the target automatically.",
    status: completed ? "Ready" : "First run will prepare target",
  };
}

function logEventKey(event: BackendLogEvent, index: number): string {
  return `${event.stage}-${event.level}-${event.message}-${index}`;
}

export function lowCortisolProgressLabel(events: BackendLogEvent[]): string {
  const latest = events.length ? events[events.length - 1] : null;
  const haystack = `${latest?.stage ?? ""} ${latest?.message ?? ""}`.toLowerCase();
  if (haystack.includes("ticket")) return "Generating Tickets";
  if (haystack.includes("intake")) return "Generating Intake";
  return "Generating Intake";
}

function logEventsFromDetails(value: unknown, runId: string): BackendLogEvent[] {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const record = asRecord(item);
    return {
      runId,
      command: stringValue(record.command, "brief.scaffold_bootstrap"),
      stage: stringValue(record.stage, `log-${index + 1}`),
      level: stringValue(record.level, "info"),
      message: stringValue(record.message, JSON.stringify(record)),
      data: asRecord(record.data),
    };
  });
}

function FormField(props: { label: string; help?: string; children: ReactNode }) {
  return (
    <label className="brief-field">
      <span>{props.label}</span>
      {props.children}
      {props.help && <small>{props.help}</small>}
    </label>
  );
}

function ToggleRow(props: {
  label: string;
  detail?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="toggle-row">
      <input checked={props.checked} onChange={(event) => props.onChange(event.target.checked)} type="checkbox" />
      <span>
        <strong>{props.label}</strong>
        {props.detail && <small>{props.detail}</small>}
      </span>
    </label>
  );
}

function DetailMetric(props: { label: string; value: string | number }) {
  return (
    <div>
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function setupStepState(step: StepKey, options: {
  draft: IntakeDraft;
  targetPath?: string;
  ticketIssueCount: number;
  contextCount: number;
  previewState: "idle" | "loading" | "ready" | "error";
}): "complete" | "warn" | "pending" {
  if (step === "project") return options.targetPath && options.draft.project_name.trim() ? "complete" : "warn";
  if (step === "goal") return options.draft.product_goal.trim() && options.draft.target_user.trim() ? "complete" : "warn";
  if (step === "stack") return options.draft.verification_commands.length ? "complete" : "pending";
  if (step === "mode") return options.ticketIssueCount ? "warn" : "complete";
  if (step === "guardrails") return options.draft.safety_constraints.length && options.draft.automation_must_never_do.length ? "complete" : "warn";
  if (step === "context") return options.contextCount ? "complete" : "pending";
  if (step === "review") return options.previewState === "ready" ? "complete" : options.previewState === "error" ? "warn" : "pending";
  return "pending";
}

function SetupPlanSummary(props: {
  draft: IntakeDraft;
  targetPath?: string;
  saveState: "idle" | "saving" | "saved" | "error";
  previewState: "idle" | "loading" | "ready" | "error";
  preview?: ScaffoldPreviewResponse | null;
  contextCount: number;
  ticketIssueCount: number;
  scaffoldBusy: boolean;
}) {
  const scope = automationScopeForDraft(props.draft);
  const issueTone = props.ticketIssueCount ? "warn" : "good";
  return (
    <aside className="setup-recipe-summary" aria-label="Live setup plan summary">
      <div className="setup-summary-head">
        <span>Setup plan</span>
        <strong>{props.draft.project_name || "Untitled target"}</strong>
      </div>
      <div className="setup-summary-ledger">
        <DetailMetric label="Target" value={props.targetPath ? "Selected" : "No target"} />
        <DetailMetric label="Campaign" value={scope === "bounded" ? "Bounded" : "Ongoing"} />
        <DetailMetric label="Architecture" value="Activity runtime" />
        <DetailMetric label="Context" value={props.contextCount} />
        <DetailMetric label="Guardrails" value={props.draft.safety_constraints.length + props.draft.automation_must_never_do.length} />
        <DetailMetric label="Tickets" value={scope === "bounded" ? props.draft.ticket_run_seed_tickets.length : "Auto"} />
      </div>
      <div className="setup-summary-status">
        <div className={props.saveState}>
          <span>Draft</span>
          <strong>{props.saveState === "saving" ? "Saving" : props.saveState === "saved" ? "Saved" : props.saveState === "error" ? "Needs retry" : "Idle"}</strong>
        </div>
        <div className={props.previewState}>
          <span>Preview</span>
          <strong>{props.scaffoldBusy ? "Working" : props.previewState === "ready" ? "Ready" : props.previewState}</strong>
        </div>
        <div className={issueTone}>
          <span>Validation</span>
          <strong>{props.ticketIssueCount ? `${props.ticketIssueCount} issue(s)` : "Clear"}</strong>
        </div>
      </div>
      {props.preview && (
        <div className="setup-preview-counts">
          {Object.entries(props.preview.summary ?? {}).map(([key, value]) => (
            <div key={key}>
              <span>{key.replace(/_/g, " ")}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}

export function BriefWizard(props: {
  snapshot: ProjectSnapshot | null;
  recents: RecentTarget[];
  loading: boolean;
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: BriefRoute) => void;
  onRefresh: () => void | Promise<void>;
  onDirtyChange?: (message: string | null) => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [activeStep, setActiveStep] = useState(0);
  const [draft, setDraft] = useState<IntakeDraft>(() => mergeDraft(props.snapshot));
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [commandError, setCommandError] = useState<string | null>(null);
  const [copiedLabel, setCopiedLabel] = useState("");
  const [contextFiles, setContextFiles] = useState<ContextUiFile[]>([]);
  const [contextBusy, setContextBusy] = useState(false);
  const [scaffoldBusy, setScaffoldBusy] = useState(false);
  const [scaffoldResult, setScaffoldResult] = useState<ScaffoldResponse | null>(null);
  const [scaffoldFailure, setScaffoldFailure] = useState<ScaffoldFailure | null>(null);
  const [progressLogs, setProgressLogs] = useState<BackendLogEvent[]>([]);
  const [preview, setPreview] = useState<ScaffoldPreviewResponse | null>(null);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [ticketEditorId, setTicketEditorId] = useState<string | null>(null);
  const [ticketEditorJson, setTicketEditorJson] = useState("");
  const [ticketImportFormat, setTicketImportFormat] = useState<TicketImportFormat>("markdown");
  const [ticketImportText, setTicketImportText] = useState("");
  const [ticketMessage, setTicketMessage] = useState<string | null>(null);
  const [ticketDraftBusy, setTicketDraftBusy] = useState(false);
  const [ticketDraftCandidates, setTicketDraftCandidates] = useState<Ticket[]>([]);
  const [lowCortisolMode, setLowCortisolMode] = useState(false);
  const [lowCortisolText, setLowCortisolText] = useState("");
  const [lowCortisolBusy, setLowCortisolBusy] = useState(false);
  const lastSavedRef = useRef("");
  const targetPath = props.snapshot?.target.path;
  const detected = asRecord(props.snapshot?.brief.detected);
  const currentStep = steps[activeStep];
  const draftPayload = useMemo(() => JSON.stringify(serializeDraft(draft)), [draft]);
  const ticketIssues = useMemo(() => localTicketIssues(draft.ticket_run_seed_tickets), [draft.ticket_run_seed_tickets]);
  const selectedTicketJson = useMemo(() => {
    if (!ticketEditorId) return "";
    const ticket = draft.ticket_run_seed_tickets.find((item) => item.id === ticketEditorId);
    return ticket ? ticketToJson(ticket) : "";
  }, [draft.ticket_run_seed_tickets, ticketEditorId]);
  const ticketEditorTicket = useMemo(() => {
    const parsed = parseTicketJson(ticketEditorJson);
    return parsed.ticket ?? emptyTicket(draft.ticket_run_seed_tickets);
  }, [draft.ticket_run_seed_tickets, ticketEditorJson]);
  const draftDirty = draftPayload !== lastSavedRef.current;
  const ticketEditorDirty = Boolean(ticketEditorJson.trim() && ticketEditorJson !== selectedTicketJson);
  const lowCortisolDirty = lowCortisolMode && Boolean(lowCortisolText.trim());
  const runState = setupRunState(props.snapshot, {
    scaffoldResultPresent: Boolean(scaffoldResult),
    draftDirty,
    saveState,
    busy: scaffoldBusy,
    ticketIssueCount: ticketIssues.length,
  });
  const routeDirtyMessage = ticketEditorDirty
    ? "A setup ticket editor has unsaved changes."
    : lowCortisolDirty
      ? "Low cortisol setup text has not generated an intake."
    : draftDirty
      ? "Setup has unsaved plan changes."
      : null;

  useEffect(() => {
    const nextDraft = mergeDraft(props.snapshot);
    setDraft(nextDraft);
    lastSavedRef.current = JSON.stringify(serializeDraft(nextDraft));
    setSaveState("idle");
    setScaffoldResult(null);
    setScaffoldFailure(null);
    setProgressLogs([]);
    setPreview(null);
    setPreviewState("idle");
    setCommandError(null);
    setTicketEditorId(null);
    setTicketEditorJson("");
    setTicketImportText("");
    setTicketMessage(null);
    setTicketDraftCandidates([]);
    setLowCortisolMode(false);
    setLowCortisolText("");
    setLowCortisolBusy(false);
    const imported = nextDraft.additional_context_files.map<ContextUiFile>((relPath) => ({
      path: relPath,
      name: relPath.split("/").pop() || relPath,
      sizeBytes: 0,
      fileType: relPath.split(".").pop() || "file",
      relPath,
      importStatus: "imported",
    }));
    setContextFiles(imported);
  }, [targetPath]);

  useEffect(() => {
    if (!targetPath) return;
    if (draftPayload === lastSavedRef.current) return;
    setSaveState("saving");
    const timeout = window.setTimeout(async () => {
      try {
        const envelope = await runBackendCommand({
          command: "brief.save_draft",
          target: targetPath,
          intakeJson: draftPayload,
        });
        if (!envelope.ok) throw new Error(envelope.message ?? "Draft save failed.");
        lastSavedRef.current = draftPayload;
        setSaveState("saved");
      } catch (error) {
        setSaveState("error");
        setCommandError(error instanceof Error ? error.message : "Draft save failed.");
      }
    }, 700);
    return () => window.clearTimeout(timeout);
  }, [draftPayload, targetPath]);

  useEffect(() => {
    props.onDirtyChange?.(routeDirtyMessage);
    return () => props.onDirtyChange?.(null);
  }, [props.onDirtyChange, routeDirtyMessage]);

  useEffect(() => {
    props.onBusyChange?.(scaffoldBusy || lowCortisolBusy);
    return () => props.onBusyChange?.(false);
  }, [lowCortisolBusy, scaffoldBusy]);

  useEffect(() => {
    if (!routeDirtyMessage) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = routeDirtyMessage;
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [routeDirtyMessage]);

  useEffect(() => {
    if (!targetPath || currentStep.key !== "review") return;
    setPreviewState("loading");
    const timeout = window.setTimeout(async () => {
      try {
        const envelope = await runBackendCommand<ScaffoldPreviewResponse>({
          command: "brief.scaffold_preview",
          target: targetPath,
          intakeJson: draftPayload,
          force: draft.overwrite_existing_scaffold_files,
        });
        if (!envelope.ok || !envelope.data) throw new Error(envelope.message ?? "Preview failed.");
        setPreview(envelope.data);
        setPreviewState("ready");
      } catch (error) {
        setPreview(null);
        setPreviewState("error");
        setCommandError(error instanceof Error ? error.message : "Preview failed.");
      }
    }, 400);
    return () => window.clearTimeout(timeout);
  }, [currentStep.key, draft.overwrite_existing_scaffold_files, draftPayload, targetPath]);

  function updateDraft<K extends keyof IntakeDraft>(key: K, value: IntakeDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function updateList(key: keyof IntakeDraft, value: string) {
    setDraft((current) => ({ ...current, [key]: listValue(value) }));
  }

  function toggleMcp(server: "context7" | "playwright", checked: boolean) {
    setDraft((current) => {
      const next = current.optional_mcp_servers.filter((item) => item !== server);
      if (checked) next.push(server);
      return { ...current, optional_mcp_servers: next };
    });
  }

  function replaceSeedTickets(tickets: Ticket[], message: string) {
    setDraft((current) => ({ ...current, ticket_run_seed_tickets: tickets.map((ticket) => normalizeTicket(ticket)) }));
    setTicketMessage(message);
  }

  function addSeedTicket() {
    const ticket = emptyTicket(draft.ticket_run_seed_tickets);
    setDraft((current) => ({ ...current, ticket_run_seed_tickets: [...current.ticket_run_seed_tickets, ticket] }));
    setTicketEditorId(ticket.id);
    setTicketEditorJson(ticketToJson(ticket));
    setTicketMessage("New seed ticket is ready to edit.");
  }

  function updateSeedTicketEditor(ticket: Ticket) {
    setTicketEditorJson(ticketToJson(ticket));
  }

  function editSeedTicket(ticket: Ticket) {
    setTicketEditorId(ticket.id);
    setTicketEditorJson(ticketToJson(ticket));
    setTicketMessage(null);
  }

  function saveSeedTicket() {
    const parsed = parseTicketJson(ticketEditorJson);
    if (!parsed.ticket) {
      setTicketMessage(parsed.error ?? "Ticket fields did not parse.");
      return;
    }
    setDraft((current) => {
      const existingId = ticketEditorId;
      const replacement = normalizeTicket(parsed.ticket);
      const found = existingId
        ? current.ticket_run_seed_tickets.some((ticket) => ticket.id === existingId)
        : false;
      const next = found
        ? current.ticket_run_seed_tickets.map((ticket) => (ticket.id === existingId ? replacement : ticket))
        : [...current.ticket_run_seed_tickets, replacement];
      return { ...current, ticket_run_seed_tickets: next };
    });
    setTicketEditorId(parsed.ticket.id);
    setTicketEditorJson(ticketToJson(parsed.ticket));
    setTicketMessage("Seed ticket saved.");
  }

  function deleteSeedTicket(ticketId: string) {
    setDraft((current) => ({
      ...current,
      ticket_run_seed_tickets: current.ticket_run_seed_tickets.filter((ticket) => ticket.id !== ticketId),
    }));
    if (ticketEditorId === ticketId) {
      setTicketEditorId(null);
      setTicketEditorJson("");
    }
    setTicketMessage("Seed ticket deleted.");
  }

  function importSeedTickets(mode: "append" | "replace-placeholder" | "replace-all" = defaultImportMode(draft.ticket_run_seed_tickets)) {
    const parsed = parseTicketImportText(ticketImportText, ticketImportFormat);
    if (!parsed.tickets) {
      setTicketMessage(parsed.error ?? "Ticket import did not parse.");
      return;
    }
    const current = draft.ticket_run_seed_tickets;
    const next =
      mode === "replace-all" || (mode === "replace-placeholder" && defaultImportMode(current) === "replace-placeholder")
        ? parsed.tickets
        : [...current, ...parsed.tickets];
    replaceSeedTickets(next, `${parsed.tickets.length} ticket candidate${parsed.tickets.length === 1 ? "" : "s"} imported.`);
  }

  async function draftSeedTicketsFromIntake() {
    if (!targetPath) {
      setTicketMessage("Choose a target folder before drafting from intake.");
      return;
    }
    setTicketDraftBusy(true);
    setTicketMessage(null);
    try {
      const envelope = await runBackendCommand<{ candidates?: Ticket[]; candidate_count?: number }>({
        command: "ticket.draft_from_intake",
        target: targetPath,
      });
      if (!envelope.ok || !envelope.data) throw new Error(envelope.message ?? "Codex draft failed.");
      const candidates = normalizeTickets(envelope.data.candidates ?? []);
      setTicketDraftCandidates(candidates);
      setTicketMessage(`${envelope.data.candidate_count ?? candidates.length} draft ticket candidate${candidates.length === 1 ? "" : "s"} ready to review.`);
    } catch (error) {
      setTicketMessage(error instanceof Error ? error.message : "Codex draft failed.");
    } finally {
      setTicketDraftBusy(false);
    }
  }

  function acceptDraftCandidates(candidates = ticketDraftCandidates) {
    if (!candidates.length) {
      setTicketMessage("No draft candidates are ready yet.");
      return;
    }
    importSeedTicketsFromCandidates(candidates);
  }

  function importSeedTicketsFromCandidates(candidates: Ticket[]) {
    const mode = defaultImportMode(draft.ticket_run_seed_tickets);
    const next = mode === "replace-placeholder" ? candidates : [...draft.ticket_run_seed_tickets, ...candidates];
    replaceSeedTickets(next, `${candidates.length} draft ticket candidate${candidates.length === 1 ? "" : "s"} accepted.`);
  }

  async function copyText(value: string, label: string) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopiedLabel(label);
      window.setTimeout(() => setCopiedLabel(""), 1400);
    } catch {
      setCommandError("Could not copy from this environment.");
    }
  }

  async function saveDraftNow(): Promise<boolean> {
    if (!targetPath) return false;
    setSaveState("saving");
    setCommandError(null);
    try {
      const envelope = await runBackendCommand({
        command: "brief.save_draft",
        target: targetPath,
        intakeJson: draftPayload,
      });
      if (!envelope.ok) throw new Error(envelope.message ?? "Draft save failed.");
      lastSavedRef.current = draftPayload;
      setSaveState("saved");
      return true;
    } catch (error) {
      setSaveState("error");
      setCommandError(error instanceof Error ? error.message : "Draft save failed.");
      return false;
    }
  }

  async function generateLowCortisolIntake() {
    const description = lowCortisolText.trim();
    if (!description) {
      setCommandError("Describe what you want to build before generating the intake.");
      return;
    }
    if (!targetPath) {
      setCommandError("Choose a target folder before generating the intake.");
      return;
    }
    setLowCortisolBusy(true);
    setCommandError(null);
    setSaveState("saving");
    setProgressLogs([]);
    const runId = `brief-intake-${Date.now()}`;
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setProgressLogs((current) => [...current, event].slice(-80));
      });
      const envelope: BackendEnvelope<GeneratedIntakeResponse> = await runBackendCommandStreamed<GeneratedIntakeResponse>({
        runId,
        command: "brief.generate_intake",
        target: targetPath,
        body: description,
      });
      if (!envelope.ok || !envelope.data?.intake) {
        const detailLogs = logEventsFromDetails(envelope.error?.details?.log, runId);
        if (detailLogs.length) {
          setProgressLogs((current) => [...current, ...detailLogs].slice(-80));
        }
        throw new Error(envelope.message ?? "Intake generation failed.");
      }
      const nextDraft = lowCortisolDraftFromGeneratedIntake(
        envelope.data.intake,
        draft,
        props.snapshot?.target.name || defaultDraft.project_name,
      );
      const nextPayload = JSON.stringify(serializeDraft(nextDraft));
      setDraft(nextDraft);
      lastSavedRef.current = nextPayload;
      setSaveState("saved");
      setPreview(null);
      setPreviewState("idle");
      setScaffoldResult(null);
      setScaffoldFailure(null);
      setTicketDraftCandidates([]);
      setTicketMessage(`${envelope.data.ticket_count ?? nextDraft.ticket_run_seed_tickets.length} generated ticket${nextDraft.ticket_run_seed_tickets.length === 1 ? "" : "s"} ready.`);
      setActiveStep(steps.length - 1);
      setLowCortisolMode(false);
    } catch (error) {
      setSaveState("error");
      setCommandError(error instanceof Error ? error.message : "Intake generation failed.");
    } finally {
      unlisten?.();
      setLowCortisolBusy(false);
    }
  }

  function changeStep(index: number) {
    if (index === activeStep) return;
    if (ticketEditorDirty) {
      setTicketMessage("Seed ticket editor changes are still open. Save the ticket before scaffolding if you want to keep them.");
    }
    setActiveStep(Math.max(0, Math.min(steps.length - 1, index)));
  }

  async function addContextFiles() {
    if (!targetPath) {
      setCommandError("Choose a target folder before importing context files.");
      return;
    }
    setContextBusy(true);
    setCommandError(null);
    try {
      const picked = await selectContextFiles();
      if (!picked.length) return;
      setContextFiles((current) => [
        ...current,
        ...picked.map((file) => ({ ...file, importStatus: "selected" as const })),
      ]);
      const envelope = await runBackendCommand<ContextImportResponse>({
        command: "context.import",
        target: targetPath,
        filesJson: JSON.stringify(picked.map((file) => file.path)),
        projectName: draft.project_name,
      });
      if (!envelope.ok || !envelope.data) {
        throw new Error(envelope.message ?? "Context import failed.");
      }
      const records = envelope.data.records;
      setContextFiles((current) => {
        const pending = [...current];
        records.forEach((record) => {
          const index = pending.findIndex(
            (item) => item.importStatus === "selected" && item.name === record.original_name,
          );
          const replacement: ContextUiFile = {
            path: record.rel_path,
            name: record.original_name,
            sizeBytes: record.size_bytes,
            fileType: record.original_name.split(".").pop() || "file",
            relPath: record.rel_path,
            importStatus: "imported",
          };
          if (index >= 0) pending[index] = replacement;
          else pending.push(replacement);
        });
        return pending;
      });
      const relPaths = records.map((record) => record.rel_path);
      setDraft((current) => ({
        ...current,
        additional_context_files: Array.from(new Set([...current.additional_context_files, ...relPaths])),
      }));
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : "Context import failed.");
      setContextFiles((current) =>
        current.map((file) => (file.importStatus === "selected" ? { ...file, importStatus: "failed" } : file)),
      );
    } finally {
      setContextBusy(false);
    }
  }

  async function scaffoldBootstrap() {
    if (!targetPath) {
      setCommandError("Choose a target folder before scaffolding.");
      return;
    }
    if (draftDirty && !(await saveDraftNow())) {
      setScaffoldFailure({ message: "Draft save failed. Resolve the save error before scaffolding." });
      return;
    }
    setScaffoldBusy(true);
    setCommandError(null);
    setScaffoldResult(null);
    setScaffoldFailure(null);
    setProgressLogs([]);
    const runId = `brief-bootstrap-${Date.now()}`;
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setProgressLogs((current) => [...current, event].slice(-220));
      });
      const envelope: BackendEnvelope<ScaffoldResponse> = await runBackendCommandStreamed<ScaffoldResponse>({
        runId,
        command: "brief.scaffold_bootstrap",
        target: targetPath,
        intakeJson: draftPayload,
        force: draft.overwrite_existing_scaffold_files,
        runCodex: false,
      });
      if (!envelope.ok || !envelope.data) {
        const detailLogs = logEventsFromDetails(envelope.error?.details?.log, runId);
        if (detailLogs.length) {
          setProgressLogs((current) => [...current, ...detailLogs].slice(-220));
        }
        setScaffoldFailure({
          message: envelope.message ?? "Scaffold failed.",
          errorType: envelope.error?.type,
          details: envelope.error?.details,
        });
        return;
      }
      setScaffoldResult(envelope.data);
      await Promise.resolve(props.onRefresh());
    } catch (error) {
      setScaffoldFailure({ message: error instanceof Error ? error.message : "Scaffold failed." });
    } finally {
      unlisten?.();
      setScaffoldBusy(false);
    }
  }

  function renderProjectStep() {
    return (
      <div className="brief-step-grid">
        <section className="brief-section span-2">
          <h2>Project</h2>
          <div className="brief-form-grid">
            <FormField label="Project name">
              <input value={draft.project_name} onChange={(event) => updateDraft("project_name", event.target.value)} />
            </FormField>
            <FormField label="Project type">
              <select
                value={draft.project_mode}
                onChange={(event) => updateDraft("project_mode", event.target.value as IntakeDraft["project_mode"])}
              >
                <option value="fresh_project">Fresh project</option>
                <option value="existing_project">Existing project</option>
              </select>
            </FormField>
          </div>
          <div className="target-picker-row">
            <button className="secondary-action" disabled={props.loading} onClick={props.onChoose}>
              <FolderOpen size={17} />
              Choose folder
            </button>
            <button className="secondary-action" disabled={!targetPath || props.loading} onClick={props.onRefresh}>
              <RefreshCw size={17} />
              Refresh target
            </button>
            <button className="secondary-action" disabled={!targetPath} onClick={() => props.onNavigate("Advanced")}>
              <SlidersHorizontal size={17} />
              <span title="Open Debug / Sidecar">Open Sidecar</span>
            </button>
          </div>
          <div className="copyable-path-row">
            <div className="target-path-chip" title={targetPath ?? ""}>
              {targetPath ?? "No target folder selected"}
            </div>
            <button
              className="icon-text-button"
              disabled={!targetPath}
              onClick={() => copyText(targetPath ?? "", "target")}
            >
              <Clipboard size={14} />
              {copiedLabel === "target" ? "Copied" : "Copy path"}
            </button>
          </div>
        </section>

        <section className="brief-section">
          <h2>Recent projects</h2>
          {props.recents.length ? (
            <div className="brief-recent-list">
              {props.recents.map((recent) => (
                <button key={recent.path} onClick={() => props.onOpenRecent(recent)}>
                  <span>{recent.name}</span>
                  <small>{recent.path}</small>
                </button>
              ))}
            </div>
          ) : (
            <div className="empty-copy">Recent project folders will appear after you open them.</div>
          )}
        </section>

        <section className="brief-section span-3">
          <h2>Repository</h2>
          <div className="brief-metrics">
            <div>
              <span>Target state</span>
              <strong>{targetStatus(props.snapshot)}</strong>
            </div>
            <div>
              <span>Git repo</span>
              <strong>{boolValue(detected.is_git_repo, false) ? "Detected" : "Not detected"}</strong>
            </div>
            <div>
              <span>Branch</span>
              <strong>{stringValue(detected.git_branch, "unknown")}</strong>
            </div>
            <div>
              <span>Dirty files</span>
              <strong>{numberValue(detected.git_dirty_count, 0)}</strong>
            </div>
            <div>
              <span>Package manager</span>
              <strong>{stringValue(detected.package_manager, "unknown")}</strong>
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderGoalStep() {
    return (
      <div className="brief-step-grid">
        <section className="brief-section span-3">
          <h2>Goal</h2>
          <div className="brief-form-grid two">
            <FormField label="Product goal">
              <textarea value={draft.product_goal} onChange={(event) => updateDraft("product_goal", event.target.value)} rows={5} />
            </FormField>
            <FormField label="Target user">
              <textarea value={draft.target_user} onChange={(event) => updateDraft("target_user", event.target.value)} rows={5} />
            </FormField>
            <FormField label="Desired runnable milestone">
              <textarea
                value={draft.desired_first_demo}
                onChange={(event) => updateDraft("desired_first_demo", event.target.value)}
                rows={5}
              />
            </FormField>
            <FormField label="Long-run direction">
              <textarea value={draft.beyond_mvp} onChange={(event) => updateDraft("beyond_mvp", event.target.value)} rows={5} />
            </FormField>
            <FormField label="Meaningful deliverable">
              <textarea
                value={draft.meaningful_deliverable}
                onChange={(event) => updateDraft("meaningful_deliverable", event.target.value)}
                rows={4}
              />
            </FormField>
            <FormField label="Assumptions">
              <textarea value={listToText(draft.assumptions)} onChange={(event) => updateList("assumptions", event.target.value)} rows={4} />
            </FormField>
          </div>
        </section>
      </div>
    );
  }

  function renderStackStep() {
    return (
      <div className="brief-step-grid">
        <section className="brief-section span-3">
          <h2>Stack</h2>
          <div className="brief-form-grid two">
            <FormField label="Tech preferences">
              <textarea
                value={listToText(draft.tech_preferences)}
                onChange={(event) => updateList("tech_preferences", event.target.value)}
                rows={5}
              />
            </FormField>
            <FormField label="Existing commands to preserve">
              <textarea
                value={listToText(draft.verification_commands)}
                onChange={(event) => updateList("verification_commands", event.target.value)}
                rows={5}
              />
            </FormField>
            <FormField label="Integration notes for existing projects">
              <textarea
                value={listToText(draft.hard_constraints)}
                onChange={(event) => updateList("hard_constraints", event.target.value)}
                rows={5}
              />
            </FormField>
            <FormField label="External services">
              <textarea
                value={listToText(draft.external_services)}
                onChange={(event) => updateList("external_services", event.target.value)}
                rows={5}
              />
            </FormField>
          </div>
        </section>
        <section className="brief-section">
          <h2>Detected state</h2>
          <div className="brief-data-list">
            <div>
              <span>Git</span>
              <strong>{boolValue(detected.is_git_repo, false) ? "Repository detected" : "No git metadata detected"}</strong>
            </div>
            <div>
              <span>Package manager</span>
              <strong>{stringValue(detected.package_manager, "unknown")}</strong>
            </div>
            <div>
              <span>Suggested checks</span>
              <strong>{listValue(detected.suggested_verification_commands).join(", ") || "No commands detected"}</strong>
            </div>
          </div>
        </section>
        <section className="brief-section span-2">
          <div className="panel-heading-row">
            <h2>Detected commands</h2>
            <button
              className="icon-text-button"
              disabled={!commandLabel(detected)}
              onClick={() => copyText(commandLabel(detected), "commands")}
            >
              <Clipboard size={14} />
              {copiedLabel === "commands" ? "Copied" : "Copy"}
            </button>
          </div>
          <pre className="command-preview">{commandLabel(detected)}</pre>
        </section>
      </div>
    );
  }

  function renderModeStep() {
    const buildScope = automationScopeForDraft(draft);
    const ticketCampaign = buildScope === "bounded";
    const ticketIssues = localTicketIssues(draft.ticket_run_seed_tickets);

    return (
      <div className="brief-step-grid">
        <section className="brief-section span-3">
          <h2>Scope</h2>
          <div className="brief-choice-grid two-up compact">
            <button
              className={buildScope === "ongoing" ? "selected" : ""}
              onClick={() => setDraft((current) => applyAutomationScope(current, "ongoing"))}
            >
              <strong>Ongoing campaign</strong>
              <span>Draft and enqueue safe follow-up tickets as work completes.</span>
            </button>
            <button
              className={ticketCampaign ? "selected" : ""}
              onClick={() => setDraft((current) => applyAutomationScope(current, "bounded"))}
            >
              <strong>Bounded campaign</strong>
              <span>Run the seeded or imported ticket queue, then stop when complete or blocked.</span>
            </button>
          </div>
        </section>
        <section className="brief-section span-3">
          {ticketCampaign && (
            <div className="ticket-queue-panel seed">
              <div className="panel-heading-row">
                <div>
                  <h2>Ticket Queue</h2>
                  <p>{draft.ticket_run_seed_tickets.length} seed ticket{draft.ticket_run_seed_tickets.length === 1 ? "" : "s"} will be written into the scaffolded SQLite queue.</p>
                </div>
                <div className="inline-actions">
                  <button className="icon-text-button" onClick={draftSeedTicketsFromIntake} disabled={ticketDraftBusy || !targetPath}>
                    <WandSparkles size={14} />
                    {ticketDraftBusy ? "Drafting" : "Draft from Intake"}
                  </button>
                  <button className="icon-text-button" onClick={addSeedTicket}>
                    <FilePlus2 size={14} />
                    Add Ticket
                  </button>
                </div>
              </div>

              <div className="ticket-summary-row">
                <DetailMetric label="Pending" value={draft.ticket_run_seed_tickets.filter((ticket) => ticket.status === "pending").length} />
                <DetailMetric label="Issues" value={ticketIssues.length} />
                <DetailMetric label="Import mode" value={defaultImportMode(draft.ticket_run_seed_tickets)} />
              </div>

              {ticketIssues.length > 0 && (
                <div className="ticket-issue-list">
                  {ticketIssues.map((issue, index) => (
                    <div className={`ticket-issue ${issue.level}`} key={`${issue.type}-${issue.ticket_id ?? index}`}>
                      <AlertTriangle size={14} />
                      <span>{issueLabel(issue)}</span>
                    </div>
                  ))}
                </div>
              )}

              <div className="ticket-list">
                {draft.ticket_run_seed_tickets.length ? (
                  draft.ticket_run_seed_tickets.map((ticket) => (
                    <div className="ticket-row" key={ticket.id}>
                      <div>
                        <strong>{ticket.id || "Untitled"}</strong>
                        <span>{ticket.summary || "No summary yet."}</span>
                      </div>
                      <em>{ticket.status}</em>
                      <button className="icon-text-button" onClick={() => editSeedTicket(ticket)}>Edit</button>
                      <button
                        className="icon-button danger"
                        aria-label={`Delete ticket ${ticket.id || "Untitled"}`}
                        title="Delete ticket"
                        onClick={() => deleteSeedTicket(ticket.id)}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="empty-copy">Add tickets manually, import a batch, or draft candidates from the intake.</p>
                )}
              </div>

              <div className="ticket-edit-grid">
                <TicketFields
                  ticket={ticketEditorTicket}
                  onChange={updateSeedTicketEditor}
                  title={ticketEditorId ? `Editing ${ticketEditorId}` : "Ticket fields"}
                />
                <div className="ticket-import-box">
                  <FormField label="Bulk import">
                    <select value={ticketImportFormat} onChange={(event) => setTicketImportFormat(event.target.value as TicketImportFormat)}>
                      <option value="markdown">Markdown</option>
                      <option value="csv">CSV</option>
                      <option value="json">JSON</option>
                    </select>
                    <textarea
                      className="ticket-import-textarea"
                      rows={7}
                      value={ticketImportText}
                      onChange={(event) => setTicketImportText(event.target.value)}
                      placeholder={ticketImportExample(ticketImportFormat)}
                    />
                  </FormField>
                  <div className="inline-actions">
                    <button className="secondary-action" onClick={saveSeedTicket} disabled={!ticketEditorJson.trim()}>
                      Save Ticket
                    </button>
                    <button className="secondary-action" onClick={() => importSeedTickets()} disabled={!ticketImportText.trim()}>
                      Import
                    </button>
                    <button className="secondary-action" onClick={() => importSeedTickets("replace-all")} disabled={!ticketImportText.trim()}>
                      Replace All
                    </button>
                  </div>
                </div>
              </div>

              {ticketDraftCandidates.length > 0 && (
                <details className="ticket-draft-details" open>
                  <summary>Draft candidates</summary>
                  <pre className="raw-json">{JSON.stringify(ticketDraftCandidates, null, 2)}</pre>
                  <button className="secondary-action" onClick={() => acceptDraftCandidates()}>
                    Accept Candidates
                  </button>
                </details>
              )}

              {ticketMessage && <p className="empty-copy">{ticketMessage}</p>}
            </div>
          )}
          <div className="toggle-grid">
            <ToggleRow
              checked={draft.worker_agents_allowed}
              label="Read-only workers"
              detail="Allow read-only worker report agents when strategy says they help."
              onChange={(checked) => updateDraft("worker_agents_allowed", checked)}
            />
            <ToggleRow
              checked={draft.codex_cli_workers_expected_on_broad_runs}
              label="Codex CLI workers"
              onChange={(checked) => updateDraft("codex_cli_workers_expected_on_broad_runs", checked)}
            />
            <ToggleRow
              checked={draft.automation_checkpoint_commits}
              label="Checkpoint commits"
              onChange={(checked) => updateDraft("automation_checkpoint_commits", checked)}
            />
            <ToggleRow
              checked={draft.ticket_completion_notify}
              label="Ticket completion notification"
              onChange={(checked) => updateDraft("ticket_completion_notify", checked)}
            />
            <ToggleRow
              checked={draft.multi_role_allow_remotes}
              label="Allow remotes"
              onChange={(checked) => updateDraft("multi_role_allow_remotes", checked)}
            />
          </div>
        </section>
      </div>
    );
  }

  function renderGuardrailsStep() {
    return (
      <div className="brief-step-grid">
        <section className="brief-section span-3">
          <h2>Guardrails</h2>
          <div className="brief-form-grid two">
            <FormField label="Safety rules">
              <textarea
                value={listToText(draft.safety_constraints)}
                onChange={(event) => updateList("safety_constraints", event.target.value)}
                rows={5}
              />
            </FormField>
            <FormField label="Prohibited actions">
              <textarea
                value={listToText(draft.automation_must_never_do)}
                onChange={(event) => updateList("automation_must_never_do", event.target.value)}
                rows={5}
              />
            </FormField>
          </div>
        </section>
        <section className="brief-section">
          <h2>Inbox</h2>
          <ToggleRow
            checked={draft.human_bridge_enabled}
            label="Enable Inbox"
            detail="Generated targets use dashboard-backed typed human-message state."
            onChange={(checked) => updateDraft("human_bridge_enabled", checked)}
          />
          <FormField label="Inbox mode">
            <select
              value={draft.human_bridge_mode}
              onChange={(event) => updateDraft("human_bridge_mode", event.target.value as IntakeDraft["human_bridge_mode"])}
            >
              <option value="file_only">File only</option>
              <option value="local_notifier">Local notifier</option>
              <option value="discord_notifier">Discord notifier</option>
              <option value="disabled">Disabled</option>
            </select>
          </FormField>
          <ToggleRow
            checked={draft.human_requested_text_responses}
            label="Request text responses"
            onChange={(checked) => updateDraft("human_requested_text_responses", checked)}
          />
          <ToggleRow
            checked={draft.local_notifications_enabled}
            label="Local notifications"
            onChange={(checked) => updateDraft("local_notifications_enabled", checked)}
          />
        </section>
        <section className="brief-section">
          <h2>Environment</h2>
          <FormField label="Environment access policy">
            <select
              value={draft.env_access_policy}
              onChange={(event) => updateDraft("env_access_policy", event.target.value as IntakeDraft["env_access_policy"])}
            >
              <option value="project_commands_only">Project commands only</option>
              <option value="direct_env_files_allowed">Direct env files allowed</option>
            </select>
          </FormField>
          <div className="guardrail-note">
            <AlertTriangle size={17} />
            <span>No secrets, credentials, paid-account exports, production data, pushes, deploys, purchases, or external side effects without direct human instruction.</span>
          </div>
        </section>
        <section className="brief-section">
          <h2>Optional MCP</h2>
          <ToggleRow
            checked={draft.optional_mcp_servers.includes("context7")}
            label="Context7 MCP"
            onChange={(checked) => toggleMcp("context7", checked)}
          />
          <ToggleRow
            checked={draft.optional_mcp_servers.includes("playwright")}
            label="Playwright MCP"
            onChange={(checked) => toggleMcp("playwright", checked)}
          />
        </section>
      </div>
    );
  }

  function renderContextStep() {
    return (
      <div className="brief-step-grid">
        <section className="brief-section span-3">
          <div className="section-heading-row">
            <h2>Context files</h2>
            <button className="secondary-action" disabled={!targetPath || contextBusy} onClick={addContextFiles}>
              <FilePlus2 size={17} />
              Add context files
            </button>
          </div>
          <div className="context-drop-zone">
            <FolderOpen size={18} />
            <span>Files are copied to .diffmogger/context/ and indexed in .diffmogger/state/PROJECT_CONTEXT.md.</span>
          </div>
          {contextFiles.length ? (
            <div className="context-file-list">
              {contextFiles.map((file, index) => (
                <div className={`context-file-row ${file.importStatus}`} key={`${file.path}-${index}`}>
                  <span>{file.name}</span>
                  <small>{file.relPath ?? file.path}</small>
                  <strong>{file.sizeBytes ? bytesLabel(file.sizeBytes) : file.fileType}</strong>
                  <em>{file.importStatus}</em>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-copy">Add research notes, PDFs, design docs, or planning files that help Codex understand the target.</div>
          )}
        </section>
      </div>
    );
  }

  function renderReviewStep() {
    const modeLabel = `Activity scheduler · ${
      automationScopeForDraft(draft) === "bounded" ? "bounded campaign" : "ongoing campaign"
    }`;
    const reviewTicketIssues = localTicketIssues(draft.ticket_run_seed_tickets);
    const previewFiles = preview ? visibleScaffoldPreviewFiles(preview.files) : null;
    const preservedPreviewCount = preview ? preview.files.length - (previewFiles?.length ?? 0) : 0;
    return (
      <div className="brief-step-grid">
        <section className="brief-section span-2">
          <h2>Review</h2>
          <div className="brief-data-list">
            <div>
              <span>Target path</span>
              <strong>{targetPath ?? "No target selected"}</strong>
            </div>
            <div>
              <span>Run mode</span>
              <strong>{modeLabel}</strong>
            </div>
            <div>
              <span>Inbox</span>
              <strong>{draft.human_bridge_enabled ? draft.human_bridge_mode : "disabled"}</strong>
            </div>
            <div>
              <span>Context files</span>
              <strong>{draft.additional_context_files.length}</strong>
            </div>
            <div>
              <span>Guardrails</span>
              <strong>{draft.safety_constraints.length + draft.automation_must_never_do.length} rules</strong>
            </div>
            <div>
              <span>Run controls</span>
              <strong>{scaffoldResult ? "Available now" : "Available after scaffold succeeds"}</strong>
            </div>
            <div>
              <span>First run</span>
              <strong>{runState.status}</strong>
            </div>
            {automationScopeForDraft(draft) === "bounded" && (
              <div>
                <span>Seed tickets</span>
                <strong>
                  {draft.ticket_run_seed_tickets.length} ticket{draft.ticket_run_seed_tickets.length === 1 ? "" : "s"} · {reviewTicketIssues.length} issue{reviewTicketIssues.length === 1 ? "" : "s"}
                </strong>
              </div>
            )}
          </div>
          {automationScopeForDraft(draft) === "bounded" && reviewTicketIssues.length > 0 && (
            <div className="ticket-issue-list">
              {reviewTicketIssues.slice(0, 5).map((issue, index) => (
                <div className={`ticket-issue ${issue.level}`} key={`${issue.type}-review-${index}`}>
                  <AlertTriangle size={14} />
                  <span>{issueLabel(issue)}</span>
                </div>
              ))}
            </div>
          )}
          {preview?.warnings.length ? (
            <div className="preview-warnings">
              {preview.warnings.map((warning) => (
                <div className={`preview-warning ${warning.level}`} key={`${warning.type}-${warning.message}`}>
                  <AlertTriangle size={16} />
                  <span>{warning.message}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="success-callout quiet" role="status" aria-live="polite">
              <CheckCircle2 size={18} />
              <span>{previewState === "loading" ? "Checking files and prerequisites." : "No blocking warnings in the current preview."}</span>
            </div>
          )}
          <ToggleRow
            checked={draft.overwrite_existing_scaffold_files}
            label="Overwrite existing scaffold-managed files"
            detail="Existing-project managed blocks remain merged instead of replacing whole files."
            onChange={(checked) => updateDraft("overwrite_existing_scaffold_files", checked)}
          />
          {scaffoldResult && (
            <div className="success-callout" role="status" aria-live="polite">
              <CheckCircle2 size={18} />
              <div>
                <strong>{scaffoldResult.native_next_state.state}</strong>
                <span>
                  Wrote {scaffoldResult.written_count} files. Required-file validation {scaffoldResult.required_files.status ?? "completed"}.
                </span>
                {scaffoldResult.native_next_state.reason && <small>{scaffoldResult.native_next_state.reason}</small>}
                <div className="result-actions">
                  <button className="secondary-action" onClick={() => props.onNavigate("Run")}>Run</button>
                  {scaffoldResult.native_next_state.state === "FIRST_REVIEW_NEEDED" && (
                    <button className="secondary-action" onClick={() => props.onNavigate("Review")}>Review</button>
                  )}
                </div>
              </div>
            </div>
          )}
          {scaffoldFailure && (
            <div className="brief-failure">
              <strong>{scaffoldFailure.errorType ?? "Scaffold failed"}</strong>
              <p>{scaffoldFailure.message}</p>
              <button className="secondary-action" title="Debug / Sidecar" onClick={() => props.onNavigate("Advanced")}>Sidecar</button>
            </div>
          )}
        </section>
        <section className="brief-section">
          <h2>Files</h2>
          <div className="generated-preview">
            {previewFiles ? (
              <>
                {previewFiles.length ? (
                  previewFiles.map((file) => (
                    <div className={`preview-file ${file.action}`} key={file.rel_path}>
                      <code>{file.rel_path}</code>
                      <span>{actionLabel(file.action)}</span>
                      {file.managed_section && <em>managed</em>}
                      <small>{file.detail}</small>
                    </div>
                  ))
                ) : (
                  <div className="empty-copy">No scaffold files need to be created or updated.</div>
                )}
                {preservedPreviewCount > 0 && (
                  <div className="empty-copy">
                    {preservedPreviewCount} existing sidecar file{preservedPreviewCount === 1 ? "" : "s"} will be preserved.
                  </div>
                )}
              </>
            ) : (
              <div className="empty-copy">
                {previewState === "loading" ? "Building preview." : "Preview is not available yet."}
              </div>
            )}
          </div>
        </section>
        <section className="brief-section span-3">
          <h2>Log</h2>
          <div className="progress-log">
            {progressLogs.length ? (
              progressLogs.map((event, index) => (
                <div className={`progress-log-line ${event.level}`} key={logEventKey(event, index)}>
                  <span>{event.stage}</span>
                  <p>{event.message}</p>
                </div>
              ))
            ) : (
              <div className="empty-copy">Logs stream here while setup and validation run.</div>
            )}
          </div>
        </section>
      </div>
    );
  }

  function renderLowCortisolMode() {
    const progressLabel = lowCortisolProgressLabel(progressLogs);
    return (
      <main className="low-cortisol-workspace">
        <label className="low-cortisol-field">
          <span>What do you want to build?</span>
          <textarea
            autoFocus
            value={lowCortisolText}
            onChange={(event) => setLowCortisolText(event.target.value)}
            rows={16}
          />
        </label>
        <footer className="wizard-footer setup-footer low-cortisol-footer">
          <button
            aria-busy={lowCortisolBusy}
            className="primary-action low-cortisol-generate-action"
            disabled={lowCortisolBusy || !lowCortisolText.trim()}
            onClick={() => void generateLowCortisolIntake()}
          >
            {lowCortisolBusy ? <Loader2 className="spin" size={22} /> : <WandSparkles size={22} />}
            <span>{lowCortisolBusy ? progressLabel : "Generate Intake"}</span>
          </button>
        </footer>
      </main>
    );
  }

  const stepContent = {
    project: renderProjectStep,
    goal: renderGoalStep,
    stack: renderStackStep,
    mode: renderModeStep,
    guardrails: renderGuardrailsStep,
    context: renderContextStep,
    review: renderReviewStep,
  }[currentStep.key]();

  return (
    <section className="brief-wizard setup-page" aria-label="Setup">
      <div className="brief-header setup-header">
        <div className="setup-header-main">
          <div className="setup-heading-copy">
            <h1>Setup</h1>
            <p>{targetStatus(props.snapshot)}</p>
          </div>
          <button
            aria-checked={lowCortisolMode}
            className={`low-cortisol-toggle ${lowCortisolMode ? "active" : ""}`}
            onClick={() => setLowCortisolMode((current) => !current)}
            role="switch"
            title="Low cortisol mode"
            type="button"
          >
            <img alt="" src={diffmoggerIcon} />
            <span className="low-cortisol-label">Low cortisol mode</span>
            <span className="low-cortisol-switch" aria-hidden="true">
              <span className="low-cortisol-switch-thumb" />
            </span>
          </button>
        </div>
        <div className={`brief-save-pill ${saveState}`}>
          {saveState === "saving" ? "Saving" : saveState === "saved" ? "Draft saved" : saveState === "error" ? "Save failed" : "Draft"}
        </div>
      </div>

      {commandError && (
        <div className="brief-error" role="alert">
          <AlertTriangle size={17} />
          <span>{commandError}</span>
        </div>
      )}

      {lowCortisolMode ? (
        renderLowCortisolMode()
      ) : (
        <div className="setup-workspace">
          <nav className="setup-stepper wizard-tabs" role="tablist" aria-label="Setup steps">
            {steps.map((step, index) => {
              const state = setupStepState(step.key, {
                draft,
                targetPath,
                ticketIssueCount: ticketIssues.length,
                contextCount: draft.additional_context_files.length,
                previewState,
              });
              return (
                <button
                  aria-current={index === activeStep ? "step" : undefined}
                  aria-selected={index === activeStep}
                  className={`${index === activeStep ? "active" : ""} ${state}`}
                  key={step.key}
                  onClick={() => changeStep(index)}
                  role="tab"
                >
                  <span>{index + 1}</span>
                  <strong>{step.label}</strong>
                  <small>{state}</small>
                </button>
              );
            })}
          </nav>

          <main className="setup-main-panel">
            {stepContent}
            <footer className="wizard-footer setup-footer">
              <button className="secondary-action" disabled={activeStep === 0} onClick={() => changeStep(activeStep - 1)}>
                <ChevronLeft size={17} />
                Previous
              </button>
              <button className="secondary-action" disabled={!targetPath || saveState === "saving" || !draftDirty} onClick={() => void saveDraftNow()}>
                Save draft
              </button>
              {activeStep < steps.length - 1 ? (
                <button className="secondary-action" onClick={() => changeStep(activeStep + 1)}>
                  Next
                  <ChevronRight size={17} />
                </button>
              ) : (
                <div className="setup-final-actions">
                  <button className="secondary-action" disabled={!targetPath || scaffoldBusy || saveState === "saving" || ticketIssues.length > 0} onClick={scaffoldBootstrap}>
                    <Hammer size={17} />
                    {scaffoldBusy ? "Working" : "Scaffold"}
                  </button>
                  <button className="primary-action" disabled={!runState.enabled} onClick={() => props.onNavigate("Run")} title={runState.reason}>
                    <RefreshCw size={17} />
                    Run
                  </button>
                </div>
              )}
            </footer>
          </main>

          <SetupPlanSummary
            contextCount={draft.additional_context_files.length}
            draft={draft}
            preview={preview}
            previewState={previewState}
            saveState={saveState}
            scaffoldBusy={scaffoldBusy}
            targetPath={targetPath}
            ticketIssueCount={ticketIssues.length}
          />
        </div>
      )}
    </section>
  );
}
