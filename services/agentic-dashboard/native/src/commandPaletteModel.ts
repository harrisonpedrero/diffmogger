import type { ProjectSnapshot } from "./api/backend";

export type PaletteCommandId =
  | "open-project"
  | "create-new-project"
  | "close-project"
  | "reveal-project"
  | "open-project-editor"
  | "continue-brief"
  | "import-context-files"
  | "scaffold-bootstrap"
  | "run-once"
  | "start-schedule"
  | "pause-schedule"
  | "remove-schedule"
  | "run-safety-check"
  | "open-observatory"
  | "open-observatory-browser"
  | "export-review-bundle"
  | "send-note-next-run"
  | "open-raw-automation-tasks"
  | "open-diagnostics"
  | "export-debug-bundle";

export type PaletteCommand = {
  id: PaletteCommandId;
  title: string;
  section: "Project" | "Brief" | "Run" | "Observatory" | "Review" | "Inbox" | "Advanced";
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

function scheduleState(snapshot: ProjectSnapshot | null): string {
  const value = snapshot?.run.schedule?.state;
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function rawAutomationTasksReason(snapshot: ProjectSnapshot | null): string | undefined {
  const targetReason = reasonForTarget(snapshot);
  if (targetReason) return targetReason;
  const file = snapshot?.files.find((item) => item.key === "monitor.automation_tasks");
  return file?.exists ? undefined : "Automation tasks file does not exist yet. Finish the Brief first.";
}

function reviewExportReason(snapshot: ProjectSnapshot | null): string | undefined {
  const targetReason = reasonForTarget(snapshot);
  if (targetReason) return targetReason;
  const controls = snapshot?.run.controls ?? {};
  return controls.can_export_review === true
    ? undefined
    : "Finish the Brief before exporting a review bundle.";
}

export function buildCommandPaletteModel(state: PaletteState): PaletteCommand[] {
  const snapshot = state.snapshot;
  const targetReason = reasonForTarget(snapshot);
  const busyReason = reasonWhenLoading(state);
  const scaffolded = snapshot?.run.controls?.is_scaffolded === true || snapshot?.target.automation_task_exists === true;

  return [
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
      title: "Create new project",
      section: "Project",
      description: "Open the Brief flow for a fresh target folder.",
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
      id: "continue-brief",
      title: "Continue Brief",
      section: "Brief",
      description: "Return to guided intake and scaffold setup.",
      keywords: ["intake", "setup", "wizard"],
      routesTo: "Brief",
      disabledReason: busyReason,
    },
    {
      id: "import-context-files",
      title: "Import context files",
      section: "Brief",
      description: "Choose files and import them into .diffmogger/context through the backend.",
      keywords: ["context", "files", "docs"],
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "scaffold-bootstrap",
      title: "Scaffold & Bootstrap",
      section: "Brief",
      description: scaffolded
        ? "Open Brief to review scaffold settings before running this again."
        : "Open Brief review step before writing generated project files.",
      keywords: ["scaffold", "bootstrap", "setup"],
      dangerous: true,
      routesTo: "Brief",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "run-once",
      title: "Run once now",
      section: "Run",
      description: "Run the target-local automation script once.",
      keywords: ["run", "automation", "now"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.run.controls?.can_run_now === true
          ? undefined
          : String(snapshot?.run.controls?.run_now_reason ?? "Automation is not ready to run.")),
    },
    {
      id: "start-schedule",
      title: "Start schedule",
      section: "Run",
      description: "Start dashboard-managed scheduled automation.",
      keywords: ["schedule", "launchd", "start"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.run.controls?.can_start_schedule === true
          ? undefined
          : String(snapshot?.run.controls?.start_schedule_reason ?? "Schedule is not ready to start.")),
    },
    {
      id: "pause-schedule",
      title: "Pause schedule",
      section: "Run",
      description: "Pause dashboard-managed scheduled automation.",
      keywords: ["schedule", "launchd", "pause"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.run.controls?.can_pause_schedule === true && scheduleState(snapshot) === "running"
          ? undefined
          : String(snapshot?.run.controls?.pause_schedule_reason ?? "No schedule is available to pause.")),
    },
    {
      id: "remove-schedule",
      title: "Remove schedule",
      section: "Run",
      description: "Remove dashboard-managed LaunchAgent plist(s) without deleting generated project files.",
      keywords: ["schedule", "launchd", "remove", "delete", "plist"],
      dangerous: true,
      disabledReason:
        busyReason ??
        targetReason ??
        (snapshot?.run.controls?.can_remove_schedule === true
          ? undefined
          : String(snapshot?.run.controls?.remove_schedule_reason ?? "No schedule is available to remove.")),
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
      id: "open-observatory",
      title: "Open Observatory",
      section: "Observatory",
      description: "Open the native Observatory page.",
      keywords: ["log", "build", "observatory"],
      routesTo: "Observatory",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "open-observatory-browser",
      title: "Open Observatory in browser",
      section: "Observatory",
      description: "Generate the old HTML Observatory and open it in the default browser.",
      keywords: ["html", "browser", "autonomous build log"],
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "export-review-bundle",
      title: "Export review bundle",
      section: "Review",
      description: "Export Observatory HTML and self-review Markdown.",
      keywords: ["review", "bundle", "export"],
      disabledReason: busyReason ?? reviewExportReason(snapshot),
    },
    {
      id: "send-note-next-run",
      title: "Send note to next run",
      section: "Inbox",
      description: "Open Inbox to write a file-only note for the next automation run.",
      keywords: ["inbox", "human bridge", "note"],
      routesTo: "Inbox",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "open-raw-automation-tasks",
      title: "Open raw automation tasks",
      section: "Advanced",
      description: "Open .diffmogger/state/CODEX_AUTOMATION_TASKS.md through the managed file allowlist.",
      keywords: ["raw", "tasks", "markdown"],
      disabledReason: busyReason ?? rawAutomationTasksReason(snapshot),
    },
    {
      id: "open-diagnostics",
      title: "Open Diagnostics",
      section: "Advanced",
      description: "Open Advanced diagnostics.",
      keywords: ["doctor", "checks", "diagnostics"],
      routesTo: "Advanced",
      disabledReason: busyReason ?? targetReason,
    },
    {
      id: "export-debug-bundle",
      title: "Export debug bundle",
      section: "Advanced",
      description: "Export a redacted support bundle without .env contents.",
      keywords: ["debug", "support", "zip", "diagnostics"],
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
