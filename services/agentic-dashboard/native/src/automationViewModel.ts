import type {
  ProjectSnapshot,
} from "./api/backend";
import type {
  RunDagClusterEdge,
  RunDagEdge,
  RunDagPhaseId,
  RunDagNode,
  RunDagStatusKind,
  RunModel,
  RunTone,
} from "./runModel";

export type AutomationPipelineColumnId = "plan" | "build" | "review" | "validate" | "integrate" | "done";
export type AutomationQueueBucketId = "ready" | "running" | "waiting" | "followup" | "done";
export type AutomationNodeStatus = "ready" | "scoping" | "building" | "running" | "waiting" | "followup" | "done" | "failed" | "skipped";
export type AutomationTicketStatus = "building" | "scoping" | "running" | "ready" | "waiting" | "pending" | "in_progress" | "candidate_done" | "done" | "blocked";
export type AutomationGraphRenderMode = "node" | "cluster";

export type AutomationPipelineNode = {
  id: string;
  title: string;
  phase: AutomationPipelineColumnId;
  status: AutomationNodeStatus;
  statusLabel: string;
  tone: RunTone;
  role: string;
  ticketId: string;
  detail: string;
  scope: string;
};

export type AutomationPipelineRow = {
  id: string;
  label: string;
  summary: string;
  cells: Record<AutomationPipelineColumnId, AutomationPipelineNode | null>;
};

export type AutomationGraphNode = {
  id: string;
  sourceKind: AutomationGraphRenderMode;
  title: string;
  subtitle: string;
  phase: AutomationPipelineColumnId;
  phaseLabel: string;
  status: AutomationNodeStatus;
  statusKind: RunDagStatusKind;
  statusLabel: string;
  tone: RunTone;
  role: string;
  ticketId: string;
  detail: string;
  scope: string;
  nodeCount: number;
  samples: string[];
  badges: string[];
  x: number;
  y: number;
  width: number;
  height: number;
};

export type AutomationGraphEdge = {
  id: string;
  source: string;
  target: string;
  presentationKind: "hard" | "advisory" | "blocker";
  dependencyKind: string;
  dependencyMode: string;
  count: number;
  label: string;
  detail: string;
  points: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
    cx1: number;
    cy1: number;
    cx2: number;
    cy2: number;
  };
};

export type AutomationGraphGroup = {
  id: string;
  label: string;
  kind: "proposed" | "active" | "completed";
  mode: string;
  status: string;
  detail: string;
  nodeIds: string[];
  tone: RunTone;
};

export type AutomationQueueBucket = {
  id: AutomationQueueBucketId;
  label: string;
  count: number;
  tone: RunTone;
  items: Array<{
    id: string;
    title: string;
    detail: string;
    statusLabel: string;
    tone: RunTone;
  }>;
};

export type AutomationActivityRow = {
  id: string;
  title: string;
  status: string;
  detail: string;
  tone: RunTone;
};

export type AutomationValidationRow = {
  id: string;
  title: string;
  status: string;
  detail: string;
  tone: RunTone;
};

export type AutomationTicketProgressRow = {
  id: string;
  summary: string;
  status: AutomationTicketStatus;
  statusLabel: string;
  tone: RunTone;
  stage: string;
  detail: string;
  dependsOn: string[];
  acceptanceCriteria: string[];
  verificationCommands: string[];
  evidenceCount: number;
  blocker: string;
  relatedCommits: string[];
  commitCount: number;
  runtimeStatus: string;
  runtimePayload: Record<string, unknown>;
};

export type AutomationTicketGraphStatus = AutomationTicketStatus | "missing";

export type AutomationTicketGraphNode = {
  id: string;
  summary: string;
  status: AutomationTicketGraphStatus;
  statusLabel: string;
  tone: RunTone;
  stage: string;
  detail: string;
  dependsOn: string[];
  acceptanceCriteria: string[];
  verificationCommands: string[];
  evidenceCount: number;
  blocker: string;
  relatedCommits: string[];
  commitCount: number;
  runtimeStatus: string;
  runtimePayload: Record<string, unknown>;
  layer: number;
  x: number;
  y: number;
  width: number;
  height: number;
  placeholder: boolean;
  cyclic: boolean;
};

export type AutomationTicketGraphEdge = {
  id: string;
  source: string;
  target: string;
  cyclic: boolean;
  path: string;
};

export type AutomationTicketGraphLayer = {
  id: string;
  index: number;
  label: string;
  x: number;
  count: number;
  cyclic: boolean;
};

export type AutomationStatusFact = {
  id: string;
  label: string;
  value: string;
  detail: string;
  tone: RunTone;
};

export type AutomationProgressLaneId = "ready" | "running" | "repair" | "integration" | "completed" | "deferred";

export type AutomationProgressLane = {
  id: AutomationProgressLaneId;
  label: string;
  count: number;
  tone: RunTone;
  tooltip: string;
  items: Array<{
    id: string;
    title: string;
    detail: string;
    statusLabel: string;
    tone: RunTone;
  }>;
};

export type AutomationSchedulerCandidateRow = {
  id: string;
  label: string;
  status: string;
  detail: string;
  fanout: number;
  owner: string;
  ownership: string;
  confidence: string;
  tone: RunTone;
};

export type AutomationEvidenceRow = {
  id: string;
  label: string;
  status: string;
  scope: "required" | "advisory";
  detail: string;
  evidencePath: string;
  repairWork: string;
  tone: RunTone;
};

export type AutomationQueueRow = {
  id: string;
  label: string;
  status: string;
  detail: string;
  meta: string;
  tone: RunTone;
};

export type AutomationTimelineCategory =
  | "scheduler"
  | "worker"
  | "validation"
  | "integration"
  | "notification"
  | "human";

export type AutomationTimelineEvent = {
  id: string;
  category: AutomationTimelineCategory;
  title: string;
  status: string;
  time: string;
  detail: string;
  tone: RunTone;
};

export type AutomationViewModel = {
  statusBand: {
    targetName: string;
    targetPath: string;
    headline: string;
    detail: string;
    runnerState: string;
    supervisor: string;
    readinessReason: string;
    tone: RunTone;
    facts: AutomationStatusFact[];
  };
  nextAction: {
    title: string;
    role: string;
    status: string;
    detail: string;
    tone: RunTone;
  };
  progressLanes: AutomationProgressLane[];
  schedulerDecision: {
    selected: AutomationSchedulerCandidateRow;
    alternatives: AutomationSchedulerCandidateRow[];
    fanout: string;
    ownership: string;
    confidence: string;
    whyParallel: {
      status: string;
      summary: string;
      next: string;
      reasons: Array<{ id: string; label: string; count: number; detail: string; tone: RunTone }>;
      tone: RunTone;
    };
  };
  validationEvidence: {
    summary: string;
    requiredFailed: number;
    requiredPassed: number;
    advisoryFailed: number;
    repairCreated: number;
    evidencePaths: string[];
    rows: AutomationEvidenceRow[];
    tone: RunTone;
  };
  queueIntegration: {
    metrics: Array<{ id: string; label: string; value: string; detail: string; tone: RunTone }>;
    rows: AutomationQueueRow[];
  };
  notification: {
    pending: number;
    unresolved: number;
    outbound: number;
    mode: string;
    status: string;
    detail: string;
    tone: RunTone;
  };
  timeline: AutomationTimelineEvent[];
  dag: {
    columns: Array<{ id: AutomationPipelineColumnId; label: string; x: number; width: number }>;
    nodes: AutomationGraphNode[];
    edges: AutomationGraphEdge[];
    groups: AutomationGraphGroup[];
    defaultSelectedNodeId: string;
    summary: string;
    mode: AutomationGraphRenderMode;
    modeLabel: string;
    hiddenSummary: string;
    sourceNodeCount: number;
    sourceEdgeCount: number;
    clusterCount: number;
    bundledEdgeCount: number;
    width: number;
    height: number;
  };
  ticketProgress: {
    summary: string;
    total: number;
    rows: AutomationTicketProgressRow[];
    counts: Array<{
      id: AutomationTicketStatus;
      label: string;
      count: number;
      tone: RunTone;
    }>;
  };
  ticketGraph: {
    summary: string;
    nodes: AutomationTicketGraphNode[];
    edges: AutomationTicketGraphEdge[];
    layers: AutomationTicketGraphLayer[];
    width: number;
    height: number;
    dependencyCount: number;
    completed: number;
    active: number;
    ready: number;
    waiting: number;
    cyclicCount: number;
  };
  queueBuckets: AutomationQueueBucket[];
  validationRepair: {
    summary: string;
    tone: RunTone;
    rows: AutomationValidationRow[];
  };
  humanInput: {
    total: number;
    requests: number;
    records: number;
    outbound: number;
    badge: string;
    detail: string;
    tone: RunTone;
  };
  activityLog: AutomationActivityRow[];
};

const GRAPH_COLUMNS: Array<{ id: AutomationPipelineColumnId; label: string; phases: RunDagPhaseId[] }> = [
  { id: "plan", label: "Plan", phases: ["orchestrate", "decompose", "scope", "audit"] },
  { id: "build", label: "Build", phases: ["build", "repair"] },
  { id: "review", label: "Review", phases: ["review"] },
  { id: "validate", label: "Validate", phases: ["validate"] },
  { id: "integrate", label: "Integrate", phases: ["integrate"] },
  { id: "done", label: "Done", phases: ["done"] },
];

const GRAPH_NODE_WIDTH = 156;
const GRAPH_NODE_HEIGHT = 62;
const GRAPH_COLUMN_GAP = 28;

const TICKET_GRAPH_NODE_WIDTH = 190;
const TICKET_GRAPH_NODE_HEIGHT = 76;
const TICKET_GRAPH_COLUMN_GAP = 86;
const TICKET_GRAPH_ROW_GAP = 18;
const TICKET_GRAPH_PADDING_X = 28;
const TICKET_GRAPH_PADDING_Y = 48;
const GRAPH_LEFT = 18;
const GRAPH_TOP = 56;
const GRAPH_ROW_GAP = 16;
const GRAPH_BOTTOM = 24;
const GRAPH_MAX_EDGES = 120;

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function bool(value: unknown): boolean {
  return value === true || value === 1 || value === "true";
}

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function firstText(values: unknown[], fallback = ""): string {
  for (const value of values) {
    const rendered = text(value, "").replace(/\s+/g, " ").trim();
    if (rendered) return rendered;
  }
  return fallback;
}

function compactTime(value: unknown, fallback = "Not recorded"): string {
  const rendered = text(value, "");
  if (!rendered) return fallback;
  const iso = rendered.replace("T", " ");
  return iso.length > 19 ? iso.slice(0, 19) : iso;
}

function normalize(value: unknown): string {
  return text(value, "").toLowerCase().replace(/[\s-]+/g, "_");
}

function roleLabel(role: string): string {
  const normalized = normalize(role);
  if (!normalized || normalized === "scheduler") return "scheduler";
  return titleCase(normalized);
}

function friendlyActionLabel(action: string, role = ""): string {
  const normalized = normalize(action);
  if (normalized === "run_serial_role") return role ? `Continue ${roleLabel(role).toLowerCase()} work` : "Continue role work";
  if (normalized === "launch_write_group") return "Start write workers";
  if (normalized === "launch_scope_group") return "Gather scope evidence";
  if (normalized === "run_validation_group" || normalized === "launch_validation_group") return "Run validation";
  if (normalized === "repair") return "Repair work generated";
  if (normalized === "setup") return "Set up local harness";
  if (normalized === "mock" || normalized === "fixture" || normalized === "harness") return "Create local test support";
  if (normalized === "defer") return "Defer safely";
  if (normalized === "split") return "Split work";
  if (normalized === "reframe") return "Reframe work";
  if (normalized === "integrate") return "Integrate patch";
  if (normalized === "validate") return "Run validation";
  if (normalized === "build") return "Build";
  if (normalized === "review" || normalized === "audit") return "Review";
  if (normalized === "scope" || normalized === "decompose" || normalized === "orchestrate") return "Plan";
  if (normalized === "completion" || normalized === "done") return "Done";
  return titleCase(action || "Work");
}

