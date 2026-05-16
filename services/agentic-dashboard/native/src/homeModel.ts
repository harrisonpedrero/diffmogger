import type { ProjectSnapshot } from "./api/backend";

export type HomeActionKind = "choose-project" | "navigate" | "refresh" | "disabled";
export type HomeTone = "good" | "warn" | "critical" | "info" | "quiet";
export type HomeRoute =
  | "Home"
  | "Brief"
  | "Run"
  | "Observatory"
  | "Inbox"
  | "Review"
  | "Advanced";

export type HomeAction = {
  label: string;
  kind: HomeActionKind;
  route?: HomeRoute;
};

export type HomeMetric = {
  label: string;
  value: string | number;
  tone: HomeTone;
};

export type HomeSafetyItem = {
  label: string;
  value: string;
  tone: HomeTone;
  detail: string;
};

export type HomeProgressItem = {
  title: string;
  detail: string;
  meta: string;
  tone: HomeTone;
};

export type HomeConveyorLane = {
  role: string;
  label: string;
  status: string;
  badge: string;
  tone: HomeTone;
  reason: string;
  counts: {
    queued: number;
    applied: number;
    deferred: number;
    failed: number;
  };
};

export type HomeSafetyRow = {
  label: string;
  status: string;
  summary: string;
  source: string;
  tone: HomeTone;
  action: HomeAction;
};

export type HomeQueueRow = {
  id: string;
  title: string;
  status: string;
  lane: string;
  lastChange: string;
  blocker: string;
  source: string;
  tone: HomeTone;
};

export type HomeEventRow = {
  id: string;
  time: string;
  type: string;
  lane: string;
  message: string;
  artifact: string;
  status: string;
  tone: HomeTone;
};

export type HomeModel = {
  projectName: string;
  statusLabel: string;
  statusTone: HomeTone;
  headline: string;
  subheadline: string;
  primaryAction: HomeAction;
  secondaryActions: HomeAction[];
  metrics: HomeMetric[];
  recommendation: {
    title: string;
    reason: string;
    action: HomeAction;
  };
  safety: {
    headline: string;
    items: HomeSafetyItem[];
    rows: HomeSafetyRow[];
  };
  progress: {
    headline: string;
    empty: boolean;
    items: HomeProgressItem[];
  };
  conveyor: {
    lanes: HomeConveyorLane[];
    activeLane: string;
    nextLane: string;
    summary: string;
    cycles: number;
  };
  queueLedger: {
    rows: HomeQueueRow[];
    totals: Record<string, number>;
    emptyMessage: string;
  };
  eventLedger: {
    rows: HomeEventRow[];
    emptyMessage: string;
  };
  humanBridge: {
    pending: number;
    unhandled: number;
    outbound: number;
    latestStatus: string;
    action: HomeAction;
  };
  isUnconfigured: boolean;
  hasNoRuns: boolean;
};

const LANE_ORDER = ["planner", "builder", "hardener", "integrator"];

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "Not recorded"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function displayCopy(value: string): string {
  return value.replace(/`([^`\n]+)`/g, "$1");
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return 0;
}

function bool(value: unknown): boolean {
  return value === true;
}

function titleCase(value: string): string {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}`)
    .join(" ");
}

function readableStatus(value: unknown, fallback = "unknown"): string {
  return text(value, fallback).replace(/_/g, " ").toLowerCase();
}

function rawStatus(snapshot: ProjectSnapshot): string {
  return text(snapshot.run.task?.status ?? snapshot.home.automation_status, "UNKNOWN").toUpperCase();
}

function toneForStatus(status: string): HomeTone {
  if (status.includes("CRITICAL")) return "critical";
  if (status.includes("PENDING") || status.includes("BLOCKED") || status.includes("STALE")) return "warn";
  if (status.includes("RUNNING")) return "info";
  if (status === "ACTIVE" || status === "STOPPED" || status === "READY") return "good";
  return "quiet";
}

function toneForResult(value: unknown): HomeTone {
  const status = text(value, "").toLowerCase();
  if (["pass", "passed", "ok", "ready", "reviewed", "clean", "complete", "completed", "none"].includes(status)) return "good";
  if (["fail", "failed", "error", "critical", "critical_stop"].includes(status)) return "critical";
  if (["warn", "warning", "blocked", "pending", "missing", "not_run", "unknown", "not_recorded"].includes(status)) return "warn";
  if (["running", "active", "info", "queued", "deferred", "draft"].includes(status)) return "info";
  return "quiet";
}

