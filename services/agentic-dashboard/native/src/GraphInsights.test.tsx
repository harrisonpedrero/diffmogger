import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { GraphInsightsPanel, buildGraphInsightsModel } from "./GraphInsights";

function snapshot(state: Record<string, unknown>): ProjectSnapshot {
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
    run: {
      automation: { state: "stopped" },
      controls: { is_running: false },
      conveyor: {},
      human: {},
      state,
    },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1",
      next_action: "Run.",
      pending_human_requests: 0,
      unhandled_inbox: 0,
      queued_patches: 0,
      deferred_patches: 0,
    },
  };
}

function graphState(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    codebase_graph_summary: {
      exists: true,
      indexed_file_count: 12,
      command_node_count: 3,
      test_node_count: 4,
      stale_node_count: 0,
      node_counts: { file: 8, test_file: 4 },
    },
    indexed_file_count: 12,
    command_node_count: 3,
    test_node_count: 4,
    stale_node_count: 0,
    task_graph_summary: {
      exists: true,
      ready_task_count: 2,
      blocked_task_count: 1,
      dependency_cycle_count: 0,
      node_counts: { ticket: 3 },
    },
    active_task_code_impacts: [
      {
        task: { id: "TICKET-001", name: "Auth polish" },
        node: { node_id: "file:src/auth.ts", kind: "file", path: "src/auth.ts" },
        edge_kind: "likely_touches",
        confidence: 0.91,
        reason: "path mention in ticket summary",
      },
    ],
    context_pack_preview: {
      item_count: 2,
      bounded: true,
      items: [
        {
          node_id: "file:src/auth.ts",
          kind: "file",
          category: "files",
          path: "src/auth.ts",
          confidence: 0.91,
          reason: "path mention in ticket summary",
          raw_contents: "SECRET_SOURCE_BODY",
          raw_contents_included: false,
        },
        {
          node_id: "file:tests/auth.test.ts",
          kind: "test_file",
          category: "tests",
          path: "tests/auth.test.ts",
          confidence: 0.77,
          reason: "test proximity for src/auth.ts",
        },
      ],
    },
    active_leases: [
      {
        lease_id: "lease-1",
        owner_role: "builder",
        task_id: "TICKET-001",
        scope_kind: "file",
        scope: { path: "src/auth.ts", name: "auth.ts" },
      },
    ],
    conflicting_leases: [],
    scheduling_candidates: [
      {
        candidate_id: "candidate-1",
        state: "selected",
        role: "builder",
        task_id: "TICKET-001",
        action_kind: "work_item",
        score: 0.88,
        reasons: ["ready task with free lease"],
      },
    ],
    selected_candidate: {
      candidate_id: "candidate-1",
      state: "selected",
      role: "builder",
      task_id: "TICKET-001",
      action_kind: "work_item",
      score: 0.88,
      reasons: ["ready task with free lease"],
    },
    scheduler_fallback_used: false,
    ...overrides,
  };
}

describe("GraphInsightsPanel", () => {
  it("renders graph summary fixture", () => {
    const html = renderToStaticMarkup(<GraphInsightsPanel snapshot={snapshot(graphState())} />);

    expect(html).toContain("Codebase Graph");
    expect(html).toContain("Task Graph");
    expect(html).toContain(">12</strong>");
    expect(html).toContain(">2</strong>");
    expect(html).toContain("Graph Insights");
  });

  it("renders stale graph warnings", () => {
    const html = renderToStaticMarkup(
      <GraphInsightsPanel
        snapshot={snapshot(graphState({
          stale_node_count: 2,
          stale_context_warning: "Relevant context includes stale file graph nodes.",
          stale_graph_warnings: [
            {
              kind: "codebase_stale_nodes",
              severity: "warn",
              count: 2,
              source: "codebase_graph",
              message: "2 indexed codebase nodes are stale.",
            },
          ],
        }))}
      />,
    );

    expect(html).toContain("Stale graph warning");
    expect(html).toContain("2 indexed codebase nodes are stale.");
    expect(html).toContain("Relevant context includes stale file graph nodes.");
  });

  it("renders context-pack reasons without raw source contents", () => {
    const html = renderToStaticMarkup(<GraphInsightsPanel snapshot={snapshot(graphState())} />);

    expect(html).toContain("Why these files?");
    expect(html).toContain("path mention in ticket summary");
    expect(html).toContain("test proximity for src/auth.ts");
    expect(html).not.toContain("SECRET_SOURCE_BODY");
  });

  it("renders lease conflicts and scheduler reasons", () => {
    const html = renderToStaticMarkup(
      <GraphInsightsPanel
        snapshot={snapshot(graphState({
          conflicting_leases: [
            {
              reason: "same graph node",
              lease: {
                lease_id: "lease-1",
                owner_role: "builder",
                scope: { path: "src/auth.ts" },
              },
              conflicting_lease: {
                lease_id: "lease-2",
                owner_role: "hardener",
                scope: { path: "src/auth.ts" },
              },
            },
          ],
        }))}
      />,
    );

    expect(html).toContain("Active leases");
    expect(html).toContain("same graph node");
    expect(html).toContain("ready task with free lease");
  });

  it("builds an empty model for targets without graph state", () => {
    const model = buildGraphInsightsModel(snapshot({}));

    expect(model.hasGraphData).toBe(false);
    expect(model.contextItems).toEqual([]);
    expect(model.warningItems).toEqual([]);
  });
});