function isDependencyWait(node?: Pick<RunDagNode, "blockerReason" | "detail" | "status"> | null): boolean {
  const haystack = `${node?.blockerReason ?? ""} ${node?.detail ?? ""} ${node?.status ?? ""}`.toLowerCase();
  return /dependency|depends|prior|previous|predecessor|follows|waiting for|blocked by/.test(haystack);
}

function isGeneratedFollowUp(value: string): boolean {
  return /repair|setup|harness|mock|fixture|defer|split|reframe|validation failure|missing tool|external service|browser|mcp|retry/.test(value.toLowerCase());
}

function friendlyDetail(raw: string, fallback: string): string {
  const detail = raw.replace(/\s+/g, " ").trim();
  const lower = detail.toLowerCase();
  if (!detail) return fallback;
  if (/serialized_role_path|no promotable ownership|dependency-ready ticket needs serialized/i.test(detail)) {
    return "Continuing one role at a time until ownership evidence supports parallel work.";
  }
  if (/follows prior|prior dag action|prior ticket action|dependency|predecessor/i.test(detail)) {
    return "Waiting for previous step.";
  }
  if (/validation failure|failed validation/i.test(detail)) {
    return "Validation failed; repair work has been generated.";
  }
  if (/missing tool|environment|harness|mock|fixture|setup/i.test(lower)) {
    return "Setup or harness work has been generated.";
  }
  if (/retry/i.test(lower) && /exhaust|failed|limit/.test(lower)) {
    return "Planner will split or reframe this work.";
  }
  return detail;
}

function toneForDisplayStatus(status: AutomationNodeStatus): RunTone {
  if (status === "done") return "good";
  if (status === "running" || status === "scoping" || status === "building" || status === "ready") return "info";
  if (status === "failed" || status === "followup") return "warn";
  return "quiet";
}

function displayStatusKind(statusKind: RunDagStatusKind, node?: RunDagNode): AutomationNodeStatus {
  const runtimeStatus = normalize(node?.runtimeStatus);
  if (runtimeStatus === "scoping" || runtimeStatus === "planning") return "scoping";
  if (runtimeStatus === "building" || runtimeStatus === "writing") return "building";
  if (statusKind === "completed") return "done";
  if (statusKind === "running") {
    const action = normalize(node?.canonicalActionType || node?.actionType);
    if (["scope", "decompose", "orchestrate"].includes(action) || node?.phase === "scope") return "scoping";
    if (["build", "repair"].includes(action) || node?.phase === "build") return "building";
    return "running";
  }
  if (statusKind === "ready") return "ready";
  if (statusKind === "failed") return "followup";
  if (statusKind === "blocked") return isDependencyWait(node) ? "waiting" : "followup";
  if (statusKind === "skipped") return "skipped";
  return "waiting";
}

function statusLabel(status: AutomationNodeStatus): string {
  if (status === "followup") return "Follow-up";
  return titleCase(status);
}

function nodeTitle(node: RunDagNode | undefined, fallbackAction: string, fallbackRole: string): string {
  const action = node?.canonicalActionType || node?.actionType || fallbackAction;
  return friendlyActionLabel(action, node?.ownerRole || fallbackRole);
}

function isInternalProgressNode(node: RunDagNode): boolean {
  const action = normalize(node.actionType || node.canonicalActionType);
  if (action === "ticket") return true;
  return node.statusKind === "completed" && ["blocker", "orchestrate", "decompose"].includes(action);
}

function usefulScope(node?: RunDagNode): string {
  const scope = text(node?.ownershipScope, "");
  return scope && scope !== "No ownership scope recorded" ? scope : "";
}

function friendlyNodeDetail(node: RunDagNode | undefined, fallback: string, status?: AutomationNodeStatus): string {
  if (!node) return friendlyDetail(fallback, "Work is recorded.");
  const displayStatus = status ?? displayStatusKind(node.statusKind, node);
  if (node.blockerReason) return friendlyDetail(node.blockerReason, "Work is waiting.");
  if (displayStatus === "scoping") return node.ticketId ? `Scoping ownership for ${node.ticketId}.` : "Scoping ownership.";
  if (displayStatus === "building") return node.ticketId ? `Building implementation for ${node.ticketId}.` : "Building implementation.";
  if (displayStatus === "waiting") return "Waiting for previous step.";
  if (displayStatus === "followup") return `${nodeTitle(node, node.actionType, node.ownerRole)} needs generated follow-up.`;
  if (displayStatus === "done" && normalize(node.actionType) === "blocker") {
    return node.ticketId ? `Follow-up is resolved for ${node.ticketId}.` : "Follow-up is resolved.";
  }
  const scope = usefulScope(node);
  const ticket = node.ticketId ? ` for ${node.ticketId}` : "";
  const scopeDetail = scope ? ` Scope: ${scope}.` : "";
  return `${nodeTitle(node, node.actionType, node.ownerRole)} is ${statusLabel(displayStatus).toLowerCase()}${ticket}.${scopeDetail}`;
}

function ticketStatus(value: unknown): AutomationTicketStatus {
  const normalized = normalize(value);
  if (normalized === "building" || normalized === "writing") return "building";
  if (normalized === "scoping" || normalized === "planning") return "scoping";
  if (normalized === "running") return "running";
  if (normalized === "ready") return "ready";
  if (normalized === "waiting" || normalized === "deferred") return "waiting";
  if (normalized === "in_progress") return "in_progress";
  if (normalized === "candidate_done") return "candidate_done";
  if (normalized === "done") return "done";
  if (normalized === "blocked") return "blocked";
  return "pending";
}

function ticketStatusLabel(status: AutomationTicketStatus): string {
  if (status === "building") return "Building";
  if (status === "scoping") return "Scoping";
  if (status === "running") return "Running";
  if (status === "ready") return "Ready";
  if (status === "waiting") return "Waiting";
  if (status === "in_progress") return "In progress";
  if (status === "candidate_done") return "Ready for hardening";
  if (status === "blocked") return "Follow-up work";
  return titleCase(status);
}

function ticketTone(status: AutomationTicketStatus): RunTone {
  if (status === "done") return "good";
  if (status === "building" || status === "scoping" || status === "running" || status === "ready" || status === "in_progress" || status === "candidate_done") return "info";
  if (status === "blocked") return "warn";
  return "quiet";
}