function itemByLabel(items: unknown[], label: string): Record<string, unknown> {
  return (
    items
      .map(record)
      .find((item) => text(item.label, "").toLowerCase() === label.toLowerCase()) ?? {}
  );
}

function firstReviewStatus(snapshot: ProjectSnapshot): string {
  return text(snapshot.run.first_review?.status, "unknown");
}

function actionPlan(snapshot: ProjectSnapshot): Record<string, unknown> {
  return record(snapshot.run.scorecard?.action_plan);
}

function queueTotals(snapshot: ProjectSnapshot): Record<string, number> {
  const raw = record(snapshot.run.queue?.totals);
  return {
    queued: number(raw.queued ?? snapshot.home.queued_patches),
    deferred: number(raw.deferred ?? snapshot.home.deferred_patches),
    applied: number(raw.applied),
    failed: number(raw.failed),
    skipped: number(raw.skipped),
  };
}

function activeRoleRun(snapshot: ProjectSnapshot): Record<string, unknown> {
  return record(snapshot.run.conveyor?.active_role_run);
}

function pendingHuman(snapshot: ProjectSnapshot): number {
  return number(snapshot.run.human?.pending_requests ?? snapshot.home.pending_human_requests);
}

function unhandledInbox(snapshot: ProjectSnapshot): number {
  return number(snapshot.run.human?.unhandled_inbox ?? snapshot.home.unhandled_inbox);
}

function acceptedTotal(snapshot: ProjectSnapshot): number {
  const progressAccepted = number(snapshot.run.progress?.accepted_total);
  if (progressAccepted) return progressAccepted;
  const accepted = itemByLabel(list(snapshot.run.scorecard?.items), "Accepted patches");
  return number(accepted.value);
}

function deferredTotal(snapshot: ProjectSnapshot): number {
  return Math.max(
    queueTotals(snapshot).deferred,
    number(snapshot.run.progress?.deferred_queue_depth),
    snapshot.home.deferred_patches,
  );
}

function queuedTotal(snapshot: ProjectSnapshot): number {
  return queueTotals(snapshot).queued;
}

function roleQueueCounts(snapshot: ProjectSnapshot, role: string): Record<string, unknown> {
  const countsByRole = record(snapshot.run.queue?.counts_by_role);
  return record(countsByRole[role]);
}

function hasRunHistory(snapshot: ProjectSnapshot): boolean {
  const recentProgress = text(
    snapshot.run.progress_recent ?? snapshot.run.progress?.recent_activity,
    "",
  );
  return Boolean(
    number(snapshot.run.conveyor?.cycles) ||
      acceptedTotal(snapshot) ||
      list(snapshot.run.queue?.recent_outcomes).length ||
      list(snapshot.run.conveyor?.history).length ||
      (recentProgress && recentProgress !== "No multi-role activity recorded yet."),
  );
}

function hasValidationFailure(snapshot: ProjectSnapshot): boolean {
  const counts = record(record(snapshot.run.task?.validation).counts);
  return number(counts.fail) > 0;
}

function safetyStatus(snapshot: ProjectSnapshot): string {
  return text(record(snapshot.run.task?.integration_safety).status, "pending");
}

function isSafetyFailure(snapshot: ProjectSnapshot): boolean {
  return safetyStatus(snapshot).toLowerCase() === "fail";
}

function isUnconfigured(snapshot: ProjectSnapshot): boolean {
  return !snapshot.target.is_diffmogger_project || !snapshot.target.automation_task_exists;
}

function isRunning(snapshot: ProjectSnapshot, status: string): boolean {
  const controls = record(snapshot.run.controls);
  const automation = record(snapshot.run.automation);
  const active = activeRoleRun(snapshot);
  return (
    bool(controls.is_running) ||
    text(automation.state, "").toLowerCase() === "running" ||
    text(active.status, "").toLowerCase() === "running" ||
    status.includes("RUNNING")
  );
}

