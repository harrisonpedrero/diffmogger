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
  automation_activity?: Record<string, unknown>;
  conveyor_state?: Record<string, unknown>;
  conveyor_machine?: ConveyorMachineSnapshot | Record<string, unknown>;
  execution_dag?: Record<string, unknown>;
  progress_model?: Record<string, unknown>;
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
  proposed_execution_groups?: Array<Record<string, unknown>>;
  parallelization_summary?: Record<string, unknown>;
  blocked_parallel_candidates?: Array<Record<string, unknown>>;
  why_not_parallel?: Record<string, unknown>;
  scheduler_parallel_dry_run?: Record<string, unknown>;
  parallelism_budgets?: Array<Record<string, unknown>>;
  active_parallel_counts?: Record<string, number>;
  budget_exhaustion_reasons?: Array<Record<string, unknown>>;
  active_read_only_workers?: Array<Record<string, unknown>>;
  pending_worker_reports?: Array<Record<string, unknown>>;
  completed_worker_reports?: Array<Record<string, unknown>>;
  worker_finding_disposition_required?: boolean;
  active_write_workers?: Array<Record<string, unknown>>;
  queued_worker_patches?: Array<Record<string, unknown>>;
  write_worker_conflicts?: Array<Record<string, unknown>>;
  lease_conflict_summary?: Record<string, unknown>;
  integration_backlog_from_parallel_workers?: Array<Record<string, unknown>>;
  worker_patch_integration_preflight?: Record<string, unknown>;
  active_validation_jobs?: Array<Record<string, unknown>>;
  validation_job_summary?: Record<string, unknown>;
  parallel_validation_available?: boolean;
  validation_budget_status?: Record<string, unknown>;
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
  setup: {
    [key: string]: unknown;
    project_name?: string;
    project_mode?: string;
    configured?: boolean;
    status?: string;
    horizon?: string;
    task?: Record<string, unknown>;
    git?: {
      branch?: string;
      dirty_count?: number;
      recent_commits?: string[];
      commits?: Array<Record<string, unknown>>;
    };
    files?: RegisteredFile[];
    context_files?: unknown[];
    intake?: Record<string, unknown>;
    draft_intake?: Record<string, unknown>;
    dashboard_state?: Record<string, unknown>;
    detected?: Record<string, unknown>;
    snapshot_generated_at?: string;
  };
  scheduler: {
    selected_action?: Record<string, unknown>;
    candidates?: Array<Record<string, unknown>>;
    next_actions?: Array<Record<string, unknown>>;
    decision_queue?: Array<Record<string, unknown>>;
    active_role_run?: Record<string, unknown>;
    last_cycle?: Record<string, unknown>;
    mode?: string;
    parallelization_summary?: Record<string, unknown>;
    scheduler_fallback_used?: boolean;
    why_not_parallel?: Record<string, unknown>;
    scheduler_parallel_dry_run?: Record<string, unknown>;
    blocked_candidates?: Array<Record<string, unknown>>;
    skipped_candidates?: Array<Record<string, unknown>>;
  };
  dag: {
    summary?: Record<string, number>;
    execution_dag?: Record<string, unknown>;
    proposed_execution_groups?: Array<Record<string, unknown>>;
    active_execution_groups?: Array<Record<string, unknown>>;
    recent_execution_groups?: Array<Record<string, unknown>>;
    recently_completed_execution_groups?: Array<Record<string, unknown>>;
    active_read_only_workers?: Array<Record<string, unknown>>;
    active_write_workers?: Array<Record<string, unknown>>;
    completed_worker_reports?: Array<Record<string, unknown>>;
    queued_worker_patches?: Array<Record<string, unknown>>;
    write_worker_conflicts?: Array<Record<string, unknown>>;
    active_leases?: Array<Record<string, unknown>>;
    conflicting_leases?: Array<Record<string, unknown>>;
    stale_graph_warnings?: Array<Record<string, unknown>>;
    integration_backlog_from_parallel_workers?: Array<Record<string, unknown>>;
    worker_patch_integration_preflight?: Record<string, unknown>;
    recent_outcomes?: Array<Record<string, unknown>>;
    queue?: Record<string, unknown>;
  };
  tickets: {
    counts?: Record<string, unknown>;
    items?: Array<Record<string, unknown>>;
    remaining?: Array<Record<string, unknown>>;
    remaining_count?: number;
    source?: string;
  };
  human_input: {
    pending_requests?: number;
    unhandled_records?: number;
    unhandled_inbox?: number;
    outbound_records?: number;
    summary?: string;
    notification_mode?: string;
    notifier_status?: Record<string, unknown>;
    message_counts?: Record<string, unknown>;
  };
  validation_repair: {
    validation?: Record<string, unknown>;
    integration_safety?: Record<string, unknown>;
    active_validation_jobs?: Array<Record<string, unknown>>;
    validation_job_summary?: Record<string, unknown>;
    validation_receipts?: Array<Record<string, unknown>>;
    repair_actions?: Array<Record<string, unknown>>;
    open_blockers?: Array<Record<string, unknown>>;
    setup_repair_inputs?: Array<Record<string, unknown>>;
  };
  controls: {
    [key: string]: unknown;
    is_scaffolded?: boolean;
    is_running?: boolean;
    can_start_automation?: boolean;
    start_automation_reason?: string;
    can_stop_automation?: boolean;
    stop_automation_reason?: string;
    can_run_safety_check?: boolean;
    automation?: Record<string, unknown>;
    worker_strategy?: Record<string, unknown>;
    worker_controls?: Record<string, unknown>;
    latest_worker_result?: Record<string, unknown>;
    run_log?: Record<string, unknown>;
  };
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
  executionGroupId?: string;
  leaseId?: string;
  groupMode?: "auto" | "read_only" | "write_workers" | "validation" | string;
  maxWorkers?: number;
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
  executionGroupId?: string;
  leaseId?: string;
  groupMode?: "auto" | "read_only" | "write_workers" | "validation" | string;
  maxWorkers?: number;
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
