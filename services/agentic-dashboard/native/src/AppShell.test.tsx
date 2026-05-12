import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App, {
  AUTO_REFRESH_ACTIVE_INTERVAL_MS,
  AUTO_REFRESH_FOCUS_STALE_MS,
  AUTO_REFRESH_IDLE_INTERVAL_MS,
  AUTO_REFRESH_MIN_OVERDUE_MS,
  autoRefreshBlocker,
  autoRefreshIntervalMs,
  autoRefreshOverdueMs,
  buildAutoRefreshChipState,
  canAutoRefreshProject,
  hasBusyRouteState,
  hasDirtyRouteState,
  shouldRefreshOnFocus,
  viewRequiresTarget,
} from "./App";
import type { ProjectSnapshot } from "./api/backend";

function snapshotWith(overrides: Partial<ProjectSnapshot> = {}): ProjectSnapshot {
  return {
    target: {
      path: "/tmp/project",
      name: "Project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    brief: {},
    run: {
      automation: { state: "stopped" },
      controls: { is_running: false },
      conveyor: {},
      human: {},
    },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "demo",
      next_action: "Keep going.",
      pending_human_requests: 0,
      unhandled_inbox: 0,
      queued_patches: 0,
      deferred_patches: 0,
    },
    ...overrides,
  } as ProjectSnapshot;
}

