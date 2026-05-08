import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { buildHomeModel } from "./homeModel";

function snapshot(overrides: Record<string, any> = {}): ProjectSnapshot {
  const base: ProjectSnapshot = {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    brief: {
      project_name: "Project",
      project_mode: "fresh_project",
      context_files: [],
      intake: {},
      dashboard_state: {},
    },
    run: {
      task: {
        status: "ACTIVE",
        horizon: "H1 Runnable baseline",
        validation: {
          counts: { pass: 1, fail: 0, pending: 0 },
          summary: "1 pass, 0 fail.",
        },
        integration_safety: {
          status: "pass",
          summary: "Latest recorded integration-safety check passed.",
        },
      },
      human: {
        pending_requests: 0,
        unhandled_inbox: 0,
        outbound_records: 0,
      },
      git: {
        branch: "main",
        dirty_count: 0,
        commits: [],
        recent_commits: [],
      },
      queue: {
        totals: { queued: 0, deferred: 0, applied: 0 },
        recent_outcomes: [],
      },
      conveyor: {
        cycles: 1,
        active_role_run: {},
        history: [{ role: "builder", status: "completed", progress_success: true }],
      },
      progress: {
        accepted_total: 1,
        deferred_queue_depth: 0,
        recent_activity: "builder completed a useful increment.",
      },
      scorecard: {
        action_plan: {
          lane: "builder",
          recommendation: "Continue with the builder lane.",
          why: "No blocker outranks builder work.",
        },
        items: [],
      },
      first_review: { status: "ready" },
      worker_strategy: {},
      review: {},
      baseline_verification: {},
    },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1 Runnable baseline",
      next_action: "Continue with the builder lane.",
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
    brief: { ...base.brief, ...overrides.brief },
    run: { ...base.run, ...overrides.run },
    home: { ...base.home, ...overrides.home },
  };
}

describe("buildHomeModel", () => {
  it("maps no target to folder selection", () => {
    const model = buildHomeModel(null);

    expect(model.primaryAction).toMatchObject({
      label: "Choose Project Folder",
      kind: "choose-project",
    });
    expect(model.headline).not.toContain("UNKNOWN");
    expect(model.metrics.map((metric) => metric.value)).toEqual(["N/A", "N/A", "N/A", "N/A", "N/A", "N/A"]);
  });

  it("maps unconfigured targets to Brief without a scaffold CTA", () => {
    const model = buildHomeModel(
      snapshot({
        target: {
          path: "/tmp/project",
          name: "project",
          is_diffmogger_project: false,
          project_intake_exists: false,
          dashboard_state_exists: false,
          automation_task_exists: false,
        },
        home: { automation_status: "UNKNOWN" },
      }),
    );

    expect(model.headline).toBe("This project is not configured yet");
    expect(model.primaryAction).toMatchObject({
      label: "Continue Brief",
      kind: "navigate",
      route: "Brief",
    });
    expect(model.primaryAction.label).not.toContain("Scaffold");
  });

  it("maps scaffolded targets with no runs to Run Once Now", () => {
    const model = buildHomeModel(
      snapshot({
        run: {
          conveyor: { cycles: 0, active_role_run: {}, history: [] },
          progress: { accepted_total: 0, recent_activity: "No multi-role activity recorded yet." },
          queue: { totals: { queued: 0, deferred: 0 }, recent_outcomes: [] },
        },
        home: { automation_status: "ACTIVE" },
      }),
    );

    expect(model.headline).toBe("Ready for the first automation run");
    expect(model.primaryAction).toMatchObject({
      label: "Run Once Now",
      route: "Run",
    });
  });

  it("maps running targets to the Run page", () => {
    const model = buildHomeModel(
      snapshot({
        run: {
          conveyor: {
            cycles: 2,
            active_role_run: { role: "builder", status: "running" },
            history: [],
          },
        },
      }),
    );

    expect(model.headline).toBe("builder lane is running");
    expect(model.primaryAction).toMatchObject({
      label: "Open Run",
      route: "Run",
    });
  });

  it("maps blocked human input to Inbox", () => {
    const model = buildHomeModel(
      snapshot({
        run: {
          task: { status: "BLOCKED_ON_USER" },
          human: { pending_requests: 1, unhandled_inbox: 0, outbound_records: 0 },
        },
        home: { pending_human_requests: 1 },
      }),
    );

    expect(model.headline).toBe("User input is needed");
    expect(model.primaryAction).toMatchObject({
      label: "Open Inbox",
      route: "Inbox",
    });
  });

  it("maps environment blockers to Review", () => {
    const model = buildHomeModel(
      snapshot({
        run: {
          task: {
            status: "BLOCKED_ON_ENVIRONMENT",
            validation: {
              counts: { pass: 0, fail: 1, pending: 0 },
              summary: "1 validation failure.",
            },
            integration_safety: {
              status: "fail",
              summary: "Integration safety failed.",
            },
          },
        },
      }),
    );

    expect(model.headline).toBe("Diffmogger is blocked");
    expect(model.primaryAction).toMatchObject({
      label: "Open Review",
      route: "Review",
    });
  });
});