function ticketNumericId(id: string): number {
  const match = id.match(/(\d+)$/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function isTicketLikeId(value: string): boolean {
  const raw = value.trim().toLowerCase();
  const normalized = normalize(value);
  if (!raw) return false;
  return !(
    raw.startsWith("task:") ||
    raw.startsWith("node:") ||
    raw.startsWith("dag-node:") ||
    raw.startsWith("dag_node:") ||
    normalized.startsWith("task_") ||
    normalized.startsWith("node_") ||
    normalized.startsWith("dag_node_") ||
    normalized === "automation"
  );
}

function ticketRecordId(ticket: Record<string, unknown>, fallback: string): string {
  return text(ticket.id || ticket.ticket_id || ticket.task_id, fallback);
}

function inferredTicketStatus(ticketId: string, model: RunModel): AutomationTicketStatus {
  const nodes = model.executionDag.nodes.filter((node) => node.ticketId === ticketId);
  if (!nodes.length) return "pending";
  const statuses = nodes.map((node) => displayStatusKind(node.statusKind, node));
  if (statuses.some((status) => status === "followup" || status === "failed")) return "blocked";
  if (statuses.some((status) => status === "building")) return "building";
  if (statuses.some((status) => status === "scoping")) return "scoping";
  if (statuses.some((status) => status === "running")) return "running";
  if (statuses.some((status) => status === "ready")) {
    return statuses.some((status) => status === "done") ? "running" : "ready";
  }
  const progressNodes = nodes.filter((node) => progressColumnForAction(node.actionType || node.canonicalActionType));
  if (progressNodes.length && progressNodes.every((node) => ["done", "skipped"].includes(displayStatusKind(node.statusKind, node)))) {
    return "done";
  }
  return statuses.some((status) => status === "done") ? "running" : "waiting";
}

function progressColumnForAction(action: string): AutomationPipelineColumnId | null {
  const normalized = normalize(action);
  if (["orchestrate", "decompose", "scope", "refresh_index", "calibrate"].includes(normalized)) return "plan";
  if (["build", "repair"].includes(normalized)) return "build";
  if (["review", "audit"].includes(normalized)) return "review";
  if (normalized === "validate") return "validate";
  if (normalized === "integrate") return "integrate";
  if (normalized === "done" || normalized === "completion") return "done";
  return null;
}

function stageForTicket(ticketId: string, status: AutomationTicketStatus, model: RunModel): string {
  const nodes = model.executionDag.nodes.filter((node) => node.ticketId === ticketId);
  const active = nodes.find((node) => ["running", "ready", "blocked", "failed"].includes(node.statusKind)) ||
    nodes.find((node) => node.statusKind === "pending");
  if (active) {
    return `${nodeTitle(active, active.actionType, active.ownerRole)} ${statusLabel(displayStatusKind(active.statusKind, active)).toLowerCase()}`;
  }
  if (status === "candidate_done") return "Awaiting hardener";
  if (status === "building") return "Building implementation";
  if (status === "scoping") return "Scoping ownership";
  if (status === "running" || status === "in_progress") return "Implementation active";
  if (status === "ready") return "Ready for scheduler";
  if (status === "waiting") return "Waiting for dependencies";
  if (status === "done") return "Completed";
  if (status === "blocked") return "Follow-up needed";
  return "Queued";
}

function activeTicketPriority(status: AutomationTicketStatus): number {
  if (status === "building") return 3;
  if (status === "scoping") return 2;
  if (status === "running" || status === "in_progress") return 1;
  return 0;
}

function setActiveTicketStatus(map: Map<string, AutomationTicketStatus>, ticketId: string, status: AutomationTicketStatus): void {
  if (!ticketId || activeTicketPriority(status) <= 0) return;
  const existing = map.get(ticketId);
  if (!existing || activeTicketPriority(status) > activeTicketPriority(existing)) {
    map.set(ticketId, status);
  }
}

function workerTicketId(worker: Record<string, unknown>): string {
  const payload = record(worker.payload);
  const lease = record(payload.lease);
  const leasePayload = record(lease.payload);
  return firstText([worker.task_id, worker.ticket_id, payload.ticket_id, lease.ticket_id, lease.task_id, leasePayload.ticket_id], "");
}

function activeTicketStatuses(snapshot: ProjectSnapshot | null, model: RunModel): Map<string, AutomationTicketStatus> {
  const active = new Map<string, AutomationTicketStatus>();
  for (const node of model.executionDag.nodes) {
    const displayStatus = displayStatusKind(node.statusKind, node);
    if (displayStatus === "building" || displayStatus === "scoping" || displayStatus === "running") {
      setActiveTicketStatus(active, node.ticketId, displayStatus);
    }
  }
  for (const worker of list(snapshot?.dag.active_read_only_workers).map(record)) {
    setActiveTicketStatus(active, workerTicketId(worker), "scoping");
  }
  for (const worker of list(snapshot?.dag.active_write_workers).map(record)) {
    setActiveTicketStatus(active, workerTicketId(worker), "building");
  }
  return active;
}

function ticketProgress(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["ticketProgress"] {
  const sourceById = new Map<string, Record<string, unknown>>();
  const activeStatusByTicket = activeTicketStatuses(snapshot, model);
  for (const rawTicket of [...list(snapshot?.tickets.items), ...list(snapshot?.tickets.remaining)].map(record)) {
    const id = ticketRecordId(rawTicket, "");
    if (id && !sourceById.has(id)) sourceById.set(id, rawTicket);
  }
  for (const node of model.executionDag.nodes) {
    const id = text(node.ticketId, "");
    if (!isTicketLikeId(id) || sourceById.has(id)) continue;
    sourceById.set(id, {
      id,
      summary: `${nodeTitle(node, node.actionType, node.ownerRole)} work is recorded.`,
      status: inferredTicketStatus(id, model),
    });
  }
  for (const progressRow of model.operations.progressRows) {
    const id = text(progressRow.taskId, "");
    if (!isTicketLikeId(id) || sourceById.has(id)) continue;
    sourceById.set(id, {
      id,
      summary: progressRow.summary || progressRow.label || "Ticket work is recorded.",
      status: inferredTicketStatus(id, model),
    });
  }
  const source = Array.from(sourceById.values());
  const rows = source.map(record).map((ticket, index) => {
    const id = ticketRecordId(ticket, `ticket-${index + 1}`);
    const canonicalStatus = ticket.status === undefined || ticket.status === null || text(ticket.status, "") === ""
      ? inferredTicketStatus(id, model)
      : ticketStatus(ticket.status);
    const activeStatus = canonicalStatus === "done" ? undefined : activeStatusByTicket.get(id);
    const status = activeStatus ?? canonicalStatus;
    const evidence = list(ticket.evidence).map((item) => text(item, "")).filter(Boolean);
    const commits = list(ticket.related_commits).map((item) => text(item, "")).filter(Boolean);
    const dependsOn = list(ticket.depends_on).map((item) => text(item, "")).filter(Boolean);
    const runtimePayload = record(ticket.runtime_payload);
    const acceptanceCriteria = list(ticket.acceptance_criteria || runtimePayload.acceptance_criteria)
      .map((item) => text(item, ""))
      .filter(Boolean);
    const verificationCommands = list(ticket.verification_commands || runtimePayload.verification_commands)
      .map((item) => text(item, ""))
      .filter(Boolean);
    const blocker = text(ticket.blocker || runtimePayload.blocker, "");
    const rawRuntimeStatus = text(ticket.runtime_status || runtimePayload.status || ticket.status, "");
    const runtimeStatus = activeStatus && !["running", "in_progress"].includes(canonicalStatus)
      ? ticketStatusLabel(activeStatus)
      : rawRuntimeStatus;
    return {
      id,
      summary: text(ticket.summary || ticket.title, "Ticket is queued."),
      status,
      statusLabel: ticketStatusLabel(status),
      tone: ticketTone(status),
      stage: stageForTicket(id, status, model),
      detail: evidence[0] || blocker || (dependsOn.length ? `Depends on ${dependsOn.slice(0, 3).join(", ")}` : "No evidence recorded yet."),
      dependsOn,
      acceptanceCriteria,
      verificationCommands,
      evidenceCount: evidence.length,
      blocker,
      relatedCommits: commits,
      commitCount: commits.length,
      runtimeStatus,
      runtimePayload,
    };
  }).filter((ticket) => ticket.id);

  const ticketOrder: AutomationTicketStatus[] = ["building", "scoping", "running", "in_progress", "ready", "waiting", "pending", "candidate_done", "blocked", "done"];
  rows.sort((first, second) => {
    const firstOrder = ticketOrder.indexOf(first.status);
    const secondOrder = ticketOrder.indexOf(second.status);
    return (
      (firstOrder === -1 ? ticketOrder.length : firstOrder) -
      (secondOrder === -1 ? ticketOrder.length : secondOrder)
    ) || ticketNumericId(first.id) - ticketNumericId(second.id) || first.id.localeCompare(second.id);
  });

  const statuses: AutomationTicketStatus[] = ["building", "scoping", "running", "ready", "waiting", "candidate_done", "blocked", "done"];
  const counts = statuses.map((status) => ({
    id: status,
    label: ticketStatusLabel(status),
    count: rows.filter((row) => row.status === status).length,
    tone: ticketTone(status),
  }));
  const done = counts.find((item) => item.id === "done")?.count ?? 0;
  const candidateDone = counts.find((item) => item.id === "candidate_done")?.count ?? 0;
  const active = rows.filter((row) => row.status === "building" || row.status === "scoping" || row.status === "running" || row.status === "in_progress").length;
  const total = rows.length;
  return {
    summary: total
      ? `${done}/${total} done · ${candidateDone} ready for hardening · ${active} active`
      : "No tickets are loaded.",
    total,
    rows,
    counts,
  };
}

function ticketGraphStatusSort(status: AutomationTicketGraphStatus): number {
  const order: AutomationTicketGraphStatus[] = ["building", "scoping", "running", "ready", "candidate_done", "blocked", "waiting", "pending", "missing", "done"];
  const index = order.indexOf(status);
  return index === -1 ? order.length : index;
}

function ticketGraphNodeSort(first: AutomationTicketGraphNode, second: AutomationTicketGraphNode): number {
  return ticketGraphStatusSort(first.status) - ticketGraphStatusSort(second.status) ||
    ticketNumericId(first.id) - ticketNumericId(second.id) ||
    first.id.localeCompare(second.id);
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((first, second) => first - second);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function ticketGraphNeighborRanks(
  nodeId: string,
  neighborsById: Map<string, string[]>,
  rankById: Map<string, number>,
  layerById: Map<string, number>,
  direction: "before" | "after",
): number[] {
  const nodeLayer = layerById.get(nodeId);
  if (nodeLayer === undefined) return [];
  return (neighborsById.get(nodeId) || [])
    .map((neighborId) => {
      const neighborLayer = layerById.get(neighborId);
      const neighborRank = rankById.get(neighborId);
      const inDirection = direction === "before"
        ? neighborLayer !== undefined && neighborLayer < nodeLayer
        : neighborLayer !== undefined && neighborLayer > nodeLayer;
      return inDirection && neighborRank !== undefined ? neighborRank : null;
    })
    .filter((rank): rank is number => rank !== null);
}

function reorderTicketGraphLayer(
  layerNodes: AutomationTicketGraphNode[],
  neighborsById: Map<string, string[]>,
  rankById: Map<string, number>,
  layerById: Map<string, number>,
  direction: "before" | "after",
): AutomationTicketGraphNode[] {
  const currentOrder = new Map(layerNodes.map((node, index) => [node.id, index]));
  return [...layerNodes].sort((first, second) => {
    const firstMedian = median(ticketGraphNeighborRanks(first.id, neighborsById, rankById, layerById, direction));
    const secondMedian = median(ticketGraphNeighborRanks(second.id, neighborsById, rankById, layerById, direction));
    const firstScore = firstMedian ?? rankById.get(first.id) ?? currentOrder.get(first.id) ?? 0;
    const secondScore = secondMedian ?? rankById.get(second.id) ?? currentOrder.get(second.id) ?? 0;
    return firstScore - secondScore ||
      (currentOrder.get(first.id) ?? 0) - (currentOrder.get(second.id) ?? 0) ||
      ticketGraphNodeSort(first, second);
  });
}

function assignTicketGraphSlots(
  layerNodes: AutomationTicketGraphNode[],
  maxLayerSize: number,
  preferredById: Map<string, number>,
  rankById: Map<string, number>,
): void {
  let previousSlot = -1;
  const centeredStart = (maxLayerSize - layerNodes.length) / 2;
  layerNodes.forEach((node, index) => {
    const remaining = layerNodes.length - index - 1;
    const minSlot = previousSlot + 1;
    const maxSlot = maxLayerSize - remaining - 1;
    const fallback = rankById.get(node.id) ?? centeredStart + index;
    const preferred = preferredById.get(node.id) ?? fallback;
    const slot = Math.max(minSlot, Math.min(maxSlot, Math.round(preferred)));
    rankById.set(node.id, slot);
    previousSlot = slot;
  });
}

function orderTicketGraphLayers(
  nodes: AutomationTicketGraphNode[],
  layers: number[],
  parentsById: Map<string, string[]>,
  childrenById: Map<string, string[]>,
  maxLayerSize: number,
): { orderedLayers: Map<number, AutomationTicketGraphNode[]>; rankById: Map<string, number> } {
  const orderedLayers = new Map<number, AutomationTicketGraphNode[]>();
  const rankById = new Map<string, number>();
  const layerById = new Map(nodes.map((node) => [node.id, node.layer]));

  for (const layer of layers) {
    const layerNodes = nodes.filter((node) => node.layer === layer).sort(ticketGraphNodeSort);
    orderedLayers.set(layer, layerNodes);
    assignTicketGraphSlots(layerNodes, maxLayerSize, new Map(), rankById);
  }

  for (let sweep = 0; sweep < 4; sweep += 1) {
    for (const layer of layers) {
      const layerNodes = orderedLayers.get(layer) || [];
      const ordered = reorderTicketGraphLayer(layerNodes, parentsById, rankById, layerById, "before");
      const preferred = new Map(ordered.map((node) => [
        node.id,
        median(ticketGraphNeighborRanks(node.id, parentsById, rankById, layerById, "before")) ?? rankById.get(node.id) ?? 0,
      ]));
      orderedLayers.set(layer, ordered);
      assignTicketGraphSlots(ordered, maxLayerSize, preferred, rankById);
    }

    for (const layer of [...layers].reverse()) {
      const layerNodes = orderedLayers.get(layer) || [];
      const ordered = reorderTicketGraphLayer(layerNodes, childrenById, rankById, layerById, "after");
      const preferred = new Map(ordered.map((node) => [
        node.id,
        median(ticketGraphNeighborRanks(node.id, childrenById, rankById, layerById, "after")) ?? rankById.get(node.id) ?? 0,
      ]));
      orderedLayers.set(layer, ordered);
      assignTicketGraphSlots(ordered, maxLayerSize, preferred, rankById);
    }
  }

  return { orderedLayers, rankById };
}

function spreadEdgeOffset(index: number, count: number, maxOffset: number): number {
  if (count <= 1) return 0;
  const step = Math.min(7, (maxOffset * 2) / Math.max(1, count - 1));
  return (index - (count - 1) / 2) * step;
}

function clamp(value: number, min: number, max: number): number {
  if (max < min) return (min + max) / 2;
  return Math.max(min, Math.min(max, value));
}

function compactPathPoints(points: Array<{ x: number; y: number }>): Array<{ x: number; y: number }> {
  const compacted: Array<{ x: number; y: number }> = [];
  for (const point of points) {
    const rounded = { x: Math.round(point.x * 10) / 10, y: Math.round(point.y * 10) / 10 };
    const previous = compacted[compacted.length - 1];
    if (previous && previous.x === rounded.x && previous.y === rounded.y) continue;
    compacted.push(rounded);
  }
  return compacted;
}

function orthogonalPath(points: Array<{ x: number; y: number }>): string {
  const compacted = compactPathPoints(points);
  if (!compacted.length) return "";
  return compacted
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
}

function ticketGraphRowSlots(nodes: AutomationTicketGraphNode[]): number[] {
  return Array.from(new Set(nodes.map((node) => node.y))).sort((a, b) => a - b);
}

function nearestTicketGraphSlot(y: number, rows: number[]): number {
  if (!rows.length) return 0;
  let bestIndex = 0;
  let bestDistance = Math.abs(rows[0] - y);
  rows.forEach((rowY, index) => {
    const distance = Math.abs(rowY - y);
    if (distance < bestDistance) {
      bestIndex = index;
      bestDistance = distance;
    }
  });
  return bestIndex;
}

function ticketGraphLaneY(
  laneIndex: number,
  rows: number[],
  nodeHeight: number,
  graphHeight: number,
  laneOffset: number,
): number {
  if (!rows.length) return TICKET_GRAPH_PADDING_Y + laneOffset;
  const rowGap = rows.length > 1
    ? Math.max(10, rows[1] - rows[0] - nodeHeight)
    : TICKET_GRAPH_ROW_GAP;
  if (laneIndex <= 0) {
    return Math.max(18, rows[0] - Math.min(18, Math.max(8, TICKET_GRAPH_PADDING_Y / 2))) + laneOffset;
  }
  if (laneIndex >= rows.length) {
    const bottomSpace = Math.max(12, graphHeight - (rows[rows.length - 1] + nodeHeight));
    return rows[rows.length - 1] + nodeHeight + Math.min(24, bottomSpace / 2) + laneOffset;
  }
  return rows[laneIndex - 1] + nodeHeight + rowGap / 2 + laneOffset;
}

function sortEdgesByTarget(edges: AutomationTicketGraphEdge[], nodeById: Map<string, AutomationTicketGraphNode>): AutomationTicketGraphEdge[] {
  return [...edges].sort((first, second) => {
    const firstTarget = nodeById.get(first.target);
    const secondTarget = nodeById.get(second.target);
    return (firstTarget?.layer ?? 0) - (secondTarget?.layer ?? 0) ||
      (firstTarget?.y ?? 0) - (secondTarget?.y ?? 0) ||
      first.target.localeCompare(second.target) ||
      first.id.localeCompare(second.id);
  });
}

function sortEdgesBySource(edges: AutomationTicketGraphEdge[], nodeById: Map<string, AutomationTicketGraphNode>): AutomationTicketGraphEdge[] {
  return [...edges].sort((first, second) => {
    const firstSource = nodeById.get(first.source);
    const secondSource = nodeById.get(second.source);
    return (firstSource?.layer ?? 0) - (secondSource?.layer ?? 0) ||
      (firstSource?.y ?? 0) - (secondSource?.y ?? 0) ||
      first.source.localeCompare(second.source) ||
      first.id.localeCompare(second.id);
  });
}

function routeTicketGraphEdges(
  edges: AutomationTicketGraphEdge[],
  nodes: AutomationTicketGraphNode[],
  layers: number[],
  graphHeight: number,
): void {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const edgesBySource = new Map<string, AutomationTicketGraphEdge[]>();
  const edgesByTarget = new Map<string, AutomationTicketGraphEdge[]>();
  for (const edge of edges) {
    edgesBySource.set(edge.source, [...(edgesBySource.get(edge.source) || []), edge]);
    edgesByTarget.set(edge.target, [...(edgesByTarget.get(edge.target) || []), edge]);
  }
  for (const [source, sourceEdges] of edgesBySource.entries()) {
    edgesBySource.set(source, sortEdgesByTarget(sourceEdges, nodeById));
  }
  for (const [target, targetEdges] of edgesByTarget.entries()) {
    edgesByTarget.set(target, sortEdgesBySource(targetEdges, nodeById));
  }

  const rows = ticketGraphRowSlots(nodes);
  const nodeHeight = Math.max(TICKET_GRAPH_NODE_HEIGHT, ...nodes.map((node) => node.height));
  const layerXByIndex = new Map(layers.map((layer) => [
    layer,
    TICKET_GRAPH_PADDING_X + layer * (TICKET_GRAPH_NODE_WIDTH + TICKET_GRAPH_COLUMN_GAP),
  ]));
  const laneByEdgeId = new Map<string, number>();
  const longEdgesByLane = new Map<number, AutomationTicketGraphEdge[]>();

  for (const edge of edges) {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) continue;
    const layerDistance = target.layer - source.layer;
    if (layerDistance <= 1) continue;
    const sourceSlot = nearestTicketGraphSlot(source.y, rows);
    const targetSlot = nearestTicketGraphSlot(target.y, rows);
    const laneIndex = clamp(Math.round((sourceSlot + targetSlot) / 2) + 1, 1, Math.max(1, rows.length));
    laneByEdgeId.set(edge.id, laneIndex);
    longEdgesByLane.set(laneIndex, [...(longEdgesByLane.get(laneIndex) || []), edge]);
  }

  const laneOffsetByEdgeId = new Map<string, number>();
  for (const laneEdges of longEdgesByLane.values()) {
    const sorted = sortEdgesBySource(sortEdgesByTarget(laneEdges, nodeById), nodeById);
    sorted.forEach((edge, index) => {
      laneOffsetByEdgeId.set(edge.id, spreadEdgeOffset(index, sorted.length, 6));
    });
  }

  for (const edge of edges) {
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) {
      edge.path = "";
      continue;
    }

    const outgoing = edgesBySource.get(edge.source) || [];
    const incoming = edgesByTarget.get(edge.target) || [];
    const sourceOrder = Math.max(0, outgoing.findIndex((item) => item.id === edge.id));
    const targetOrder = Math.max(0, incoming.findIndex((item) => item.id === edge.id));
    const x1 = source.x + source.width;
    const x2 = target.x;
    const y1 = source.y + ((sourceOrder + 1) * source.height) / (outgoing.length + 1);
    const y2 = target.y + ((targetOrder + 1) * target.height) / (incoming.length + 1);
    const layerDistance = target.layer - source.layer;

    if (layerDistance <= 1) {
      const gap = Math.max(24, x2 - x1);
      const sharedIndex = sourceOrder + targetOrder;
      const sharedCount = Math.max(outgoing.length, incoming.length, 1);
      const midX = x1 + gap / 2 + spreadEdgeOffset(sharedIndex, sharedCount * 2, 14);
      edge.path = orthogonalPath([
        { x: x1, y: y1 },
        { x: midX, y: y1 },
        { x: midX, y: y2 },
        { x: x2, y: y2 },
      ]);
      continue;
    }

    const nextLayerX = layerXByIndex.get(source.layer + 1) ?? x2;
    const previousLayerX = layerXByIndex.get(target.layer - 1) ?? source.x;
    const sourceGutterLeft = x1 + 10;
    const sourceGutterRight = Math.max(sourceGutterLeft, nextLayerX - 10);
    const targetGutterLeft = previousLayerX + target.width + 10;
    const targetGutterRight = x2 - 10;
    const sourceGutterX = clamp(
      x1 + 24 + spreadEdgeOffset(sourceOrder, outgoing.length, 18),
      sourceGutterLeft,
      sourceGutterRight,
    );
    const targetGutterX = clamp(
      x2 - 24 - spreadEdgeOffset(targetOrder, incoming.length, 18),
      targetGutterLeft,
      targetGutterRight,
    );
    const laneY = ticketGraphLaneY(
      laneByEdgeId.get(edge.id) ?? 1,
      rows,
      nodeHeight,
      graphHeight,
      laneOffsetByEdgeId.get(edge.id) ?? 0,
    );

    edge.path = orthogonalPath([
      { x: x1, y: y1 },
      { x: sourceGutterX, y: y1 },
      { x: sourceGutterX, y: laneY },
      { x: targetGutterX, y: laneY },
      { x: targetGutterX, y: y2 },
      { x: x2, y: y2 },
    ]);
  }
}

function buildTicketGraph(progress: AutomationViewModel["ticketProgress"]): AutomationViewModel["ticketGraph"] {
  const nodeById = new Map<string, AutomationTicketGraphNode>();
  const edges: AutomationTicketGraphEdge[] = [];
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, number>();

  const makeNode = (
    row: AutomationTicketProgressRow,
    placeholder = false,
  ): AutomationTicketGraphNode => ({
    id: row.id,
    summary: row.summary,
    status: placeholder ? "missing" : row.status,
    statusLabel: placeholder ? "Missing dependency" : row.statusLabel,
    tone: placeholder ? "quiet" : row.tone,
    stage: placeholder ? "Referenced by another ticket" : row.stage,
    detail: placeholder ? "This dependency is referenced but no ticket row is loaded." : row.detail,
    dependsOn: placeholder ? [] : row.dependsOn,
    acceptanceCriteria: placeholder ? [] : row.acceptanceCriteria,
    verificationCommands: placeholder ? [] : row.verificationCommands,
    evidenceCount: placeholder ? 0 : row.evidenceCount,
    blocker: placeholder ? "" : row.blocker,
    relatedCommits: placeholder ? [] : row.relatedCommits,
    commitCount: placeholder ? 0 : row.commitCount,
    runtimeStatus: placeholder ? "" : row.runtimeStatus,
    runtimePayload: placeholder ? {} : row.runtimePayload,
    layer: 0,
    x: 0,
    y: 0,
    width: TICKET_GRAPH_NODE_WIDTH,
    height: TICKET_GRAPH_NODE_HEIGHT,
    placeholder,
    cyclic: false,
  });

  for (const row of progress.rows) {
    nodeById.set(row.id, makeNode(row));
  }
  for (const row of progress.rows) {
    for (const dependencyId of row.dependsOn) {
      if (!dependencyId) continue;
      if (!nodeById.has(dependencyId)) {
        nodeById.set(dependencyId, makeNode({
          id: dependencyId,
          summary: "Missing dependency",
          status: "waiting",
          statusLabel: "Waiting",
          tone: "quiet",
          stage: "Referenced dependency",
          detail: "This dependency is referenced but no ticket row is loaded.",
          dependsOn: [],
          acceptanceCriteria: [],
          verificationCommands: [],
          evidenceCount: 0,
          blocker: "",
          relatedCommits: [],
          commitCount: 0,
          runtimeStatus: "",
          runtimePayload: {},
        }, true));
      }
      edges.push({
        id: `${dependencyId}->${row.id}`,
        source: dependencyId,
        target: row.id,
        cyclic: false,
        path: "",
      });
      outgoing.set(dependencyId, [...(outgoing.get(dependencyId) || []), row.id]);
      incoming.set(row.id, (incoming.get(row.id) || 0) + 1);
      incoming.set(dependencyId, incoming.get(dependencyId) || 0);
    }
  }
  for (const id of nodeById.keys()) {
    incoming.set(id, incoming.get(id) || 0);
    outgoing.set(id, outgoing.get(id) || []);
  }
  const parentsById = new Map(Array.from(nodeById.keys()).map((id) => [id, [] as string[]]));
  const childrenById = new Map(Array.from(nodeById.keys()).map((id) => [id, [] as string[]]));
  for (const edge of edges) {
    parentsById.set(edge.target, [...(parentsById.get(edge.target) || []), edge.source]);
    childrenById.set(edge.source, [...(childrenById.get(edge.source) || []), edge.target]);
  }

  const layerById = new Map<string, number>();
  const queue = Array.from(nodeById.values())
    .filter((node) => (incoming.get(node.id) || 0) === 0)
    .sort(ticketGraphNodeSort)
    .map((node) => node.id);
  for (const id of queue) layerById.set(id, 0);

  const processed = new Set<string>();
  while (queue.length) {
    const current = queue.shift() || "";
    if (!current || processed.has(current)) continue;
    processed.add(current);
    const currentLayer = layerById.get(current) || 0;
    for (const target of outgoing.get(current) || []) {
      layerById.set(target, Math.max(layerById.get(target) || 0, currentLayer + 1));
      incoming.set(target, Math.max(0, (incoming.get(target) || 0) - 1));
      if ((incoming.get(target) || 0) === 0) {
        queue.push(target);
        queue.sort((first, second) => ticketGraphNodeSort(nodeById.get(first)!, nodeById.get(second)!));
      }
    }
  }

  const maxProcessedLayer = Math.max(0, ...Array.from(layerById.values()));
  const cyclicIds = new Set<string>();
  for (const id of nodeById.keys()) {
    if (processed.has(id)) continue;
    cyclicIds.add(id);
    layerById.set(id, maxProcessedLayer + 1);
  }

  const nodes = Array.from(nodeById.values()).map((node) => ({
    ...node,
    layer: layerById.get(node.id) || 0,
    cyclic: cyclicIds.has(node.id),
  }));
  for (const edge of edges) {
    edge.cyclic = cyclicIds.has(edge.source) || cyclicIds.has(edge.target);
  }

  const layers = Array.from(new Set(nodes.map((node) => node.layer))).sort((a, b) => a - b);
  const maxLayerSize = Math.max(1, ...layers.map((layer) => nodes.filter((node) => node.layer === layer).length));
  const { orderedLayers, rankById } = orderTicketGraphLayers(nodes, layers, parentsById, childrenById, maxLayerSize);
  for (const layer of layers) {
    const layerNodes = orderedLayers.get(layer) || [];
    layerNodes.forEach((node, index) => {
      node.x = TICKET_GRAPH_PADDING_X + layer * (TICKET_GRAPH_NODE_WIDTH + TICKET_GRAPH_COLUMN_GAP);
      node.y = TICKET_GRAPH_PADDING_Y + (rankById.get(node.id) ?? index) * (TICKET_GRAPH_NODE_HEIGHT + TICKET_GRAPH_ROW_GAP);
    });
  }

  const layerRecords = layers.map((layer) => {
    const layerNodes = nodes.filter((node) => node.layer === layer);
    const cyclic = layerNodes.some((node) => node.cyclic);
    return {
      id: `ticket-layer-${layer}`,
      index: layer,
      label: cyclic ? "Cycle / unresolved" : `Layer ${layer + 1}`,
      x: TICKET_GRAPH_PADDING_X + layer * (TICKET_GRAPH_NODE_WIDTH + TICKET_GRAPH_COLUMN_GAP),
      count: layerNodes.length,
      cyclic,
    };
  });
  const width = Math.max(
    720,
    TICKET_GRAPH_PADDING_X * 2 + (layers.length || 1) * TICKET_GRAPH_NODE_WIDTH + Math.max(0, layers.length - 1) * TICKET_GRAPH_COLUMN_GAP,
  );
  const height = Math.max(360, TICKET_GRAPH_PADDING_Y * 2 + maxLayerSize * TICKET_GRAPH_NODE_HEIGHT + Math.max(0, maxLayerSize - 1) * TICKET_GRAPH_ROW_GAP);
  routeTicketGraphEdges(edges, nodes, layers, height);
  const completed = nodes.filter((node) => node.status === "done").length;
  const active = nodes.filter((node) => ["building", "scoping", "running", "in_progress"].includes(node.status)).length;
  const ready = nodes.filter((node) => node.status === "ready").length;
  const waiting = nodes.filter((node) => node.status === "waiting" || node.status === "pending" || node.status === "missing").length;

  return {
    summary: `${nodes.length} tickets / ${edges.length} dependencies`,
    nodes,
    edges,
    layers: layerRecords,
    width,
    height,
    dependencyCount: edges.length,
    completed,
    active,
    ready,
    waiting,
    cyclicCount: cyclicIds.size,
  };
}

function graphColumnForPhase(phase: RunDagPhaseId): AutomationPipelineColumnId {
  return GRAPH_COLUMNS.find((column) => column.phases.includes(phase))?.id ?? "done";
}

function graphColumnLabel(id: AutomationPipelineColumnId): string {
  return GRAPH_COLUMNS.find((column) => column.id === id)?.label ?? titleCase(id);
}

function graphStatusSort(status: AutomationNodeStatus): number {
  const order: AutomationNodeStatus[] = ["building", "scoping", "running", "ready", "followup", "failed", "waiting", "done", "skipped"];
  const index = order.indexOf(status);
  return index === -1 ? order.length : index;
}

function graphNodeBadges(node: RunDagNode): string[] {
  return node.badges.map((badge) => badge.label).filter(Boolean).slice(0, 3);
}

function graphNodeFromDagNode(node: RunDagNode): AutomationGraphNode {
  const status = displayStatusKind(node.statusKind, node);
  const phase = graphColumnForPhase(node.phase);
  const title = nodeTitle(node, node.actionType, node.ownerRole);
  return {
    id: node.id,
    sourceKind: "node",
    title,
    subtitle: node.ticketId || roleLabel(node.ownerRole),
    phase,
    phaseLabel: graphColumnLabel(phase),
    status,
    statusKind: node.statusKind,
    statusLabel: statusLabel(status),
    tone: toneForDisplayStatus(status),
    role: roleLabel(node.ownerRole),
    ticketId: node.ticketId,
    detail: friendlyNodeDetail(node, node.detail, status),
    scope: usefulScope(node),
    nodeCount: 1,
    samples: [node.ticketId, usefulScope(node)].filter(Boolean).slice(0, 3),
    badges: graphNodeBadges(node),
    x: 0,
    y: 0,
    width: GRAPH_NODE_WIDTH,
    height: GRAPH_NODE_HEIGHT,
  };
}

function graphNodeFromCluster(cluster: RunModel["executionDag"]["clusters"][number]): AutomationGraphNode {
  const status = displayStatusKind(cluster.statusKind);
  const phase = graphColumnForPhase(cluster.phase);
  const actionSamples = cluster.actionSamples.map((item) => friendlyActionLabel(item));
  const badges = [
    cluster.activeGroupNodeCount ? `${cluster.activeGroupNodeCount} running group` : "",
    cluster.plannedGroupNodeCount ? `${cluster.plannedGroupNodeCount} planned wave` : "",
    cluster.ownerSamples.length ? cluster.ownerSamples.slice(0, 2).map(roleLabel).join(", ") : "",
  ].filter(Boolean);
  return {
    id: cluster.id,
    sourceKind: "cluster",
    title: `${graphColumnLabel(phase)} ${statusLabel(status)}`,
    subtitle: `${cluster.nodeCount} node${cluster.nodeCount === 1 ? "" : "s"}`,
    phase,
    phaseLabel: graphColumnLabel(phase),
    status,
    statusKind: cluster.statusKind,
    statusLabel: statusLabel(status),
    tone: toneForDisplayStatus(status),
    role: cluster.ownerSamples.length ? cluster.ownerSamples.slice(0, 2).map(roleLabel).join(", ") : "scheduler",
    ticketId: cluster.ticketSamples[0] || "",
    detail: friendlyDetail(cluster.detail, `${cluster.nodeCount} execution DAG node${cluster.nodeCount === 1 ? "" : "s"} are grouped here.`),
    scope: actionSamples.length ? `Actions: ${actionSamples.slice(0, 3).join(", ")}` : "",
    nodeCount: cluster.nodeCount,
    samples: [...cluster.ticketSamples, ...actionSamples].filter(Boolean).slice(0, 4),
    badges,
    x: 0,
    y: 0,
    width: GRAPH_NODE_WIDTH,
    height: GRAPH_NODE_HEIGHT + 8,
  };
}

function layoutGraphNodes(nodes: AutomationGraphNode[]): {
  columns: AutomationViewModel["dag"]["columns"];
  nodes: AutomationGraphNode[];
  width: number;
  height: number;
} {
  const width = GRAPH_LEFT * 2 + GRAPH_COLUMNS.length * GRAPH_NODE_WIDTH + (GRAPH_COLUMNS.length - 1) * GRAPH_COLUMN_GAP;
  const columns = GRAPH_COLUMNS.map((column, index) => ({
    id: column.id,
    label: column.label,
    x: GRAPH_LEFT + index * (GRAPH_NODE_WIDTH + GRAPH_COLUMN_GAP),
    width: GRAPH_NODE_WIDTH,
  }));
  const columnById = new Map(columns.map((column) => [column.id, column]));
  const bucketed = new Map<AutomationPipelineColumnId, AutomationGraphNode[]>();
  for (const column of GRAPH_COLUMNS) bucketed.set(column.id, []);
  for (const node of nodes) {
    bucketed.get(node.phase)?.push(node);
  }
  const laidOut: AutomationGraphNode[] = [];
  let height = 320;
  for (const [phase, bucket] of bucketed.entries()) {
    const column = columnById.get(phase);
    if (!column) continue;
    bucket.sort((first, second) => (
      graphStatusSort(first.status) - graphStatusSort(second.status) ||
      second.nodeCount - first.nodeCount ||
      first.subtitle.localeCompare(second.subtitle) ||
      first.title.localeCompare(second.title)
    ));
    let y = GRAPH_TOP;
    for (const node of bucket) {
      laidOut.push({
        ...node,
        x: column.x,
        y,
        width: column.width,
      });
      y += node.height + GRAPH_ROW_GAP;
    }
    height = Math.max(height, y + GRAPH_BOTTOM);
  }
  return { columns, nodes: laidOut, width, height };
}

function edgeLabel(edge: RunDagEdge | RunDagClusterEdge): string {
  const count = "count" in edge ? edge.count : 1;
  if (count > 1) return `${count} ${edge.dependencyKind}`;
  if (edge.presentationKind === "blocker") return "blocker";
  if (edge.dependencyMode === "advisory") return "advisory";
  return edge.dependencyKind.replace(/_/g, " ");
}

function graphEdges(
  sourceEdges: Array<RunDagEdge | RunDagClusterEdge>,
  nodes: AutomationGraphNode[],
): AutomationGraphEdge[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  return sourceEdges
    .filter((edge) => nodeById.has(edge.source) && nodeById.has(edge.target))
    .slice(0, GRAPH_MAX_EDGES)
    .map((edge) => {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (!source || !target) throw new Error("graph edge references missing nodes after filtering");
      const x1 = source.x + source.width;
      const y1 = source.y + source.height / 2;
      const x2 = target.x;
      const y2 = target.y + target.height / 2;
      const curve = Math.max(42, Math.abs(x2 - x1) * 0.42);
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        presentationKind: edge.presentationKind,
        dependencyKind: edge.dependencyKind,
        dependencyMode: edge.dependencyMode,
        count: "count" in edge ? edge.count : 1,
        label: edgeLabel(edge),
        detail: friendlyDetail(edge.detail, edge.reason),
        points: {
          x1,
          y1,
          x2,
          y2,
          cx1: x1 + curve,
          cy1: y1,
          cx2: x2 - curve,
          cy2: y2,
        },
      };
    });
}

function groupTone(kind: AutomationGraphGroup["kind"], status: string): RunTone {
  if (kind === "active") return "info";
  if (kind === "completed") return "good";
  if (/fail|block|error|conflict/i.test(status)) return "warn";
  return "quiet";
}

function graphGroups(model: RunModel, visibleNodeIds: Set<string>, mode: AutomationGraphRenderMode): AutomationGraphGroup[] {
  if (mode === "cluster") return [];
  return model.executionDag.groups
    .map((group) => {
      const nodeIds = group.nodeIds.filter((nodeId) => visibleNodeIds.has(nodeId));
      return {
        id: group.id,
        label: group.label,
        kind: group.kind,
        mode: group.mode,
        status: group.status,
        detail: friendlyDetail(group.detail, "Execution wave is recorded."),
        nodeIds,
        tone: groupTone(group.kind, group.status),
      };
    })
    .filter((group) => group.nodeIds.length > 0)
    .slice(0, 8);
}

function dagGraph(model: RunModel): AutomationViewModel["dag"] {
  const mode: AutomationGraphRenderMode = model.executionDag.abstraction.enabled ? "cluster" : "node";
  const sourceNodes = mode === "cluster"
    ? model.executionDag.clusters.map(graphNodeFromCluster)
    : model.executionDag.visibleNodes.map(graphNodeFromDagNode);
  const layout = layoutGraphNodes(sourceNodes);
  const sourceEdges = mode === "cluster" ? model.executionDag.clusterEdges : model.executionDag.visibleEdges;
  const edges = graphEdges(sourceEdges, layout.nodes);
  const visibleNodeIds = new Set(layout.nodes.map((node) => node.id));
  const groups = graphGroups(model, visibleNodeIds, mode);
  const defaultSelectedNode = layout.nodes.find((node) => node.status === "building") ||
    layout.nodes.find((node) => node.status === "scoping") ||
    layout.nodes.find((node) => node.status === "running") ||
    layout.nodes.find((node) => node.status === "ready") ||
    layout.nodes.find((node) => node.status === "followup") ||
    layout.nodes.find((node) => node.status === "waiting") ||
    layout.nodes[0];
  const summaryParts = [
    `${model.executionDag.summary.running} running`,
    `${model.executionDag.summary.ready} ready`,
    `${model.executionDag.summary.completed} done`,
    `${model.executionDag.summary.blocked + model.executionDag.summary.failed + model.executionDag.summary.pending} waiting or follow-up`,
  ];
  const hidden = [
    model.executionDag.renderLimit.hiddenNodeCount ? `${model.executionDag.renderLimit.hiddenNodeCount} nodes folded` : "",
    model.executionDag.renderLimit.hiddenEdgeCount ? `${model.executionDag.renderLimit.hiddenEdgeCount} edges folded` : "",
    mode === "cluster" ? `${model.executionDag.abstraction.clusterCount} clusters / ${model.executionDag.abstraction.bundledEdgeCount} bundled edges` : "",
  ].filter(Boolean).join(" · ");

  return {
    columns: layout.columns,
    nodes: layout.nodes,
    edges,
    groups,
    defaultSelectedNodeId: defaultSelectedNode?.id || "",
    summary: model.executionDag.hasData ? summaryParts.join(" / ") : "No DAG work has been recorded yet.",
    mode,
    modeLabel: "Execution DAG",
    hiddenSummary: hidden,
    sourceNodeCount: model.executionDag.abstraction.sourceNodeCount || model.executionDag.nodes.length,
    sourceEdgeCount: model.executionDag.abstraction.sourceEdgeCount || model.executionDag.edges.length,
    clusterCount: model.executionDag.abstraction.clusterCount,
    bundledEdgeCount: model.executionDag.abstraction.bundledEdgeCount,
    width: layout.width,
    height: layout.height,
  };
}

function queueItemFromNode(node: RunDagNode): AutomationQueueBucket["items"][number] {
  const displayStatus = displayStatusKind(node.statusKind, node);
  return {
    id: node.id,
    title: nodeTitle(node, node.actionType, node.ownerRole),
    detail: friendlyNodeDetail(node, node.ticketId || "Automation work", displayStatus),
    statusLabel: statusLabel(displayStatus),
    tone: toneForDisplayStatus(displayStatus),
  };
}

function queueBuckets(snapshot: ProjectSnapshot | null, model: RunModel, tickets: AutomationViewModel["ticketProgress"]): AutomationQueueBucket[] {
  const buckets: Record<AutomationQueueBucketId, AutomationQueueBucket> = {
    running: { id: "running", label: "Running", count: 0, tone: "info", items: [] },
    ready: { id: "ready", label: "Next", count: 0, tone: "info", items: [] },
    waiting: { id: "waiting", label: "Harden", count: 0, tone: "info", items: [] },
    followup: { id: "followup", label: "Generated follow-up", count: 0, tone: "warn", items: [] },
    done: { id: "done", label: "Recently done", count: 0, tone: "good", items: [] },
  };
  const add = (bucketId: AutomationQueueBucketId, item: AutomationQueueBucket["items"][number]) => {
    buckets[bucketId].count += 1;
    if (buckets[bucketId].items.length < 3) buckets[bucketId].items.push(item);
  };

  for (const node of model.executionDag.nodes) {
    if (isInternalProgressNode(node)) continue;
    const displayStatus = displayStatusKind(node.statusKind, node);
    const generated = isGeneratedFollowUp(`${node.actionType} ${node.canonicalActionType} ${node.detail} ${node.blockerReason}`);
    if (displayStatus === "building" || displayStatus === "scoping" || displayStatus === "running") add("running", queueItemFromNode(node));
    else if (displayStatus === "ready") add(generated ? "followup" : "ready", queueItemFromNode(node));
    else if (displayStatus === "followup" || generated) add("followup", queueItemFromNode(node));
  }

  for (const ticket of tickets.rows.filter((row) => row.status === "candidate_done")) {
    add("waiting", {
      id: `candidate:${ticket.id}`,
      title: ticket.id,
      detail: `${ticket.summary} · ${ticket.stage}`,
      statusLabel: ticket.statusLabel,
      tone: ticket.tone,
    });
  }

  const nextActions = list(snapshot?.scheduler.next_actions).map(record);
  const repairActions = list(snapshot?.validation_repair.repair_actions).map(record);
  [...nextActions, ...repairActions].forEach((action, index) => {
    const kind = text(action.kind || action.action_kind || action.action_type, "work");
    const detail = text(action.reason || action.summary, "");
    if (!isGeneratedFollowUp(`${kind} ${detail}`)) return;
    add("followup", {
      id: text(action.action_id || action.id, `followup-${index + 1}`),
      title: friendlyActionLabel(kind),
      detail: friendlyDetail(detail, "Generated follow-up work is queued."),
      statusLabel: titleCase(text(action.status, "planned")),
      tone: "warn",
    });
  });

  return [buckets.running, buckets.ready, buckets.waiting, buckets.followup];
}

function selectedSchedulerAction(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["nextAction"] {
  const selected = record(snapshot?.scheduler.selected_action);
  const decision = list(snapshot?.scheduler.decision_queue).map(record)[0] || {};
  const selectedReasons = list(selected.reasons).map((item) => text(item, "")).filter(Boolean).join("; ");
  const rawRole = text(selected.role || decision.role || model.operations.nextUnlock.role, "scheduler");
  const rawAction = firstText([
    selected.action_kind,
    selected.action_type,
    decision.action_kind,
    decision.action_type,
    model.operations.nextUnlock.action,
    model.operations.nextUnlock.title,
  ], "work");
  const detail = friendlyDetail(
    firstText([selectedReasons, selected.reason, decision.reason, model.operations.nextUnlock.detail], ""),
    "No scheduler decision is recorded yet.",
  );
  return {
    title: friendlyActionLabel(rawAction, rawRole),
    role: roleLabel(rawRole),
    status: model.banner.badge,
    detail,
    tone: model.banner.tone,
  };
}

function humanInput(snapshot: ProjectSnapshot | null): AutomationViewModel["humanInput"] {
  const human = record(snapshot?.human_input);
  const requests = number(human.pending_requests);
  const records = number(human.unhandled_records) + number(human.unhandled_inbox);
  const outbound = number(human.outbound_records);
  const total = requests + records;
  return {
    total,
    requests,
    records,
    outbound,
    badge: total ? `${total} pending` : "Clear",
    detail: total ? text(human.summary, `${requests} request${requests === 1 ? "" : "s"}, ${records} record${records === 1 ? "" : "s"}.`) : "No pending input.",
    tone: total ? "warn" : "good",
  };
}

function validationRepair(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["validationRepair"] {
  const rows: AutomationValidationRow[] = [];
  const add = (row: AutomationValidationRow) => {
    if (rows.some((item) => item.title === row.title && item.detail === row.detail && item.status === row.status)) return;
    rows.push(row);
  };

  list(snapshot?.validation_repair.active_validation_jobs).map(record).forEach((job, index) => {
    add({
      id: text(job.job_id || job.gate_id, `validation-${index + 1}`),
      title: "Validation running",
      status: titleCase(text(job.status, "running")),
      detail: friendlyDetail(firstText([job.command, job.summary, job.reason], ""), "Validation job is active."),
      tone: "info",
    });
  });

  list(snapshot?.validation_repair.repair_actions).map(record).forEach((action, index) => {
    const kind = text(action.kind || action.action_kind, "repair");
    add({
      id: text(action.action_id || action.id, `repair-${index + 1}`),
      title: friendlyActionLabel(kind),
      status: titleCase(text(action.status, "planned")),
      detail: friendlyDetail(text(action.reason || action.summary, ""), "Repair/setup follow-up is queued."),
      tone: "warn",
    });
  });

  model.executionDag.nodes
    .filter((node) => {
      const displayStatus = displayStatusKind(node.statusKind, node);
      if (displayStatus === "done" || displayStatus === "skipped" || displayStatus === "waiting") return false;
      return node.phase === "validate" || node.phase === "repair" || isGeneratedFollowUp(`${node.actionType} ${node.canonicalActionType} ${node.detail}`);
    })
    .slice(0, 8)
    .forEach((node) => {
      const displayStatus = displayStatusKind(node.statusKind, node);
      add({
        id: node.id,
        title: nodeTitle(node, node.actionType, node.ownerRole),
        status: statusLabel(displayStatus),
        detail: friendlyNodeDetail(node, "Validation or repair work is recorded.", displayStatus),
        tone: toneForDisplayStatus(displayStatus),
      });
    });

  const activeCount = rows.filter((row) => row.status.toLowerCase().includes("running")).length;
  const followUpCount = rows.filter((row) => row.tone === "warn").length;
  return {
    summary: rows.length
      ? `${activeCount} running / ${followUpCount} follow-up`
      : "Clear",
    tone: followUpCount ? "warn" : activeCount ? "info" : "quiet",
    rows: rows.slice(0, 6),
  };
}

function toneForStatus(status: string): RunTone {
  const normalized = normalize(status);
  if (["done", "completed", "complete", "passed", "pass", "applied", "ready", "accepted"].includes(normalized)) return "good";
  if (["running", "scoping", "building", "active", "queued", "in_progress", "planned", "selected", "recorded"].includes(normalized)) return "info";
  if (["blocked", "failed", "critical", "critical_stop", "error", "conflict"].includes(normalized)) return normalized === "critical_stop" ? "critical" : "warn";
  return "quiet";
}

function calmToneForStatus(status: string): RunTone {
  const normalized = normalize(status);
  if (["blocked", "skipped", "deferred", "waiting", "serialized_role_path", "parallel_not_worth_it"].includes(normalized)) return "quiet";
  return toneForStatus(status);
}

function percentLabel(value: unknown): string {
  const parsed = number(value);
  if (!parsed) return "n/a";
  return `${Math.round(Math.min(1, Math.max(0, parsed)) * 100)}%`;
}

function statusBand(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["statusBand"] {
  const automation = record(snapshot?.controls.automation);
  const runner = record(automation.runner);
  const runnerDetail = record(runner.runner);
  const lastCycle = record(snapshot?.scheduler.last_cycle);
  const supervisor = text(runner.supervisor || automation.supervisor, "portable-subprocess");
  const supervisorLabel = supervisor === "portable-subprocess" ? "fallback subprocess" : supervisor;
  const runnerState = text(automation.state || model.automation.state, "stopped");
  const ready = bool(automation.ready) || model.controls.startAutomation.enabled || model.isRunning;
  const readinessReason = friendlyDetail(
    text(automation.ready_reason || snapshot?.controls.start_automation_reason || automation.message || model.automation.message, ""),
    "No readiness reason recorded.",
  );
  const mode = firstText([
    snapshot?.scheduler.mode,
    record(snapshot?.scheduler.parallelization_summary).display_mode_label,
    record(snapshot?.scheduler.scheduler_parallel_dry_run).display_mode_label,
  ], "Planning preview");
  const rawPid = text(runnerDetail.pid || automation.pid, "");
  const pid = rawPid && rawPid !== "0" ? rawPid : "";
  const facts: AutomationStatusFact[] = [
    {
      id: "runner",
      label: "Runner",
      value: titleCase(runnerState),
      detail: model.automation.message,
      tone: model.banner.tone,
    },
    {
      id: "supervisor",
      label: "Supervisor",
      value: supervisorLabel,
      detail: bool(runner.launchd_available) ? "launchd is available on this host." : "Portable subprocess fallback is available.",
      tone: "info",
    },
    {
      id: "last-cycle",
      label: "Last scheduler cycle",
      value: compactTime(lastCycle.occurred_at || snapshot?.setup.task?.last_updated || snapshot?.setup.snapshot_generated_at),
      detail: firstText([lastCycle.event_type, lastCycle.status], "No scheduler cycle event recorded."),
      tone: lastCycle.occurred_at ? "info" : "quiet",
    },
    {
      id: "mode",
      label: "Mode",
      value: mode,
      detail: snapshot?.scheduler.scheduler_fallback_used
        ? "Scheduler used deterministic fallback selection for this snapshot."
        : "Scheduler is using typed read-model telemetry.",
      tone: snapshot?.scheduler.scheduler_fallback_used ? "quiet" : "info",
    },
    {
      id: "readiness",
      label: "Readiness",
      value: ready ? "Ready" : titleCase(runnerState === "running" ? "running" : "not ready"),
      detail: readinessReason,
      tone: ready || runnerState === "running" ? "good" : "quiet",
    },
    {
      id: "pid",
      label: "Process",
      value: pid || "no pid",
      detail: text(automation.runner_state_path || runner.runner_state_path, "No runner state path recorded."),
      tone: pid ? "info" : "quiet",
    },
  ];
  return {
    targetName: snapshot?.target.name || "No target",
    targetPath: snapshot?.target.path || "",
    headline: model.banner.badge,
    detail: model.banner.subheadline,
    runnerState: titleCase(runnerState),
    supervisor: supervisorLabel,
    readinessReason,
    tone: model.banner.tone,
    facts,
  };
}

function progressLaneFromNode(node: RunDagNode, displayStatus: AutomationNodeStatus): AutomationProgressLaneId {
  if (node.phase === "integrate") return "integration";
  if (displayStatus === "building" || displayStatus === "scoping" || displayStatus === "running") return "running";
  if (displayStatus === "done" || displayStatus === "skipped") return "completed";
  if (displayStatus === "followup" || displayStatus === "failed" || node.phase === "repair" || isGeneratedFollowUp(`${node.actionType} ${node.canonicalActionType} ${node.detail}`)) return "repair";
  if (displayStatus === "waiting") return "deferred";
  return "ready";
}

function progressLanes(model: RunModel): AutomationProgressLane[] {
  const lanes: Record<AutomationProgressLaneId, AutomationProgressLane> = {
    ready: { id: "ready", label: "Ready", count: 0, tone: "info", tooltip: "DAG work that can run next.", items: [] },
    running: { id: "running", label: "Running", count: 0, tone: "info", tooltip: "Runtime work currently active.", items: [] },
    repair: { id: "repair", label: "Repair", count: 0, tone: "warn", tooltip: "Generated repair, setup, fixture, split, or reframe work.", items: [] },
    integration: { id: "integration", label: "Integration", count: 0, tone: "info", tooltip: "Patches and integration DAG nodes handled serially.", items: [] },
    completed: { id: "completed", label: "Completed", count: 0, tone: "good", tooltip: "Recently completed DAG work.", items: [] },
    deferred: { id: "deferred", label: "Deferred", count: 0, tone: "quiet", tooltip: "Work waiting on dependencies, evidence, or scheduled follow-up.", items: [] },
  };
  for (const node of model.executionDag.nodes) {
    if (isInternalProgressNode(node)) continue;
    const displayStatus = displayStatusKind(node.statusKind, node);
    const laneId = progressLaneFromNode(node, displayStatus);
    const lane = lanes[laneId];
    lane.count += 1;
    if (lane.items.length < 4) {
      lane.items.push({
        id: node.id,
        title: nodeTitle(node, node.actionType, node.ownerRole),
        detail: friendlyNodeDetail(node, node.ticketId || "Automation work", displayStatus),
        statusLabel: statusLabel(displayStatus),
        tone: toneForDisplayStatus(displayStatus),
      });
    }
  }
  if (model.operations.integrationBacklog.queuedCount && lanes.integration.items.length < 4) {
    lanes.integration.count += model.operations.integrationBacklog.queuedCount;
    lanes.integration.items.push({
      id: "integration-backlog",
      title: "Serialized patch queue",
      detail: model.operations.integrationBacklog.summary,
      statusLabel: "Queued",
      tone: model.operations.integrationBacklog.tone,
    });
  }
  return [lanes.ready, lanes.running, lanes.repair, lanes.integration, lanes.completed, lanes.deferred];
}

function candidateDetail(candidate: Record<string, unknown>): string {
  const blockers = list(candidate.blockers).map(record).map((item) => firstText([item.reason, item.reason_kind], "")).filter(Boolean);
  const reasons = list(candidate.reasons).map((item) => text(item, "")).filter(Boolean);
  return friendlyDetail(
    firstText([candidate.skipped_reason, candidate.reason, reasons.join("; "), blockers.join("; ")], ""),
    "Scheduler candidate is recorded.",
  );
}

function candidateOwnership(candidate: Record<string, unknown>): string {
  const payload = record(candidate.payload);
  const leases = [...list(candidate.required_leases), ...list(payload.required_leases)].map(record);
  const leaseLabels = leases.map((lease) => firstText([lease.path, lease.scope_node_id, lease.name, lease.lease_id], "")).filter(Boolean);
  const pathLabels = [
    ...list(candidate.paths),
    ...list(candidate.ownership_paths),
    ...list(candidate.node_ids),
    ...list(payload.paths),
  ].map((item) => text(item, "")).filter(Boolean);
  return [...leaseLabels, ...pathLabels].slice(0, 3).join(", ") || "Ownership evidence not recorded";
}

function candidateFanout(candidate: Record<string, unknown>): number {
  const payload = record(candidate.payload);
  return number(candidate.fanout) ||
    number(candidate.max_fanout) ||
    number(candidate.item_count) ||
    number(payload.candidate_count) ||
    list(candidate.node_ids).length ||
    list(payload.node_ids).length ||
    1;
}

function schedulerCandidateRow(candidate: Record<string, unknown>, fallbackId: string, fallbackStatus = "candidate"): AutomationSchedulerCandidateRow {
  const role = text(candidate.owner_role || candidate.role, "scheduler");
  const action = firstText([candidate.action_kind, candidate.action_type, candidate.kind], "work");
  const rawStatus = text(candidate.state || candidate.status, fallbackStatus);
  const status = ["blocked", "failed", "skipped", "cancelled", "canceled"].includes(normalize(rawStatus)) && fallbackStatus !== "selected"
    ? "not selected"
    : rawStatus;
  return {
    id: firstText([candidate.candidate_id, candidate.execution_group_id, candidate.action_id, candidate.task_id], fallbackId),
    label: friendlyActionLabel(action, role),
    status: titleCase(status),
    detail: candidateDetail(candidate),
    fanout: candidateFanout(candidate),
    owner: roleLabel(role),
    ownership: candidateOwnership(candidate),
    confidence: percentLabel(candidate.score || candidate.confidence),
    tone: normalize(status) === "not_selected" ? "quiet" : calmToneForStatus(status),
  };
}

function schedulerDecision(snapshot: ProjectSnapshot | null, model: RunModel, nextAction: AutomationViewModel["nextAction"]): AutomationViewModel["schedulerDecision"] {
  const selected = record(snapshot?.scheduler.selected_action);
  const candidates = list(snapshot?.scheduler.candidates).map(record);
  const selectedRow = Object.keys(selected).length
    ? schedulerCandidateRow(selected, "selected-scheduler-candidate", "selected")
    : {
        id: "selected-scheduler-candidate",
        label: nextAction.title,
        status: nextAction.status,
        detail: nextAction.detail,
        fanout: 1,
        owner: nextAction.role,
        ownership: "Current action",
        confidence: "n/a",
        tone: nextAction.tone,
      };
  const skipped = [
    ...list(snapshot?.scheduler.skipped_candidates).map(record),
    ...list(snapshot?.scheduler.blocked_candidates).map(record),
  ];
  const alternatives = [...candidates, ...skipped]
    .filter((candidate) => schedulerCandidateRow(candidate, "candidate").id !== selectedRow.id)
    .map((candidate, index) => schedulerCandidateRow(candidate, `candidate-${index + 1}`, text(candidate.state || candidate.status, "not selected")))
    .slice(0, 5);
  const dryRun = record(snapshot?.scheduler.scheduler_parallel_dry_run);
  const summary = record(snapshot?.scheduler.parallelization_summary || dryRun.parallelization_summary);
  const why = record(snapshot?.scheduler.why_not_parallel || dryRun.why_not_parallel);
  const reasonGroups = list(why.reason_groups).map(record).slice(0, 4).map((group, index) => ({
    id: text(group.reason_kind || group.label, `reason-${index + 1}`),
    label: titleCase(text(group.label || group.reason_kind, "Parallel telemetry")),
    count: number(group.count),
    detail: friendlyDetail(text(group.next_action || group.summary, ""), "Parallelism is adjusted to current evidence."),
    tone: "quiet" as RunTone,
  }));
  const blockedCount = number(why.blocked_candidate_count || summary.blocked_candidate_count);
  return {
    selected: selectedRow,
    alternatives,
    fanout: `${number(summary.group_count) || list(dryRun.proposed_execution_groups).length || 0} proposed / ${model.executionDag.parallel.activeGroups} active`,
    ownership: selectedRow.ownership,
    confidence: selectedRow.confidence,
    whyParallel: {
      status: titleCase(text(why.status, blockedCount ? "reduced fanout" : "nominal")),
      summary: friendlyDetail(text(why.summary, ""), blockedCount ? `${blockedCount} candidate${blockedCount === 1 ? "" : "s"} need more ownership evidence before parallel launch.` : "No reduced-fanout telemetry recorded."),
      next: friendlyDetail(firstText([why.top_next_action, summary.next_parallel_improvement], ""), "Continue selected work; gather more ownership evidence when useful."),
      reasons: reasonGroups,
      tone: blockedCount ? "info" : "good",
    },
  };
}

function receiptRequired(receipt: Record<string, unknown>): boolean {
  const payload = record(receipt.payload);
  if (receipt.required !== undefined) return bool(receipt.required);
  if (payload.required !== undefined) return bool(payload.required);
  return true;
}

function evidencePath(receipt: Record<string, unknown>): string {
  const payload = record(receipt.payload);
  return firstText([receipt.evidence_path, receipt.log_artifact_id, receipt.report_path, payload.evidence_path, payload.log_path], "");
}

function validationEvidence(snapshot: ProjectSnapshot | null): AutomationViewModel["validationEvidence"] {
  const validation = record(snapshot?.validation_repair.validation);
  const counts = record(validation.counts);
  const rows: AutomationEvidenceRow[] = [];
  const add = (row: AutomationEvidenceRow) => {
    if (rows.some((item) => item.id === row.id || (item.label === row.label && item.detail === row.detail))) return;
    rows.push(row);
  };
  list(snapshot?.validation_repair.validation_receipts).map(record).forEach((receipt, index) => {
    const required = receiptRequired(receipt);
    const status = text(receipt.status, "recorded");
    add({
      id: text(receipt.receipt_id || receipt.validation_id || receipt.run_id, `receipt-${index + 1}`),
      label: firstText([receipt.kind, receipt.command], "Validation receipt"),
      status: titleCase(status),
      scope: required ? "required" : "advisory",
      detail: friendlyDetail(firstText([receipt.command, receipt.summary, receipt.reason], ""), "Validation receipt is recorded."),
      evidencePath: evidencePath(receipt),
      repairWork: "",
      tone: required && ["failed", "fail", "error"].includes(normalize(status)) ? "warn" : toneForStatus(status),
    });
  });
  list(snapshot?.validation_repair.active_validation_jobs).map(record).forEach((job, index) => {
    add({
      id: text(job.job_id || job.gate_id, `active-validation-${index + 1}`),
      label: "Running check",
      status: titleCase(text(job.status, "running")),
      scope: bool(record(job.payload).required ?? true) ? "required" : "advisory",
      detail: friendlyDetail(firstText([job.command, job.summary, job.reason], ""), "Validation job is active."),
      evidencePath: "",
      repairWork: "",
      tone: "info",
    });
  });
  list(validation.items).map(record).forEach((item, index) => {
    add({
      id: text(item.id || item.command, `validation-item-${index + 1}`),
      label: firstText([item.name, item.kind, item.command, item.text], "Validation"),
      status: titleCase(text(item.status, "recorded")),
      scope: bool(item.required ?? true) ? "required" : "advisory",
      detail: friendlyDetail(firstText([item.detail, item.summary, item.text], ""), "Validation item is recorded."),
      evidencePath: evidencePath(item),
      repairWork: "",
      tone: toneForStatus(text(item.status, "recorded")),
    });
  });
  const repairActions = list(snapshot?.validation_repair.repair_actions).map(record);
  repairActions.slice(0, 4).forEach((action, index) => {
    add({
      id: text(action.action_id || action.id, `repair-action-${index + 1}`),
      label: friendlyActionLabel(text(action.kind || action.action_kind, "repair")),
      status: titleCase(text(action.status, "planned")),
      scope: "required",
      detail: friendlyDetail(text(action.reason || action.summary, ""), "Repair work has been created."),
      evidencePath: "",
      repairWork: friendlyActionLabel(text(action.kind || action.action_kind, "repair")),
      tone: "warn",
    });
  });
  const requiredFailedFromRows = rows.filter((row) => row.scope === "required" && ["fail", "failed", "error"].includes(normalize(row.status))).length;
  const advisoryFailed = rows.filter((row) => row.scope === "advisory" && ["fail", "failed", "error"].includes(normalize(row.status))).length;
  const requiredPassedFromRows = rows.filter((row) => row.scope === "required" && ["pass", "passed", "ok", "success"].includes(normalize(row.status))).length;
  const requiredFailed = requiredFailedFromRows || number(counts.fail);
  const requiredPassed = requiredPassedFromRows || number(counts.pass);
  const evidencePaths = rows.map((row) => row.evidencePath).filter(Boolean).slice(0, 6);
  return {
    summary: requiredFailed
      ? `${requiredFailed} required check${requiredFailed === 1 ? "" : "s"} need repair; automation should create follow-up work.`
      : requiredPassed
      ? `${requiredPassed} required check${requiredPassed === 1 ? "" : "s"} have evidence.`
      : "No required validation evidence recorded yet.",
    requiredFailed,
    requiredPassed,
    advisoryFailed,
    repairCreated: repairActions.length,
    evidencePaths,
    rows: rows.slice(0, 8),
    tone: requiredFailed ? "warn" : requiredPassed ? "good" : "quiet",
  };
}

function queueIntegration(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["queueIntegration"] {
  const activeGroups = list(snapshot?.dag.active_execution_groups).map(record);
  const activeReadWorkers = list(snapshot?.dag.active_read_only_workers).map(record);
  const activeWriteWorkers = list(snapshot?.dag.active_write_workers).map(record);
  const activeLeases = list(snapshot?.dag.active_leases).map(record);
  const conflictingLeases = list(snapshot?.dag.conflicting_leases).map(record);
  const queuedPatches = list(snapshot?.dag.queued_worker_patches).map(record);
  const conflicts = list(snapshot?.dag.write_worker_conflicts).map(record);
  const preflight = record(snapshot?.dag.worker_patch_integration_preflight);
  const staleBase = number(preflight.stale_base_count);
  const workers = activeReadWorkers.length + activeWriteWorkers.length;
  const metrics = [
    { id: "groups", label: "Active groups", value: String(activeGroups.length), detail: "Execution groups currently running.", tone: activeGroups.length ? "info" as RunTone : "quiet" as RunTone },
    { id: "leases", label: "Leases", value: String(activeLeases.length), detail: conflictingLeases.length ? `${conflictingLeases.length} lease overlap${conflictingLeases.length === 1 ? "" : "s"} being serialized.` : "No active lease overlap.", tone: conflictingLeases.length ? "warn" as RunTone : "good" as RunTone },
    { id: "workers", label: "Worker runs", value: String(workers), detail: `${activeReadWorkers.length} read-only / ${activeWriteWorkers.length} write.`, tone: workers ? "info" as RunTone : "quiet" as RunTone },
    { id: "patches", label: "Queued patches", value: String(model.operations.integrationBacklog.queuedCount || queuedPatches.length), detail: model.operations.integrationBacklog.summary, tone: model.operations.integrationBacklog.tone },
    { id: "serial", label: "Integration", value: String(model.operations.integrationBacklog.safeCount), detail: "Repository integration remains serialized.", tone: model.operations.integrationBacklog.safeCount ? "info" as RunTone : "quiet" as RunTone },
    { id: "recovery", label: "Lease recovery", value: staleBase ? String(staleBase) : "auto", detail: staleBase ? `${staleBase} stale-base patch${staleBase === 1 ? "" : "es"} need reconciliation.` : "Snapshots expire stale leases before planning.", tone: staleBase ? "warn" as RunTone : "good" as RunTone },
  ];
  const rows: AutomationQueueRow[] = [];
  const add = (row: AutomationQueueRow) => {
    if (rows.some((item) => item.id === row.id && item.label === row.label)) return;
    rows.push(row);
  };
  activeGroups.slice(0, 3).forEach((group, index) => add({
    id: text(group.execution_group_id || group.group_id, `group-${index + 1}`),
    label: firstText([group.display_mode_label, group.mode], "Execution group"),
    status: titleCase(text(group.status, "running")),
    detail: friendlyDetail(firstText([group.human_summary, group.display_reason, group.reason], ""), "Execution group is active."),
    meta: `${number(group.item_count) || list(group.items).length || 0} item${(number(group.item_count) || list(group.items).length) === 1 ? "" : "s"}`,
    tone: toneForStatus(text(group.status, "running")),
  }));
  [...activeReadWorkers, ...activeWriteWorkers].slice(0, 4).forEach((worker, index) => {
    const workerStatus = firstText([worker.display_status, worker.runtime_status, worker.status], "running");
    add({
      id: text(worker.worker_id || worker.run_id, `worker-${index + 1}`),
      label: firstText([worker.mode, worker.role, worker.owner_role], "Worker"),
      status: titleCase(workerStatus),
      detail: friendlyDetail(firstText([worker.status_label, worker.failure_reason, worker.context_pack_id, worker.report_artifact_id], ""), "Worker run is active."),
      meta: firstText([worker.execution_group_id, worker.task_id, worker.ticket_id], ""),
      tone: toneForStatus(workerStatus),
    });
  });
  queuedPatches.slice(0, 4).forEach((patch, index) => add({
    id: text(patch.patch_id || patch.manifest_path || patch.patch_path, `patch-${index + 1}`),
    label: "Queued patch",
    status: titleCase(text(patch.status, "queued")),
    detail: friendlyDetail(firstText([patch.summary, patch.patch_path, patch.manifest_path], ""), "Patch is queued for serialized integration."),
    meta: firstText([patch.worker_id, patch.execution_group_id], ""),
    tone: toneForStatus(text(patch.status, "queued")),
  }));
  conflicts.slice(0, 3).forEach((conflict, index) => add({
    id: text(conflict.conflict_id || conflict.patch_id, `conflict-${index + 1}`),
    label: "Integration follow-up",
    status: titleCase(text(conflict.status || conflict.reason_kind, "review")),
    detail: friendlyDetail(firstText([conflict.reason, conflict.detail, conflict.reason_kind], ""), "Integrator will serialize or defer this patch."),
    meta: firstText([conflict.patch_id, conflict.execution_group_id], ""),
    tone: "warn",
  }));
  for (const recordItem of list(preflight.records).map(record).slice(0, 3)) {
    add({
      id: text(recordItem.preflight_id || recordItem.patch_id, `preflight-${rows.length + 1}`),
      label: "Preflight",
      status: titleCase(text(recordItem.status, "recorded")),
      detail: friendlyDetail(firstText([recordItem.integration_resolution_detail, recordItem.reason_kind], ""), "Patch preflight is recorded."),
      meta: text(recordItem.patch_id, ""),
      tone: calmToneForStatus(text(recordItem.status, "recorded")),
    });
  }
  if (!rows.length) {
    add({
      id: "queue-empty",
      label: "Queue",
      status: "Clear",
      detail: "No active worker group, lease conflict, or queued patch is recorded.",
      meta: "",
      tone: "quiet",
    });
  }
  return { metrics, rows: rows.slice(0, 8) };
}

function notification(snapshot: ProjectSnapshot | null): AutomationViewModel["notification"] {
  const human = record(snapshot?.human_input);
  const notifier = record(human.notifier_status);
  const mode = text(human.notification_mode || notifier.mode, "file_only");
  const pending = number(human.pending_requests);
  const unresolved = number(human.unhandled_records) + number(human.unhandled_inbox);
  const outbound = number(human.outbound_records);
  const total = pending + unresolved;
  return {
    pending,
    unresolved,
    outbound,
    mode: mode.replace(/_/g, " "),
    status: titleCase(text(notifier.status, mode === "disabled" ? "disabled" : mode === "file_only" ? "file only" : "enabled")),
    detail: text(notifier.detail, total ? "Human input is pending; independent automation can continue." : "No pending human input."),
    tone: total ? "warn" : mode === "disabled" ? "quiet" : "good",
  };
}

function timelineCategory(event: Record<string, unknown>): AutomationTimelineCategory {
  const haystack = `${event.event_type ?? ""} ${event.actor_role ?? ""} ${event.phase ?? ""} ${event.kind ?? ""}`.toLowerCase();
  if (/human|input|message|inbox/.test(haystack)) return "human";
  if (/notif|apprise|outbound/.test(haystack)) return "notification";
  if (/valid|check|receipt/.test(haystack)) return "validation";
  if (/integrat|patch|merge/.test(haystack)) return "integration";
  if (/worker|builder|hardener|planner/.test(haystack)) return "worker";
  return "scheduler";
}

function timeline(snapshot: ProjectSnapshot | null): AutomationTimelineEvent[] {
  const rows: AutomationTimelineEvent[] = [];
  const add = (row: AutomationTimelineEvent) => {
    if (rows.some((item) => item.id === row.id && item.title === row.title)) return;
    rows.push(row);
  };
  [
    ...list(snapshot?.dag.recent_execution_groups).map(record),
    ...list(snapshot?.dag.recently_completed_execution_groups).map(record),
    ...list(snapshot?.dag.completed_worker_reports).map(record),
    ...list(snapshot?.dag.recent_outcomes).map(record),
  ].forEach((event, index) => {
    const category = timelineCategory(event);
    const status = text(event.status || event.result || event.disposition_status, "recorded");
    add({
      id: text(event.event_id || event.outcome_id || event.execution_group_id || event.run_id, `event-${index + 1}`),
      category,
      title: titleCase(firstText([event.event_type, event.title, event.kind, event.mode], "Runtime event")),
      status: titleCase(status),
      time: compactTime(event.occurred_at || event.finished_at || event.started_at || event.created_at, ""),
      detail: friendlyDetail(firstText([event.summary, event.disposition_summary, event.reason, event.command], ""), "Runtime event recorded."),
      tone: calmToneForStatus(status),
    });
  });
  list(snapshot?.validation_repair.validation_receipts).map(record).slice(0, 4).forEach((receipt, index) => {
    const status = text(receipt.status, "recorded");
    add({
      id: text(receipt.receipt_id || receipt.validation_id, `timeline-receipt-${index + 1}`),
      category: "validation",
      title: titleCase(firstText([receipt.kind, receipt.command], "Validation receipt")),
      status: titleCase(status),
      time: compactTime(receipt.finished_at || receipt.started_at || receipt.recorded_at, ""),
      detail: friendlyDetail(firstText([receipt.command, receipt.summary], ""), "Validation evidence recorded."),
      tone: toneForStatus(status),
    });
  });
  if (snapshot?.human_input && (number(snapshot.human_input.pending_requests) || number(snapshot.human_input.unhandled_inbox))) {
    add({
      id: "timeline-human-input",
      category: "human",
      title: "Human input",
      status: "Pending",
      time: "",
      detail: text(snapshot.human_input.summary, "Human input is pending; independent scheduler work may continue."),
      tone: "warn",
    });
  }
  return rows.slice(0, 12);
}

function meaningfulActivity(row: AutomationActivityRow): boolean {
  const title = normalize(row.title);
  const detail = normalize(row.detail);
  const status = normalize(row.status);
  if (!title && !detail) return false;
  if (title === "outcome" && (!detail || detail === "recorded") && status === "recorded") return false;
  if (title === "recorded" && !detail) return false;
  return true;
}

function activityLog(snapshot: ProjectSnapshot | null, model: RunModel): AutomationActivityRow[] {
  const rows: AutomationActivityRow[] = [];
  const add = (row: AutomationActivityRow) => {
    if (!meaningfulActivity(row)) return;
    if (rows.some((item) => item.title === row.title && item.detail === row.detail && item.status === row.status)) return;
    rows.push(row);
  };

  [
    ...list(snapshot?.dag.recent_execution_groups).map(record),
    ...list(snapshot?.dag.recently_completed_execution_groups).map(record),
    ...list(snapshot?.dag.completed_worker_reports).map(record),
    ...list(snapshot?.dag.recent_outcomes).map(record),
    ...list(snapshot?.validation_repair.validation_receipts).map(record),
  ].forEach((item, index) => {
    const title = firstText([item.title, item.disposition_label, item.mode, item.kind, item.action_kind, item.label], "outcome");
    const status = text(item.status || item.disposition_status || item.result, "recorded");
    const detail = friendlyDetail(firstText([item.summary, item.disposition_summary, item.reason, item.report_path, item.command], ""), "");
    add({
      id: text(item.outcome_id || item.execution_group_id || item.report_id || item.receipt_id || item.run_id, `activity-${index + 1}`),
      title: titleCase(title),
      status: titleCase(status),
      detail,
      tone: toneForStatus(status),
    });
  });

  model.operations.concurrencyWaves
    .filter((wave) => ["completed", "integration"].includes(wave.kind))
    .forEach((wave) => {
      add({
        id: wave.id,
        title: titleCase(wave.mode || wave.label),
        status: titleCase(wave.status),
        detail: friendlyDetail(wave.detail, ""),
        tone: wave.tone,
      });
    });

  return rows.slice(0, 6);
}

export function buildAutomationViewModel(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel {
  const progress = ticketProgress(snapshot, model);
  const next = selectedSchedulerAction(snapshot, model);
  return {
    statusBand: statusBand(snapshot, model),
    nextAction: next,
    progressLanes: progressLanes(model),
    schedulerDecision: schedulerDecision(snapshot, model, next),
    validationEvidence: validationEvidence(snapshot),
    queueIntegration: queueIntegration(snapshot, model),
    notification: notification(snapshot),
    timeline: timeline(snapshot),
    dag: dagGraph(model),
    ticketProgress: progress,
    ticketGraph: buildTicketGraph(progress),
    queueBuckets: queueBuckets(snapshot, model, progress),
    validationRepair: validationRepair(snapshot, model),
    humanInput: humanInput(snapshot),
    activityLog: activityLog(snapshot, model),
  };
}
