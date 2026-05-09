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
  const rawBudget = strategy.parallelism_budget;
  const budget = typeof rawBudget === "number" && Number.isFinite(rawBudget) ? rawBudget : Number(rawBudget || 0);
  const lane = text(strategy.action_lane, "local");
  const budgetText = budget === 1 ? "one" : budget > 1 ? String(budget) : "no";
  if (name === "READ_ONLY_REPORTS") {
    return `Read-only workers: ${budgetText} for ${lane}.`;
  }
  if (name === "WRITE_WORKERS") {
    return `Write workers: ${budgetText} for ${lane}.`;
  }
  if (name === "INTEGRATION_ONLY") {
    return "Integrator lane recommended.";
  }
  return "No worker run recommended.";
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
  const automation = record(snapshot?.run.automation);
  const workerStrategy = record(snapshot?.run.worker_strategy);
  const workerControls = record(snapshot?.run.worker_controls);
  const latestWorker = record(snapshot?.run.latest_worker_result);
  const blockers = list(snapshot?.run.environment_blockers).map(record);
  const status = text(task.status, snapshot ? "UNKNOWN" : "NO_TARGET");
  const automationState = text(automation.state, "").toLowerCase();
  const automationRunning = automationState === "running";
  const running = bool(controls.is_running) || status.includes("RUNNING") || automationRunning;

  const startAutomation = makeAction(
    "Start",
    scaffolded && bool(controls.can_start_automation),
    scaffolded ? text(controls.start_automation_reason, text(automation.message, "Automation is not ready.")) : "Complete setup before running.",
    "automation.start",
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

  let headline = "No project selected";
  let subheadline = "Choose a project before running.";
  let badge = "No target";
  let primaryAction: RunAction = { label: "Choose project", kind: "choose-project", enabled: true, reason: "Select a target folder." };
  if (snapshot && !scaffolded) {
    headline = "Not Ready";
    subheadline = "Complete setup before running.";
    badge = "Setup needed";
    primaryAction = routeAction("Open setup", "Brief", "Confirm the target setup.");
  } else if (snapshot && running) {
    headline = "Run in progress";
    subheadline = text(automation.message, "Refresh to inspect the latest run state.");
    badge = "Running";
    primaryAction = routeAction("Refresh", "Run", "Reload the latest run state.");
  } else if (snapshot && blockers.length > 0) {
    headline = "Not Ready";
    subheadline = blockers.map((item) => text(item.name, "Environment blocker")).join(", ");
    badge = "Blocked";
    primaryAction = safetyCheck;
  } else if (snapshot && startAutomation.enabled) {
    headline = "Ready";
    subheadline = "The target files are present and continuous automation can start.";
    badge = "Ready";
    primaryAction = startAutomation;
  } else if (snapshot) {
    headline = "Not Ready";
    subheadline = text(controls.start_automation_reason, text(automation.message, "Refresh diagnostics before running."));
    badge = status === "UNKNOWN" ? "Needs Review" : status.replace(/_/g, " ");
    primaryAction = safetyCheck.enabled ? safetyCheck : routeAction("Open setup", "Brief", "Confirm the target setup.");
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
    runLog: runLog(snapshot),
    worker: {
      headline: workerHeadline(workerStrategy),
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
    blockers: blockers.map((item) => ({
      name: text(item.name, "Environment blocker"),
      detail: text(item.detail, ""),
      required: bool(item.required),
    })),
  };
}
