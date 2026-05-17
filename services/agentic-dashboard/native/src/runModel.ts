import type { ProjectSnapshot } from "./api/backend";

export type RunActionKind = "choose-project" | "navigate" | "backend" | "disabled";
export type RunRoute = "Brief" | "Review" | "Advanced" | "Run" | "Inbox";
export type RunTone = "good" | "warn" | "critical" | "info" | "quiet";

export type RunAction = {
  label: string;
  kind: RunActionKind;
  command?: string;
  route?: RunRoute;
  enabled: boolean;
  reason: string;
};

export type RunLogLine = {
  timestamp: string;
  text: string;
};

export type RunSafetyRow = {
  label: string;
  status: string;
  summary: string;
  source: string;
  tone: RunTone;
  action: RunAction;
};

export type RunDagPhaseId =
  | "orchestrate"
  | "decompose"
  | "scope"
  | "build"
  | "review"
  | "validate"
  | "repair"
  | "integrate"
  | "audit"
  | "done";
export type RunDagStatusKind = "pending" | "ready" | "running" | "completed" | "blocked" | "failed" | "skipped";
export type RunDagBadgeTone = "good" | "warn" | "critical" | "info" | "quiet";
export type RunDagRenderMode = "normal" | "large" | "oversized";

export type RunDagBadge = {
  kind: "attempt" | "validation" | "patch" | "blocker" | "worktree" | "lease";
  label: string;
  tone: RunDagBadgeTone;
};

export type RunDagNode = {
  id: string;
  ticketId: string;
  actionType: string;
  canonicalActionType: string;
  status: string;
  statusKind: RunDagStatusKind;
  ownerRole: string;
  phase: RunDagPhaseId;
  attemptCount: number;
  confidence: number;
  confidenceLabel: string;
  blockerReason: string;
  validationReceiptRefs: string[];
  ownershipScope: string;
  patchId: string;
  patchPath: string;
  worktreePath: string;
  startedAt: string;
  finishedAt: string;
  badges: RunDagBadge[];
  detail: string;
};

export type RunDagEdge = {
  id: string;
  source: string;
  target: string;
  dependencyKind: string;
  dependencyMode: string;
  presentationKind: "hard" | "advisory" | "blocker";
  reason: string;
  confidence: number;
  confidenceLabel: string;
  detail: string;
};

export type RunDagColumn = {
  id: RunDagPhaseId;
  label: string;
  nodes: RunDagNode[];
};

export type RunDagSummary = {
  total: number;
  pending: number;
  ready: number;
  running: number;
  completed: number;
  blocked: number;
  failed: number;
  skipped: number;
};

export type RunDagGroup = {
  id: string;
  label: string;
  mode: string;
  status: string;
  kind: "proposed" | "active" | "completed";
  nodeIds: string[];
  detail: string;
};

export type RunOperationItem = {
  id: string;
  label: string;
  role: string;
  action: string;
  taskId: string;
  status: string;
  tone: RunTone;
  source: string;
  groupId: string;
  detail: string;
};

export type RunOperationCallout = {
  title: string;
  detail: string;
  tone: RunTone;
  role: string;
  action: string;
  taskId: string;
  source: string;
};

export type RunProgressCell = {
  status: string;
  statusKind: RunDagStatusKind;
  role: string;
  detail: string;
  nodeId: string;
};

export type RunProgressColumnId = "scope" | "build" | "review" | "validate" | "integrate" | "done";

export type RunProgressRow = {
  taskId: string;
  label: string;
  compatibility: boolean;
  cells: Record<RunProgressColumnId, RunProgressCell | null>;
  summary: string;
};

export type RunConcurrencyWave = {
  id: string;
  label: string;
  kind: "proposed" | "active" | "completed" | "blocked" | "integration";
  mode: string;
  status: string;
  tone: RunTone;
  itemCount: number;
  owners: string[];
  tasks: string[];
  leases: string[];
  detail: string;
};

export type RunIntegrationBacklog = {
  queuedCount: number;
  conflictCount: number;
  safeCount: number;
  blockedCount: number;
  tone: RunTone;
  summary: string;
  patchSamples: string[];
};

export type RunDagCluster = {
  id: string;
  label: string;
  phase: RunDagPhaseId;
  kind: "phase_status";
  statusKind: RunDagStatusKind;
  nodeIds: string[];
  nodeCount: number;
  statusCounts: RunDagSummary;
  ticketSamples: string[];
  ownerSamples: string[];
  actionSamples: string[];
  plannedGroupNodeCount: number;
  activeGroupNodeCount: number;
  detail: string;
};

export type RunDagClusterEdge = {
  id: string;
  source: string;
  target: string;
  dependencyKind: string;
  dependencyMode: string;
  presentationKind: "hard" | "advisory" | "blocker";
  count: number;
  reason: string;
  detail: string;
};

