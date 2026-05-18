import type { ProjectSnapshot } from "./api/backend";

export type PaletteCommandId =
  | "open-control-room"
  | "open-run-control"
  | "open-human-bridge"
  | "open-review"
  | "open-sidecar"
  | "open-project"
  | "create-new-project"
  | "close-project"
  | "reveal-project"
  | "open-project-editor"
  | "continue-brief"
  | "import-context-files"
  | "scaffold-project"
  | "start-automation"
  | "stop-automation"
  | "run-safety-check"
  | "open-observatory"
  | "export-review-bundle"
  | "send-note-next-run"
  | "open-raw-automation-tasks"
  | "open-canonical-state"
  | "open-diagnostics"
  | "export-debug-bundle";

export type PaletteCommand = {
  id: PaletteCommandId;
  title: string;
  section: "Navigation" | "Project" | "Setup" | "Run" | "Activity" | "Review" | "Inbox" | "Debug";
  description: string;
  keywords: string[];
  disabledReason?: string;
  dangerous?: boolean;
  routesTo?: string;
};

export type PaletteState = {
  snapshot: ProjectSnapshot | null;
  loading?: boolean;
  busy?: boolean;
};

function reasonForTarget(snapshot: ProjectSnapshot | null): string | undefined {
  return snapshot ? undefined : "Choose a project folder first.";
}

function reasonWhenLoading(state: PaletteState): string | undefined {
  return state.loading || state.busy ? "Wait for the current command to finish." : undefined;
}

function runControlReason(snapshot: ProjectSnapshot | null, key: string, fallback: string): string | undefined {
  const controls = snapshot?.run.controls ?? {};
  const value = controls[key];
  return value === true ? undefined : String(controls[`${key.replace(/^can_/, "").replace(/_/g, "_")}_reason`] ?? fallback);
}