function isUserBlocked(snapshot: ProjectSnapshot, status: string): boolean {
  return (
    pendingHuman(snapshot) > 0 ||
    unhandledInbox(snapshot) > 0 ||
    status === "ACTIVE_WITH_PENDING_USER_INPUT" ||
    status === "BLOCKED_ON_USER"
  );
}

function isEnvironmentBlocked(snapshot: ProjectSnapshot, status: string): boolean {
  return (
    status === "BLOCKED_ON_ENVIRONMENT" ||
    hasValidationFailure(snapshot) ||
    isSafetyFailure(snapshot) ||
    list(snapshot.run.environment_blockers).length > 0
  );
}

function operationalTitle(snapshot: ProjectSnapshot | null): string {
  if (!snapshot) return "No target";
  const status = rawStatus(snapshot);
  if (status.includes("STALE")) return "Stale";
  if (status === "CRITICAL_STOP") return "Critical stop";
  if (isUserBlocked(snapshot, status)) return "User input";
  if (isEnvironmentBlocked(snapshot, status)) return "Env blocked";
  if (isRunning(snapshot, status)) return "Running";
  if (isUnconfigured(snapshot) || status === "UNKNOWN") return "Unknown";
  return "Ready";
}

function primaryForTitle(title: string): HomeAction {
  if (title === "No target") return { label: "Choose project", kind: "choose-project" };
  if (title === "User input") return { label: "Open Inbox", kind: "navigate", route: "Inbox" };
  if (title === "Env blocked") return { label: "Open Sidecar", kind: "navigate", route: "Advanced" };
  if (title === "Critical stop") return { label: "Open Review", kind: "navigate", route: "Review" };
  if (title === "Running") return { label: "View Activity", kind: "navigate", route: "Observatory" };
  if (title === "Unknown" || title === "Stale") return { label: title === "Stale" ? "Refresh" : "Open setup", kind: title === "Stale" ? "refresh" : "navigate", route: "Brief" };
  return { label: "Start automation", kind: "navigate", route: "Run" };
}

function subtitleForSnapshot(snapshot: ProjectSnapshot | null, title: string): string {
  if (!snapshot) return "Choose a target folder or open setup to begin.";
  const plan = actionPlan(snapshot);
  const active = activeRoleRun(snapshot);
  if (title === "Unknown" && isUnconfigured(snapshot)) {
    return "Setup has not recorded a runnable automation task for this target.";
  }
  if (title === "User input") {
    const total = pendingHuman(snapshot) + unhandledInbox(snapshot);
    return `${total || "A"} human handoff${total === 1 ? "" : "s"} waiting in the target inbox.`;
  }
  if (title === "Env blocked") return "Safety, validation, or local environment state needs attention before the next run.";
  if (title === "Critical stop") return "Review the recorded stop condition before allowing another run.";
  if (title === "Running") {
    return text(active.reason ?? snapshot.run.automation?.message, `${titleCase(text(active.role, "automation"))} lane is active.`);
  }
  if (title === "Stale") return "Refresh the target before taking action.";
  if (!hasRunHistory(snapshot)) return "Target files are present. Start automation from Run.";
  return displayCopy(text(plan.recommendation, snapshot.home.next_action || "Review the next action and run the next local lane when ready."));
}

function bannerForSnapshot(snapshot: ProjectSnapshot | null): Pick<
  HomeModel,
  "headline" | "subheadline" | "statusLabel" | "statusTone" | "primaryAction" | "secondaryActions"
> {
  const title = operationalTitle(snapshot);
  const status = snapshot ? rawStatus(snapshot) : "NO_TARGET";
  const tone =
    title === "No target" || title === "Unknown"
      ? "quiet"
      : title === "Critical stop"
        ? "critical"
        : title === "User input" || title === "Env blocked" || title === "Stale"
          ? "warn"
          : title === "Running"
            ? "info"
            : toneForStatus(status) === "quiet"
              ? "good"
              : toneForStatus(status);

  return {
    headline: title,
    subheadline: subtitleForSnapshot(snapshot, title),
    statusLabel: title,
    statusTone: tone,
    primaryAction: primaryForTitle(title),
    secondaryActions: snapshot
      ? [
          { label: "Refresh", kind: "refresh" },
          { label: "Run", kind: "navigate", route: "Run" },
          { label: "Review", kind: "navigate", route: "Review" },
        ]
      : [{ label: "Open setup", kind: "navigate", route: "Brief" }],
  };
}

