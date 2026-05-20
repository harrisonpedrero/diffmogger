import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AutomationPage } from "./AutomationPage";
import type { ProjectSnapshot } from "./api/backend";

function snapshot(): ProjectSnapshot {
  return {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    setup: { project_name: "Project", status: "ACTIVE", files: [] },
    scheduler: {
      selected_action: {
        role: "builder",
        action_kind: "run_serial_role",
        reasons: ["serialized_role_path: No promotable ownership evidence; continuing with serialized role work."],
      },
      next_actions: [
        { action_id: "action:setup", kind: "setup", status: "planned", reason: "Create local fixture." },
      ],
      blocked_candidates: [{ candidate_id: "group:failed", reason_kind: "retry failed work", status: "failed" }],
    },
    dag: {
      execution_dag: {
        nodes: [
          { node_id: "dag-node:plan-raw-id", task_id: "AUTO-001", action_type: "scope", status: "completed", owner_role: "planner" },
          { node_id: "dag-node:build-raw-id", task_id: "AUTO-001", action_type: "build", status: "running", owner_role: "builder" },
          { node_id: "dag-node:review-raw-id", task_id: "AUTO-001", action_type: "review", status: "blocked", owner_role: "hardener" },
          { node_id: "dag-node:validate-raw-id", task_id: "AUTO-001", action_type: "validate", status: "ready", owner_role: "hardener" },
          { node_id: "dag-node:repair-raw-id", task_id: "AUTO-002", action_type: "repair", status: "ready", owner_role: "builder" },
        ],
        edges: [
          { edge_id: "edge:plan-build", source: "dag-node:plan-raw-id", target: "dag-node:build-raw-id", dependency_kind: "depends_on" },
          { edge_id: "edge:build-review", source: "dag-node:build-raw-id", target: "dag-node:review-raw-id", dependency_kind: "depends_on" },
        ],
        blocked_nodes: [
          {
            node_id: "dag-node:review-raw-id",
            blocked_reasons: [{ kind: "dependency", reason: "review follows prior DAG action" }],
          },
        ],
      },
      recent_outcomes: [{ outcome_id: "outcome-1", status: "recorded" }],
      recent_execution_groups: [{ execution_group_id: "group:recent", mode: "write", status: "completed", reason: "Patch accepted." }],
    },
    tickets: {
      items: [{ id: "AUTO-001", summary: "Repair validation", status: "pending" }],
      remaining: [{ id: "AUTO-001", summary: "Repair validation", status: "pending" }],
      counts: { pending: 1 },
    },
    human_input: { pending_requests: 1, unhandled_records: 0, outbound_records: 2 },
    validation_repair: {
      active_validation_jobs: [{ job_id: "validation:1", status: "running", command: "npm test" }],
      repair_actions: [{ action_id: "action:setup", kind: "setup", status: "planned", reason: "Create local fixture." }],
    },
    controls: {
      is_scaffolded: true,
      can_start_automation: true,
      can_stop_automation: false,
      can_run_safety_check: true,
      automation: { state: "stopped", message: "Ready." },
    },
  } as ProjectSnapshot;
}

describe("AutomationPage", () => {
  it("renders an execution graph operations screen without legacy blocker/outcome panels", () => {
    const html = renderToStaticMarkup(
      <AutomationPage
        snapshot={snapshot()}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Automation");
    expect(html).toContain("Start");
    expect(html).toContain("Stop");
    expect(html).toContain("Retry");
    expect(html).toContain("Run safety check");
    expect(html).toContain("Execution Graph");
    expect(html).toContain("Selected Work");
    expect(html).toContain("Ticket Progress");
    expect(html).toContain("Now &amp; Next");
    expect(html).toContain("Human Input");
    expect(html).toContain("1 pending");
    expect(html).toContain("Checks &amp; Repair");
    expect(html).toContain("Activity Log");
    expect(html).toContain("Plan");
    expect(html).toContain("Build");
    expect(html).toContain("Review");
    expect(html).toContain("Validate");
    expect(html).toContain("Integrate");
    expect(html).toContain("Done");
    expect(html).toContain("Continue builder work");
    expect(html).toContain("Waiting for previous step.");
    expect(html).toContain("Set up local harness");
    expect(html).toContain("Setup or harness work has been generated.");
    expect(html).toContain("Patch accepted.");
    expect(html).toContain("npm test");
    expect(html).not.toContain("Scheduler Next");
    expect(html).not.toContain("Unblocker Work");
    expect(html).not.toContain("Recent Outcomes");
    expect(html).not.toContain("run_serial_role");
    expect(html).not.toContain("serialized_role_path");
    expect(html).not.toContain("dag-node:");
    expect(html).not.toContain("No ownership scope recorded");
    expect(html).not.toContain("outcome-1");
  });

  it("fills ticket progress from DAG rows when ticket projection rows are empty", () => {
    const data = snapshot();
    data.tickets = { counts: { done: 1 }, items: [], remaining: [], remaining_count: 0 };
    data.dag.execution_dag = {
      nodes: [
        { node_id: "dag-node:ticket-030:scope", task_id: "TICKET-030", action_type: "scope", status: "done", owner_role: "planner" },
        { node_id: "dag-node:ticket-030:build", task_id: "TICKET-030", action_type: "build", status: "done", owner_role: "builder" },
        { node_id: "dag-node:ticket-030:done", task_id: "TICKET-030", action_type: "completion", status: "complete", owner_role: "integrator" },
      ],
      edges: [],
    };
    const html = renderToStaticMarkup(
      <AutomationPage
        snapshot={data}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("TICKET-030");
    expect(html).toContain("1/1 done");
    expect(html).not.toContain("No tickets are loaded.");
  });
});
