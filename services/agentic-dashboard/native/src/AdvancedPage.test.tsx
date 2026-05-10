import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AdvancedPage } from "./AdvancedPage";
import type { ProjectSnapshot } from "./api/backend";

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
    files: [
      {
        key: "monitor.automation_tasks",
        label: "Automation Tasks",
        rel_path: ".diffmogger/state/CODEX_AUTOMATION_TASKS.md",
        group: "monitor",
        category: "Core state",
        exists: true,
        editable: true,
        size_bytes: 128,
        modified_at: "2026-05-06T12:00:00+00:00",
      },
    ],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1",
      next_action: "Run",
      pending_human_requests: 0,
      unhandled_inbox: 0,
      queued_patches: 0,
      deferred_patches: 0,
    },
  };
}

describe("AdvancedPage", () => {
  it("renders Sidecar files, diagnostics, settings, and debug bundle tabs", () => {
    const html = renderToStaticMarkup(
      <AdvancedPage
        snapshot={projectSnapshot()}
        loading={false}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Sidecar");
    expect(html).toContain("Managed files");
    expect(html).toContain('role="tablist"');
    expect(html).toContain("Files");
    expect(html).toContain("Diagnostics");
    expect(html).toContain("Settings");
    expect(html).toContain("Debug bundle");
    expect(html).toContain("Automation Tasks");
  });
});
