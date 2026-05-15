import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type BackendEnvelope<T = unknown> = {
  schema_version: number;
  ok: boolean;
  command: string;
  data?: T;
  message?: string;
  error?: {
    type: string;
    details?: Record<string, unknown>;
  };
};

export type RecentTarget = {
  path: string;
  name: string;
  lastOpenedAt: number;
};

export type TargetMetadata = {
  path: string;
  name: string;
  is_diffmogger_project: boolean;
  project_intake_exists: boolean;
  dashboard_state_exists: boolean;
  automation_task_exists: boolean;
};

export type HomeSnapshot = {
  title: string;
  automation_status: string;
  current_horizon: string;
  next_action: string;
  pending_human_requests: number;
  unhandled_inbox: number;
  queued_patches: number;
  deferred_patches: number;
};

export type RegisteredFile = {
  key: string;
  label: string;
  rel_path: string;
  group: string;
  category?: string;
  path?: string;
  exists: boolean;
  editable?: boolean;
  validation?: string;
  size_bytes: number | null;
  modified_at: string | null;
};

export type CanonicalStateSnapshot = {
  schema_version: number;
  authority: string;
  status: string;
  database: Record<string, unknown>;
  projection: Record<string, unknown>;
  projections?: Record<string, Record<string, unknown>>;
  contract: Record<string, unknown>;
  counts: Record<string, number>;
  last_event?: Record<string, unknown>;
  last_checkpoint?: Record<string, unknown>;
  recent_events: Array<Record<string, unknown>>;
  open_blockers: Array<Record<string, unknown>>;
  next_actions: Array<Record<string, unknown>>;
  validations: Record<string, unknown>;
  conveyor_state?: Record<string, unknown>;
  conveyor_machine?: ConveyorMachineSnapshot | Record<string, unknown>;
  capability_manifest?: Record<string, unknown>;
  codebase_graph_summary?: Record<string, unknown>;
  task_graph_summary?: Record<string, unknown>;
  impact_graph_summary?: Record<string, unknown>;
  active_task_code_impacts?: Array<Record<string, unknown>>;
  context_pack_preview?: Record<string, unknown>;
  top_impacted_nodes?: Array<Record<string, unknown>>;
  stale_context_warning?: string;
  stale_graph_warnings?: Array<Record<string, unknown>>;
  active_leases?: Array<Record<string, unknown>>;
  conflicting_leases?: Array<Record<string, unknown>>;
  lease_suggestions_for_next_action?: Array<Record<string, unknown>>;
  scheduling_candidates?: Array<Record<string, unknown>>;
  selected_candidate?: Record<string, unknown>;
  skipped_candidates?: Array<Record<string, unknown>>;
  scheduler_fallback_used?: boolean;
  runner_state?: Record<string, unknown>;
};

export type ConveyorMachineSnapshot = {
  schema_version: number;
  machine_version: number;
  authority: "sqlite" | string;
  current_stage: string;
  stage_status: string;
  owner_role: string;
  work_item: {
    id: string;
    title?: string;
    status: string;
    current_stage: string;
    stage_status: string;
    owner_role: string;
    capability_manifest_id: string;
    capability_manifest_version: number;
    validation_status: string;
    risk_tier?: string;
    continuation_token: string;
    entered_at?: string;
    updated_at?: string;
  };
  stage_contract: Record<string, unknown>;
  stage_contracts: Array<Record<string, unknown>>;
  capability_manifest: Record<string, unknown>;
  stage_attempts: Array<Record<string, unknown>>;
  validation_receipts: Array<Record<string, unknown>>;
  policy: Record<string, unknown>;
};