function metricRow(snapshot: ProjectSnapshot | null): HomeMetric[] {
  if (!snapshot) {
    return [
      { label: "Cycles", value: "N/A", tone: "quiet" },
      { label: "Landed", value: "N/A", tone: "quiet" },
      { label: "Queued", value: "N/A", tone: "quiet" },
      { label: "Deferred", value: "N/A", tone: "quiet" },
      { label: "Human", value: "N/A", tone: "quiet" },
      { label: "Dirty", value: "N/A", tone: "quiet" },
    ];
  }
  const dirty = number(snapshot.run.git?.dirty_count);
  const human = pendingHuman(snapshot) + unhandledInbox(snapshot);
  return [
    { label: "Cycles", value: number(snapshot.run.conveyor?.cycles), tone: number(snapshot.run.conveyor?.cycles) ? "info" : "quiet" },
    { label: "Landed", value: acceptedTotal(snapshot), tone: acceptedTotal(snapshot) ? "good" : "quiet" },
    { label: "Queued", value: queuedTotal(snapshot), tone: queuedTotal(snapshot) ? "warn" : "quiet" },
    { label: "Deferred", value: deferredTotal(snapshot), tone: deferredTotal(snapshot) ? "warn" : "quiet" },
    { label: "Human", value: human, tone: human ? "warn" : "good" },
    { label: "Dirty", value: dirty, tone: dirty ? "warn" : "good" },
  ];
}

function safetyRows(snapshot: ProjectSnapshot | null): HomeSafetyRow[] {
  if (!snapshot) {
    return [
      {
        label: "Target",
        status: "not selected",
        summary: "Choose a project folder to load safety gates.",
        source: "project picker",
        tone: "quiet",
        action: { label: "Choose", kind: "choose-project" },
      },
    ];
  }

  const integrationSafety = record(snapshot.run.task?.integration_safety);
  const validation = record(snapshot.run.task?.validation);
  const validationCounts = record(validation.counts);
  const git = snapshot.run.git ?? {};
  const envBlockers = list(snapshot.run.environment_blockers).map(record);
  const humanTotal = pendingHuman(snapshot) + unhandledInbox(snapshot);
  const firstReview = firstReviewStatus(snapshot);
  const validationStatus = hasValidationFailure(snapshot)
    ? "fail"
    : number(validationCounts.pending)
      ? "pending"
      : number(validationCounts.pass)
        ? "pass"
        : "not recorded";

  return [
    {
      label: "Integration safety",
      status: readableStatus(safetyStatus(snapshot), "pending"),
      summary: text(integrationSafety.summary, "Integration-safety check has not run yet."),
      source: "run.task.integration_safety",
      tone: toneForResult(safetyStatus(snapshot)),
      action: { label: "Run check", kind: "navigate", route: "Run" },
    },
    {
      label: "Validation",
      status: `${number(validationCounts.pass)} pass / ${number(validationCounts.fail)} fail`,
      summary: text(validation.summary, "No validation results recorded yet."),
      source: "run.task.validation",
      tone: toneForResult(validationStatus),
      action: { label: "Review", kind: "navigate", route: "Review" },
    },
    {
      label: "Git state",
      status: `${number(git.dirty_count)} dirty`,
      summary: `Branch ${text(git.branch, "unknown")}.`,
      source: "run.git",
      tone: number(git.dirty_count) ? "warn" : "good",
      action: { label: "Activity", kind: "navigate", route: "Observatory" },
    },
    {
      label: "Environment",
      status: envBlockers.length ? `${envBlockers.length} blocker(s)` : "clear",
      summary: envBlockers.length
        ? envBlockers.map((item) => text(item.name, "Environment blocker")).join(", ")
        : "No environment blocker is recorded.",
      source: "run.environment_blockers",
      tone: envBlockers.length ? "warn" : "good",
      action: { label: "Sidecar", kind: "navigate", route: "Advanced" },
    },
    {
      label: "Human input",
      status: humanTotal ? `${humanTotal} waiting` : "clear",
      summary: humanTotal ? "Manual decisions or next-run notes are waiting." : "No human handoff is pending.",
      source: "run.human",
      tone: humanTotal ? "warn" : "good",
      action: { label: "Bridge", kind: "navigate", route: "Inbox" },
    },
    {
      label: "Review bundle",
      status: readableStatus(firstReview, "unknown"),
      summary: `First review status is ${readableStatus(firstReview, "unknown")}.`,
      source: "run.first_review",
      tone: toneForResult(firstReview),
      action: { label: "Review", kind: "navigate", route: "Review" },
    },
  ];
}

