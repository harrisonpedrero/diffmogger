import type {
  ProjectSnapshot,
} from "./api/backend";
import type {
  RunDagNode,
  RunDagStatusKind,
  RunModel,
  RunProgressColumnId,
  RunTone,
} from "./runModel";

export type AutomationPipelineColumnId = "plan" | "build" | "review" | "validate" | "integrate" | "done";
export type AutomationQueueBucketId = "ready" | "running" | "waiting" | "followup" | "done";
export type AutomationNodeStatus = "ready" | "running" | "waiting" | "followup" | "done" | "failed" | "skipped";
export type AutomationTicketStatus = "pending" | "in_progress" | "candidate_done" | "done" | "blocked";

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
  evidenceCount: number;
  commitCount: number;
};

export type AutomationViewModel = {
  nextAction: {
    title: string;
    role: string;
    status: string;
    detail: string;
    tone: RunTone;
  };
  dag: {
    columns: Array<{ id: AutomationPipelineColumnId; label: string }>;
    rows: AutomationPipelineRow[];
    nodes: AutomationPipelineNode[];
    defaultSelectedNodeId: string;
    summary: string;
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

const PIPELINE_COLUMNS: Array<{ id: AutomationPipelineColumnId; label: string; source: RunProgressColumnId }> = [
  { id: "plan", label: "Plan", source: "scope" },
  { id: "build", label: "Build", source: "build" },
  { id: "review", label: "Review", source: "review" },
  { id: "validate", label: "Validate", source: "validate" },
  { id: "integrate", label: "Integrate", source: "integrate" },
  { id: "done", label: "Done", source: "done" },
];

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
  if (status === "running" || status === "ready") return "info";
  if (status === "failed" || status === "followup") return "warn";
  return "quiet";
}

function displayStatusKind(statusKind: RunDagStatusKind, node?: RunDagNode): AutomationNodeStatus {
  if (statusKind === "completed") return "done";
  if (statusKind === "running") return "running";
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

function isInternalDoneNode(node: RunDagNode): boolean {
  const action = normalize(node.actionType || node.canonicalActionType);
  return node.statusKind === "completed" && ["blocker", "ticket", "orchestrate", "decompose"].includes(action);
}

function usefulScope(node?: RunDagNode): string {
  const scope = text(node?.ownershipScope, "");
  return scope && scope !== "No ownership scope recorded" ? scope : "";
}

function friendlyNodeDetail(node: RunDagNode | undefined, fallback: string, status?: AutomationNodeStatus): string {
  if (!node) return friendlyDetail(fallback, "Work is recorded.");
  const displayStatus = status ?? displayStatusKind(node.statusKind, node);
  if (node.blockerReason) return friendlyDetail(node.blockerReason, "Work is waiting.");
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

function emptyPipelineCells(): Record<AutomationPipelineColumnId, AutomationPipelineNode | null> {
  return {
    plan: null,
    build: null,
    review: null,
    validate: null,
    integrate: null,
    done: null,
  };
}

function pipelineRowSummary(cells: Record<AutomationPipelineColumnId, AutomationPipelineNode | null>, fallback: string): string {
  const nodes = PIPELINE_COLUMNS.map((column) => cells[column.id]).filter((node): node is AutomationPipelineNode => Boolean(node));
  const active = nodes.find((node) => node.status === "running") ||
    nodes.find((node) => node.status === "ready") ||
    nodes.find((node) => node.status === "followup") ||
    nodes.find((node) => node.status === "waiting");
  if (active) return `${active.title} is ${active.statusLabel.toLowerCase()}.`;
  const done = nodes.filter((node) => node.status === "done").length;
  if (done) return `${done} step${done === 1 ? "" : "s"} done.`;
  return fallback;
}

function ticketRows(snapshot: ProjectSnapshot | null): Array<{ id: string; label: string; summary: string }> {
  return list(snapshot?.tickets.remaining || snapshot?.tickets.items)
    .map(record)
    .map((ticket, index) => ({
      id: text(ticket.id || ticket.ticket_id, `ticket-${index + 1}`),
      label: text(ticket.id || ticket.ticket_id, `Ticket ${index + 1}`),
      summary: text(ticket.summary || ticket.title, "Ticket is queued."),
    }))
    .filter((ticket) => ticket.id)
    .slice(0, 12);
}

function ticketStatus(value: unknown): AutomationTicketStatus {
  const normalized = normalize(value);
  if (normalized === "in_progress") return "in_progress";
  if (normalized === "candidate_done") return "candidate_done";
  if (normalized === "done") return "done";
  if (normalized === "blocked") return "blocked";
  return "pending";
}

function ticketStatusLabel(status: AutomationTicketStatus): string {
  if (status === "in_progress") return "In progress";
  if (status === "candidate_done") return "Ready for hardening";
  if (status === "blocked") return "Needs attention";
  return titleCase(status);
}

function ticketTone(status: AutomationTicketStatus): RunTone {
  if (status === "done") return "good";
  if (status === "in_progress" || status === "candidate_done") return "info";
  if (status === "blocked") return "warn";
  return "quiet";
}

function ticketNumericId(id: string): number {
  const match = id.match(/(\d+)$/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function isTicketLikeId(value: string): boolean {
  const normalized = normalize(value);
  return Boolean(value) && !normalized.startsWith("task:") && !normalized.startsWith("dag_node:") && normalized !== "automation";
}

function ticketRecordId(ticket: Record<string, unknown>, fallback: string): string {
  return text(ticket.id || ticket.ticket_id || ticket.task_id, fallback);
}

function inferredTicketStatus(ticketId: string, model: RunModel): AutomationTicketStatus {
  const nodes = model.executionDag.nodes.filter((node) => node.ticketId === ticketId);
  if (!nodes.length) return "pending";
  const statuses = nodes.map((node) => displayStatusKind(node.statusKind, node));
  if (statuses.some((status) => status === "followup" || status === "failed")) return "blocked";
  if (statuses.some((status) => status === "running")) return "in_progress";
  if (statuses.some((status) => status === "ready")) {
    return statuses.some((status) => status === "done") ? "in_progress" : "pending";
  }
  const progressNodes = nodes.filter((node) => progressColumnForAction(node.actionType || node.canonicalActionType));
  if (progressNodes.length && progressNodes.every((node) => ["done", "skipped"].includes(displayStatusKind(node.statusKind, node)))) {
    return "done";
  }
  return statuses.some((status) => status === "done") ? "in_progress" : "pending";
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
  if (status === "in_progress") return "Implementation active";
  if (status === "done") return "Completed";
  if (status === "blocked") return "Follow-up needed";
  return "Queued";
}

function ticketProgress(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["ticketProgress"] {
  const sourceById = new Map<string, Record<string, unknown>>();
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
    const status = ticket.status === undefined || ticket.status === null || text(ticket.status, "") === ""
      ? inferredTicketStatus(id, model)
      : ticketStatus(ticket.status);
    const evidence = list(ticket.evidence).map((item) => text(item, "")).filter(Boolean);
    const commits = list(ticket.related_commits).map((item) => text(item, "")).filter(Boolean);
    const dependsOn = list(ticket.depends_on).map((item) => text(item, "")).filter(Boolean);
    return {
      id,
      summary: text(ticket.summary || ticket.title, "Ticket is queued."),
      status,
      statusLabel: ticketStatusLabel(status),
      tone: ticketTone(status),
      stage: stageForTicket(id, status, model),
      detail: evidence[0] || text(ticket.blocker, "") || (dependsOn.length ? `Depends on ${dependsOn.slice(0, 3).join(", ")}` : "No evidence recorded yet."),
      dependsOn,
      evidenceCount: evidence.length,
      commitCount: commits.length,
    };
  }).filter((ticket) => ticket.id);

  rows.sort((first, second) => {
    return ticketNumericId(first.id) - ticketNumericId(second.id) || first.id.localeCompare(second.id);
  });

  const statuses: AutomationTicketStatus[] = ["in_progress", "candidate_done", "blocked", "pending", "done"];
  const counts = statuses.map((status) => ({
    id: status,
    label: ticketStatusLabel(status),
    count: rows.filter((row) => row.status === status).length,
    tone: ticketTone(status),
  }));
  const done = counts.find((item) => item.id === "done")?.count ?? 0;
  const candidateDone = counts.find((item) => item.id === "candidate_done")?.count ?? 0;
  const active = counts.find((item) => item.id === "in_progress")?.count ?? 0;
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

function pipelineRows(snapshot: ProjectSnapshot | null, model: RunModel): AutomationViewModel["dag"] {
  const nodeById = new Map(model.executionDag.nodes.map((node) => [node.id, node]));
  const rows: AutomationPipelineRow[] = model.operations.progressRows.map((progressRow) => {
    const cells = emptyPipelineCells();
    for (const column of PIPELINE_COLUMNS) {
      const cell = progressRow.cells[column.source];
      if (!cell) continue;
      const node = nodeById.get(cell.nodeId);
      const displayStatus = displayStatusKind(cell.statusKind, node);
      const detail = friendlyNodeDetail(node, cell.detail, displayStatus);
      cells[column.id] = {
        id: cell.nodeId,
        title: nodeTitle(node, column.source, cell.role),
        phase: column.id,
        status: displayStatus,
        statusLabel: statusLabel(displayStatus),
        tone: toneForDisplayStatus(displayStatus),
        role: roleLabel(node?.ownerRole || cell.role),
        ticketId: progressRow.taskId,
        detail,
        scope: usefulScope(node),
      };
    }
    return {
      id: progressRow.taskId,
      label: progressRow.label || progressRow.taskId,
      summary: pipelineRowSummary(cells, "DAG work is recorded for this row."),
      cells,
    };
  });

  const existingRows = new Set(rows.map((row) => row.id));
  for (const ticket of ticketRows(snapshot)) {
    if (existingRows.has(ticket.id)) continue;
    rows.push({
      id: ticket.id,
      label: ticket.label,
      summary: ticket.summary,
      cells: emptyPipelineCells(),
    });
  }

  const nodes = rows.flatMap((row) => PIPELINE_COLUMNS.map((column) => row.cells[column.id]).filter((node): node is AutomationPipelineNode => Boolean(node)));
  const defaultSelectedNode = nodes.find((node) => node.status === "running") ||
    nodes.find((node) => node.status === "ready") ||
    nodes.find((node) => node.status === "followup") ||
    nodes.find((node) => node.status === "waiting") ||
    nodes[0];

  const summaryParts = [
    `${model.executionDag.summary.running} running`,
    `${model.executionDag.summary.ready} ready`,
    `${model.executionDag.summary.completed} done`,
    `${model.executionDag.summary.blocked + model.executionDag.summary.failed + model.executionDag.summary.pending} waiting or follow-up`,
  ];

  return {
    columns: PIPELINE_COLUMNS.map(({ id, label }) => ({ id, label })),
    rows,
    nodes,
    defaultSelectedNodeId: defaultSelectedNode?.id || "",
    summary: model.executionDag.hasData ? summaryParts.join(" / ") : "No DAG work has been recorded yet.",
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
    followup: { id: "followup", label: "Needs attention", count: 0, tone: "warn", items: [] },
    done: { id: "done", label: "Recently done", count: 0, tone: "good", items: [] },
  };
  const add = (bucketId: AutomationQueueBucketId, item: AutomationQueueBucket["items"][number]) => {
    buckets[bucketId].count += 1;
    if (buckets[bucketId].items.length < 3) buckets[bucketId].items.push(item);
  };

  for (const node of model.executionDag.nodes) {
    if (isInternalDoneNode(node)) continue;
    const displayStatus = displayStatusKind(node.statusKind, node);
    const generated = isGeneratedFollowUp(`${node.actionType} ${node.canonicalActionType} ${node.detail} ${node.blockerReason}`);
    if (displayStatus === "running") add("running", queueItemFromNode(node));
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
  if (["running", "active", "queued", "in_progress", "planned", "selected", "recorded"].includes(normalized)) return "info";
  if (["blocked", "failed", "critical", "critical_stop", "error", "conflict"].includes(normalized)) return normalized === "critical_stop" ? "critical" : "warn";
  return "quiet";
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
  return {
    nextAction: selectedSchedulerAction(snapshot, model),
    dag: pipelineRows(snapshot, model),
    ticketProgress: progress,
    queueBuckets: queueBuckets(snapshot, model, progress),
    validationRepair: validationRepair(snapshot, model),
    humanInput: humanInput(snapshot),
    activityLog: activityLog(snapshot, model),
  };
}