export type ProjectSnapshot = {
  target: TargetMetadata;
  brief: {
    project_name?: string;
    project_mode?: string;
    context_files?: unknown[];
    intake?: Record<string, unknown>;
    draft_intake?: Record<string, unknown>;
    dashboard_state?: Record<string, unknown>;
    detected?: Record<string, unknown>;
  };
  run: {
    task?: Record<string, unknown>;
    human?: Record<string, unknown>;
    git?: {
      branch?: string;
      dirty_count?: number;
      recent_commits?: string[];
      commits?: Array<Record<string, unknown>>;
    };
    queue?: Record<string, unknown>;
    conveyor?: Record<string, unknown>;
    state?: CanonicalStateSnapshot | Record<string, unknown>;
    progress?: Record<string, unknown>;
    scorecard?: Record<string, unknown>;
    first_review?: Record<string, unknown>;
    follow_through?: Record<string, unknown>;
    recommendation_history?: Record<string, unknown>;
    worker_strategy?: Record<string, unknown>;
    review?: Record<string, unknown>;
    baseline_verification?: Record<string, unknown>;
    progress_recent?: string;
    empty_states?: Record<string, unknown>;
    logs?: Array<Record<string, unknown>>;
    controls?: Record<string, unknown>;
    automation?: Record<string, unknown>;
    run_log?: Record<string, unknown>;
    worker_controls?: Record<string, unknown>;
    latest_worker_result?: Record<string, unknown>;
    environment_blockers?: Array<Record<string, unknown>>;
    snapshot_generated_at?: string;
  };
  files: RegisteredFile[];
  home: HomeSnapshot;
};

export type ObservatoryBadge = {
  label: string;
  value: string;
  tone: "good" | "warn" | "critical" | "info" | "quiet" | string;
};

export type ObservatoryRoleCard = {
  role: "planner" | "builder" | "hardener" | "integrator" | string;
  status: string;
  badge: string;
  tone: string;
  reason: string;
  counts: Record<string, number>;
};

export type ObservatoryCommit = {
  hash?: string;
  time?: string;
  subject?: string;
  role?: string;
  summary?: string;
  file_count?: number;
  additions?: number;
  deletions?: number;
  files?: Array<Record<string, unknown>>;
};

export type ObservatorySnapshot = {
  schema_version: number;
  generated_at?: string;
  target: TargetMetadata;
  title: string;
  subtitle: string;
  mission: {
    project_name: string;
    automation_status: string;
    current_horizon: string;
    mission_text: string;
    best_next_milestone: string;
    known_issue: string;
    tags: ObservatoryBadge[];
  };
  scorecard: {
    status: string;
    summary: string;
    counts: Array<Record<string, unknown>>;
  };
  conveyor: {
    cycles: number;
    updated_at?: string;
    roles: ObservatoryRoleCard[];
    state_machine?: ConveyorMachineSnapshot | Record<string, unknown>;
    active_run?: Record<string, unknown>;
    decision_queue?: Array<Record<string, unknown>>;
    health?: Record<string, unknown>;
    no_progress?: Record<string, unknown>;
  };
  progress: {
    story: string;
    latest_landed_work?: ObservatoryCommit;
    landed_work_feed: ObservatoryCommit[];
    recent_outcomes: Array<Record<string, unknown>>;
  };
  validation_safety: {
    validation?: Record<string, unknown>;
    integration_safety?: Record<string, unknown>;
    baseline_verification?: Record<string, unknown>;
    first_review?: Record<string, unknown>;
  };
  patches: {
    queue_totals: Record<string, number>;
    manifests: Array<Record<string, unknown>>;
    deferred_backlog: Array<Record<string, unknown>>;
    deferred_triage?: Record<string, unknown>;
    recent_outcomes: Array<Record<string, unknown>>;
  };
  timeline: Array<Record<string, unknown>>;
  metrics: Record<string, number>;
  review?: {
    items?: Array<Record<string, unknown>>;
    known_issues?: Array<Record<string, unknown>>;
  };
};

export type InboxMessage = {
  id: string;
  title: string;
  status: string;
  status_label: string;
  ui_state: "pending" | "handled" | "queued" | "consumed" | "archived" | "failed" | "sent" | "unknown" | string;
  timestamp?: string;
  request_id?: string;
  source_inbox_id?: string;
  intent?: string;
  channel?: string;
  from?: string;
  to?: string;
  related?: {
    request?: string;
    ticket?: string;
    run?: string;
    file?: string;
  };
  metadata?: Record<string, string>;
  body: string;
  summary: string;
  kind: "request" | "note" | "archive" | "outbound" | string;
  source_file_key?: string;
  truncated?: boolean;
};

export type InboxSnapshot = {
  target: TargetMetadata;
  bridge_mode: string;
  requests: InboxMessage[];
  active_requests: InboxMessage[];
  notes: InboxMessage[];
  active_notes: InboxMessage[];
  archive: InboxMessage[];
  outbox: InboxMessage[];
  counts: {
    pending_requests: number;
    queued_notes: number;
    failed_notes: number;
    archived_items: number;
    outbound_records: number;
  };
  raw_file_keys: string[];
};

