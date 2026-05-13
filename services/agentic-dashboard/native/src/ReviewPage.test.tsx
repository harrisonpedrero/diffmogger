import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReviewPage } from "./ReviewPage";
import type { ProjectSnapshot, ReviewSnapshot } from "./api/backend";
import { buildReviewDecision } from "./reviewModel";

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
      controls: { is_running: false },
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

function reviewSnapshot(overrides: DeepPartial<ReviewSnapshot> = {}): ReviewSnapshot {
  const base: ReviewSnapshot = {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    generated_at: "2026-05-06T12:00:00+00:00",
    review_fingerprint: "fingerprint-current",
    latest_run: {
      status: "STOPPED",
      horizon: "H1",
      summary: "Automation stopped after the latest run.",
      action_plan: {},
    },
    changed_files: [],
    changed_files_source: "git_status",
    latest_commits: [],
    verification: {
      summary: "No validation results recorded yet.",
      counts: { pass: 0, fail: 0, warn: 0, pending: 0 },
      items: [],
    },
    safety: { status: "pending", summary: "Integration-safety check has not run yet." },
    limitations: [],
    self_review: {
      markdown_preview: "# Diffmogger Self-Review Snapshot",
      truncated: false,
      default_markdown_path: "/tmp/project/.diffmogger/runtime/first-review/Diffmogger-self-review.md",
    },
    bundle: {
      review_dir: "/tmp/project/.diffmogger/runtime/first-review",
      html_path: "/tmp/project/.diffmogger/runtime/first-review/Diffmogger-observatory.html",
      markdown_path: "/tmp/project/.diffmogger/runtime/first-review/Diffmogger-self-review.md",
    },
    reviewed: {
      exists: false,
      path: "/tmp/project/.diffmogger/agentic/reviewed.json",
      reviewed_at: "",
      note: "",
      snapshot_generated_at: "",
      review_fingerprint: "",
      is_current_snapshot: false,
    },
  };
  return {
    ...base,
    ...overrides,
    target: { ...base.target, ...overrides.target },
    latest_run: { ...base.latest_run, ...overrides.latest_run },
    verification: { ...base.verification, ...overrides.verification },
    self_review: { ...base.self_review, ...overrides.self_review },
    bundle: { ...base.bundle, ...overrides.bundle },
    reviewed: { ...base.reviewed, ...overrides.reviewed },
    changed_files: overrides.changed_files ?? base.changed_files,
    latest_commits: overrides.latest_commits ?? base.latest_commits,
    limitations: overrides.limitations ?? base.limitations,
  } as ReviewSnapshot;
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

    expect(html).toContain("Latest Run Review");
    expect(html).not.toContain("Latest stable outcome");
    expect(html).toContain("Review marker");
    expect(html).toContain("Stable snapshot");
    expect(html).not.toContain("Outcome review");
    expect(html).toContain("Safety check");
    expect(html).toContain("Verification");
    expect(html).toContain("Changed files");
    expect(html).toContain("Human input");
    expect(html).toContain("Markdown preview");
    expect(html).toContain("Review export");
    expect(html).toContain("Open Inbox");
    expect(html).not.toContain("Next-run note");
    expect(html).not.toContain("Send follow-up");
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

  it("disables final review while automation is live", () => {
    const decision = buildReviewDecision(
      projectSnapshot({
        run: { controls: { is_running: true } },
      }),
      null,
    );

    expect(decision.mode).toBe("live");
    expect(decision.title).toBe("Run in progress");
    expect(decision.primaryAction.enabled).toBe(false);
    expect(decision.primaryAction.label).toBe("Review available when run finishes");
    expect(decision.exportLabel).toBe("Export current snapshot");
  });

  it("does not treat ACTIVE task status as a running process", () => {
    const decision = buildReviewDecision(
      projectSnapshot({
        run: { task: { status: "ACTIVE" }, human: { pending_requests: 0, unhandled_inbox: 0 } },
        home: { automation_status: "ACTIVE", pending_human_requests: 0, unhandled_inbox: 0 },
      }),
      reviewSnapshot(),
    );

    expect(decision.mode).toBe("outcome");
    expect(decision.primaryAction.enabled).toBe(true);
  });

  it("enables review for a stable unreviewed snapshot", () => {
    const decision = buildReviewDecision(
      projectSnapshot({
        run: { task: { status: "STOPPED" }, human: { pending_requests: 0, unhandled_inbox: 0 } },
        home: { automation_status: "STOPPED", pending_human_requests: 0, unhandled_inbox: 0 },
      }),
      reviewSnapshot(),
    );

    expect(decision.mode).toBe("outcome");
    expect(decision.primaryAction.enabled).toBe(true);
    expect(decision.primaryAction.label).toBe("Mark latest snapshot reviewed");
  });

  it("recognizes an already reviewed stable snapshot", () => {
    const decision = buildReviewDecision(
      projectSnapshot({
        run: { task: { status: "STOPPED" }, human: { pending_requests: 0, unhandled_inbox: 0 } },
        home: { automation_status: "STOPPED", pending_human_requests: 0, unhandled_inbox: 0 },
      }),
      reviewSnapshot({
        reviewed: {
          exists: true,
          reviewed_at: "2026-05-06T12:05:00+00:00",
          snapshot_generated_at: "2026-05-06T12:00:00+00:00",
          review_fingerprint: "fingerprint-current",
          is_current_snapshot: true,
        },
      }),
    );

    expect(decision.mode).toBe("already_reviewed");
    expect(decision.title).toBe("Already reviewed");
    expect(decision.primaryAction.enabled).toBe(false);
  });

  it("flags new evidence after an older review", () => {
    const decision = buildReviewDecision(
      projectSnapshot({
        run: { task: { status: "STOPPED" }, human: { pending_requests: 0, unhandled_inbox: 0 } },
        home: { automation_status: "STOPPED", pending_human_requests: 0, unhandled_inbox: 0 },
      }),
      reviewSnapshot({
        reviewed: {
          exists: true,
          reviewed_at: "2026-05-06T11:30:00+00:00",
          snapshot_generated_at: "2026-05-06T11:25:00+00:00",
          review_fingerprint: "older-fingerprint",
          is_current_snapshot: false,
        },
      }),
    );

    expect(decision.mode).toBe("new_evidence");
    expect(decision.title).toBe("New evidence since review");
    expect(decision.primaryAction.enabled).toBe(true);
  });

  it("routes human-input follow-up to Inbox instead of a Review note form", () => {
    const decision = buildReviewDecision(
      projectSnapshot({
        run: { task: { status: "STOPPED" }, human: { pending_requests: 1, unhandled_inbox: 0 } },
        home: { automation_status: "STOPPED", pending_human_requests: 1, unhandled_inbox: 0 },
      }),
      reviewSnapshot(),
    );

    expect(decision.hasHumanBlocker).toBe(true);
    expect(decision.primaryAction.enabled).toBe(false);
    expect(decision.primaryAction.label).toBe("Resolve Inbox before review");
  });
});