function automationState(snapshot: ProjectSnapshot | null): string {
  const value = snapshot?.run.automation?.state;
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function rawAutomationTasksReason(snapshot: ProjectSnapshot | null): string | undefined {
  const targetReason = reasonForTarget(snapshot);
  if (targetReason) return targetReason;
  const file = snapshot?.files.find((item) => item.key === "monitor.automation_tasks");
  return file?.exists ? undefined : "Task file does not exist yet. Complete setup first.";
}

function reviewExportReason(snapshot: ProjectSnapshot | null): string | undefined {
  const targetReason = reasonForTarget(snapshot);
  if (targetReason) return targetReason;
  const controls = snapshot?.run.controls ?? {};
  return controls.can_export_review === true
    ? undefined
    : "Complete setup before exporting review files.";
}

export function buildCommandPaletteModel(state: PaletteState): PaletteCommand[] {
  const snapshot = state.snapshot;
  const targetReason = reasonForTarget(snapshot);
  const busyReason = reasonWhenLoading(state);
  const scaffolded = snapshot?.run.controls?.is_scaffolded === true || snapshot?.target.automation_task_exists === true;

  return [
    {
      id: "open-control-room",
      title: "Open Home",
      section: "Navigation",
      description: "Open the Home overview.",
      keywords: ["home", "control room", "overview", "ready"],
      routesTo: "Home",
      disabledReason: busyReason,
    },
    {
      id: "continue-brief",
      title: "Open setup",
      section: "Navigation",
      description: "Return to setup.",
      keywords: ["brief", "setup", "intake", "wizard"],
      routesTo: "Brief",
      disabledReason: busyReason,
    },
    {
      id: "open-run-control",
      title: "Open Run",
      section: "Navigation",
      description: "Open the Run page.",
      keywords: ["run", "run control", "automation", "start", "stop"],
      routesTo: "Run",
      disabledReason: busyReason,
    },
    {
      id: "open-observatory",
      title: "Open activity",
      section: "Navigation",
      description: "Open Activity.",
      keywords: ["observatory", "activity", "log", "build"],
      routesTo: "Observatory",
      disabledReason: busyReason,
    },
    {
      id: "open-human-bridge",
      title: "Open Inbox",
      section: "Navigation",
      description: "Open the Inbox handoff surface.",
      keywords: ["inbox", "human bridge", "bridge", "note", "request"],
      routesTo: "Inbox",
      disabledReason: busyReason,
    },
    {
      id: "open-review",
      title: "Open review",
      section: "Navigation",
      description: "Open Review.",
      keywords: ["review", "evidence", "export"],
      routesTo: "Review",
      disabledReason: busyReason,
    },
    {
      id: "open-sidecar",
      title: "Open Sidecar",
      section: "Navigation",
      description: "Open Advanced managed files, diagnostics, settings, and debug tools.",
      keywords: ["advanced", "debug", "sidecar", "settings", "files", "diagnostics"],
      routesTo: "Advanced",
      disabledReason: busyReason,
    },
    {
      id: "open-project",
      title: "Open project",
      section: "Project",
      description: "Choose a Diffmogger target folder.",
      keywords: ["folder", "target", "choose"],
      disabledReason: busyReason,
    },
    {
      id: "create-new-project",
      title: "New project",
      section: "Project",
      description: "Open setup for a fresh target folder.",
      keywords: ["fresh", "new", "brief"],
      routesTo: "Brief",
      disabledReason: busyReason,
    },
    {
      id: "close-project",
      title: "Close project",
      section: "Project",
      description: "Exit the selected project without changing target-local files.",
      keywords: ["exit", "close", "switch", "target"],
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "reveal-project",
      title: "Reveal project in Finder",
      section: "Project",
      description: "Show the selected target folder in the OS file browser.",
      keywords: ["finder", "reveal", "folder"],
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "open-project-editor",
      title: "Open project in editor",
      section: "Project",
      description: "Open the selected target folder in a supported local editor.",
      keywords: ["editor", "code", "cursor", "zed", "sublime"],
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "import-context-files",
      title: "Import context files",
      section: "Setup",
      description: "Choose files and import them into .diffmogger/context through the backend.",
      keywords: ["context", "files", "docs"],
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "scaffold-project",
      title: "Scaffold",
      section: "Setup",
      description: scaffolded
        ? "Open setup to review scaffold settings before running this again."
        : "Open setup review before writing generated project files.",
      keywords: ["scaffold", "setup"],
      dangerous: true,
      routesTo: "Brief",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "start-automation",
      title: "Start",
      section: "Run",
      description: "Start automation.",
      keywords: ["automation", "run", "start"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.run.controls?.can_start_automation === true
          ? undefined
          : String(snapshot?.run.controls?.start_automation_reason ?? "Automation is not ready to start.")),
    },
    {
      id: "stop-automation",
      title: "Stop",
      section: "Run",
      description: "Stop automation.",
      keywords: ["automation", "run", "stop"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.run.controls?.can_stop_automation === true && automationState(snapshot) === "running"
          ? undefined
          : String(snapshot?.run.controls?.stop_automation_reason ?? "No automation is running.")),
    },
    {
      id: "run-safety-check",
      title: "Run safety check",
      section: "Run",
      description: "Run and record the integration safety check.",
      keywords: ["safety", "diagnostics", "check"],
      disabledReason:
        busyReason ??
        targetReason ??
        runControlReason(snapshot, "can_run_safety_check", "Safety check is not available."),
    },
    {
      id: "export-review-bundle",
      title: "Export review",
      section: "Review",
      description: "Export review files.",
      keywords: ["review", "bundle", "export"],
      disabledReason: busyReason ?? reviewExportReason(snapshot),
    },
    {
      id: "send-note-next-run",
      title: "Send note to next run",
      section: "Inbox",
      description: "Queue a typed dashboard note for the next run.",
      keywords: ["inbox", "human bridge", "bridge", "note"],
      routesTo: "Inbox",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "open-raw-automation-tasks",
      title: "Open task state",
      section: "Debug",
      description: "Open .diffmogger/state/CODEX_AUTOMATION_TASKS.md through the managed file allowlist.",
      keywords: ["raw", "tasks", "markdown", "projection"],
      disabledReason: busyReason ?? rawAutomationTasksReason(snapshot),
    },
    {
      id: "open-canonical-state",
      title: "Open canonical state",
      section: "Debug",
      description: "Open the SQLite orchestration state dashboard.",
      keywords: ["state", "sqlite", "canonical", "ledger", "database", "control plane"],
      routesTo: "Advanced",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "open-diagnostics",
      title: "Open diagnostics",
      section: "Debug",
      description: "Open diagnostics.",
      keywords: ["sidecar", "advanced", "doctor", "checks", "diagnostics"],
      routesTo: "Advanced",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "export-debug-bundle",
      title: "Export debug",
      section: "Debug",
      description: "Export a redacted debug bundle without .env contents.",
      keywords: ["debug", "bundle", "support", "zip", "diagnostics", "sidecar"],
      disabledReason: busyReason ?? targetReason,
    },
  ];
}

export function filterPaletteCommands(commands: PaletteCommand[], query: string): PaletteCommand[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return commands;
  const terms = normalized.split(/\s+/).filter(Boolean);
  return commands.filter((command) => {
    const haystack = [
      command.title,
      command.section,
      command.description,
      ...command.keywords,
    ].join(" ").toLowerCase();
    return terms.every((term) => haystack.includes(term));
  });
}
