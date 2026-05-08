import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { buildCommandPaletteModel, filterPaletteCommands } from "./commandPaletteModel";

function snapshot(overrides: Partial<ProjectSnapshot> = {}): ProjectSnapshot {
  const base: ProjectSnapshot = {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    brief: { project_name: "Project", project_mode: "fresh_project" },
    run: {
      controls: {
        is_scaffolded: true,
        can_run_now: true,
        run_now_reason: "Ready.",
        can_start_schedule: true,
        start_schedule_reason: "Schedule ready.",
        can_pause_schedule: false,
        pause_schedule_reason: "No schedule is running.",
        can_remove_schedule: false,
        remove_schedule_reason: "No schedule is installed.",
        can_run_safety_check: true,
        can_export_review: true,
      },
    },
    files: [
      {
        key: "monitor.automation_tasks",
        label: "Automation Tasks",
        rel_path: "docs/CODEX_AUTOMATION_TASKS.md",
        group: "monitor",
        exists: true,
        size_bytes: 120,
        modified_at: "2026-05-06T12:00:00+00:00",
      },
    ],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1",
      next_action: "Run.",
      pending_human_requests: 0,
      unhandled_inbox: 0,
      queued_patches: 0,
      deferred_patches: 0,
    },
  };
  return {
    ...base,
    ...overrides,
    target: { ...base.target, ...overrides.target },
    run: { ...base.run, ...overrides.run },
    home: { ...base.home, ...overrides.home },
    files: overrides.files ?? base.files,
  };
}

describe("command palette model", () => {
  it("includes the required command surface", () => {
    const ids = buildCommandPaletteModel({ snapshot: snapshot() }).map((command) => command.id);

    expect(ids).toContain("open-project");
    expect(ids).toContain("create-new-project");
    expect(ids).toContain("close-project");
    expect(ids).toContain("run-once");
    expect(ids).toContain("remove-schedule");
    expect(ids).toContain("open-observatory-browser");
    expect(ids).toContain("export-debug-bundle");
    expect(ids).toHaveLength(20);
  });

  it("explains disabled target-scoped commands without a selected target", () => {
    const commands = buildCommandPaletteModel({ snapshot: null });
    const run = commands.find((command) => command.id === "run-once");
    const reveal = commands.find((command) => command.id === "reveal-project");
    const close = commands.find((command) => command.id === "close-project");

    expect(run?.disabledReason).toContain("Choose a project folder");
    expect(reveal?.disabledReason).toContain("Choose a project folder");
    expect(close?.disabledReason).toContain("Choose a project folder");
    expect(commands.find((command) => command.id === "open-project")?.disabledReason).toBeUndefined();
  });

  it("uses run-control reasons for gated automation commands", () => {
    const commands = buildCommandPaletteModel({
      snapshot: snapshot({
        run: {
          controls: {
            is_scaffolded: true,
            can_run_now: false,
            run_now_reason: "A role run is already active.",
            can_start_schedule: false,
            start_schedule_reason: "Fix prerequisites first.",
            can_pause_schedule: true,
            can_remove_schedule: true,
            can_run_safety_check: true,
            can_export_review: true,
          },
          schedule: { state: "running", message: "Schedule is running via launchd." },
        },
      }),
    });

    expect(commands.find((command) => command.id === "run-once")?.disabledReason).toBe("A role run is already active.");
    expect(commands.find((command) => command.id === "start-schedule")?.disabledReason).toBe("Fix prerequisites first.");
    expect(commands.find((command) => command.id === "pause-schedule")?.disabledReason).toBeUndefined();
    expect(commands.find((command) => command.id === "remove-schedule")?.disabledReason).toBeUndefined();
  });

  it("disables Pause schedule when a plist exists but launchd is not running it", () => {
    const commands = buildCommandPaletteModel({
      snapshot: snapshot({
        run: {
          controls: {
            is_scaffolded: true,
            can_pause_schedule: true,
            pause_schedule_reason: "Schedule plist exists but is not loaded.",
          },
          schedule: { state: "installed", message: "Schedule plist exists but is not loaded." },
        },
      }),
    });

    expect(commands.find((command) => command.id === "pause-schedule")?.disabledReason).toBe(
      "Schedule plist exists but is not loaded.",
    );
  });

  it("searches command title, section, description, and keywords", () => {
    const commands = buildCommandPaletteModel({ snapshot: snapshot() });

    expect(filterPaletteCommands(commands, "autonomous build").map((command) => command.id)).toEqual([
      "open-observatory-browser",
    ]);
    expect(filterPaletteCommands(commands, "human bridge").map((command) => command.id)).toContain("send-note-next-run");
    expect(filterPaletteCommands(commands, "raw tasks").map((command) => command.id)).toEqual([
      "open-raw-automation-tasks",
    ]);
  });
});
