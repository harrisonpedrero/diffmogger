import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { buildCommandPaletteModel, filterPaletteCommands } from "./commandPaletteModel";

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends Array<infer U>
    ? Array<DeepPartial<U>>
    : T[K] extends object
      ? DeepPartial<T[K]>
      : T[K];
};

function snapshot(overrides: DeepPartial<ProjectSnapshot> = {}): ProjectSnapshot {
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
        can_start_automation: true,
        start_automation_reason: "Automation ready.",
        can_stop_automation: false,
        stop_automation_reason: "No automation is running.",
        can_run_safety_check: true,
        can_export_review: true,
      },
      automation: { state: "stopped", message: "Continuous automation is ready to start." },
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
  } as ProjectSnapshot;
}

describe("command palette model", () => {
  it("includes the required command surface", () => {
    const ids = buildCommandPaletteModel({ snapshot: snapshot() }).map((command) => command.id);

    expect(ids).toContain("open-project");
    expect(ids).toContain("open-control-room");
    expect(ids).toContain("open-run-control");
    expect(ids).toContain("open-human-bridge");
    expect(ids).toContain("open-sidecar");
    expect(ids).toContain("create-new-project");
    expect(ids).toContain("close-project");
    expect(ids).toContain("start-automation");
    expect(ids).toContain("stop-automation");
    expect(ids).toContain("export-debug-bundle");
    expect(ids).toHaveLength(22);
  });

  it("explains disabled target-scoped commands without a selected target", () => {
    const commands = buildCommandPaletteModel({ snapshot: null });
    const start = commands.find((command) => command.id === "start-automation");
    const reveal = commands.find((command) => command.id === "reveal-project");
    const close = commands.find((command) => command.id === "close-project");

    expect(start?.disabledReason).toContain("Choose a project folder");
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
            can_start_automation: false,
            start_automation_reason: "Fix prerequisites first.",
            can_stop_automation: true,
            can_run_safety_check: true,
            can_export_review: true,
          },
          automation: { state: "running", message: "Continuous automation is running." },
        },
      }),
    });

    expect(commands.find((command) => command.id === "start-automation")?.disabledReason).toBe("Fix prerequisites first.");
    expect(commands.find((command) => command.id === "stop-automation")?.disabledReason).toBeUndefined();
  });

  it("disables Stop when automation is not running", () => {
    const commands = buildCommandPaletteModel({
      snapshot: snapshot({
        run: {
          controls: {
            is_scaffolded: true,
            can_stop_automation: false,
            stop_automation_reason: "No automation is running.",
          },
          automation: { state: "stopped", message: "Continuous automation is ready to start." },
        },
      }),
    });

    expect(commands.find((command) => command.id === "stop-automation")?.disabledReason).toBe("No automation is running.");
  });

  it("searches command title, section, description, and keywords", () => {
    const commands = buildCommandPaletteModel({ snapshot: snapshot() });

    expect(filterPaletteCommands(commands, "activity").map((command) => command.id)).toEqual(["open-observatory"]);
    expect(filterPaletteCommands(commands, "home").map((command) => command.id)).toContain("open-control-room");
    expect(filterPaletteCommands(commands, "control room").map((command) => command.id)).toContain("open-control-room");
    expect(filterPaletteCommands(commands, "brief").map((command) => command.id)).toContain("continue-brief");
    expect(filterPaletteCommands(commands, "setup").map((command) => command.id)).toContain("continue-brief");
    expect(filterPaletteCommands(commands, "run control").map((command) => command.id)).toContain("open-run-control");
    expect(filterPaletteCommands(commands, "human bridge").map((command) => command.id)).toContain("open-human-bridge");
    expect(filterPaletteCommands(commands, "inbox").map((command) => command.id)).toContain("open-human-bridge");
    expect(filterPaletteCommands(commands, "advanced").map((command) => command.id)).toContain("open-sidecar");
    expect(filterPaletteCommands(commands, "sidecar").map((command) => command.id)).toContain("open-sidecar");
    expect(filterPaletteCommands(commands, "debug bundle").map((command) => command.id)).toContain("export-debug-bundle");
    expect(filterPaletteCommands(commands, "inbox note").map((command) => command.id)).toContain("send-note-next-run");
    expect(filterPaletteCommands(commands, "raw tasks").map((command) => command.id)).toEqual([
      "open-raw-automation-tasks",
    ]);
  });

  it("covers representative start gating states", () => {
    const states = [
      {
        name: "targetless",
        snapshot: null,
        reason: "Choose a project folder",
      },
      {
        name: "missing sidecar",
        snapshot: snapshot({
          target: {
            is_diffmogger_project: false,
            automation_task_exists: false,
          },
          run: { controls: { can_start_automation: false, start_automation_reason: "Target sidecar is missing. Complete setup first." } },
        }),
        reason: "Target sidecar is missing",
      },
      {
        name: "running",
        snapshot: snapshot({
          run: {
            controls: { can_start_automation: false, start_automation_reason: "Automation is already running." },
            automation: { state: "running" },
          },
        }),
        reason: "Automation is already running",
      },
      {
        name: "critical stop",
        snapshot: snapshot({
          home: { automation_status: "CRITICAL_STOP" },
          run: { controls: { can_start_automation: false, start_automation_reason: "Critical stop recorded. Review before continuing." } },
        }),
        reason: "Critical stop recorded",
      },
    ];

    for (const state of states) {
      const start = buildCommandPaletteModel({ snapshot: state.snapshot }).find((command) => command.id === "start-automation");
      expect(start?.disabledReason, state.name).toContain(state.reason);
    }

    const ready = buildCommandPaletteModel({ snapshot: snapshot() }).find((command) => command.id === "start-automation");
    expect(ready?.disabledReason).toBeUndefined();
  });
});