export type ReviewChangedFile = {
  path: string;
  status: string;
  kind: string;
  summary: string;
};

export type ReviewSnapshot = {
  target: TargetMetadata;
  generated_at?: string;
  review_fingerprint?: string;
  latest_run: {
    status: string;
    horizon: string;
    summary: string;
    log?: Record<string, unknown>;
    action_plan?: Record<string, unknown>;
  };
  changed_files: ReviewChangedFile[];
  changed_files_source: string;
  latest_commits: ObservatoryCommit[];
  verification: {
    summary: string;
    counts: Record<string, number>;
    items: Array<Record<string, unknown>>;
    baseline?: Record<string, unknown>;
  };
  safety: Record<string, unknown>;
  limitations: Array<Record<string, unknown>>;
  self_review: {
    markdown_preview: string;
    truncated: boolean;
    default_markdown_path: string;
  };
  bundle: {
    review_dir: string;
    html_path: string;
    markdown_path: string;
  };
  review?: Record<string, unknown>;
  reviewed: {
    exists: boolean;
    path: string;
    reviewed_at?: string;
    note?: string;
    snapshot_generated_at?: string;
    review_fingerprint?: string;
    is_current_snapshot?: boolean;
  };
  empty_states?: Record<string, unknown>;
};

export type AdvancedFilesSnapshot = {
  target: TargetMetadata;
  files: RegisteredFile[];
  categories: Record<string, number>;
};

export type AdvancedLoadedFile = {
  target: TargetMetadata;
  file: RegisteredFile;
  content: string;
  truncated: boolean;
};

export type AdvancedValidationResult = {
  target: TargetMetadata;
  file: RegisteredFile;
  status: "pass" | "fail" | "missing" | "not_available" | string;
  items: Array<{ ok: boolean; detail: string }>;
  result?: Record<string, unknown>;
};

export type AdvancedDebugBundleResult = {
  target: TargetMetadata;
  bundle_path: string;
  included: string[];
  omitted: string[];
};

export type StateSnapshotResult = {
  target: TargetMetadata;
  state: CanonicalStateSnapshot;
};

export type DiagnosticsSnapshot = {
  target: TargetMetadata;
  prerequisites: {
    status: string;
    items: Array<Record<string, unknown>>;
    required_failures: Array<Record<string, unknown>>;
  };
  required_files: Record<string, unknown>;
  state?: Record<string, unknown>;
  integration_safety: Record<string, unknown>;
  tools: Array<Record<string, unknown>>;
  target_writability: Record<string, unknown>;
  macos_permissions: Record<string, unknown>;
  notifier_health: Record<string, unknown>;
  automation: Record<string, unknown>;
  runtime_environment?: RuntimeEnvironmentSnapshot;
  fix_suggestions?: FixSuggestion[];
  backend: Record<string, unknown>;
};

export type ToolStatus = {
  name: string;
  ok: boolean;
  required: boolean;
  path?: string;
  detail: string;
};

export type RuntimeEnvironmentSnapshot = {
  kit_root: string;
  backend_python: string;
  backend_python_version: string;
  native_app_path: string;
  effective_path: string;
  codex_automation_path_override?: string;
  dotenv_loaded?: boolean;
  tools: ToolStatus[];
};

export type FixSuggestion = {
  id: string;
  title: string;
  detail: string;
  command: string;
};

export type EnvironmentDiagnosticsSnapshot = {
  status: string;
  runtime_environment: RuntimeEnvironmentSnapshot;
  fix_suggestions: FixSuggestion[];
  required_failures: Array<Record<string, unknown>>;
  setup_mode: string;
};

export type AdvancedSettings = {
  reviewExportDir: string;
  preferredEditorCommand: string;
  humanBridgeMode: string;
  appearance: "system" | "light" | "dark" | string;
  density: "compact" | "comfortable" | string;
};

export type ProjectLoadResult = {
  target: RecentTarget;
  snapshot: BackendEnvelope<ProjectSnapshot>;
};

export type PickedContextFile = {
  path: string;
  name: string;
  sizeBytes: number;
  fileType: string;
};

