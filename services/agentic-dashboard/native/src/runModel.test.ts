import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { buildRunModel } from "./runModel";

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
      task: {
        status: "ACTIVE",
        horizon: "H1 Runnable baseline",
        last_updated: "2026-05-06T12:00:00+00:00",
      },
      controls: {
        is_scaffolded: true,
        is_running: false,
        can_start_automation: true,
        can_stop_automation: false,
        can_run_safety_check: true,
      },
      automation: {
        state: "stopped",
        message: "Continuous automation is ready to start.",
      },
      worker_strategy: {
        strategy: "NO_WORKERS",
        parallelism_budget: 0,
        action_lane: "builder",
      },
      worker_controls: {
        can_run_read_only: false,
        can_run_write: false,
        can_run_integrator: false,
      },
      latest_worker_result: { label: "Latest worker result: none yet." },
      environment_blockers: [],
    },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1 Runnable baseline",
      next_action: "Continue builder work.",
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
  };
}

describe("buildRunModel", () => {
  it("disables run controls when no target is selected", () => {
    const model = buildRunModel(null);

    expect(model.banner.primaryAction.label).toBe("Choose project");
    expect(model.controls.startAutomation.enabled).toBe(false);
    expect(model.controls.stopAutomation.enabled).toBe(false);
  });

  it("maps unscaffolded targets to the Brief gate", () => {
    const model = buildRunModel(
      snapshot({
        target: {
          path: "/tmp/project",
          name: "project",
          is_diffmogger_project: false,
          project_intake_exists: false,
          dashboard_state_exists: false,
          automation_task_exists: false,
        },
        run: {
          controls: {
            is_scaffolded: false,
            can_start_automation: false,
            can_stop_automation: false,
            can_run_safety_check: false,
          },
        },
      }),
    );

    expect(model.banner.headline).toBe("Unknown");
    expect(model.banner.primaryAction.label).toBe("Open setup");
    expect(model.controls.startAutomation.enabled).toBe(false);
    expect(model.controls.safetyCheck.enabled).toBe(false);
  });

  it("enables Start for ready scaffolded targets", () => {
    const model = buildRunModel(snapshot());

    expect(model.banner.primaryAction.label).toBe("Start");
    expect(model.controls.startAutomation.enabled).toBe(true);
    expect(model.controls.stopAutomation.enabled).toBe(false);
    expect(model.controls.safetyCheck.enabled).toBe(true);
  });

  it("labels a missing first safety result as pending", () => {
    const model = buildRunModel(snapshot());
    const safety = model.safety.find((row) => row.label === "Integration safety");

    expect(safety).toMatchObject({
      status: "pending",
      summary: "Integration-safety check has not run yet.",
      tone: "warn",
    });
  });

  it("disables start controls while automation is active", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            is_running: true,
            can_start_automation: false,
            can_stop_automation: true,
            can_run_safety_check: true,
          },
          automation: { state: "running", message: "Continuous automation is running." },
          task: { status: "RUNNING" },
        },
      }),
    );

    expect(model.isRunning).toBe(true);
    expect(model.controls.startAutomation.enabled).toBe(false);
    expect(model.controls.stopAutomation.enabled).toBe(true);
  });

  it("enables Stop only when automation is running", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_start_automation: false,
            can_stop_automation: true,
            can_run_safety_check: true,
          },
          automation: { state: "running", message: "Continuous automation is running." },
        },
      }),
    );

    expect(model.controls.stopAutomation.enabled).toBe(true);
  });

  it("keeps Stop disabled when automation is stopped", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_start_automation: true,
            can_stop_automation: false,
            stop_automation_reason: "No automation is running.",
            can_run_safety_check: true,
          },
          automation: { state: "stopped", message: "Continuous automation is ready to start." },
        },
      }),
    );

    expect(model.controls.stopAutomation.enabled).toBe(false);
  });

  it("translates read-only worker strategy strings into human copy", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          worker_strategy: {
            strategy: "READ_ONLY_REPORTS",
            parallelism_budget: 1,
            action_lane: "builder",
          },
          worker_controls: {
            can_run_read_only: true,
            read_only_reason: "Supported by current worker strategy.",
          },
        },
      }),
    );

    expect(model.worker.headline).toBe("Recommended: one read-only builder report");
    expect(model.worker.mode).toBe("Read-only report");
    expect(model.worker.focus).toBe("builder lane");
    expect(model.worker.output).toBe("target/agent_runs/<run-id>/worker_builder_strategy.md");
    expect(model.worker.actions.readOnly.enabled).toBe(true);
    expect(model.worker.actions.write.enabled).toBe(false);
  });
});
