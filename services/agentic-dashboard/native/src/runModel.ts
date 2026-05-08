import type { ProjectSnapshot } from "./api/backend";

export type RunActionKind = "choose-project" | "navigate" | "backend" | "disabled";
export type RunRoute = "Brief" | "Review" | "Advanced" | "Run";
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
    runOnce: RunAction;
    startSchedule: RunAction;
    pauseSchedule: RunAction;
    removeSchedule: RunAction;
    safetyCheck: RunAction;
    exportReview: RunAction;
  };
  schedule: {
    state: string;
    message: string;
    strategyLabel: string;
    cadence: string;
    labels: string[];
    logDir: string;
    canRemove: boolean;
  };
  latestRun: {
    status: string;
    horizon: string;
    lastUpdated: string;
    summary: string;
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
    summary: string;
    raw: Record<string, unknown>;
    latest: string;
    actions: {
      readOnly: RunAction;
      write: RunAction;
      integrator: RunAction;
    };
  };
  blockers: Array<{ name: string; detail: string; required: boolean }>;
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

function bool(value: unknown): boolean {
  return value === true;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function cadenceLabel(seconds: unknown): string {
  const value = number(seconds);
  if (!value) return "Not scheduled";
  const minutes = Math.round(value / 60);
  if (minutes < 60) return `${minutes} min`;
  if (minutes % 1440 === 0) return `${minutes / 1440} d`;
  if (minutes % 60 === 0) return `${minutes / 60} hr`;
  return `${minutes} min`;
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

function displayStatus(status: string): string {
  if (!status || status === "UNKNOWN" || status === "NO_TARGET") return "Not recorded yet";
  return status.replace(/_/g, " ");
}

function workerHeadline(strategy: Record<string, unknown>): string {
  const name = text(strategy.strategy, "NO_WORKERS");
  const budget = number(strategy.parallelism_budget);
  const lane = text(strategy.action_lane, "local");
  const budgetText = budget === 1 ? "one" : budget > 1 ? String(budget) : "no";
  if (name === "READ_ONLY_REPORTS") {
    return `Recommended: ${budgetText} read-only review worker${budget === 1 ? "" : "s"} for ${lane} work.`;
  }
  if (name === "WRITE_WORKERS") {
    return `Recommended: ${budgetText} bounded write worker${budget === 1 ? "" : "s"} for ${lane} work.`;
  }
  if (name === "INTEGRATION_ONLY") {
    return "Recommended: run the integrator lane.";
  }
  return "No worker launch is recommended right now.";
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

export function buildRunModel(snapshot: ProjectSnapshot | null): RunModel {
  const scaffolded = isScaffolded(snapshot);
  const task = record(snapshot?.run.task);
  const controls = record(snapshot?.run.controls);
  const schedule = record(snapshot?.run.schedule);
  const workerStrategy = record(snapshot?.run.worker_strategy);
  const workerControls = record(snapshot?.run.worker_controls);
  const latestWorker = record(snapshot?.run.latest_worker_result);
  const blockers = list(snapshot?.run.environment_blockers).map(record);
  const status = text(task.status, snapshot ? "UNKNOWN" : "NO_TARGET");
  const scheduleState = text(schedule.state, "").toLowerCase();
  const scheduleRunning = scheduleState === "running";
  const running = bool(controls.is_running) || status.includes("RUNNING") || scheduleRunning;

  const runOnce = makeAction(
    "Run Once Now",
    scaffolded && bool(controls.can_run_now),
    scaffolded ? text(controls.run_now_reason, "Ready.") : "Finish the Brief before running automation.",
    "run.once",
  );
  const startSchedule = makeAction(
    "Start Schedule",
    scaffolded && bool(controls.can_start_schedule),
    scaffolded ? text(controls.start_schedule_reason, text(schedule.message, "Schedule is not ready.")) : "Finish the Brief before running automation.",
    "schedule.start",
  );
  const pauseSchedule = makeAction(
    "Pause Schedule",
    scaffolded && bool(controls.can_pause_schedule) && scheduleRunning,
    scaffolded ? text(controls.pause_schedule_reason, text(schedule.message, "No schedule is loaded.")) : "Finish the Brief before running automation.",
    "schedule.pause",
  );
  const removeSchedule = makeAction(
    "Remove Schedule",
    scaffolded && bool(controls.can_remove_schedule),
    scaffolded ? text(controls.remove_schedule_reason, text(schedule.message, "No schedule is available to remove.")) : "Finish the Brief before running automation.",
    "schedule.remove",
  );
  const safetyCheck = makeAction(
    "Run Safety Check",
    scaffolded && bool(controls.can_run_safety_check),
    scaffolded ? "Records the latest integration safety result in the target." : "Finish the Brief before running automation.",
    "safety.run_check",
  );
  const exportReview = routeAction("Open Review Export", "Review", "Review bundles live on the Review page.");
  exportReview.enabled = scaffolded;
  exportReview.kind = scaffolded ? "navigate" : "disabled";

  let headline = "No project selected";
  let subheadline = "Choose a project folder before running automation.";
  let badge = "No Target";
  let primaryAction: RunAction = { label: "Choose Project", kind: "choose-project", enabled: true, reason: "Select a target folder." };
  if (snapshot && !scaffolded) {
    headline = "Finish the Brief before running automation.";
    subheadline = "Run controls unlock after the Brief creates the target Diffmogger contract.";
    badge = "Brief Needed";
    primaryAction = routeAction("Go to Brief", "Brief", "The Brief page owns scaffold and bootstrap.");
  } else if (snapshot && running) {
    headline = "Automation activity is in progress";
    subheadline = text(schedule.message, "Refresh to inspect the latest run state.");
    badge = "Running";
    primaryAction = routeAction("Refresh Run", "Run", "Reload the latest run state.");
  } else if (snapshot && blockers.length > 0) {
    headline = "Check blockers before running";
    subheadline = blockers.map((item) => text(item.name, "Environment blocker")).join(", ");
    badge = "Blocked";
    primaryAction = safetyCheck;
  } else if (snapshot && runOnce.enabled) {
    headline = "Ready to run automation";
    subheadline = "The target contract is present and the current status is schedulable.";
    badge = "Ready";
    primaryAction = runOnce;
  } else if (snapshot) {
    headline = "Run controls need attention";
    subheadline = text(controls.run_now_reason, text(schedule.message, "Refresh diagnostics before running."));
    badge = status === "UNKNOWN" ? "Needs Review" : status.replace(/_/g, " ");
    primaryAction = safetyCheck.enabled ? safetyCheck : routeAction("Go to Brief", "Brief", "Confirm the target setup.");
  }

  return {
    isScaffolded: scaffolded,
    isRunning: running,
    banner: {
      headline,
      subheadline,
      badge,
      tone: statusTone(status, blockers),
      primaryAction,
    },
    controls: {
      runOnce,
      startSchedule,
      pauseSchedule,
      removeSchedule,
      safetyCheck,
      exportReview,
    },
    schedule: {
      state: text(schedule.state, "not_installed"),
      message: text(schedule.message, "Schedule has not been installed yet."),
      strategyLabel: text(schedule.strategy_label, text(schedule.strategy, "Not selected")),
      cadence: cadenceLabel(schedule.cadence_seconds),
      labels: list(schedule.active_labels).map((item) => text(item, "")).filter(Boolean),
      logDir: text(schedule.log_dir, ""),
      canRemove: bool(schedule.can_remove),
    },
    latestRun: {
      status: displayStatus(status),
      horizon: text(task.horizon, "No horizon recorded yet"),
      lastUpdated: text(task.last_updated, text(snapshot?.run.snapshot_generated_at, "Not recorded")),
      summary: text(snapshot?.run.progress_recent, text(task.suggested_next_task, "No automation run has been recorded yet.")),
    },
    runLog: runLog(snapshot),
    worker: {
      headline: workerHeadline(workerStrategy),
      summary: text(workerStrategy.summary, text(workerStrategy.reason, "No worker strategy detail recorded yet.")),
      raw: workerStrategy,
      latest: text(latestWorker.label, "Latest worker result: none yet."),
      actions: {
        readOnly: makeAction(
          "Run Read-Only Worker",
          scaffolded && bool(workerControls.can_run_read_only),
          text(workerControls.read_only_reason, "Not supported by the current strategy."),
          "worker.run_read_only",
        ),
        write: makeAction(
          "Run Write Worker",
          scaffolded && bool(workerControls.can_run_write),
          text(workerControls.write_reason, "Not supported by the current strategy."),
          "worker.run_write",
        ),
        integrator: makeAction(
          "Run Integrator",
          scaffolded && bool(workerControls.can_run_integrator),
          text(workerControls.integrator_reason, "Not supported by the current strategy."),
          "worker.run_integrator",
        ),
      },
    },
    blockers: blockers.map((item) => ({
      name: text(item.name, "Environment blocker"),
      detail: text(item.detail, ""),
      required: bool(item.required),
    })),
  };
}