export type RunModel = {
  isScaffolded: boolean;
  isRunning: boolean;
  banner: {
    headline: string;
    subheadline: string;
    badge: string;
    tone: RunTone;
    primaryAction: RunAction;
  };
  controls: {
    startAutomation: RunAction;
    stopAutomation: RunAction;
    safetyCheck: RunAction;
    exportReview: RunAction;
  };
  automation: {
    state: string;
    message: string;
    pid: string;
    startedAt: string;
    logDir: string;
  };
  latestRun: {
    status: string;
    horizon: string;
    lastUpdated: string;
    summary: string;
  };
  executionDag: {
    hasData: boolean;
    authority: string;
    digest: string;
    summary: RunDagSummary;
    columns: RunDagColumn[];
    nodes: RunDagNode[];
    edges: RunDagEdge[];
    visibleNodes: RunDagNode[];
    visibleEdges: RunDagEdge[];
    groups: RunDagGroup[];
    clusters: RunDagCluster[];
    clusterEdges: RunDagClusterEdge[];
    abstraction: {
      enabled: boolean;
      level: "node" | "phase-status";
      clusterCount: number;
      bundledEdgeCount: number;
      sourceNodeCount: number;
      sourceEdgeCount: number;
    };
    renderMode: RunDagRenderMode;
    renderLimit: {
      nodeCap: number;
      edgeCap: number;
      visibleNodeCount: number;
      visibleEdgeCount: number;
      hiddenNodeCount: number;
      hiddenEdgeCount: number;
    };
    parallel: {
      proposedGroups: number;
      activeGroups: number;
      completedGroups: number;
      plannedNodeCount: number;
      activeNodeCount: number;
    };
  };
  operations: {
    runningNow: RunOperationItem[];
    nextUnlock: RunOperationCallout;
    progressRows: RunProgressRow[];
    concurrencyWaves: RunConcurrencyWave[];
    integrationBacklog: RunIntegrationBacklog;
  };
  runLog: {
    exists: boolean;
    path: string;
    modifiedAt: string;
    content: string;
    lines: RunLogLine[];
  };
  worker: {
    headline: string;
    mode: string;
    tone: RunTone;
    focus: string;
    output: string;
    summary: string;
    raw: Record<string, unknown>;
    latest: string;
    actions: {
      readOnly: RunAction;
      write: RunAction;
      integrator: RunAction;
    };
  };
  safety: RunSafetyRow[];
  blockers: Array<{
    name: string;
    detail: string;
    required: boolean;
    canRecheck: boolean;
    recheckCommand: string;
    recheckLabel: string;
  }>;
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "Not recorded"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function bool(value: unknown): boolean {
  return value === true;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function makeAction(
  label: string,
  enabled: boolean,
  reason: string,
  command?: string,
): RunAction {
  return {
    label,
    kind: enabled ? "backend" : "disabled",
    command,
    enabled,
    reason,
  };
}

function routeAction(label: string, route: RunRoute, reason: string): RunAction {
  return { label, kind: "navigate", route, enabled: true, reason };
}

function isScaffolded(snapshot: ProjectSnapshot | null): boolean {
  if (!snapshot) return false;
  const controls = record(snapshot.run.controls);
  return Boolean(controls.is_scaffolded || snapshot.target.automation_task_exists);
}

function statusTone(status: string, blockers: unknown[]): RunTone {
  if (status.includes("CRITICAL")) return "critical";
  if (status.includes("BLOCKED") || blockers.length > 0) return "warn";
  if (status.includes("RUNNING")) return "info";
  if (status === "ACTIVE" || status === "ACTIVE_WITH_PENDING_USER_INPUT") return "good";
  return "quiet";
}

function bannerTone(title: string, status: string, blockers: unknown[]): RunTone {
  if (title === "Critical stop") return "critical";
  if (title === "Env blocked" || title === "User input" || title === "Stale") return "warn";
  if (title === "Running") return "info";
  if (title === "No target" || title === "Unknown") return "quiet";
  return statusTone(status, blockers);
}

function safetyTone(value: unknown): RunTone {
  const raw = text(value, "").toLowerCase();
  if (["pass", "passed", "ok", "ready", "clean", "reviewed", "none", "clear"].includes(raw)) return "good";
  if (["fail", "failed", "critical", "critical_stop", "error"].includes(raw)) return "critical";
  if (["warn", "warning", "blocked", "pending", "missing", "not_run", "unknown", "not_recorded", "setup needed"].includes(raw)) return "warn";
  if (["running", "active", "info"].includes(raw)) return "info";
  return "quiet";
}

function stateTitle(snapshot: ProjectSnapshot | null, scaffolded: boolean, running: boolean, blockers: unknown[], status: string): string {
  if (!snapshot) return "No target";
  const upper = status.toUpperCase();
  const human = record(snapshot.run.human);
  const pendingHuman = number(human.pending_requests) + number(human.unhandled_inbox);
  const validation = record(record(snapshot.run.task).validation);
  const validationCounts = record(validation.counts);
  const integrationSafety = record(record(snapshot.run.task).integration_safety);
  if (upper.includes("STALE")) return "Stale";
  if (upper === "CRITICAL_STOP") return "Critical stop";
  if (upper === "BLOCKED_ON_USER" || upper === "ACTIVE_WITH_PENDING_USER_INPUT" || pendingHuman > 0) return "User input";
  if (upper === "BLOCKED_ON_ENVIRONMENT" || blockers.length > 0 || number(validationCounts.fail) > 0 || text(integrationSafety.status, "").toLowerCase() === "fail") return "Env blocked";
  if (running) return "Running";
  if (!scaffolded || upper === "UNKNOWN") return "Unknown";
  if (upper === "STOPPED") return "Stopped";
  return "Ready";
}

function displayStatus(status: string): string {
  if (!status || status === "UNKNOWN" || status === "NO_TARGET") return "Not recorded yet";
  return status.replace(/_/g, " ");
}

function workerHeadline(strategy: Record<string, unknown>): string {
  const name = text(strategy.strategy, "NO_WORKERS");
  const rawBudget = strategy.parallelism_budget;
  const budget = typeof rawBudget === "number" && Number.isFinite(rawBudget) ? rawBudget : Number(rawBudget || 0);
  const lane = text(strategy.action_lane, "local");
  if (name === "READ_ONLY_REPORTS") {
    return `Recommended: ${budget === 1 ? "one" : Math.max(1, budget)} read-only ${lane} report`;
  }
  if (name === "WRITE_WORKERS") {
    return `Recommended: up to ${Math.max(1, budget)} bounded ${lane} write worker${Math.max(1, budget) === 1 ? "" : "s"}`;
  }
  if (name === "INTEGRATION_ONLY") {
    return "Recommended: integration-only pass";
  }
  return "No manual helper run recommended";
}

function workerMode(strategy: Record<string, unknown>): string {
  const name = text(strategy.strategy, "NO_WORKERS");
  if (name === "READ_ONLY_REPORTS") return "Read-only report";
  if (name === "WRITE_WORKERS") return "Write helper";
  if (name === "INTEGRATION_ONLY") return "Integrator";
  return "No helper";
}

function workerTone(strategy: Record<string, unknown>): RunTone {
  const name = text(strategy.strategy, "NO_WORKERS");
  if (name === "WRITE_WORKERS") return "warn";
  if (name === "READ_ONLY_REPORTS" || name === "INTEGRATION_ONLY") return "info";
  return "quiet";
}

function workerRole(strategy: Record<string, unknown>): string {
  const lane = text(strategy.action_lane, "review").toLowerCase();
  if (["planner", "builder", "hardener", "integrator"].includes(lane)) return `${lane}_strategy`;
  return `${text(strategy.strategy, "review").toLowerCase()}_strategy`
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function runLog(snapshot: ProjectSnapshot | null): RunModel["runLog"] {
  const raw = record(snapshot?.run.run_log);
  const lines = list(raw.lines)
    .map(record)
    .map((line) => ({
      timestamp: text(line.timestamp, text(raw.modified_at, "")),
      text: text(line.text, ""),
    }))
    .filter((line) => line.text);
  return {
    exists: bool(raw.exists),
    path: text(raw.rel_path, text(raw.path, "")),
    modifiedAt: text(raw.modified_at, ""),
    content: text(raw.content, ""),
    lines,
  };
}

const NORMAL_DAG_NODE_CAP = 250;
const NORMAL_DAG_EDGE_CAP = 700;
const OVERSIZED_DAG_NODE_THRESHOLD = 800;
const OVERSIZED_DAG_EDGE_THRESHOLD = 2500;

const DAG_PHASES: Array<{ id: RunDagPhaseId; label: string }> = [
  { id: "orchestrate", label: "Orchestrate" },
  { id: "decompose", label: "Decompose" },
  { id: "scope", label: "Scope" },
  { id: "build", label: "Build" },
  { id: "review", label: "Review" },
  { id: "validate", label: "Validate" },
  { id: "repair", label: "Repair" },
  { id: "integrate", label: "Integrate" },
  { id: "audit", label: "Audit/Calibrate" },
  { id: "done", label: "Done" },
];

const DAG_ACTION_ALIASES: Record<string, string> = {
  planning: "decompose",
  scoping: "scope",
  building: "build",
  reviewing: "review",
  validation: "validate",
  integration: "integrate",
  calibrate: "audit",
  completion: "done",
  blocker: "done",
  ticket: "decompose",
};

const DAG_STATUS_ORDER: RunDagStatusKind[] = ["running", "ready", "blocked", "failed", "pending", "completed", "skipped"];

function executionDagSnapshot(snapshot: ProjectSnapshot | null): Record<string, unknown> {
  const state = record(snapshot?.run.state);
  const activity = record(state.automation_activity);
  if (Array.isArray(activity.nodes)) return activity;
  const dag = record(state.execution_dag);
  if (Object.keys(dag).length) return dag;
  const progress = record(state.progress_model);
  if (text(progress.projection, "") === "execution_dag" || Array.isArray(progress.nodes)) return progress;
  return {};
}

function textList(value: unknown): string[] {
  return list(value)
    .map((item) => text(item, ""))
    .filter((item) => item.length > 0);
}

function compactText(value: unknown, fallback = ""): string {
  return text(value, fallback).replace(/\s+/g, " ").trim();
}

function confidenceLabel(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0%";
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`;
}

function statusKind(rawStatus: string, dependencyBlocked: boolean, blockerReason: string): RunDagStatusKind {
  const status = rawStatus.toLowerCase().replace(/[\s-]+/g, "_");
  if (["skipped", "superseded"].includes(status)) return "skipped";
  if (["failed", "failure", "cancelled", "canceled", "error"].includes(status)) return "failed";
  if (["blocked", "blocked_on_user", "blocked_on_environment", "critical_stop"].includes(status) || blockerReason) return "blocked";
  if (["done", "complete", "completed", "candidate_done", "passed", "validated", "reviewed", "integrated", "resolved", "closed"].includes(status)) {
    return "completed";
  }
  if (["active", "running", "in_progress"].includes(status)) return "running";
  if (status === "ready") return dependencyBlocked ? "pending" : "ready";
  return "pending";
}

function canonicalDagAction(actionType: string): string {
  const action = actionType.toLowerCase().replace(/[\s-]+/g, "_");
  return DAG_ACTION_ALIASES[action] ?? action;
}

function dagPhase(actionType: string): RunDagPhaseId {
  const action = canonicalDagAction(actionType);
  if (DAG_PHASES.some((phase) => phase.id === action)) return action as RunDagPhaseId;
  return "done";
}

function ownershipScope(metadata: Record<string, unknown>): string {
  const paths = textList(metadata.paths || metadata.changed_files || metadata.target_paths);
  if (paths.length) return paths.slice(0, 3).join(", ");
  const scope = compactText(metadata.ownership_scope || metadata.scope || metadata.execution_mode, "");
  return scope || "No ownership scope recorded";
}

function dagNodeDetail(node: {
  id: string;
  ticketId: string;
  actionType: string;
  canonicalActionType: string;
  status: string;
  ownerRole: string;
  attemptCount: number;
  confidenceLabel: string;
  blockerReason: string;
  validationReceiptRefs: string[];
  ownershipScope: string;
  patchId: string;
  patchPath: string;
  worktreePath: string;
}): string {
  return [
    `${node.actionType} for ${node.ticketId || node.id}`,
    `action ${node.canonicalActionType}`,
    `status ${node.status}`,
    `owner ${node.ownerRole}`,
    `attempt ${node.attemptCount}`,
    `confidence ${node.confidenceLabel}`,
    `scope ${node.ownershipScope}`,
    node.blockerReason ? `blocker ${node.blockerReason}` : "",
    node.validationReceiptRefs.length ? `validation receipts ${node.validationReceiptRefs.join(", ")}` : "",
    node.patchId || node.patchPath ? `patch ${[node.patchId, node.patchPath].filter(Boolean).join(" ")}` : "",
    node.worktreePath ? `worktree ${node.worktreePath}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function dagBadges(node: {
  attemptCount: number;
  blockerReason: string;
  validationReceiptRefs: string[];
  patchId: string;
  patchPath: string;
  worktreePath: string;
}): RunDagBadge[] {
  const badges: RunDagBadge[] = [];
  if (node.attemptCount > 1) badges.push({ kind: "attempt", label: `${node.attemptCount} attempts`, tone: "warn" });
  if (node.validationReceiptRefs.length) badges.push({ kind: "validation", label: `${node.validationReceiptRefs.length} receipts`, tone: "good" });
  if (node.patchId || node.patchPath) badges.push({ kind: "patch", label: "patch", tone: "info" });
  if (node.blockerReason) badges.push({ kind: "blocker", label: "blocker", tone: "warn" });
  if (node.worktreePath) badges.push({ kind: "worktree", label: "worktree", tone: "quiet" });
  return badges;
}

function blockedReasonByNode(dag: Record<string, unknown>): Map<string, { hardBlocked: boolean; dependencyBlocked: boolean; reason: string }> {
  const result = new Map<string, { hardBlocked: boolean; dependencyBlocked: boolean; reason: string }>();
  for (const item of list(dag.blocked_nodes).map(record)) {
    const id = text(item.node_id, "");
    if (!id) continue;
    const reasons = list(item.blocked_reasons).map(record);
    const hardReason = reasons.find((reason) => ["status", "blocker"].includes(text(reason.kind, "")));
    const dependencyReason = reasons.find((reason) => text(reason.kind, "") === "dependency");
    result.set(id, {
      hardBlocked: Boolean(hardReason),
      dependencyBlocked: Boolean(dependencyReason),
      reason: text(hardReason?.reason, text(dependencyReason?.reason, "")),
    });
  }
  return result;
}

function groupItemNodeIds(group: Record<string, unknown>, nodes: RunDagNode[]): string[] {
  const nodesByTaskAction = new Map<string, string>();
  for (const node of nodes) {
    nodesByTaskAction.set(`${node.ticketId}::${node.canonicalActionType}`, node.id);
    nodesByTaskAction.set(`${node.ticketId}::${node.actionType}`, node.id);
  }
  const ids = new Set<string>();
  for (const item of list(group.items).map(record)) {
    const payload = record(item.payload);
    const dagNodeId = text(payload.dag_node_id || item.dag_node_id, "");
    if (dagNodeId) ids.add(dagNodeId);
    const taskId = text(item.task_id || payload.task_id, "");
    const action = canonicalDagAction(text(item.action_kind || payload.action_type || payload.canonical_action_type, ""));
    const inferred = nodesByTaskAction.get(`${taskId}::${action}`);
    if (inferred) ids.add(inferred);
  }
  return Array.from(ids).filter((id) => nodes.some((node) => node.id === id));
}

function dagGroups(snapshot: ProjectSnapshot | null, nodes: RunDagNode[]): RunDagGroup[] {
  const state = record(snapshot?.run.state);
  const proposed = list(state.proposed_execution_groups).map(record);
  const groups: RunDagGroup[] = proposed
    .map((group, index) => {
      const id = text(group.execution_group_id, `proposed-wave-${index + 1}`);
      const mode = text(group.mode, text(record(group.payload).execution_mode, "dry_run"));
      const status = text(group.status, "proposed");
      const nodeIds = groupItemNodeIds(group, nodes);
      return {
        id,
        label: `planned wave ${index + 1}`,
        mode,
        status,
        kind: "proposed" as const,
        nodeIds,
        detail: compactText(group.reason, `${nodeIds.length} activity node(s) are safe to consider together.`),
      };
    })
    .filter((group) => group.nodeIds.length > 0);

  const byId = new Map(groups.map((group) => [group.id, group]));
  const activeSources = [
    ...list(state.active_read_only_workers).map(record),
    ...list(state.active_write_workers).map(record),
    ...list(state.active_validation_jobs).map(record),
  ];
  const activeIds = new Set(activeSources.map((item) => text(item.execution_group_id, "")).filter(Boolean));
  for (const id of activeIds) {
    const base = byId.get(id);
    if (base) {
      groups.push({ ...base, id: `${id}:active`, label: "running group", status: "running", kind: "active" });
      continue;
    }
    const nodeIds = new Set<string>();
    for (const item of activeSources.filter((source) => text(source.execution_group_id, "") === id)) {
      const taskId = text(item.task_id || item.ticket_id, "");
      const dagNodeId = text(item.dag_node_id || item.source_dag_node_id, "");
      if (dagNodeId) nodeIds.add(dagNodeId);
      if (taskId) {
        for (const node of nodes) {
          if (node.ticketId === taskId && ["running", "ready", "pending"].includes(node.statusKind)) nodeIds.add(node.id);
        }
      }
    }
    groups.push({
      id: `${id}:active`,
      label: "running group",
      mode: "runtime",
      status: "running",
      kind: "active",
      nodeIds: Array.from(nodeIds).filter((nodeId) => nodes.some((node) => node.id === nodeId)),
      detail: "Runtime workers or validation jobs are active for this group.",
    });
  }

  for (const item of list(state.completed_worker_reports).map(record).slice(0, 6)) {
    const taskId = text(item.task_id || item.ticket_id, "");
    const nodeIds = nodes.filter((node) => node.ticketId === taskId && node.statusKind === "completed").map((node) => node.id);
    if (!nodeIds.length) continue;
    groups.push({
      id: text(item.report_id || item.worker_id, `completed-${groups.length + 1}`),
      label: "completed group",
      mode: "worker",
      status: "completed",
      kind: "completed",
      nodeIds,
      detail: "A worker report has completed for this ticket.",
    });
  }
  return groups.filter((group, index, all) => all.findIndex((item) => item.id === group.id) === index);
}

function visibleDagSet(nodes: RunDagNode[], edges: RunDagEdge[], groups: RunDagGroup[]): Set<string> {
  if (nodes.length <= NORMAL_DAG_NODE_CAP && edges.length <= NORMAL_DAG_EDGE_CAP) {
    return new Set(nodes.map((node) => node.id));
  }
  const groupNodeIds = new Set(groups.flatMap((group) => group.nodeIds));
  const important = new Set<string>();
  for (const node of nodes) {
    if (["running", "ready", "blocked", "failed"].includes(node.statusKind) || groupNodeIds.has(node.id)) important.add(node.id);
  }
  for (const edge of edges) {
    if (important.has(edge.source) || important.has(edge.target)) {
      important.add(edge.source);
      important.add(edge.target);
    }
  }
  if (important.size < NORMAL_DAG_NODE_CAP) {
    for (const node of nodes) {
      if (important.size >= NORMAL_DAG_NODE_CAP) break;
      important.add(node.id);
    }
  }
  return new Set(Array.from(important).slice(0, NORMAL_DAG_NODE_CAP));
}

function emptyDagSummary(): RunDagSummary {
  return {
    total: 0,
    pending: 0,
    ready: 0,
    running: 0,
    completed: 0,
    blocked: 0,
    failed: 0,
    skipped: 0,
  };
}

function summarizeClusterStatus(nodes: RunDagNode[]): RunDagSummary {
  const summary = emptyDagSummary();
  summary.total = nodes.length;
  for (const node of nodes) {
    summary[node.statusKind] += 1;
  }
  return summary;
}

function clusterStatusKind(nodes: RunDagNode[]): RunDagStatusKind {
  const statusOrder: RunDagStatusKind[] = ["failed", "blocked", "running", "ready", "pending", "completed", "skipped"];
  const statuses = new Set(nodes.map((node) => node.statusKind));
  return statusOrder.find((status) => statuses.has(status)) ?? "pending";
}

function sampleUnique(values: string[], limit = 4): string[] {
  return Array.from(new Set(values.filter(Boolean))).slice(0, limit);
}

function buildDagClusters(nodes: RunDagNode[], edges: RunDagEdge[], groups: RunDagGroup[]): {
  clusters: RunDagCluster[];
  clusterEdges: RunDagClusterEdge[];
} {
  const plannedNodeIds = new Set(groups.filter((group) => group.kind === "proposed").flatMap((group) => group.nodeIds));
  const activeNodeIds = new Set(groups.filter((group) => group.kind === "active").flatMap((group) => group.nodeIds));
  const buckets = new Map<string, RunDagNode[]>();
  for (const node of nodes) {
    const key = `${node.phase}::${node.statusKind}`;
    buckets.set(key, [...(buckets.get(key) ?? []), node]);
  }
  const clusters = Array.from(buckets.entries())
    .map(([key, bucket]) => {
      const [phase, statusKind] = key.split("::") as [RunDagPhaseId, RunDagStatusKind];
      const phaseLabel = DAG_PHASES.find((item) => item.id === phase)?.label ?? phase;
      const statusCounts = summarizeClusterStatus(bucket);
      const ticketSamples = sampleUnique(bucket.map((node) => node.ticketId || node.id));
      const ownerSamples = sampleUnique(bucket.map((node) => node.ownerRole));
      const actionSamples = sampleUnique(bucket.map((node) => node.canonicalActionType || node.actionType));
      const plannedGroupNodeCount = bucket.filter((node) => plannedNodeIds.has(node.id)).length;
      const activeGroupNodeCount = bucket.filter((node) => activeNodeIds.has(node.id)).length;
      return {
        id: `cluster:${key}`,
        label: `${phaseLabel} / ${statusKind}`,
        phase,
        kind: "phase_status" as const,
        statusKind: clusterStatusKind(bucket),
        nodeIds: bucket.map((node) => node.id),
        nodeCount: bucket.length,
        statusCounts,
        ticketSamples,
        ownerSamples,
        actionSamples,
        plannedGroupNodeCount,
        activeGroupNodeCount,
        detail: [
          `${bucket.length} activity node${bucket.length === 1 ? "" : "s"}`,
          `${phaseLabel} phase`,
          `${statusKind} status`,
          ticketSamples.length ? `tickets ${ticketSamples.join(", ")}` : "",
          ownerSamples.length ? `owners ${ownerSamples.join(", ")}` : "",
          activeGroupNodeCount ? `${activeGroupNodeCount} active grouped node${activeGroupNodeCount === 1 ? "" : "s"}` : "",
          plannedGroupNodeCount ? `${plannedGroupNodeCount} planned wave node${plannedGroupNodeCount === 1 ? "" : "s"}` : "",
        ].filter(Boolean).join(" / "),
      };
    })
    .sort((first, second) => {
      const phaseOrder = DAG_PHASES.findIndex((phase) => phase.id === first.phase) - DAG_PHASES.findIndex((phase) => phase.id === second.phase);
      return phaseOrder || DAG_STATUS_ORDER.indexOf(first.statusKind) - DAG_STATUS_ORDER.indexOf(second.statusKind);
    });
  const clusterByNodeId = new Map<string, string>();
  for (const cluster of clusters) {
    for (const nodeId of cluster.nodeIds) {
      clusterByNodeId.set(nodeId, cluster.id);
    }
  }
  const edgeBuckets = new Map<string, { edge: RunDagEdge; source: string; target: string; count: number; reasons: string[] }>();
  for (const edge of edges) {
    const source = clusterByNodeId.get(edge.source);
    const target = clusterByNodeId.get(edge.target);
    if (!source || !target || source === target) continue;
    const key = `${source}::${target}::${edge.dependencyKind}::${edge.dependencyMode}::${edge.presentationKind}`;
    const current = edgeBuckets.get(key);
    if (current) {
      current.count += 1;
      if (edge.reason && current.reasons.length < 3) current.reasons.push(edge.reason);
    } else {
      edgeBuckets.set(key, { edge, source, target, count: 1, reasons: edge.reason ? [edge.reason] : [] });
    }
  }
  const clusterEdges: RunDagClusterEdge[] = Array.from(edgeBuckets.values()).map((bucket) => ({
    id: `cluster-edge:${bucket.source}:${bucket.target}:${bucket.edge.dependencyKind}:${bucket.edge.dependencyMode}:${bucket.edge.presentationKind}`,
    source: bucket.source,
    target: bucket.target,
    dependencyKind: bucket.edge.dependencyKind,
    dependencyMode: bucket.edge.dependencyMode,
    presentationKind: bucket.edge.presentationKind,
    count: bucket.count,
    reason: bucket.reasons[0] || "Bundled dependency edge.",
    detail: `${bucket.count} bundled ${bucket.edge.dependencyMode} ${bucket.edge.dependencyKind} edge${bucket.count === 1 ? "" : "s"}${bucket.reasons.length ? ` / ${bucket.reasons.join(" / ")}` : ""}`,
  }));
  return { clusters, clusterEdges };
}

function executionDagModel(snapshot: ProjectSnapshot | null): RunModel["executionDag"] {
  const dag = executionDagSnapshot(snapshot);
  const rawNodes = list(dag.nodes).map(record);
  const rawEdges = list(dag.edges).map(record);
  const blockedReasons = blockedReasonByNode(dag);
  const nodes: RunDagNode[] = rawNodes
    .map((raw) => {
      const metadata = record(raw.metadata);
      const worktree = record(raw.worktree);
      const patch = record(raw.patch);
      const id = text(raw.node_id || raw.id, "");
      const blocked = blockedReasons.get(id);
      const blockerReason = compactText(raw.blocker_reason, blocked?.reason ?? "");
      const confidence = number(raw.confidence);
      const visualStatus = statusKind(text(raw.status, "pending"), Boolean(blocked?.dependencyBlocked), blockerReason);
      const actionType = text(raw.action_type, "node");
      const canonicalActionType = text(raw.canonical_action_type, canonicalDagAction(actionType));
      const node: Omit<RunDagNode, "detail"> = {
        id,
        ticketId: text(raw.task_id || raw.ticket_id, ""),
        actionType,
        canonicalActionType,
        status: text(raw.status, "pending"),
        statusKind: visualStatus,
        ownerRole: text(raw.owner_role, "unassigned"),
        phase: dagPhase(actionType),
        attemptCount: number(raw.attempt_count),
        confidence,
        confidenceLabel: confidenceLabel(confidence),
        blockerReason,
        validationReceiptRefs: textList(raw.validation_receipt_refs),
        ownershipScope: ownershipScope(metadata),
        patchId: text(patch.id || raw.patch_id, ""),
        patchPath: text(patch.path || raw.patch_path, ""),
        worktreePath: text(worktree.path || raw.worktree_path, ""),
        startedAt: text(raw.started_at, ""),
        finishedAt: text(raw.finished_at, ""),
        badges: [],
      };
      const withBadges = { ...node, badges: dagBadges(node) };
      return { ...withBadges, detail: dagNodeDetail(withBadges) };
    })
    .filter((node) => node.id);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: RunDagEdge[] = rawEdges
    .map((raw) => {
      const confidence = number(raw.confidence);
      const dependencyKind = text(raw.dependency_kind, "depends_on");
      const dependencyMode = text(raw.dependency_mode, "hard");
      const presentationKind: RunDagEdge["presentationKind"] =
        dependencyKind === "blocks" ? "blocker" : dependencyMode === "advisory" ? "advisory" : "hard";
      const edge = {
        id: text(raw.edge_id || raw.id, ""),
        source: text(raw.source || raw.source_node_id, ""),
        target: text(raw.target || raw.target_node_id, ""),
        dependencyKind,
        dependencyMode,
        presentationKind,
        reason: compactText(raw.reason, "No edge reason recorded."),
        confidence,
        confidenceLabel: confidenceLabel(confidence),
      };
      return {
        ...edge,
        detail: `${edge.dependencyKind} ${edge.dependencyMode} dependency · confidence ${edge.confidenceLabel} · ${edge.reason}`,
      };
    })
    .filter((edge) => edge.source && edge.target && nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const summary: RunDagSummary = {
    total: nodes.length,
    pending: 0,
    ready: 0,
    running: 0,
    completed: 0,
    blocked: 0,
    failed: 0,
    skipped: 0,
  };
  for (const node of nodes) {
    summary[node.statusKind] += 1;
  }
  const groups = dagGroups(snapshot, nodes);
  const renderMode: RunDagRenderMode =
    nodes.length > OVERSIZED_DAG_NODE_THRESHOLD || edges.length > OVERSIZED_DAG_EDGE_THRESHOLD
      ? "oversized"
      : nodes.length > NORMAL_DAG_NODE_CAP || edges.length > NORMAL_DAG_EDGE_CAP
        ? "large"
        : "normal";
  const abstractionEnabled = renderMode !== "normal";
  const clustered = abstractionEnabled ? buildDagClusters(nodes, edges, groups) : { clusters: [], clusterEdges: [] };
  const visibleNodeIds = renderMode === "oversized" ? new Set<string>() : visibleDagSet(nodes, edges, groups);
  const visibleNodes = nodes.filter((node) => visibleNodeIds.has(node.id));
  const visibleEdges = edges
    .filter((edge) => visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target))
    .slice(0, NORMAL_DAG_EDGE_CAP);
  const activeGroupNodeIds = new Set(groups.filter((group) => group.kind === "active").flatMap((group) => group.nodeIds));
  const plannedGroupNodeIds = new Set(groups.filter((group) => group.kind === "proposed").flatMap((group) => group.nodeIds));
  const columns = DAG_PHASES.map((phase) => ({
    ...phase,
    nodes: visibleNodes
      .filter((node) => node.phase === phase.id)
      .sort((first, second) => {
        return (
          DAG_STATUS_ORDER.indexOf(first.statusKind) - DAG_STATUS_ORDER.indexOf(second.statusKind) ||
          first.ticketId.localeCompare(second.ticketId) ||
          first.actionType.localeCompare(second.actionType)
        );
      }),
  }));
  return {
    hasData: nodes.length > 0,
    authority: text(dag.authority, ""),
    digest: text(dag.digest, ""),
    summary,
    columns,
    nodes,
    edges,
    visibleNodes,
    visibleEdges,
    groups,
    clusters: clustered.clusters,
    clusterEdges: clustered.clusterEdges,
    abstraction: {
      enabled: abstractionEnabled,
      level: abstractionEnabled ? "phase-status" : "node",
      clusterCount: clustered.clusters.length,
      bundledEdgeCount: clustered.clusterEdges.length,
      sourceNodeCount: nodes.length,
      sourceEdgeCount: edges.length,
    },
    renderMode,
    renderLimit: {
      nodeCap: NORMAL_DAG_NODE_CAP,
      edgeCap: NORMAL_DAG_EDGE_CAP,
      visibleNodeCount: visibleNodes.length,
      visibleEdgeCount: visibleEdges.length,
      hiddenNodeCount: Math.max(0, nodes.length - visibleNodes.length),
      hiddenEdgeCount: Math.max(0, edges.length - visibleEdges.length),
    },
    parallel: {
      proposedGroups: groups.filter((group) => group.kind === "proposed").length,
      activeGroups: groups.filter((group) => group.kind === "active").length,
      completedGroups: groups.filter((group) => group.kind === "completed").length,
      plannedNodeCount: plannedGroupNodeIds.size,
      activeNodeCount: activeGroupNodeIds.size,
    },
  };
}

const COMPATIBILITY_TASK_IDS = new Set(["task:automation", "task:conveyor"]);
const PROGRESS_COLUMNS: RunProgressColumnId[] = ["scope", "build", "review", "validate", "integrate", "done"];
const PROGRESS_STATUS_PRIORITY: RunDagStatusKind[] = ["failed", "blocked", "running", "ready", "pending", "completed", "skipped"];

function operationTone(status: unknown): RunTone {
  const normalized = text(status, "").toLowerCase().replace(/[\s-]+/g, "_");
  if (["completed", "done", "passed", "integrated", "resolved"].includes(normalized)) return "good";
  if (["failed", "critical", "conflict", "error"].includes(normalized)) return "critical";
  if (["blocked", "blocked_on_user", "blocked_on_environment", "warning", "warn"].includes(normalized)) return "warn";
  if (["running", "active", "ready", "selected", "queued", "proposed", "in_progress"].includes(normalized)) return "info";
  return "quiet";
}

function firstNonEmpty(values: unknown[], fallback = ""): string {
  for (const value of values) {
    const rendered = compactText(value, "");
    if (rendered) return rendered;
  }
  return fallback;
}

function candidateReason(candidate: Record<string, unknown>, fallback = "No scheduler reason recorded."): string {
  const reasons = list(candidate.reasons).map((item) => compactText(item, "")).filter(Boolean);
  const blockers = list(candidate.blockers)
    .map((item) => {
      const blocker = record(item);
      return firstNonEmpty([blocker.reason, blocker.reason_kind, item], "");
    })
    .filter(Boolean);
  return firstNonEmpty([candidate.skipped_reason, reasons.join("; "), blockers.join("; ")], fallback);
}

function operationItemFromCandidate(candidate: Record<string, unknown>, fallbackId: string): RunOperationItem {
  const role = text(candidate.role, "scheduler");
  const action = text(candidate.action_kind, text(candidate.action_type, "selected action"));
  const taskId = text(candidate.public_task_id || candidate.task_id || candidate.dag_node_id, "");
  const groupId = text(candidate.execution_group_id, "");
  return {
    id: firstNonEmpty([candidate.candidate_id, groupId, taskId], fallbackId),
    label: action.replace(/_/g, " "),
    role,
    action,
    taskId,
    status: text(candidate.state, "selected"),
    tone: operationTone(candidate.state || "selected"),
    source: "scheduler",
    groupId,
    detail: candidateReason(candidate),
  };
}

function activeRoleRun(snapshot: ProjectSnapshot | null): Record<string, unknown> {
  const state = record(snapshot?.run.state);
  const conveyor = record(snapshot?.run.conveyor);
  const activity = record(state.automation_activity);
  const focus = record(activity.active_focus);
  return record(conveyor.active_role_run || state.active_role_run || focus.runner);
}

function runningNowModel(snapshot: ProjectSnapshot | null, dag: RunModel["executionDag"]): RunOperationItem[] {
  const state = record(snapshot?.run.state);
  const items: RunOperationItem[] = [];
  const seen = new Set<string>();
  const add = (item: RunOperationItem) => {
    const key = `${item.source}:${item.id}:${item.action}:${item.taskId}:${item.groupId}`;
    if (seen.has(key)) return;
    seen.add(key);
    items.push(item);
  };

  for (const node of dag.nodes.filter((item) => item.statusKind === "running")) {
    add({
      id: node.id,
      label: node.canonicalActionType.replace(/_/g, " "),
      role: node.ownerRole,
      action: node.canonicalActionType,
      taskId: node.ticketId,
      status: node.status,
      tone: operationTone(node.statusKind),
      source: "execution_dag",
      groupId: "",
      detail: node.detail,
    });
  }

  const active = activeRoleRun(snapshot);
  if (Object.keys(active).length) {
    const role = text(active.role, "runtime");
    const action = text(active.action_kind, role);
    add({
      id: text(active.run_id || active.pid, `active-role:${role}`),
      label: role,
      role,
      action,
      taskId: text(active.task_id || active.dag_node_id, ""),
      status: text(active.status, "running"),
      tone: operationTone(active.status || "running"),
      source: "active_role_run",
      groupId: text(active.execution_group_id, ""),
      detail: firstNonEmpty([active.reason, active.command_display, active.started_at], "Runtime role is active."),
    });
  }

  const workerSources: Record<string, unknown>[] = [
    ...list(state.active_read_only_workers).map((item): Record<string, unknown> => ({
      ...record(item),
      mode: "read_only",
      defaultRole: "planner",
    })),
    ...list(state.active_write_workers).map((item): Record<string, unknown> => ({
      ...record(item),
      mode: "write_workers",
      defaultRole: "builder",
    })),
  ];
  for (const worker of workerSources) {
    const role = text(worker.role || worker.owner_role || worker.defaultRole, "worker");
    add({
      id: text(worker.worker_id || worker.run_id, `worker:${items.length + 1}`),
      label: text(worker.mode, "worker").replace(/_/g, " "),
      role,
      action: text(worker.action_kind || worker.mode, "worker"),
      taskId: text(worker.task_id || worker.ticket_id || worker.dag_node_id, ""),
      status: text(worker.status, "running"),
      tone: operationTone(worker.status || "running"),
      source: "worker_agent",
      groupId: text(worker.execution_group_id, ""),
      detail: firstNonEmpty([worker.failure_reason, worker.context_pack_id, worker.report_artifact_id], "Worker is active."),
    });
  }

  for (const job of list(state.active_validation_jobs).map(record)) {
    add({
      id: text(job.job_id || job.gate_id, `validation:${items.length + 1}`),
      label: "validation",
      role: "hardener",
      action: "validate",
      taskId: text(job.task_id || job.ticket_id || job.dag_node_id || job.gate_id, ""),
      status: text(job.status, "running"),
      tone: operationTone(job.status || "running"),
      source: "validation_job",
      groupId: text(job.execution_group_id || job.plan_id, ""),
      detail: firstNonEmpty([job.command, job.summary, job.reason], "Validation job is active."),
    });
  }

  const selectedCandidate = record(state.selected_candidate);
  if (Object.keys(selectedCandidate).length) {
    add(operationItemFromCandidate(selectedCandidate, "selected-scheduler-candidate"));
  }

  if (!items.length) {
    add({
      id: "idle-runtime",
      label: "idle",
      role: "scheduler",
      action: "awaiting decision",
      taskId: "",
      status: "idle",
      tone: "quiet",
      source: "snapshot",
      groupId: "",
      detail: "No active role, worker, validation job, or selected scheduler candidate is recorded.",
    });
  }
  return items.slice(0, 8);
}

function nextUnlockModel(snapshot: ProjectSnapshot | null, dag: RunModel["executionDag"]): RunOperationCallout {
  const state = record(snapshot?.run.state);
  const selected = record(state.selected_candidate);
  if (Object.keys(selected).length) {
    return {
      title: firstNonEmpty([selected.action_kind, selected.action_type], "Selected scheduler action").replace(/_/g, " "),
      detail: candidateReason(selected),
      tone: operationTone(selected.state || "selected"),
      role: text(selected.role, "scheduler"),
      action: text(selected.action_kind || selected.action_type, ""),
      taskId: text(selected.public_task_id || selected.task_id || selected.dag_node_id, ""),
      source: "selected_candidate",
    };
  }
  const why = record(state.why_not_parallel || record(state.scheduler_parallel_dry_run).why_not_parallel);
  const whyDetail = firstNonEmpty([why.top_next_action, why.summary], "");
  if (whyDetail) {
    return {
      title: text(why.top_reason_kind, "Parallel unlock").replace(/_/g, " "),
      detail: whyDetail,
      tone: operationTone(why.status || "blocked"),
      role: "scheduler",
      action: "parallel evidence",
      taskId: "",
      source: "why_not_parallel",
    };
  }
  const blockedCandidate = list(state.blocked_parallel_candidates).map(record)[0] || list(state.skipped_scheduler_candidates || state.skipped_candidates).map(record)[0];
  if (blockedCandidate) {
    return {
      title: firstNonEmpty([blockedCandidate.reason_kind, blockedCandidate.action_kind], "Blocked candidate").replace(/_/g, " "),
      detail: firstNonEmpty([blockedCandidate.reason, blockedCandidate.skipped_reason], "Scheduler candidate needs more evidence before it can run."),
      tone: "warn",
      role: text(blockedCandidate.owner_role || blockedCandidate.role, "scheduler"),
      action: text(blockedCandidate.action_kind || blockedCandidate.action_type, ""),
      taskId: text(blockedCandidate.task_id || blockedCandidate.dag_node_id, ""),
      source: "blocked_candidate",
    };
  }
  const readyNode = dag.nodes.find((node) => node.statusKind === "ready");
  if (readyNode) {
    return {
      title: `${readyNode.canonicalActionType.replace(/_/g, " ")} ready`,
      detail: readyNode.detail,
      tone: "info",
      role: readyNode.ownerRole,
      action: readyNode.canonicalActionType,
      taskId: readyNode.ticketId,
      source: "execution_dag",
    };
  }
  return {
    title: "No runnable unlock recorded",
    detail: dag.hasData ? "The current DAG snapshot has no ready or selected action." : "Fresh snapshots will populate scheduler unlocks.",
    tone: "quiet",
    role: "scheduler",
    action: "idle",
    taskId: "",
    source: "snapshot",
  };
}

function progressColumnForNode(node: RunDagNode): RunProgressColumnId | null {
  const rawAction = node.actionType.toLowerCase().replace(/[\s-]+/g, "_");
  if (rawAction === "ticket" || rawAction === "blocker") return null;
  const action = canonicalDagAction(node.canonicalActionType || node.actionType);
  if (["orchestrate", "decompose", "scope", "refresh_index", "calibrate"].includes(action)) return "scope";
  if (["build", "repair"].includes(action)) return "build";
  if (["review", "audit"].includes(action)) return "review";
  if (action === "validate") return "validate";
  if (action === "integrate") return "integrate";
  if (action === "done" || action === "completion") return "done";
  return null;
}

function betterProgressCell(current: RunProgressCell | null, candidate: RunProgressCell): RunProgressCell {
  if (!current) return candidate;
  const currentIndex = PROGRESS_STATUS_PRIORITY.indexOf(current.statusKind);
  const candidateIndex = PROGRESS_STATUS_PRIORITY.indexOf(candidate.statusKind);
  return candidateIndex < currentIndex ? candidate : current;
}

function emptyProgressCells(): Record<RunProgressColumnId, RunProgressCell | null> {
  return {
    scope: null,
    build: null,
    review: null,
    validate: null,
    integrate: null,
    done: null,
  };
}

function progressRowsModel(dag: RunModel["executionDag"]): RunProgressRow[] {
  const rows = new Map<string, RunProgressRow>();
  for (const node of dag.nodes) {
    const taskId = node.ticketId || node.id;
    if (!taskId) continue;
    if (!rows.has(taskId)) {
      const compatibility = COMPATIBILITY_TASK_IDS.has(taskId);
      rows.set(taskId, {
        taskId,
        label: compatibility ? "Compatibility fallback" : taskId,
        compatibility,
        cells: emptyProgressCells(),
        summary: "",
      });
    }
    const column = progressColumnForNode(node);
    if (!column) continue;
    const row = rows.get(taskId);
    if (!row) continue;
    row.cells[column] = betterProgressCell(row.cells[column], {
      status: node.status,
      statusKind: node.statusKind,
      role: node.ownerRole,
      detail: node.detail,
      nodeId: node.id,
    });
  }
  return Array.from(rows.values())
    .map((row) => {
      const activeCells = PROGRESS_COLUMNS.map((column) => row.cells[column]).filter((cell): cell is RunProgressCell => Boolean(cell));
      const summary = activeCells.length
        ? activeCells.map((cell) => `${cell.role}:${cell.statusKind}`).join(" / ")
        : "No action cells recorded.";
      return { ...row, summary };
    })
    .sort((first, second) => {
      if (first.compatibility !== second.compatibility) return first.compatibility ? 1 : -1;
      return first.taskId.localeCompare(second.taskId);
    })
    .slice(0, 10);
}

function leaseLabel(lease: Record<string, unknown>): string {
  return firstNonEmpty([lease.path, lease.name, lease.scope_node_id, lease.lease_id], "");
}

function groupWave(
  group: Record<string, unknown>,
  kind: RunConcurrencyWave["kind"],
  fallbackIndex: number,
  sources: Record<string, unknown>[] = [],
): RunConcurrencyWave {
  const payload = record(group.payload);
  const items = list(group.items).map(record);
  const sourceItems = items.length ? items : sources;
  const mode = text(payload.execution_mode || group.mode, kind);
  const status = text(group.status, kind);
  const owners = sampleUnique(sourceItems.map((item) => text(item.owner_role || item.role, "")), 3);
  const tasks = sampleUnique(sourceItems.map((item) => text(item.task_id || item.ticket_id || item.graph_task_node_id || item.dag_node_id, "")), 4);
  const leases = sampleUnique(
    sourceItems.flatMap((item) => list(item.required_leases).map((lease) => leaseLabel(record(lease))).filter(Boolean)),
    3,
  );
  return {
    id: text(group.execution_group_id || group.group_id, `${kind}-wave-${fallbackIndex + 1}`),
    label: kind === "proposed" ? `planned wave ${fallbackIndex + 1}` : `${kind} wave`,
    kind,
    mode,
    status,
    tone: operationTone(status || kind),
    itemCount: number(group.item_count) || sourceItems.length || number(payload.candidate_count),
    owners,
    tasks,
    leases,
    detail: firstNonEmpty([group.reason, payload.why_together, payload.summary], kind === "blocked" ? "Parallel candidate is blocked." : "Execution wave is recorded."),
  };
}

function concurrencyWavesModel(snapshot: ProjectSnapshot | null, integrationBacklog: RunIntegrationBacklog): RunConcurrencyWave[] {
  const state = record(snapshot?.run.state);
  const waves: RunConcurrencyWave[] = [];
  const add = (wave: RunConcurrencyWave) => {
    if (waves.some((item) => item.id === wave.id && item.kind === wave.kind)) return;
    waves.push(wave);
  };
  list(state.proposed_execution_groups).map(record).forEach((group, index) => add(groupWave(group, "proposed", index)));

  const activeGroups = list(state.active_execution_groups).map(record);
  activeGroups.forEach((group, index) => add(groupWave(group, "active", index)));
  const activeSources = [
    ...list(state.active_read_only_workers).map(record),
    ...list(state.active_write_workers).map(record),
    ...list(state.active_validation_jobs).map(record),
  ];
  const sourcesByGroup = new Map<string, Record<string, unknown>[]>();
  for (const source of activeSources) {
    const groupId = text(source.execution_group_id || source.plan_id, "");
    if (!groupId) continue;
    sourcesByGroup.set(groupId, [...(sourcesByGroup.get(groupId) ?? []), source]);
  }
  Array.from(sourcesByGroup.entries()).forEach(([groupId, sources], index) => {
    add(groupWave({ execution_group_id: groupId, status: "running", mode: text(sources[0]?.mode, "runtime") }, "active", index, sources));
  });

  list(state.completed_worker_reports).map(record).slice(0, 4).forEach((report, index) => {
    add(groupWave({
      execution_group_id: text(report.execution_group_id || report.report_id || report.worker_id, `completed:${index + 1}`),
      status: text(report.status, "completed"),
      mode: "worker",
      reason: firstNonEmpty([report.summary, report.report_path], "Worker report completed."),
      items: [report],
    }, "completed", index));
  });

  list(state.blocked_parallel_candidates).map(record).slice(0, 4).forEach((candidate, index) => {
    add(groupWave({
      execution_group_id: text(candidate.candidate_id || candidate.task_id || candidate.dag_node_id, `blocked:${index + 1}`),
      status: "blocked",
      mode: text(candidate.execution_mode || candidate.action_kind, "parallel"),
      reason: firstNonEmpty([candidate.reason, candidate.skipped_reason], "Candidate is blocked from parallel launch."),
      items: [candidate],
    }, "blocked", index));
  });

  if (integrationBacklog.queuedCount || integrationBacklog.conflictCount || integrationBacklog.safeCount) {
    add({
      id: "integration-backlog",
      label: "integration backlog",
      kind: "integration",
      mode: "serialized_repo",
      status: integrationBacklog.safeCount ? "ready" : integrationBacklog.queuedCount ? "queued" : "blocked",
      tone: integrationBacklog.tone,
      itemCount: integrationBacklog.queuedCount + integrationBacklog.conflictCount,
      owners: ["integrator"],
      tasks: integrationBacklog.patchSamples,
      leases: [],
      detail: integrationBacklog.summary,
    });
  }
  return waves.slice(0, 12);
}

function integrationBacklogModel(snapshot: ProjectSnapshot | null): RunIntegrationBacklog {
  const state = record(snapshot?.run.state);
  const queued = [
    ...list(state.queued_worker_patches).map(record),
    ...list(state.integration_backlog_from_parallel_workers).map(record),
  ];
  const patchesById = new Map<string, Record<string, unknown>>();
  for (const patch of queued) {
    const id = text(patch.patch_id || patch.manifest_path || patch.patch_path, "");
    if (id) patchesById.set(id, patch);
  }
  const uniquePatches = Array.from(patchesById.values());
  const conflicts = [
    ...list(state.write_worker_conflicts).map(record),
    ...uniquePatches.filter((patch) => ["conflict", "deferred"].includes(text(patch.status, "").toLowerCase())),
  ];
  const preflight = record(state.worker_patch_integration_preflight);
  const safeCount = number(preflight.safe_count) || list(preflight.safe_patch_ids).length;
  const blockedCount = number(preflight.likely_conflict_count) + number(preflight.stale_base_count) + number(preflight.missing_metadata_count);
  const queuedCount = uniquePatches.filter((patch) => text(patch.status, "queued").toLowerCase() === "queued").length || uniquePatches.length;
  const conflictCount = conflicts.length;
  const tone: RunTone = conflictCount ? "critical" : blockedCount ? "warn" : safeCount || queuedCount ? "info" : "quiet";
  const patchSamples = sampleUnique(uniquePatches.map((patch) => text(patch.patch_id || patch.manifest_path || patch.patch_path, "")), 4);
  const summary = queuedCount || conflictCount || safeCount || blockedCount
    ? `${queuedCount} queued patch${queuedCount === 1 ? "" : "es"}; ${safeCount} safe for serialized integration; ${blockedCount + conflictCount} need attention.`
    : "No queued worker patches are waiting for serialized integration.";
  return {
    queuedCount,
    conflictCount,
    safeCount,
    blockedCount: blockedCount + conflictCount,
    tone,
    summary,
    patchSamples,
  };
}

function operationsModel(snapshot: ProjectSnapshot | null, dag: RunModel["executionDag"]): RunModel["operations"] {
  const integrationBacklog = integrationBacklogModel(snapshot);
  return {
    runningNow: runningNowModel(snapshot, dag),
    nextUnlock: nextUnlockModel(snapshot, dag),
    progressRows: progressRowsModel(dag),
    concurrencyWaves: concurrencyWavesModel(snapshot, integrationBacklog),
    integrationBacklog,
  };
}

function safetyRows(snapshot: ProjectSnapshot | null, scaffolded: boolean, blockers: Record<string, unknown>[]): RunSafetyRow[] {
  if (!snapshot) {
    return [
      {
        label: "Target",
        status: "not selected",
        summary: "Choose a project before running automation.",
        source: "project picker",
        tone: "quiet",
        action: { label: "Choose project", kind: "choose-project", enabled: true, reason: "Select a target folder." },
      },
    ];
  }
  const task = record(snapshot.run.task);
  const validation = record(task.validation);
  const validationCounts = record(validation.counts);
  const integrationSafety = record(task.integration_safety);
  const firstReview = record(snapshot.run.first_review);
  const controls = record(snapshot.run.controls);
  const dirtyCount = number(snapshot.run.git?.dirty_count);
  const pendingHuman = number(snapshot.run.human?.pending_requests) + number(snapshot.run.human?.unhandled_inbox);
  const validationStatus = number(validationCounts.fail) ? "fail" : number(validationCounts.pending) ? "pending" : number(validationCounts.pass) ? "pass" : "not recorded";
  const integrationSafetyStatus = text(integrationSafety.status, scaffolded ? "pending" : "setup needed");
  const recheckableBlocker = blockers.find((item) => bool(item.can_recheck) && text(item.recheck_command, ""));
  const environmentAction = recheckableBlocker
    ? makeAction(
        text(recheckableBlocker.recheck_label, "Recheck blocker"),
        scaffolded,
        "Rerun baseline verification in a freshly loaded automation environment.",
        text(recheckableBlocker.recheck_command, "blocker.recheck_baseline"),
      )
    : routeAction("Sidecar", "Advanced", "Open diagnostics.");
  return [
    {
      label: "Integration safety",
      status: integrationSafetyStatus.replace(/_/g, " ").toLowerCase(),
      summary: text(integrationSafety.summary, scaffolded ? "Integration-safety check has not run yet." : "Complete setup before running safety checks."),
      source: "run.task.integration_safety",
      tone: safetyTone(integrationSafetyStatus),
      action: makeAction(
        "Run check",
        scaffolded && bool(controls.can_run_safety_check),
        scaffolded ? "Records the integration safety result." : "Complete setup before running.",
        "safety.run_check",
      ),
    },
    {
      label: "Validation",
      status: `${number(validationCounts.pass)} pass / ${number(validationCounts.fail)} fail`,
      summary: text(validation.summary, "No validation result is recorded yet."),
      source: "run.task.validation",
      tone: safetyTone(validationStatus),
      action: routeAction("Review", "Review", "Open review evidence."),
    },
    {
      label: "Git state",
      status: `${dirtyCount} dirty`,
      summary: `Branch ${text(snapshot.run.git?.branch, "unknown")}.`,
      source: "run.git",
      tone: dirtyCount ? "warn" : "good",
      action: routeAction("Activity", "Run", "Refresh run state."),
    },
    {
      label: "Environment",
      status: blockers.length ? `${blockers.length} blocker(s)` : "clear",
      summary: blockers.length ? blockers.map((item) => text(item.name, "Environment blocker")).join(", ") : "No environment blocker is recorded.",
      source: "run.environment_blockers",
      tone: blockers.length ? "warn" : "good",
      action: environmentAction,
    },
    {
      label: "Human input",
      status: pendingHuman ? `${pendingHuman} waiting` : "clear",
      summary: pendingHuman ? "Inbox has pending work before automation can proceed." : "No human handoff is pending.",
      source: "run.human",
      tone: pendingHuman ? "warn" : "good",
      action: routeAction("Inbox", "Inbox", "Open human handoffs."),
    },
    {
      label: "Review bundle",
      status: text(firstReview.status, "unknown").replace(/_/g, " ").toLowerCase(),
      summary: text(firstReview.summary, "Review evidence can be exported from Review."),
      source: "run.first_review",
      tone: safetyTone(firstReview.status),
      action: routeAction("Review", "Review", "Open review evidence."),
    },
  ];
}

export function buildRunModel(snapshot: ProjectSnapshot | null): RunModel {
  const scaffolded = isScaffolded(snapshot);
  const task = record(snapshot?.run.task);
  const controls = record(snapshot?.run.controls);
  const automation = record(snapshot?.run.automation);
  const workerStrategy = record(snapshot?.run.worker_strategy);
  const workerControls = record(snapshot?.run.worker_controls);
  const latestWorker = record(snapshot?.run.latest_worker_result);
  const blockers = list(snapshot?.run.environment_blockers).map(record);
  const status = text(task.status, snapshot ? "UNKNOWN" : "NO_TARGET");
  const statusUpper = status.toUpperCase();
  const automationState = text(automation.state, "").toLowerCase();
  const automationRunning = automationState === "running";
  const running = bool(controls.is_running) || statusUpper.includes("RUNNING") || automationRunning;
  const canBootstrapAndStart = scaffolded && bool(controls.can_bootstrap_and_start) && !running;

  const startAutomation = makeAction(
    "Start",
    scaffolded && (bool(controls.can_start_automation) || canBootstrapAndStart),
    canBootstrapAndStart
      ? text(controls.bootstrap_start_reason, "First start will prepare the target, then automation will start.")
      : scaffolded ? text(controls.start_automation_reason, text(automation.message, "Automation is not ready.")) : "Complete setup before running.",
    canBootstrapAndStart ? "automation.bootstrap_start" : "automation.start",
  );
  const stopAutomation = makeAction(
    "Stop",
    scaffolded && bool(controls.can_stop_automation) && automationRunning,
    scaffolded ? text(controls.stop_automation_reason, text(automation.message, "No automation is running.")) : "Complete setup before running.",
    "automation.stop",
  );
  const safetyCheck = makeAction(
    "Run safety check",
    scaffolded && bool(controls.can_run_safety_check),
    scaffolded ? "Records the integration safety result." : "Complete setup before running.",
    "safety.run_check",
  );
  const exportReview = routeAction("Review export", "Review", "Review files live on the Review page.");
  exportReview.enabled = scaffolded;
  exportReview.kind = scaffolded ? "navigate" : "disabled";

  const title = stateTitle(snapshot, scaffolded, running, blockers, statusUpper);
  const executionDag = executionDagModel(snapshot);
  const operations = operationsModel(snapshot, executionDag);
  let headline = title;
  let subheadline = "Choose a project before running.";
  let badge = "No target";
  let primaryAction: RunAction = { label: "Choose project", kind: "choose-project", enabled: true, reason: "Select a target folder." };
  if (snapshot && title === "Unknown" && !scaffolded) {
    subheadline = "Complete setup before running.";
    badge = "Setup needed";
    primaryAction = routeAction("Open setup", "Brief", "Confirm the target setup.");
  } else if (snapshot && title === "Critical stop") {
    subheadline = "Review the stop condition before starting another run.";
    badge = "Critical stop";
    primaryAction = routeAction("Open review", "Review", "Review critical stop evidence.");
  } else if (snapshot && title === "User input") {
    subheadline = "A human handoff is waiting before useful progress can continue.";
    badge = "User input";
    primaryAction = routeAction("Open Inbox", "Inbox", "Resolve human handoffs.");
  } else if (snapshot && title === "Env blocked") {
    subheadline = blockers.length ? blockers.map((item) => text(item.name, "Environment blocker")).join(", ") : "Safety, validation, or environment state needs attention.";
    badge = "Env blocked";
    primaryAction = safetyCheck.enabled ? safetyCheck : routeAction("Open sidecar", "Advanced", "Open diagnostics.");
  } else if (snapshot && title === "Running") {
    subheadline = text(automation.message, "Refresh to inspect the latest run state.");
    badge = "Running";
    primaryAction = routeAction("Refresh", "Run", "Reload the latest run state.");
  } else if (snapshot && canBootstrapAndStart) {
    subheadline = "First start will prepare the target, then continuous automation will start.";
    badge = "Ready";
    primaryAction = startAutomation;
  } else if (snapshot && startAutomation.enabled) {
    subheadline = "The target files are present and continuous automation can start.";
    badge = "Ready";
    primaryAction = startAutomation;
  } else if (snapshot) {
    subheadline = text(controls.start_automation_reason, text(automation.message, "Refresh diagnostics before running."));
    badge = title;
    primaryAction = safetyCheck.enabled ? safetyCheck : routeAction("Open setup", "Brief", "Confirm the target setup.");
  }

  return {
    isScaffolded: scaffolded,
    isRunning: running,
    banner: {
      headline,
      subheadline,
      badge,
      tone: bannerTone(title, statusUpper, blockers),
      primaryAction,
    },
    controls: {
      startAutomation,
      stopAutomation,
      safetyCheck,
      exportReview,
    },
    automation: {
      state: text(automation.state, "stopped"),
      message: text(automation.message, "Automation has not been started yet."),
      pid: text(automation.pid, ""),
      startedAt: text(automation.started_at, ""),
      logDir: text(automation.log_dir, ""),
    },
    latestRun: {
      status: displayStatus(status),
      horizon: text(task.horizon, "No plan recorded"),
      lastUpdated: text(task.last_updated, text(snapshot?.run.snapshot_generated_at, "Not recorded")),
      summary: text(snapshot?.run.progress_recent, text(task.suggested_next_task, "No run has been recorded yet.")),
    },
    executionDag,
    operations,
    runLog: runLog(snapshot),
    worker: {
      headline: workerHeadline(workerStrategy),
      mode: workerMode(workerStrategy),
      tone: workerTone(workerStrategy),
      focus: `${text(workerStrategy.action_lane, "local")} lane`,
      output: `.diffmogger/runtime/agent_runs/<run-id>/worker_${workerRole(workerStrategy)}.md`,
      summary: text(workerStrategy.summary, text(workerStrategy.reason, "No worker strategy detail recorded yet.")),
      raw: workerStrategy,
      latest: text(latestWorker.label, "No worker result recorded."),
      actions: {
        readOnly: makeAction(
          "Run read-only worker",
          scaffolded && bool(workerControls.can_run_read_only),
          text(workerControls.read_only_reason, "Not supported by the current strategy."),
          "worker.run_read_only",
        ),
        write: makeAction(
          "Run write worker",
          scaffolded && bool(workerControls.can_run_write),
          text(workerControls.write_reason, "Not supported by the current strategy."),
          "worker.run_write",
        ),
        integrator: makeAction(
          "Run integrator",
          scaffolded && bool(workerControls.can_run_integrator),
          text(workerControls.integrator_reason, "Not supported by the current strategy."),
          "worker.run_integrator",
        ),
      },
    },
    safety: safetyRows(snapshot, scaffolded, blockers),
    blockers: blockers.map((item) => ({
      name: text(item.name, "Environment blocker"),
      detail: text(item.detail, ""),
      required: bool(item.required),
      canRecheck: bool(item.can_recheck),
      recheckCommand: text(item.recheck_command, ""),
      recheckLabel: text(item.recheck_label, "Recheck blocker"),
    })),
  };
}
