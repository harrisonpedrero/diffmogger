import type { ProjectSnapshot } from "./api/backend";

export type PaletteCommandId =
  | "open-setup"
  | "open-automation"
  | "open-project"
  | "create-new-project"
  | "close-project"
  | "reveal-project"
  | "open-project-editor"
  | "import-context-files"
  | "scaffold-project"
  | "start-automation"
  | "stop-automation"
  | "run-safety-check"
  | "open-raw-automation-tasks";

export type PaletteSection = "Navigation" | "Project" | "Setup" | "Automation";

export type PaletteCommand = {
  id: PaletteCommandId;
  title: string;
  section: PaletteSection;
  description: string;
  keywords: string[];
  disabledReason?: string;
  dangerous?: boolean;
  routesTo?: "Setup" | "Automation";
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
  const controls = snapshot?.controls ?? {};
  const value = controls[key];
  return value === true ? undefined : String(controls[`${key.replace(/^can_/, "").replace(/_/g, "_")}_reason`] ?? fallback);
}

function automationState(snapshot: ProjectSnapshot | null): string {
  const value = snapshot?.controls.automation?.state;
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function rawAutomationTasksReason(snapshot: ProjectSnapshot | null): string | undefined {
  const targetReason = reasonForTarget(snapshot);
  if (targetReason) return targetReason;
  const file = snapshot?.setup.files?.find((item) => item.key === "monitor.automation_tasks");
  return file?.exists ? undefined : "Task projection does not exist yet. Complete setup first.";
}

export function buildCommandPaletteModel(state: PaletteState): PaletteCommand[] {
  const snapshot = state.snapshot;
  const targetReason = reasonForTarget(snapshot);
  const busyReason = reasonWhenLoading(state);
  const scaffolded = snapshot?.controls.is_scaffolded === true || snapshot?.target.automation_task_exists === true;

  return [
    {
      id: "open-setup",
      title: "Open Setup",
      section: "Navigation",
      description: "Open project selection and setup.",
      keywords: ["setup", "project", "brief", "intake"],
      routesTo: "Setup",
      disabledReason: busyReason,
    },
    {
      id: "open-automation",
      title: "Open Automation",
      section: "Navigation",
      description: "Open scheduler state, queued work, input records, and run controls.",
      keywords: ["automation", "run", "scheduler", "activity", "tickets"],
      routesTo: "Automation",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "open-project",
      title: "Choose project",
      section: "Project",
      description: "Choose a Diffmogger target folder.",
      keywords: ["folder", "target", "choose", "switch"],
      disabledReason: busyReason,
    },
    {
      id: "create-new-project",
      title: "New project",
      section: "Project",
      description: "Open setup for a fresh target folder.",
      keywords: ["fresh", "new", "setup", "brief"],
      routesTo: "Setup",
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
        ? "Open setup to inspect scaffold settings before running this again."
        : "Open setup before writing generated project files.",
      keywords: ["scaffold", "setup", "install", "configure"],
      dangerous: true,
      routesTo: "Setup",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "start-automation",
      title: "Start automation",
      section: "Automation",
      description: "Start the scheduler.",
      keywords: ["automation", "run", "start", "scheduler"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.controls.can_start_automation === true
          ? undefined
          : String(snapshot?.controls.start_automation_reason ?? "Automation is not ready to start.")),
    },
    {
      id: "stop-automation",
      title: "Stop automation",
      section: "Automation",
      description: "Stop the scheduler process.",
      keywords: ["automation", "run", "stop", "scheduler"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.controls.can_stop_automation === true && automationState(snapshot) === "running"
          ? undefined
          : String(snapshot?.controls.stop_automation_reason ?? "No automation is running.")),
    },
    {
      id: "run-safety-check",
      title: "Run safety check",
      section: "Automation",
      description: "Run and record the integration safety check.",
      keywords: ["safety", "diagnostics", "check"],
      disabledReason:
        busyReason ??
        targetReason ??
        runControlReason(snapshot, "can_run_safety_check", "Safety check is not available."),
    },
    {
      id: "open-raw-automation-tasks",
      title: "Open task projection",
      section: "Automation",
      description: "Open .diffmogger/state/CODEX_AUTOMATION_TASKS.md through the managed file allowlist.",
      keywords: ["raw", "tasks", "markdown", "projection"],
      disabledReason: busyReason ?? rawAutomationTasksReason(snapshot),
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
