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
  };
  progress: {
    headline: string;
    empty: boolean;
    items: HomeProgressItem[];
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

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "Not recorded"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return 0;
}

function toneForStatus(status: string): HomeTone {
  if (status === "ACTIVE") return "good";
  if (status === "RUNNING" || status.includes("RUNNING")) return "info";
  if (status.includes("PENDING") || status.includes("BLOCKED")) return "warn";
  if (status.includes("CRITICAL")) return "critical";
  return "quiet";
}

function humanizeStatus(status: string): string {
  return status.replace(/_/g, " ").toLowerCase();
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

function queueTotals(snapshot: ProjectSnapshot): Record<string, unknown> {
  return record(snapshot.run.queue?.totals);
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
    number(queueTotals(snapshot).deferred),
    number(snapshot.run.progress?.deferred_queue_depth),
    snapshot.home.deferred_patches,
  );
}

function queuedTotal(snapshot: ProjectSnapshot): number {
  return number(queueTotals(snapshot).queued ?? snapshot.home.queued_patches);
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
  return text(record(snapshot.run.task?.integration_safety).status, "not_recorded");
}

function isSafetyFailure(snapshot: ProjectSnapshot): boolean {
  return safetyStatus(snapshot) === "fail";
}

function isUnconfigured(snapshot: ProjectSnapshot): boolean {
  return !snapshot.target.is_diffmogger_project || !snapshot.target.automation_task_exists;
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
    status === "CRITICAL_STOP" ||
    hasValidationFailure(snapshot) ||
    isSafetyFailure(snapshot)
  );
}

function primaryForSnapshot(snapshot: ProjectSnapshot): HomeAction {
  const status = text(snapshot.run.task?.status ?? snapshot.home.automation_status, "");
  const active = activeRoleRun(snapshot);

  if (isUnconfigured(snapshot)) {
    return { label: "Open setup", kind: "navigate", route: "Brief" };
  }
  if (isUserBlocked(snapshot, status)) {
    return { label: "Inbox", kind: "navigate", route: "Inbox" };
  }
  if (isEnvironmentBlocked(snapshot, status)) {
    return { label: "Review", kind: "navigate", route: "Review" };
  }
  if (text(active.status, "") === "running") {
    return { label: "Run", kind: "navigate", route: "Run" };
  }
  if (!hasRunHistory(snapshot)) {
    return { label: "Run", kind: "navigate", route: "Run" };
  }
  return { label: "Run", kind: "navigate", route: "Run" };
}

function bannerForSnapshot(snapshot: ProjectSnapshot): Pick<
  HomeModel,
  "headline" | "subheadline" | "statusLabel" | "statusTone"
> {
  const status = text(snapshot.run.task?.status ?? snapshot.home.automation_status, "");
  const active = activeRoleRun(snapshot);

  if (isUnconfigured(snapshot)) {
    return {
      headline: "Setup incomplete",
      subheadline: "Complete setup to write target-local files.",
      statusLabel: "Setup needed",
      statusTone: "warn",
    };
  }
  if (isUserBlocked(snapshot, status)) {
    return {
      headline: "Input needed",
      subheadline: "A target-local inbox item is waiting.",
      statusLabel: "Input needed",
      statusTone: "warn",
    };
  }
  if (status === "CRITICAL_STOP") {
    return {
      headline: "Critical stop recorded",
      subheadline: "Review the recorded stop condition before allowing another run.",
      statusLabel: "Critical stop",
      statusTone: "critical",
    };
  }
  if (isEnvironmentBlocked(snapshot, status)) {
    return {
      headline: "Blocked",
      subheadline: "Safety, validation, or environment state needs attention before the next run.",
      statusLabel: humanizeStatus(status) || "Blocked",
      statusTone: "warn",
    };
  }
  if (text(active.status, "") === "running") {
    const role = text(active.role, "run");
    return {
      headline: `${role} lane is running`,
      subheadline: "Watch the current run and avoid overlapping local changes until it finishes.",
      statusLabel: "Running",
      statusTone: "info",
    };
  }
  if (!hasRunHistory(snapshot)) {
    return {
      headline: "Ready",
      subheadline: "No runs recorded yet.",
      statusLabel: "Ready",
      statusTone: "good",
    };
  }
  return {
    headline: "Ready",
    subheadline: text(snapshot.home.next_action, "Review the next action and run the next local lane when ready."),
    statusLabel: status && status !== "UNKNOWN" ? status.replace(/_/g, " ") : "Ready",
    statusTone: toneForStatus(status || "ACTIVE"),
  };
}

function metricRow(snapshot: ProjectSnapshot): HomeMetric[] {
  const cycles = number(snapshot.run.conveyor?.cycles);
  const nextRun = text(snapshot.brief.dashboard_state?.next_run_at, "Not configured");
  return [
    { label: "Cycles", value: cycles, tone: cycles ? "info" : "quiet" },
    { label: "Applied patches", value: acceptedTotal(snapshot), tone: "good" },
    { label: "Queued patches", value: queuedTotal(snapshot), tone: queuedTotal(snapshot) ? "warn" : "quiet" },
    { label: "Deferred patches", value: deferredTotal(snapshot), tone: deferredTotal(snapshot) ? "warn" : "quiet" },
    {
      label: "Input pending",
      value: pendingHuman(snapshot) + unhandledInbox(snapshot),
      tone: pendingHuman(snapshot) + unhandledInbox(snapshot) ? "warn" : "good",
    },
    { label: "Next run", value: nextRun, tone: nextRun === "Not configured" ? "quiet" : "info" },
  ];
}

