import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReviewPage } from "./ReviewPage";
import type { ProjectSnapshot } from "./api/backend";

type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends Array<infer U>
    ? Array<DeepPartial<U>>
    : T[K] extends object
      ? DeepPartial<T[K]>
      : T[K];
};

function projectSnapshot(overrides: DeepPartial<ProjectSnapshot> = {}): ProjectSnapshot {
  const base: ProjectSnapshot = {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    brief: {},
    run: {
      human: { pending_requests: 1, unhandled_inbox: 0 },
      first_review: { status: "pending" },
      snapshot_generated_at: "2026-05-06T12:00:00+00:00",
    },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE_WITH_PENDING_USER_INPUT",
      current_horizon: "H1",
      next_action: "Review",
      pending_human_requests: 1,
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

describe("ReviewPage", () => {
  it("renders a nonblank evidence stack before command data loads", () => {
    const html = renderToStaticMarkup(
      <ReviewPage
        snapshot={projectSnapshot()}
        loading={false}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Review marker");
    expect(html).toContain("Safety check");
    expect(html).toContain("Verification");
    expect(html).toContain("Changed files");
    expect(html).toContain("Human input");
    expect(html).toContain("Markdown preview");
    expect(html).toContain("Export and artifacts");
    expect(html).toContain("Next-run note");
  });

  it("places human input before the stretched verification summary", () => {
    const html = renderToStaticMarkup(
      <ReviewPage
        snapshot={projectSnapshot()}
        loading={false}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    const summaryStart = html.indexOf("review-trust-summary");
    const summaryHtml = html.slice(summaryStart, html.indexOf("Next action"));

    expect(summaryStart).toBeGreaterThan(-1);
    expect(summaryHtml.indexOf("Human input")).toBeLessThan(summaryHtml.indexOf("Verification"));
    expect(summaryHtml).toContain('class="review-trust-item wide"');
  });

  it("preserves the unavailable state when setup has not produced a runnable task", () => {
    const html = renderToStaticMarkup(
      <ReviewPage
        snapshot={projectSnapshot({ target: { automation_task_exists: false } })}
        loading={false}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Review unavailable");
    expect(html).toContain("Complete setup and run once");
  });
});
