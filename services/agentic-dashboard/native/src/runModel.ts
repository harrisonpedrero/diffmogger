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
  stateMachine: {
    stage: string;
    stageStatus: string;
    ownerRole: string;
    validationStatus: string;
    capability: string;
    capabilityVersion: string;
    continuationToken: string;
    enteredAt: string;
    nextActions: Array<{ role: string; state: string; reason: string }>;
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

function stateMachineSnapshot(snapshot: ProjectSnapshot | null): Record<string, unknown> {
  const state = record(snapshot?.run.state);
  const machine = record(state.conveyor_machine);
  if (Object.keys(machine).length) return machine;
  return record(record(snapshot?.run.conveyor).state_machine);
}

function capabilityLabel(capability: Record<string, unknown>): string {
  const languages = record(capability.languages);
  const primary = text(languages.primary, "");
  const commands = list(capability.commands).length;
  if (primary && commands) return `${primary} / ${commands} command${commands === 1 ? "" : "s"}`;
  if (primary) return primary;
  if (commands) return `${commands} command${commands === 1 ? "" : "s"}`;
  return "Not discovered";
}

function stateMachineModel(snapshot: ProjectSnapshot | null): RunModel["stateMachine"] {
  const machine = stateMachineSnapshot(snapshot);
  const workItem = record(machine.work_item);
  const capability = record(machine.capability_manifest);
  const state = record(snapshot?.run.state);
  const actions = list(state.next_actions)
    .map(record)
    .slice(0, 4)
    .map((item) => ({
      role: text(item.owner_role, "idle"),
      state: text(item.status, "planned"),
      reason: text(item.reason, "No reason recorded."),
    }));
  return {
    stage: text(workItem.current_stage, text(machine.current_stage, "intake")),
    stageStatus: text(workItem.stage_status, text(machine.stage_status, "ready")),
    ownerRole: text(workItem.owner_role, text(machine.owner_role, "planner")),
    validationStatus: text(workItem.validation_status, "not recorded"),
    capability: capabilityLabel(capability),
    capabilityVersion: text(workItem.capability_manifest_version, text(capability.version, "0")),
    continuationToken: text(workItem.continuation_token, ""),
    enteredAt: text(workItem.entered_at, ""),
    nextActions: actions,
  };
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

  const title = stateTitle(snapshot, scaffolded, running, blockers, statusUpper);
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
    stateMachine: stateMachineModel(snapshot),
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