function safetyItems(snapshot: ProjectSnapshot): HomeSafetyItem[] {
  const integrationSafety = record(snapshot.run.task?.integration_safety);
  const validation = record(snapshot.run.task?.validation);
  const validationCounts = record(validation.counts);
  const git = snapshot.run.git ?? {};
  const firstReview = firstReviewStatus(snapshot);
  const blockers: string[] = [];
  if (hasValidationFailure(snapshot)) blockers.push(`${number(validationCounts.fail)} validation failure(s)`);
  if (isSafetyFailure(snapshot)) blockers.push("integration safety failed");
  if (text(snapshot.run.task?.status, "") === "BLOCKED_ON_ENVIRONMENT") blockers.push("environment blocked");
  if (text(snapshot.run.task?.status, "") === "CRITICAL_STOP") blockers.push("critical stop");

  return [
    {
      label: "Safety check",
      value: safetyStatus(snapshot).replace(/_/g, " "),
      tone: safetyStatus(snapshot) === "pass" ? "good" : safetyStatus(snapshot) === "fail" ? "critical" : "warn",
      detail: text(integrationSafety.summary, "No safety check result is recorded yet."),
    },
    {
      label: "Validation state",
      value: `${number(validationCounts.pass)} pass / ${number(validationCounts.fail)} fail`,
      tone: hasValidationFailure(snapshot) ? "critical" : number(validationCounts.pending) ? "warn" : "good",
      detail: text(validation.summary, "No validation results recorded yet."),
    },
    {
      label: "Git state",
      value: `${number(git.dirty_count)} dirty file(s)`,
      tone: number(git.dirty_count) ? "warn" : "good",
      detail: `Branch ${text(git.branch, "unknown")}.`,
    },
    {
      label: "Blockers",
      value: blockers.length ? `${blockers.length} blocker(s)` : "None recorded",
      tone: blockers.length ? "warn" : "good",
      detail: blockers.length
        ? blockers.join(", ")
        : `Review is ${firstReview.replace(/_/g, " ")}; no environment blocker is recorded.`,
    },
  ];
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
    title: text(plan.recommendation, snapshot.home.next_action || "Choose the next local action."),
    reason: text(plan.why, "This recommendation is derived from the backend activity snapshot."),
    action: {
      label: route === "Inbox" ? "Inbox" : route === "Run" ? "Run" : "Review",
      kind: "navigate",
      route,
    },
  };
}

export function buildHomeModel(snapshot: ProjectSnapshot | null): HomeModel {
  if (!snapshot) {
    return {
      projectName: "No project selected",
      statusLabel: "No target",
      statusTone: "quiet",
      headline: "Choose a project",
      subheadline: "Select a target folder to load state.",
      primaryAction: { label: "Choose project", kind: "choose-project" },
      secondaryActions: [],
      metrics: [
        { label: "Cycles", value: "N/A", tone: "quiet" },
        { label: "Applied patches", value: "N/A", tone: "quiet" },
        { label: "Queued patches", value: "N/A", tone: "quiet" },
        { label: "Deferred patches", value: "N/A", tone: "quiet" },
        { label: "Input pending", value: "N/A", tone: "quiet" },
        { label: "Next run", value: "N/A", tone: "quiet" },
      ],
      recommendation: {
        title: "Choose a project folder",
        reason: "A target snapshot is required.",
        action: { label: "Choose project", kind: "choose-project" },
      },
      safety: {
        headline: "No target selected",
        items: [],
      },
      progress: {
        headline: "Recent activity",
        empty: true,
        items: [],
      },
      humanBridge: {
        pending: 0,
        unhandled: 0,
        outbound: 0,
        latestStatus: "No target selected",
        action: { label: "Inbox", kind: "disabled", route: "Inbox" },
      },
      isUnconfigured: false,
      hasNoRuns: true,
    };
  }

  const banner = bannerForSnapshot(snapshot);
  const progress = progressItems(snapshot);
  const noRuns = !hasRunHistory(snapshot);
  const primaryAction = primaryForSnapshot(snapshot);

  return {
    projectName: snapshot.home.title || snapshot.target.name,
    ...banner,
    primaryAction,
    secondaryActions: [
      { label: "Refresh", kind: "refresh" },
      { label: "Activity", kind: "navigate", route: "Observatory" },
      { label: "Review", kind: "navigate", route: "Review" },
    ],
    metrics: metricRow(snapshot),
    recommendation: recommendation(snapshot),
    safety: {
      headline: isEnvironmentBlocked(snapshot, text(snapshot.run.task?.status, ""))
        ? "Attention needed before running"
        : "Checks",
      items: safetyItems(snapshot),
    },
    progress: {
      headline: "Recent activity",
      empty: progress.length === 0,
      items: progress,
    },
    humanBridge: {
      pending: pendingHuman(snapshot),
      unhandled: unhandledInbox(snapshot),
      outbound: number(snapshot.run.human?.outbound_records),
      latestStatus:
        pendingHuman(snapshot) || unhandledInbox(snapshot)
          ? "Input pending"
          : "No input pending",
      action: { label: "Inbox", kind: "navigate", route: "Inbox" },
    },
    isUnconfigured: isUnconfigured(snapshot),
    hasNoRuns: noRuns,
  };
}
