import { describe, expect, it } from "vitest";
import type { ObservatorySnapshot } from "./api/backend";
import { buildObservatoryViewModel } from "./observatoryModel";

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends Array<infer U>
    ? Array<DeepPartial<U>>
    : T[K] extends object
      ? DeepPartial<T[K]>
      : T[K];
};

function snapshot(overrides: DeepPartial<ObservatorySnapshot> = {}): ObservatorySnapshot {
  const base: ObservatorySnapshot = {
    schema_version: 1,
    generated_at: "2026-05-06T12:00:00+00:00",
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    title: "Activity",
    subtitle: "Run, queue, commit, and check state from the selected target.",
    mission: {
      project_name: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1 Runnable baseline",
      mission_text: "Keep the automation moving.",
      best_next_milestone: "Ship the next small demo.",
      known_issue: "No active issue summary.",
      tags: [{ label: "Human", value: "0", tone: "good" }],
    },
    scorecard: { status: "clear", summary: "All clear.", counts: [] },
    conveyor: {
      cycles: 1,
      roles: [
        { role: "planner", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
        { role: "builder", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
        { role: "hardener", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
        { role: "integrator", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
      ],
      active_run: {},
      decision_queue: [],
      health: { status: "ok" },
    },
    progress: {
      story: "No progress pulse yet.",
      latest_landed_work: {},
      landed_work_feed: [],
      recent_outcomes: [],
    },
    validation_safety: { validation: {}, integration_safety: {}, baseline_verification: {} },
    patches: {
      queue_totals: { queued: 0, deferred: 0, applied: 0, failed: 0, skipped: 0 },
      manifests: [],
      deferred_backlog: [],
      recent_outcomes: [],
    },
    timeline: [],
    metrics: { pending_human: 0, queued_patches: 0 },
  };
  return {
    ...base,
    ...overrides,
    mission: { ...base.mission, ...overrides.mission },
    conveyor: { ...base.conveyor, ...overrides.conveyor },
    patches: { ...base.patches, ...overrides.patches },
    metrics: { ...base.metrics, ...overrides.metrics },
  } as ObservatorySnapshot;
}

describe("buildObservatoryViewModel", () => {
  it("covers the empty state", () => {
    const model = buildObservatoryViewModel(null);

    expect(model.empty).toBe(true);
    expect(model.headline).toBe("Activity");
    expect(model.tabs).toEqual(["Summary", "Events", "Queue", "Metrics"]);
  });

  it("covers an active builder", () => {
    const model = buildObservatoryViewModel(
      snapshot({ conveyor: { active_run: { role: "builder", status: "running" } } }),
    );

    expect(model.activeRole).toBe("builder");
    expect(model.headline).toBe("builder is running");
    expect(model.tone).toBe("good");
  });

  it("covers a queued patch", () => {
    const model = buildObservatoryViewModel(
      snapshot({ patches: { queue_totals: { queued: 2, deferred: 0, applied: 0, failed: 0, skipped: 0 } } }),
    );

    expect(model.hasQueuedPatch).toBe(true);
  });

  it("covers blocked user input", () => {
    const model = buildObservatoryViewModel(
      snapshot({
        mission: {
          automation_status: "BLOCKED_ON_USER",
          tags: [{ label: "Human", value: "1", tone: "warn" }],
        },
        metrics: { pending_human: 1 },
      }),
    );

    expect(model.needsHuman).toBe(true);
    expect(model.headline).toBe("Input needed");
    expect(model.tone).toBe("warn");
  });

  it("covers critical stop", () => {
    const model = buildObservatoryViewModel(
      snapshot({ mission: { automation_status: "CRITICAL_STOP" } }),
    );

    expect(model.criticalStop).toBe(true);
    expect(model.headline).toBe("Critical stop is active");
    expect(model.tone).toBe("critical");
  });
});