export type BackendLogEvent = {
  runId: string;
  command: string;
  stage: string;
  level: "info" | "warning" | "error" | string;
  message: string;
  data?: Record<string, unknown>;
};

export function listRecentProjects(): Promise<RecentTarget[]> {
  return invoke<RecentTarget[]>("list_recent_projects");
}

export function selectProjectFolder(): Promise<ProjectLoadResult | null> {
  return invoke<ProjectLoadResult | null>("select_project_folder");
}

export function selectContextFiles(): Promise<PickedContextFile[]> {
  return invoke<PickedContextFile[]>("select_context_files");
}

export function selectTicketImportFile(): Promise<string | null> {
  return invoke<string | null>("select_ticket_import_file");
}

export function loadProjectSnapshot(
  target: string,
): Promise<BackendEnvelope<ProjectSnapshot>> {
  return invoke<BackendEnvelope<ProjectSnapshot>>("load_project_snapshot", {
    target,
  });
}

export function runBackendCommand<T = unknown>(request: {
  command: string;
  target?: string;
  reviewDir?: string;
  outputDir?: string;
  fileKey?: string;
  intakeJson?: string;
  filesJson?: string;
  projectName?: string;
  ownership?: string;
  requestId?: string;
  body?: string;
  intent?: string;
  related?: string;
  force?: boolean;
  runCodex?: boolean;
  ticketJson?: string;
  ticketId?: string;
  importFormat?: "markdown" | "csv" | "json" | string;
  importMode?: "append" | "replace-placeholder" | "replace-all" | string;
  inputFile?: string;
  inputJson?: string;
  inputText?: string;
  preview?: boolean;
  draftId?: string;
  ticketIds?: string;
}): Promise<BackendEnvelope<T>> {
  return invoke<BackendEnvelope<T>>("run_backend_command", request);
}

export function runBackendCommandStreamed<T = unknown>(request: {
  runId: string;
  command: string;
  target?: string;
  reviewDir?: string;
  outputDir?: string;
  fileKey?: string;
  intakeJson?: string;
  filesJson?: string;
  projectName?: string;
  ownership?: string;
  requestId?: string;
  body?: string;
  intent?: string;
  related?: string;
  force?: boolean;
  runCodex?: boolean;
  ticketJson?: string;
  ticketId?: string;
  importFormat?: "markdown" | "csv" | "json" | string;
  importMode?: "append" | "replace-placeholder" | "replace-all" | string;
  inputFile?: string;
  inputJson?: string;
  inputText?: string;
  preview?: boolean;
  draftId?: string;
  ticketIds?: string;
}): Promise<BackendEnvelope<T>> {
  return invoke<BackendEnvelope<T>>("run_backend_command_streamed", request);
}

export function openObservatoryFile(path: string): Promise<void> {
  return invoke<void>("open_observatory_file", { path });
}

export function openReviewArtifact(path: string): Promise<void> {
  return invoke<void>("open_review_artifact", { path });
}

export function revealReviewArtifact(path: string): Promise<void> {
  return invoke<void>("reveal_review_artifact", { path });
}

export function openManagedFile(target: string, fileKey: string): Promise<void> {
  return invoke<void>("open_managed_file", { target, fileKey });
}

export function revealManagedFile(target: string, fileKey: string): Promise<void> {
  return invoke<void>("reveal_managed_file", { target, fileKey });
}

export function revealProject(target: string): Promise<void> {
  return invoke<void>("reveal_project", { target });
}

export function openProjectInEditor(target: string): Promise<void> {
  return invoke<void>("open_project_in_editor", { target });
}

export function getAdvancedSettings(): Promise<AdvancedSettings> {
  return invoke<AdvancedSettings>("get_advanced_settings");
}

export function updateAdvancedSettings(
  settings: AdvancedSettings,
): Promise<AdvancedSettings> {
  return invoke<AdvancedSettings>("update_advanced_settings", { settings });
}

export function selectSettingsDirectory(): Promise<string | null> {
  return invoke<string | null>("select_settings_directory");
}

export function listenBackendLogs(
  runId: string,
  onLog: (event: BackendLogEvent) => void,
): Promise<UnlistenFn> {
  return listen<BackendLogEvent>("backend-log", (event) => {
    if (event.payload.runId === runId) {
      onLog(event.payload);
    }
  });
}
