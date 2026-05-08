import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ObservatoryPage } from "./ObservatoryPage";
import type { ObservatorySnapshot, ProjectSnapshot } from "./api/backend";

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends Array<infer U>
    ? Array<DeepPartial<U>>
    : T[K] extends object
      ? DeepPartial<T[K]>
      : T[K];
};

function projectSnapshot(): ProjectSnapshot {
  return {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    brief: {},
    run: { snapshot_generated_at: "2026-05-06T12:00:00+00:00" },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1 Runnable baseline",
      next_action: "Run Once Now",
      pending_human_requests: 0,
      unhandled_inbox: 0,
      queued_patches: 0,
      deferred_patches: 0,
    },
  };
}

function observatorySnapshot(overrides: DeepPartial<ObservatorySnapshot> = {}): ObservatorySnapshot {
  const base: ObservatorySnapshot = {
    schema_version: 1,
    generated_at: "2026-05-06T12:00:00+00:00",
    target: projectSnapshot().target,
    title: "Diffmogger Autonomous Build Log",
    subtitle: "Diffmogger Observatory view: replay-style automation progress reconstructed from conveyor events, commits, and diff stats.",
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
      health: { status: "ok", summary: "builder-first conveyor policy active." },
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
    signals: { active_count: 0, nudges: [], recent_completed: [] },
    timeline: [],
    metrics: { pending_human: 0, queued_patches: 0 },
  };
  return {
    ...base,
    ...overrides,
    mission: { ...base.mission, ...overrides.mission },
    conveyor: { ...base.conveyor, ...overrides.conveyor },
    progress: { ...base.progress, ...overrides.progress },
    patches: { ...base.patches, ...overrides.patches },
    signals: { ...base.signals, ...overrides.signals },
    metrics: { ...base.metrics, ...overrides.metrics },
  } as ObservatorySnapshot;
}

function render(initialSnapshot: ObservatorySnapshot | null, selectedProject = projectSnapshot()): string {
  return renderToStaticMarkup(
    <ObservatoryPage
      snapshot={selectedProject}
      loading={false}
      onChoose={() => undefined}
      onRefresh={() => undefined}
      initialSnapshot={initialSnapshot}
    />,
  );
}

describe("ObservatoryPage", () => {
  it("renders the empty state", () => {
    const html = renderToStaticMarkup(
      <ObservatoryPage snapshot={null} loading={false} onChoose={() => undefined} onRefresh={() => undefined} />,
    );

    expect(html).toContain("Diffmogger Autonomous Build Log");
    expect(html).toContain("Choose a project folder");
  });

  it("renders an active builder", () => {
    const html = render(
      observatorySnapshot({ conveyor: { active_run: { role: "builder", status: "running" } } }),
    );

    expect(html).toContain("builder is running");
    expect(html).toContain("Running now");
  });

  it("renders a queued patch", () => {
    const html = render(
      observatorySnapshot({
        conveyor: {
          roles: [
            { role: "planner", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
            { role: "builder", status: "next", badge: "next", tone: "info", reason: "Patch is queued.", counts: { queued: 2 } },
            { role: "hardener", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
            { role: "integrator", status: "standby", badge: "standby", tone: "quiet", reason: "", counts: {} },
          ],
        },
        patches: { queue_totals: { queued: 2, deferred: 0, applied: 0, failed: 0, skipped: 0 } },
      }),
    );

    expect(html).toContain("queued: 2");
    expect(html).toContain("Patch is queued.");
  });

  it("renders blocked user input", () => {
    const html = render(
      observatorySnapshot({
        mission: {
          automation_status: "BLOCKED_ON_USER",
          tags: [{ label: "Human", value: "1", tone: "warn" }],
        },
        metrics: { pending_human: 1 },
      }),
    );

    expect(html).toContain("Human input is needed");
    expect(html).toContain("BLOCKED_ON_USER");
  });

  it("renders a critical stop", () => {
    const html = render(observatorySnapshot({ mission: { automation_status: "CRITICAL_STOP" } }));

    expect(html).toContain("Critical stop is active");
    expect(html).toContain("CRITICAL_STOP");
  });
});
