import type { ProjectSnapshot, ReviewSnapshot } from "./api/backend";

export type ReviewFreshness = "not_reviewed" | "current" | "stale";
export type ReviewMode = "live" | "outcome" | "already_reviewed" | "new_evidence";
export type ReviewTone = "good" | "warn" | "bad" | "info" | "quiet";

export type ReviewDecision = {
  mode: ReviewMode;
  tone: ReviewTone;
  title: string;
  summary: string;
  detail: string;
  freshness: ReviewFreshness;
  isLive: boolean;
  hasHumanBlocker: boolean;
  primaryAction: {
    label: string;
    enabled: boolean;
    reason: string;
  };
  exportLabel: string;
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function text(value: unknown, fallback = ""): string {
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

function sameTimestamp(left?: string, right?: string): boolean | null {
  if (!left || !right) return null;
  const leftDate = new Date(left);
  const rightDate = new Date(right);
  if (!Number.isNaN(leftDate.getTime()) && !Number.isNaN(rightDate.getTime())) {
    return leftDate.getTime() === rightDate.getTime();
  }
  return left === right;
}

export function pendingHumanCount(snapshot: ProjectSnapshot): number {
  return (
    number(snapshot.run.human?.pending_requests ?? snapshot.home.pending_human_requests) +
    number(snapshot.run.human?.unhandled_inbox ?? snapshot.home.unhandled_inbox)
  );
}

export function isAutomationLive(snapshot: ProjectSnapshot): boolean {
  const controls = record(snapshot.run.controls);
  const automation = record(snapshot.run.automation);
  const conveyor = record(snapshot.run.conveyor);
  const activeRoleRun = record(conveyor.active_role_run);
  const activeRun = record(conveyor.active_run);
  const status = text(snapshot.run.task?.status ?? snapshot.home.automation_status, "UNKNOWN").toUpperCase();
  const automationState = text(automation.state, "").toLowerCase();
  const activeRoleStatus = text(activeRoleRun.status, "").toLowerCase();
  const activeRunStatus = text(activeRun.status, "").toLowerCase();
  return (
    bool(controls.is_running) ||
    ["running", "starting", "stopping"].includes(automationState) ||
    activeRoleStatus === "running" ||
    activeRunStatus === "running" ||
    status.includes("RUNNING")
  );
}

export function reviewFreshness(snapshot: ReviewSnapshot | null): ReviewFreshness {
  if (!snapshot?.reviewed.exists) return "not_reviewed";
  if (typeof snapshot.reviewed.is_current_snapshot === "boolean") {
    return snapshot.reviewed.is_current_snapshot ? "current" : "stale";
  }
  if (snapshot.review_fingerprint && snapshot.reviewed.review_fingerprint) {
    return snapshot.review_fingerprint === snapshot.reviewed.review_fingerprint ? "current" : "stale";
  }
  const timestampMatch = sameTimestamp(snapshot.generated_at, snapshot.reviewed.snapshot_generated_at);
  if (timestampMatch === true) return "current";
  if (timestampMatch === false) return "stale";
  return "current";
}

export function reviewFreshnessLabel(value: ReviewFreshness): string {
  if (value === "current") return "Reviewed";
  if (value === "stale") return "New evidence";
  return "Pending";
}

export function buildReviewDecision(projectSnapshot: ProjectSnapshot, reviewSnapshot: ReviewSnapshot | null): ReviewDecision {
  const isLive = isAutomationLive(projectSnapshot);
  const humanCount = pendingHumanCount(projectSnapshot);
  const hasHumanBlocker = humanCount > 0;
  const freshness = reviewFreshness(reviewSnapshot);
  const rawStatus = text(projectSnapshot.run.task?.status ?? projectSnapshot.home.automation_status, "UNKNOWN").toUpperCase();
  const blocked = rawStatus.includes("BLOCKED") || rawStatus.includes("CRITICAL_STOP");

  if (isLive) {
    return {
      mode: "live",
      tone: hasHumanBlocker ? "warn" : "info",
      title: "Run in progress",
      summary: "A local automation process is running, so this snapshot can still change.",
      detail: "Wait for the running process to finish before marking this snapshot reviewed.",
      freshness,
      isLive,
      hasHumanBlocker,
      primaryAction: {
        label: "Review available when run finishes",
        enabled: false,
        reason: "Wait for the running process to finish before recording a review.",
      },
      exportLabel: "Export current snapshot",
    };
  }

  if (freshness === "current") {
    return {
      mode: "already_reviewed",
      tone: "good",
      title: "Already reviewed",
      summary: "The latest stable snapshot matches the recorded review.",
      detail: "You can still inspect evidence or export the review bundle, but no new review action is needed.",
      freshness,
      isLive,
      hasHumanBlocker,
      primaryAction: {
        label: "Latest snapshot reviewed",
        enabled: false,
        reason: "The latest snapshot already has a matching review record.",
      },
      exportLabel: "Export review bundle",
    };
  }

  if (freshness === "stale") {
    return {
      mode: "new_evidence",
      tone: "warn",
      title: "New evidence since review",
      summary: "A newer stable snapshot is available after the last recorded review.",
      detail: hasHumanBlocker
        ? "Resolve pending Inbox items, then review the updated evidence before marking it reviewed."
        : "Review the changed evidence below before marking this snapshot reviewed.",
      freshness,
      isLive,
      hasHumanBlocker,
      primaryAction: {
        label: hasHumanBlocker ? "Resolve Inbox before review" : "Mark latest snapshot reviewed",
        enabled: !hasHumanBlocker,
        reason: hasHumanBlocker
          ? "Pending human input must be resolved before recording this review."
          : "Record that this stable snapshot has been reviewed.",
      },
      exportLabel: "Export review bundle",
    };
  }

  return {
    mode: "outcome",
    tone: blocked || hasHumanBlocker ? "warn" : "info",
    title: "Outcome review",
    summary: blocked
      ? "This run outcome is blocked or stopped for attention."
      : "Review the latest stable automation outcome before trusting it or continuing unattended work.",
    detail: hasHumanBlocker
      ? "Resolve pending Inbox items, then return here to record the review."
      : "Check changed files, verification, skipped checks, and commits before marking this snapshot reviewed.",
    freshness,
    isLive,
    hasHumanBlocker,
    primaryAction: {
      label: hasHumanBlocker ? "Resolve Inbox before review" : "Mark latest snapshot reviewed",
      enabled: !hasHumanBlocker,
      reason: hasHumanBlocker
        ? "Pending human input must be resolved before recording this review."
        : "Record that this stable snapshot has been reviewed.",
    },
    exportLabel: "Export review bundle",
  };
}
