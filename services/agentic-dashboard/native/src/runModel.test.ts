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
        can_run_now: true,
        can_start_schedule: true,
        can_pause_schedule: false,
        can_remove_schedule: false,
        can_run_safety_check: true,
      },
      schedule: {
        state: "not_installed",
        message: "Schedule is ready to start.",
        strategy_label: "Periodic sprint",
        cadence_seconds: 3600,
        active_labels: ["com.diffmogger.automation.project"],
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

    expect(model.banner.primaryAction.label).toBe("Choose Project");
    expect(model.controls.runOnce.enabled).toBe(false);
    expect(model.controls.startSchedule.enabled).toBe(false);
    expect(model.controls.pauseSchedule.enabled).toBe(false);
    expect(model.controls.removeSchedule.enabled).toBe(false);
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
            can_run_now: false,
            can_start_schedule: false,
            can_pause_schedule: false,
            can_remove_schedule: false,
            can_run_safety_check: false,
          },
        },
      }),
    );

    expect(model.banner.headline).toBe("Finish the Brief before running automation.");
    expect(model.banner.primaryAction.label).toBe("Go to Brief");
    expect(model.controls.runOnce.enabled).toBe(false);
    expect(model.controls.startSchedule.enabled).toBe(false);
    expect(model.controls.safetyCheck.enabled).toBe(false);
    expect(model.controls.removeSchedule.enabled).toBe(false);
  });

  it("enables Run Once Now and Start Schedule for ready scaffolded targets", () => {
    const model = buildRunModel(snapshot());

    expect(model.banner.primaryAction.label).toBe("Run Once Now");
    expect(model.controls.runOnce.enabled).toBe(true);
    expect(model.controls.startSchedule.enabled).toBe(true);
    expect(model.controls.pauseSchedule.enabled).toBe(false);
    expect(model.controls.removeSchedule.enabled).toBe(false);
    expect(model.controls.safetyCheck.enabled).toBe(true);
  });

  it("disables launch controls while a run is active", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            is_running: true,
            can_run_now: false,
            can_start_schedule: false,
            can_pause_schedule: true,
            can_remove_schedule: false,
            can_run_safety_check: true,
          },
          schedule: { state: "running", message: "Schedule is running via launchd." },
          task: { status: "RUNNING" },
        },
      }),
    );

    expect(model.isRunning).toBe(true);
    expect(model.controls.runOnce.enabled).toBe(false);
    expect(model.controls.startSchedule.enabled).toBe(false);
    expect(model.controls.pauseSchedule.enabled).toBe(true);
    expect(model.controls.removeSchedule.enabled).toBe(false);
  });

  it("enables Pause Schedule only when a schedule is running", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_run_now: true,
            can_start_schedule: true,
            can_pause_schedule: true,
            can_remove_schedule: true,
            can_run_safety_check: true,
          },
          schedule: { state: "running", message: "Schedule is running via launchd.", can_remove: true },
        },
      }),
    );

    expect(model.controls.pauseSchedule.enabled).toBe(true);
    expect(model.controls.removeSchedule.enabled).toBe(true);
    expect(model.schedule.canRemove).toBe(true);
  });

  it("keeps Pause Schedule disabled for installed schedules that are not running", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_run_now: true,
            can_start_schedule: true,
            can_pause_schedule: true,
            pause_schedule_reason: "Schedule plist exists but is not loaded.",
            can_remove_schedule: true,
            can_run_safety_check: true,
          },
          schedule: { state: "installed", message: "Schedule plist exists but is not loaded.", can_remove: true },
        },
      }),
    );

    expect(model.controls.pauseSchedule.enabled).toBe(false);
    expect(model.controls.removeSchedule.enabled).toBe(true);
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

    expect(model.worker.headline).toBe("Recommended: one read-only review worker for builder work.");
    expect(model.worker.actions.readOnly.enabled).toBe(true);
    expect(model.worker.actions.write.enabled).toBe(false);
  });
});