function safetyItems(snapshot: ProjectSnapshot | null): HomeSafetyItem[] {
  return safetyRows(snapshot).map((row) => ({
    label: row.label,
    value: row.status,
    tone: row.tone,
    detail: row.summary,
  }));
}

function roleStatusTone(status: string): HomeTone {
  const raw = status.toLowerCase();
  if (raw.includes("fail") || raw.includes("critical")) return "critical";
  if (raw.includes("block") || raw.includes("defer")) return "warn";
  if (raw.includes("running") || raw.includes("next")) return "info";
  if (raw.includes("accept") || raw.includes("complete") || raw.includes("done")) return "good";
  return "quiet";
}

function conveyorModel(snapshot: ProjectSnapshot | null): HomeModel["conveyor"] {
  if (!snapshot) {
    return {
      lanes: LANE_ORDER.map((role) => ({
        role,
        label: titleCase(role),
        status: "unavailable",
        badge: "no target",
        tone: "quiet",
        reason: "Choose a target to load lane state.",
        counts: { queued: 0, applied: 0, deferred: 0, failed: 0 },
      })),
      activeLane: "",
      nextLane: "",
      summary: "No target selected.",
      cycles: 0,
    };
  }

  const rawRoles = list(snapshot.run.conveyor?.roles).map(record);
  const active = activeRoleRun(snapshot);
  const activeRole = text(active.role, "").toLowerCase();
  const planLane = text(actionPlan(snapshot).lane, "").toLowerCase();
  const history = list(snapshot.run.conveyor?.history).map(record);

  const lanes = LANE_ORDER.map((role) => {
    const fromSnapshot = rawRoles.find((item) => text(item.role, "").toLowerCase() === role) ?? {};
    const latest = [...history].reverse().find((item) => text(item.role, "").toLowerCase() === role) ?? {};
    const counts = { ...record(fromSnapshot.counts), ...roleQueueCounts(snapshot, role) };
    const derivedStatus =
      text(fromSnapshot.status, "") ||
      (activeRole === role ? "running" : planLane === role ? "next" : text(latest.status, "standby"));
    return {
      role,
      label: titleCase(role),
      status: derivedStatus,
      badge: text(fromSnapshot.badge, derivedStatus),
      tone: roleStatusTone(derivedStatus),
      reason: text(fromSnapshot.reason ?? latest.reason, activeRole === role ? text(active.reason, "Lane is active.") : "Awaiting DAG scheduler decision."),
      counts: {
        queued: number(counts.queued),
        applied: number(counts.applied),
        deferred: number(counts.deferred),
        failed: number(counts.failed),
      },
    };
  });

  const activeLane = activeRole ? titleCase(activeRole) : "";
  const nextLane = lanes.find((lane) => lane.status.toLowerCase() === "next")?.label ?? (planLane ? titleCase(planLane) : "");

  return {
    lanes,
    activeLane,
    nextLane,
    summary: activeLane
      ? `${activeLane} lane is active.`
      : nextLane
        ? `${nextLane} is the next recommended lane.`
        : "No active lane recorded.",
    cycles: number(snapshot.run.conveyor?.cycles),
  };
}

