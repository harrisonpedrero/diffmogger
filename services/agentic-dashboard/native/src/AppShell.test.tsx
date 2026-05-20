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
    setup: { project_name: "Project", status: "ACTIVE", horizon: "demo", files: [] },
    scheduler: {},
    dag: {},
    tickets: {},
    human_input: {},
    validation_repair: {},
    controls: { automation: { state: "stopped" }, is_running: false },
    ...overrides,
  } as ProjectSnapshot;
}

describe("App shell", () => {
  it("renders the simplified routes in order", () => {
    const html = renderToStaticMarkup(<App />);
    const labels = ["Setup", "Automation"];
    const positions = labels.map((label) => html.indexOf(`data-sidebar-view="${label}"`));

    expect(positions.every((position) => position > -1)).toBe(true);
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
    expect(html).toContain('aria-label="Setup"');
    expect(html).toContain('aria-label="Automation"');
    expect(html).not.toContain('data-sidebar-view="Inbox"');
    expect(html).not.toContain('data-sidebar-view="Review"');
    expect(html).not.toContain('data-sidebar-view="Advanced"');
  });

  it("adds accessible names, titles, and live region hooks for shell controls", () => {
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

    expect(html).toContain("No project");
    expect(html).toContain("Choose folder");
    expect(html).toContain("Backend checks");
    expect(html).not.toContain("UNKNOWN");
  });

  it("renders the Automation placeholder when no project is selected", () => {
    const html = renderToStaticMarkup(<App initialView="Automation" />);

    expect(html).toContain("Choose Project");
    expect(html).toContain("scheduler state");
    expect(html).toContain("Open setup");
    expect(viewRequiresTarget("Automation")).toBe(true);
    expect(viewRequiresTarget("Setup")).toBe(false);
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
      controls: {
        automation: { state: "running" },
        is_running: false,
      },
    }))).toBe(AUTO_REFRESH_ACTIVE_INTERVAL_MS);
    expect(autoRefreshIntervalMs(snapshotWith({
      setup: { status: "ACTIVE_WITH_PENDING_USER_INPUT" },
      human_input: { pending_requests: 1 },
    }))).toBe(AUTO_REFRESH_ACTIVE_INTERVAL_MS);
  });

  it("waits past the refresh cadence before calling a snapshot overdue", () => {
    expect(autoRefreshOverdueMs(snapshotWith())).toBe(AUTO_REFRESH_IDLE_INTERVAL_MS * 2);
    expect(autoRefreshOverdueMs(snapshotWith({
      controls: {
        automation: { state: "running" },
        is_running: false,
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
    expect(hasDirtyRouteState({ Setup: "Unsaved setup changes." })).toBe(true);
    expect(hasBusyRouteState({ Automation: true })).toBe(true);
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
