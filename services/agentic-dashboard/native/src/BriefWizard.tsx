import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  FilePlus2,
  FolderOpen,
  Hammer,
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
import {
  defaultImportMode,
  emptyTicket,
  issueLabel,
  localTicketIssues,
  normalizeTicket,
  normalizeTickets,
  parseTicketImportText,
  parseTicketJson,
  ticketToJson,
  type Ticket,
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
  multi_role_automations_allowed: boolean;
  automation_role_profile: "single_lane" | "planner_builder_hardener_integrator";
  automation_checkpoint_commits: boolean;
  multi_role_allow_remotes: boolean;
  optional_mcp_servers: string[];
  automation_run_mode: "continuous_improvement" | "ticket_campaign";
  ticket_run_file: string;
  ticket_run_seed_tickets: Ticket[];
  ticket_completion_notify: boolean;
  meaningful_deliverable: string;
  beyond_mvp: string;
  assumptions: string[];
  additional_context_files: string[];
  overwrite_existing_scaffold_files: boolean;
};

export type AutomationScope = "boundless_build" | "ticket_campaign";

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

type ScaffoldPreviewFile = {
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
    "A user can create a project, capture goals, generate a weekly plan, and review progress from local Markdown files.",
  tech_preferences: ["Use a simple, well-supported stack.", "Prefer local-first storage and clear validation commands."],
  hard_constraints: ["Keep the generated project target-agnostic.", "Preserve existing project conventions when integrating into a repo."],
  safety_constraints: ["Do not store secrets in generated docs.", "Keep destructive operations explicit and human-approved."],
  automation_must_never_do: ["Never push to remotes without direct human instruction.", "Never modify credentials or production data."],
  external_services: ["None required for the first demo."],
  env_access_policy: "project_commands_only",
  verification_commands: ["Run the project test suite.", "Run lint/typecheck/build commands when present."],
  human_bridge_enabled: true,
  human_bridge_mode: "file_only",
  human_requested_text_responses: true,
  local_notifications_enabled: true,
  worker_agents_allowed: true,
  codex_cli_workers_expected_on_broad_runs: true,
  write_worker_agents_allowed: false,
  max_write_worker_count: 0,
  write_worker_guidance:
    "Write workers are optional and should be used only for large, well-planned changes with disjoint file or module ownership. Prefer fewer workers when the change can be done clearly by the main agent.",
  multi_role_automations_allowed: true,
  automation_role_profile: "planner_builder_hardener_integrator",
  automation_checkpoint_commits: true,
  multi_role_allow_remotes: false,
  optional_mcp_servers: [],
  automation_run_mode: "continuous_improvement",
  ticket_run_file: ".diffmogger/state/TICKET_RUN.md",
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
    const parsed = Number.parseInt(value, 10);
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

function roleProfileValues(source: Record<string, unknown>): Pick<IntakeDraft, "multi_role_automations_allowed" | "automation_role_profile"> {
  const rawProfile = enumValue(
    source.automation_role_profile,
    ["single_lane", "planner_builder_hardener_integrator"],
    defaultDraft.automation_role_profile,
  );
  const rawMultiRole = boolValue(source.multi_role_automations_allowed, defaultDraft.multi_role_automations_allowed);
  if (rawProfile === "single_lane" || !rawMultiRole) {
    return { multi_role_automations_allowed: false, automation_role_profile: "single_lane" };
  }
  return {
    multi_role_automations_allowed: true,
    automation_role_profile: "planner_builder_hardener_integrator",
  };
}

export function automationScopeForDraft(
  draft: Pick<IntakeDraft, "automation_run_mode">,
): AutomationScope {
  return draft.automation_run_mode === "ticket_campaign" ? "ticket_campaign" : "boundless_build";
}

export function applyAutomationScope(draft: IntakeDraft, scope: AutomationScope): IntakeDraft {
  return {
    ...draft,
    automation_run_mode: scope === "ticket_campaign" ? "ticket_campaign" : "continuous_improvement",
  };
}

function mergeDraft(snapshot: ProjectSnapshot | null): IntakeDraft {
  const source = {
    ...asRecord(snapshot?.brief?.intake),
    ...asRecord(snapshot?.brief?.draft_intake),
    ...asRecord(snapshot?.brief?.dashboard_state),
  };
  const targetName = snapshot?.target.name || defaultDraft.project_name;
  const optionalMcp = listValue(source.optional_mcp_servers).filter((item) =>
    ["context7", "playwright"].includes(item),
  );
  const roleProfile = roleProfileValues(source);
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
    write_worker_agents_allowed: boolValue(source.write_worker_agents_allowed, defaultDraft.write_worker_agents_allowed),
    max_write_worker_count: numberValue(source.max_write_worker_count, defaultDraft.max_write_worker_count),
    write_worker_guidance: stringValue(source.write_worker_guidance, defaultDraft.write_worker_guidance),
    multi_role_automations_allowed: roleProfile.multi_role_automations_allowed,
    automation_role_profile: roleProfile.automation_role_profile,
    automation_checkpoint_commits: boolValue(source.automation_checkpoint_commits, defaultDraft.automation_checkpoint_commits),
    multi_role_allow_remotes: boolValue(source.multi_role_allow_remotes, defaultDraft.multi_role_allow_remotes),
    optional_mcp_servers: optionalMcp,
    automation_run_mode: enumValue(
      source.automation_run_mode,
      ["continuous_improvement", "ticket_campaign"],
      defaultDraft.automation_run_mode,
    ),
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

function serializeDraft(draft: IntakeDraft): Record<string, unknown> {
  const scope = automationScopeForDraft(draft);
  const roleProfile = roleProfileValues(draft as unknown as Record<string, unknown>);
  const payload: Record<string, unknown> = {
    ...draft,
    multi_role_automations_allowed: roleProfile.multi_role_automations_allowed,
    automation_role_profile: roleProfile.automation_role_profile,
    automation_run_mode: scope === "ticket_campaign" ? "ticket_campaign" : "continuous_improvement",
    ticket_run_seed_tickets: draft.ticket_run_seed_tickets.map((ticket) => normalizeTicket(ticket)),
    human_bridge_mode: draft.human_bridge_enabled ? draft.human_bridge_mode : "disabled",
    max_write_worker_count: draft.write_worker_agents_allowed ? Math.max(1, Math.min(10, draft.max_write_worker_count)) : 0,
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

function logEventKey(event: BackendLogEvent, index: number): string {
  return `${event.stage}-${event.level}-${event.message}-${index}`;
}

function logEventsFromDetails(value: unknown, runId: string): BackendLogEvent[] {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => {
    const record = asRecord(item);
    return {
      runId,
      command: "brief.scaffold_bootstrap",
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

export function BriefWizard(props: {
  snapshot: ProjectSnapshot | null;
  recents: RecentTarget[];
  loading: boolean;
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: BriefRoute) => void;
  onRefresh: () => void | Promise<void>;
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
  const [ticketImportFormat, setTicketImportFormat] = useState<"markdown" | "csv" | "json">("markdown");
  const [ticketImportText, setTicketImportText] = useState("");
  const [ticketMessage, setTicketMessage] = useState<string | null>(null);
  const [ticketDraftBusy, setTicketDraftBusy] = useState(false);
  const [ticketDraftCandidates, setTicketDraftCandidates] = useState<Ticket[]>([]);
  const lastSavedRef = useRef("");
  const targetPath = props.snapshot?.target.path;
  const detected = asRecord(props.snapshot?.brief.detected);
  const currentStep = steps[activeStep];
  const draftPayload = useMemo(() => JSON.stringify(serializeDraft(draft)), [draft]);

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

  function editSeedTicket(ticket: Ticket) {
    setTicketEditorId(ticket.id);
    setTicketEditorJson(ticketToJson(ticket));
    setTicketMessage(null);
  }

  function saveSeedTicket() {
    const parsed = parseTicketJson(ticketEditorJson);
    if (!parsed.ticket) {
      setTicketMessage(parsed.error ?? "Ticket JSON did not parse.");
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
    const requiredFailures = preview?.prerequisites.required_failures ?? [];
    if (requiredFailures.length && !confirm("Required prerequisites are missing. Continue with setup-only and skip Codex?")) {
      return;
    }
    setScaffoldBusy(true);
    setCommandError(null);
    setScaffoldResult(null);
    setScaffoldFailure(null);
    setProgressLogs([]);
    const runId = `brief-bootstrap-${Date.now()}`;
    const unlisten = await listenBackendLogs(runId, (event) => {
      setProgressLogs((current) => [...current, event].slice(-220));
    });
    try {
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
      unlisten();
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
              Open Debug
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
            <FormField label="Desired first demo">
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
      </div>
    );
  }

  function renderModeStep() {
    const buildScope = automationScopeForDraft(draft);
    const ticketCampaign = buildScope === "ticket_campaign";
    const ticketIssues = localTicketIssues(draft.ticket_run_seed_tickets);

    return (
      <div className="brief-step-grid">
        <section className="brief-section span-3">
          <h2>Automation profile</h2>
          <div className="brief-choice-grid two-up compact">
            <button
              className={draft.automation_role_profile === "single_lane" ? "selected" : ""}
              onClick={() =>
                setDraft((current) => ({
                  ...current,
                  multi_role_automations_allowed: false,
                  automation_role_profile: "single_lane",
                }))
              }
            >
              <strong>Single lane</strong>
              <span>One continuous agent loop for docs, research, reports, cleanup, and simpler work.</span>
            </button>
            <button
              className={draft.automation_role_profile === "planner_builder_hardener_integrator" ? "selected" : ""}
              onClick={() =>
                setDraft((current) => ({
                  ...current,
                  multi_role_automations_allowed: true,
                  automation_role_profile: "planner_builder_hardener_integrator",
                }))
              }
            >
              <strong>Multi-role conveyor</strong>
              <span>Planner, builder, hardener, and integrator lanes for larger engineering work.</span>
            </button>
          </div>
        </section>
        <section className="brief-section span-3">
          <h2>Scope</h2>
          <div className="brief-choice-grid two-up compact">
            <button
              className={buildScope === "boundless_build" ? "selected" : ""}
              onClick={() => setDraft((current) => applyAutomationScope(current, "boundless_build"))}
            >
              <strong>Continuous improvement</strong>
              <span>Use the project goal and guardrails as the ongoing backlog.</span>
            </button>
            <button
              className={ticketCampaign ? "selected" : ""}
              onClick={() => setDraft((current) => applyAutomationScope(current, "ticket_campaign"))}
            >
              <strong>Ticket file</strong>
              <span>Use the configured ticket file and completion signal.</span>
            </button>
          </div>
        </section>
        <section className="brief-section span-3">
          <div className="brief-form-grid two">
            <FormField label="Ticket run file" help="Used when Ticket campaign is selected.">
              <input
                disabled={!ticketCampaign}
                value={draft.ticket_run_file}
                onChange={(event) => updateDraft("ticket_run_file", event.target.value)}
              />
            </FormField>
          </div>
          {ticketCampaign && (
            <div className="ticket-queue-panel seed">
              <div className="panel-heading-row">
                <div>
                  <h2>Ticket Queue</h2>
                  <p>{draft.ticket_run_seed_tickets.length} seed ticket{draft.ticket_run_seed_tickets.length === 1 ? "" : "s"} will be written into the scaffolded ticket file.</p>
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
                      <button className="icon-button danger" title="Delete ticket" onClick={() => deleteSeedTicket(ticket.id)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="empty-copy">Add tickets manually, import a batch, or draft candidates from the intake.</p>
                )}
              </div>

              <div className="ticket-edit-grid">
                <FormField label="Ticket JSON">
                  <textarea
                    rows={10}
                    value={ticketEditorJson}
                    onChange={(event) => setTicketEditorJson(event.target.value)}
                    placeholder={ticketToJson(emptyTicket(draft.ticket_run_seed_tickets))}
                  />
                </FormField>
                <div className="ticket-import-box">
                  <FormField label="Bulk import">
                    <select value={ticketImportFormat} onChange={(event) => setTicketImportFormat(event.target.value as "markdown" | "csv" | "json")}>
                      <option value="markdown">Markdown</option>
                      <option value="csv">CSV</option>
                      <option value="json">JSON</option>
                    </select>
                    <textarea
                      rows={7}
                      value={ticketImportText}
                      onChange={(event) => setTicketImportText(event.target.value)}
                      placeholder="TICKET-001: Build the first local workflow"
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
              checked={draft.write_worker_agents_allowed}
              label="Write workers"
              detail="Keeps write workers explicit, bounded, and ownership-scoped."
              onChange={(checked) =>
                setDraft((current) => ({
                  ...current,
                  write_worker_agents_allowed: checked,
                  max_write_worker_count: checked ? Math.max(1, current.max_write_worker_count || 1) : 0,
                }))
              }
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
          <div className="brief-form-grid two">
            <FormField label="Max write-worker count">
              <input
                disabled={!draft.write_worker_agents_allowed}
                max={10}
                min={0}
                type="number"
                value={draft.max_write_worker_count}
                onChange={(event) => updateDraft("max_write_worker_count", numberValue(event.target.value, 0))}
              />
            </FormField>
            <FormField label="Write-worker guidance">
              <textarea
                value={draft.write_worker_guidance}
                onChange={(event) => updateDraft("write_worker_guidance", event.target.value)}
                rows={4}
              />
            </FormField>
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
            label="Enable inbox files"
            detail="Generated targets use Markdown inbox files."
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
    const modeLabel = `Continuous role conveyor · ${
      automationScopeForDraft(draft) === "ticket_campaign" ? "ticket file" : "continuous improvement"
    }`;
    const reviewTicketIssues = localTicketIssues(draft.ticket_run_seed_tickets);
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
            {automationScopeForDraft(draft) === "ticket_campaign" && (
              <div>
                <span>Seed tickets</span>
                <strong>
                  {draft.ticket_run_seed_tickets.length} ticket{draft.ticket_run_seed_tickets.length === 1 ? "" : "s"} · {reviewTicketIssues.length} issue{reviewTicketIssues.length === 1 ? "" : "s"}
                </strong>
              </div>
            )}
          </div>
          {automationScopeForDraft(draft) === "ticket_campaign" && reviewTicketIssues.length > 0 && (
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
            <div className="success-callout quiet">
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
            <div className="success-callout">
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
              <button className="secondary-action" onClick={() => props.onNavigate("Advanced")}>Debug</button>
            </div>
          )}
        </section>
        <section className="brief-section">
          <h2>Files</h2>
          <div className="generated-preview">
            {preview?.files ? (
              preview.files.map((file) => (
                <div className={`preview-file ${file.action}`} key={file.rel_path}>
                  <code>{file.rel_path}</code>
                  <span>{actionLabel(file.action)}</span>
                  {file.managed_section && <em>managed</em>}
                  <small>{file.detail}</small>
                </div>
              ))
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
    <section className="brief-wizard">
      <div className="brief-header">
        <div>
          <h1>Setup</h1>
          <p>{targetStatus(props.snapshot)}</p>
        </div>
        <div className={`brief-save-pill ${saveState}`}>
          {saveState === "saving" ? "Saving" : saveState === "saved" ? "Draft saved" : saveState === "error" ? "Save failed" : "Draft"}
        </div>
      </div>

      <div className="wizard-tabs">
        {steps.map((step, index) => (
          <button className={index === activeStep ? "active" : ""} key={step.key} onClick={() => setActiveStep(index)}>
            <span>{index + 1}</span>
            {step.label}
          </button>
        ))}
      </div>

      {commandError && (
        <div className="brief-error">
          <AlertTriangle size={17} />
          <span>{commandError}</span>
        </div>
      )}

      {stepContent}

      <footer className="wizard-footer">
        <button className="secondary-action" disabled={activeStep === 0} onClick={() => setActiveStep((step) => Math.max(0, step - 1))}>
          <ChevronLeft size={17} />
          Previous
        </button>
        {activeStep < steps.length - 1 ? (
          <button className="secondary-action" onClick={() => setActiveStep((step) => Math.min(steps.length - 1, step + 1))}>
            Next
            <ChevronRight size={17} />
          </button>
        ) : (
          <button className="primary-action" disabled={!targetPath || scaffoldBusy || previewState !== "ready"} onClick={scaffoldBootstrap}>
            <Hammer size={17} />
            {scaffoldBusy ? "Working" : "Scaffold"}
          </button>
        )}
      </footer>
    </section>
  );
}