function progressItems(snapshot: ProjectSnapshot): HomeProgressItem[] {
  const commits = list(snapshot.run.git?.commits).map(record).slice(0, 3);
  if (commits.length) {
    return commits.map((commit) => ({
      title: text(commit.subject, "Commit"),
      detail: text(commit.summary, "Recent commit."),
      meta: `${text(commit.hash, "")} ${text(commit.time, "")}`.trim(),
      tone: "good",
    }));
  }

  const outcomes = list(snapshot.run.queue?.recent_outcomes).map(record).slice(0, 3);
  if (outcomes.length) {
    return outcomes.map((item) => ({
      title: `${text(item.role, "role")} ${text(item.status, "updated")}`,
      detail: text(item.summary, "No summary recorded."),
      meta: text(item.timestamp ?? item.created_at, "No timestamp"),
      tone: text(item.status, "") === "failed" ? "critical" : "info",
    }));
  }

  const history = list(snapshot.run.conveyor?.history).map(record).slice(-3).reverse();
  return history.map((item) => ({
    title: `${text(item.role, "role")} ${text(item.status, "completed")}`,
    detail: text(item.reason, "No reason recorded."),
    meta: text(item.completed_at ?? item.started_at, "No timestamp"),
    tone: item.progress_success === false ? "warn" : "info",
  }));
}

function recommendation(snapshot: ProjectSnapshot): HomeModel["recommendation"] {
  const plan = actionPlan(snapshot);
  const lane = text(plan.lane, "Run");
  const route: HomeRoute =
    lane === "human"
      ? "Inbox"
      : lane === "integrator" || lane === "builder" || lane === "planner" || lane === "hardener"
        ? "Run"
        : "Review";
  return {
    title: displayCopy(text(plan.recommendation, snapshot.home.next_action || "Choose the next local action.")),
    reason: displayCopy(text(plan.why, "This recommendation is derived from the backend activity snapshot.")),
    action: {
      label: route === "Inbox" ? "Open Inbox" : route === "Run" ? "Open Run" : "Open Review",
      kind: "navigate",
      route,
    },
  };
}

function queueRowFromRecord(item: Record<string, unknown>, index: number): HomeQueueRow {
  const id = text(item.ticketId ?? item.ticket_id ?? item.id ?? item.run_id, `QUEUE-${index + 1}`);
  const status = text(item.status ?? item.state ?? item.result ?? (item.deferral_reason ? "deferred" : "queued"), "queued");
  const title = text(item.title ?? item.summary ?? item.reason ?? item.subject, id);
  return {
    id,
    title,
    status: readableStatus(status),
    lane: titleCase(text(item.lane ?? item.role ?? item.next_lane, "unassigned")),
    lastChange: text(item.last_updated ?? item.timestamp ?? item.created_at ?? item.finished_at, "not recorded"),
    blocker: text(item.blocker ?? item.deferral_reason ?? item.known_issue, ""),
    source: text(item.source ?? item.artifact ?? item.path ?? item.file, "snapshot"),
    tone: roleStatusTone(status),
  };
}

function queueLedger(snapshot: ProjectSnapshot | null): HomeModel["queueLedger"] {
  if (!snapshot) {
    return {
      rows: [],
      totals: {},
      emptyMessage: "Choose a target to load the queue ledger.",
    };
  }

  const rawRows = [
    ...list(snapshot.run.queue?.items),
    ...list(snapshot.run.queue?.tickets),
    ...list(snapshot.run.queue?.manifests),
    ...list(snapshot.run.queue?.deferred_backlog),
    ...list(snapshot.run.queue?.recent_outcomes),
    ...list(snapshot.run.conveyor?.decision_queue),
  ].map(record);

  const seedTickets = list(snapshot.brief.dashboard_state?.ticket_run_seed_tickets).map(record);
  const rows = [...rawRows, ...seedTickets].slice(0, 6).map(queueRowFromRecord);
  const totals = queueTotals(snapshot);

  if (!rows.length && (totals.queued || totals.deferred)) {
    rows.push({
      id: totals.queued ? "queued-patches" : "deferred-patches",
      title: totals.queued ? `${totals.queued} queued patch${totals.queued === 1 ? "" : "es"}` : `${totals.deferred} deferred patch${totals.deferred === 1 ? "" : "es"}`,
      status: totals.queued ? "queued" : "deferred",
      lane: conveyorModel(snapshot).nextLane || "Unassigned",
      lastChange: text(snapshot.run.snapshot_generated_at, "snapshot"),
      blocker: "",
      source: "run.queue.totals",
      tone: "warn",
    });
  }

  return {
    rows,
    totals,
    emptyMessage: "No queued, deferred, or ticket rows are exposed in the current snapshot.",
  };
}