describe("App shell", () => {
  it("renders the preserved sidebar routes in order", () => {
    const html = renderToStaticMarkup(<App />);
    const labels = ["Home", "Brief", "Run", "Observatory", "Inbox", "Review", "Advanced"];
    const positions = labels.map((label) => html.indexOf(`data-sidebar-view="${label}"`));

    expect(positions.every((position) => position > -1)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(html).toContain('aria-label="Home"');
    expect(html).toContain('title="Home"');
    expect(html).toContain('aria-label="Run"');
    expect(html).toContain('aria-label="Inbox"');
    expect(html).toContain('aria-label="Sidecar"');
  });

  it("exposes display aliases and legacy aliases on the icon-only rail", () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('data-testid="primary-icon-rail"');
    expect(html).toContain('data-testid="sidebar-nav-Home"');
    expect(html).toContain('data-aliases="Home Control Room"');
    expect(html).toContain('data-aliases="Setup Brief"');
    expect(html).toContain('data-aliases="Activity Observatory"');
    expect(html).toContain('data-aliases="Inbox Handoffs"');
    expect(html).toContain('data-aliases="Sidecar Advanced"');
    expect(html).not.toContain('data-sidebar-view="Settings"');
  });

  it("adds accessible names, titles, and live region hooks for icon-only shell controls", () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('aria-label="Close"');
    expect(html).toContain('title="Close"');
    expect(html).toContain('aria-label="Refresh target"');
    expect(html).toContain('title="Refresh target"');
    expect(html).toContain('aria-label="Open command palette"');
    expect(html).toContain('data-testid="shell-live-region"');
    expect(html).toContain('aria-live="polite"');
  });

  it("renders useful no-target startup state without raw UNKNOWN", () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain("No target");
    expect(html).toContain("Choose project");
    expect(html).toContain("Backend checks");
    expect(html).not.toContain("UNKNOWN");
  });

  it("renders page-specific placeholders when target-required pages are selected without a project", () => {
    const html = renderToStaticMarkup(<App initialView="Run" />);

    expect(html).toContain("Select a project to run jobs");
    expect(html).toContain("Choose project");
    expect(html).toContain("Open setup");
    expect(html).not.toContain("Choose a project to begin");
    expect(viewRequiresTarget("Run")).toBe(true);
    expect(viewRequiresTarget("Brief")).toBe(false);
  });

  it("renders nonblank targetless placeholders for every target-required surface", () => {
    const expectations = [
      ["Run", "Select a project to run jobs"],
      ["Observatory", "Select a project to view activity"],
      ["Inbox", "Select a project to open Inbox"],
      ["Review", "Select a project to review a run"],
      ["Advanced", "Select a project to inspect Sidecar"],
    ] as const;

    for (const [view, copy] of expectations) {
      const html = renderToStaticMarkup(<App initialView={view} />);
      expect(html).toContain(copy);
      expect(html).toContain("Choose project");
    }
  });

  it("exposes project switch and close actions from the project chip menu", () => {
    const html = renderToStaticMarkup(<App initialProjectMenuOpen />);

    expect(html).toContain("Switch project...");
    expect(html).toContain("New project");
    expect(html).toContain("Close Project");
  });

  it("chooses a polite auto-refresh cadence from target activity", () => {
    expect(autoRefreshIntervalMs(null)).toBe(AUTO_REFRESH_IDLE_INTERVAL_MS);
    expect(autoRefreshIntervalMs(snapshotWith())).toBe(AUTO_REFRESH_IDLE_INTERVAL_MS);
    expect(autoRefreshIntervalMs(snapshotWith({
      run: {
        automation: { state: "running" },
        controls: { is_running: false },
        conveyor: {},
        human: {},
      },
    }))).toBe(AUTO_REFRESH_ACTIVE_INTERVAL_MS);
    expect(autoRefreshIntervalMs(snapshotWith({
      home: {
        title: "Project",
        automation_status: "ACTIVE_WITH_PENDING_USER_INPUT",
        current_horizon: "demo",
        next_action: "Answer a question.",
        pending_human_requests: 1,
        unhandled_inbox: 0,
        queued_patches: 0,
        deferred_patches: 0,
      },
    }))).toBe(AUTO_REFRESH_ACTIVE_INTERVAL_MS);
  });

  it("waits past the refresh cadence before calling a snapshot overdue", () => {
    expect(autoRefreshOverdueMs(snapshotWith())).toBe(AUTO_REFRESH_IDLE_INTERVAL_MS * 2);
    expect(autoRefreshOverdueMs(snapshotWith({
      run: {
        automation: { state: "running" },
        controls: { is_running: false },
        conveyor: {},
        human: {},
      },
    }))).toBe(AUTO_REFRESH_MIN_OVERDUE_MS);

    const loadedAt = 1_000;
    const beforeOverdue = buildAutoRefreshChipState({
      lastUpdatedAt: loadedAt,
      now: loadedAt + AUTO_REFRESH_IDLE_INTERVAL_MS + 1,
      refreshing: false,
      pauseReason: null,
      overdueMs: autoRefreshOverdueMs(snapshotWith()),
    });
    const overdue = buildAutoRefreshChipState({
      lastUpdatedAt: loadedAt,
      now: loadedAt + autoRefreshOverdueMs(snapshotWith()) + 1,
      refreshing: false,
      pauseReason: null,
      overdueMs: autoRefreshOverdueMs(snapshotWith()),
    });

    expect(beforeOverdue.label).toContain("Updated");
    expect(overdue.label).toBe("Refresh delayed");
    expect(overdue.tone).toBe("warn");
  });

  it("explains why quiet auto-refresh is paused or failed", () => {
    expect(autoRefreshBlocker({
      hasSelectedTarget: true,
      loadState: "loaded",
      refreshInFlight: false,
      hasDirtyRoutes: true,
      hasBusyCommands: false,
    })).toBe("dirty_route");

    const paused = buildAutoRefreshChipState({
      lastUpdatedAt: 1_000,
      now: 140_000,
      refreshing: false,
      pauseReason: "dirty_route",
      pauseDetail: "Setup has unsaved plan changes.",
      overdueMs: AUTO_REFRESH_MIN_OVERDUE_MS,
    });
    const failed = buildAutoRefreshChipState({
      lastUpdatedAt: 1_000,
      now: 140_000,
      refreshing: false,
      pauseReason: null,
      failureMessage: "Backend CLI did not return valid JSON.",
      overdueMs: AUTO_REFRESH_MIN_OVERDUE_MS,
    });

    expect(paused.label).toBe("Auto-refresh paused");
    expect(paused.title).toContain("Setup has unsaved plan changes.");
    expect(paused.paused).toBe(true);
    expect(failed.label).toBe("Refresh failed");
    expect(failed.title).toContain("Backend CLI did not return valid JSON.");
  });

  it("guards quiet auto-refresh while the dashboard is already busy or locally dirty", () => {
    expect(hasDirtyRouteState({ Brief: "Unsaved setup changes." })).toBe(true);
    expect(hasBusyRouteState({ Run: true })).toBe(true);
    expect(canAutoRefreshProject({
      hasSelectedTarget: true,
      loadState: "loaded",
      refreshInFlight: false,
      hasDirtyRoutes: false,
      hasBusyCommands: false,
    })).toBe(true);
    expect(canAutoRefreshProject({
      hasSelectedTarget: true,
      loadState: "loaded",
      refreshInFlight: false,
      hasDirtyRoutes: true,
      hasBusyCommands: false,
    })).toBe(false);
    expect(canAutoRefreshProject({
      hasSelectedTarget: true,
      loadState: "loading",
      refreshInFlight: false,
      hasDirtyRoutes: false,
      hasBusyCommands: false,
    })).toBe(false);
  });

  it("refreshes on focus only after the loaded snapshot is stale", () => {
    const loadedAt = 1_000;

    expect(shouldRefreshOnFocus(null, loadedAt + AUTO_REFRESH_FOCUS_STALE_MS)).toBe(false);
    expect(shouldRefreshOnFocus(loadedAt, loadedAt + AUTO_REFRESH_FOCUS_STALE_MS - 1)).toBe(false);
    expect(shouldRefreshOnFocus(loadedAt, loadedAt + AUTO_REFRESH_FOCUS_STALE_MS)).toBe(true);
  });
});