function eventFromRecord(item: Record<string, unknown>, index: number, fallbackType: string): HomeEventRow {
  const status = text(item.status ?? item.state ?? item.result ?? item.level, "info");
  return {
    id: text(item.id ?? item.run_id ?? item.hash, `${fallbackType}-${index + 1}`),
    time: text(item.time ?? item.timestamp ?? item.created_at ?? item.started_at ?? item.finished_at ?? item.completed_at, "not recorded"),
    type: titleCase(text(item.type ?? item.stage ?? fallbackType, fallbackType)),
    lane: titleCase(text(item.lane ?? item.role ?? "system", "system")),
    message: text(item.message ?? item.summary ?? item.reason ?? item.subject ?? item.text, "No message recorded."),
    artifact: text(item.artifact ?? item.path ?? item.file ?? item.hash, ""),
    status: readableStatus(status, "info"),
    tone: toneForResult(status),
  };
}

function eventLedger(snapshot: ProjectSnapshot | null): HomeModel["eventLedger"] {
  if (!snapshot) {
    return {
      rows: [],
      emptyMessage: "Choose a target to load recent events.",
    };
  }

  const rows: HomeEventRow[] = [];
  rows.push(...list(snapshot.run.logs).map(record).map((item, index) => eventFromRecord(item, index, "log")));
  const runLog = record(snapshot.run.run_log);
  rows.push(...list(runLog.lines).map(record).map((item, index) => eventFromRecord(item, index, "run log")));
  rows.push(...list(snapshot.run.conveyor?.history).map(record).map((item, index) => eventFromRecord(item, index, "conveyor")));
  rows.push(...list(snapshot.run.queue?.recent_outcomes).map(record).map((item, index) => eventFromRecord(item, index, "queue")));
  rows.push(...list(snapshot.run.git?.commits).map(record).map((item, index) => eventFromRecord(item, index, "commit")));

  return {
    rows: rows.slice(0, 8),
    emptyMessage: "No command, queue, DAG scheduler, or commit events are exposed in the current snapshot.",
  };
}

export function buildHomeModel(snapshot: ProjectSnapshot | null): HomeModel {
  const banner = bannerForSnapshot(snapshot);
  if (!snapshot) {
    return {
      projectName: "No project selected",
      ...banner,
      metrics: metricRow(null),
      recommendation: {
        title: "Choose a project folder",
        reason: "A target snapshot is required.",
        action: { label: "Choose project", kind: "choose-project" },
      },
      safety: {
        headline: "Safety",
        items: safetyItems(null),
        rows: safetyRows(null),
      },
      progress: {
        headline: "Event ledger",
        empty: true,
        items: [],
      },
      conveyor: conveyorModel(null),
      queueLedger: queueLedger(null),
      eventLedger: eventLedger(null),
      humanBridge: {
        pending: 0,
        unhandled: 0,
        outbound: 0,
        latestStatus: "No target selected",
        action: { label: "Open Inbox", kind: "disabled", route: "Inbox" },
      },
      isUnconfigured: false,
      hasNoRuns: true,
    };
  }

  const progress = progressItems(snapshot);
  const noRuns = !hasRunHistory(snapshot);

  return {
    projectName: snapshot.home.title || snapshot.target.name,
    ...banner,
    metrics: metricRow(snapshot),
    recommendation: recommendation(snapshot),
    safety: {
      headline: isEnvironmentBlocked(snapshot, rawStatus(snapshot)) ? "Gates needing attention" : "Safety",
      items: safetyItems(snapshot),
      rows: safetyRows(snapshot),
    },
    progress: {
      headline: "Event ledger",
      empty: progress.length === 0,
      items: progress,
    },
    conveyor: conveyorModel(snapshot),
    queueLedger: queueLedger(snapshot),
    eventLedger: eventLedger(snapshot),
    humanBridge: {
      pending: pendingHuman(snapshot),
      unhandled: unhandledInbox(snapshot),
      outbound: number(snapshot.run.human?.outbound_records),
      latestStatus:
        pendingHuman(snapshot) || unhandledInbox(snapshot)
          ? "Input pending"
          : "Clear",
      action: { label: "Open Inbox", kind: "navigate", route: "Inbox" },
    },
    isUnconfigured: isUnconfigured(snapshot),
    hasNoRuns: noRuns,
  };
}
