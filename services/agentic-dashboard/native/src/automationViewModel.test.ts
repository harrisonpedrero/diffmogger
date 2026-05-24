import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { buildAutomationViewModel } from "./automationViewModel";
import { buildRunModel } from "./runModel";

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
    setup: {
      project_name: "Project",
      status: "ACTIVE",
      task: { status: "ACTIVE", last_updated: "2026-05-21T12:00:00+00:00" },
      files: [],
    },
    scheduler: {
      selected_action: {
        candidate_id: "candidate:selected",
        role: "builder",
        action_kind: "launch_write_group",
        state: "selected",
        score: 0.82,
        required_leases: [{ path: "src/app.ts" }],
        reasons: ["Direct path ownership is available."],
      },
      candidates: [
        { candidate_id: "candidate:selected", role: "builder", action_kind: "launch_write_group", state: "selected", score: 0.82 },
        { candidate_id: "candidate:serial", role: "builder", action_kind: "run_serial_role", state: "skipped", skipped_reason: "serialized_role_path" },
      ],
      last_cycle: { occurred_at: "2026-05-21T12:10:00+00:00", event_type: "scheduler_decision", status: "ok" },
      mode: "Planning preview",
      parallelization_summary: { group_count: 1, blocked_candidate_count: 1, next_parallel_improvement: "Add direct ownership evidence." },
      why_not_parallel: {
        status: "reduced_fanout",
        blocked_candidate_count: 1,
        summary: "Fanout reduced while ownership evidence is incomplete.",
        top_next_action: "Add direct ownership evidence.",
        reason_groups: [{ reason_kind: "serialized_role_path", label: "Serialized role path", count: 1, next_action: "Continue one role at a time." }],
      },
    },
    dag: {
      execution_dag: {
        nodes: [
          { node_id: "node:build", task_id: "TICKET-001", action_type: "build", status: "running", owner_role: "builder", confidence: 0.82, metadata: { paths: ["src/app.ts"] } },
          { node_id: "node:repair", task_id: "TICKET-002", action_type: "repair", status: "ready", owner_role: "builder" },
          { node_id: "node:integrate", task_id: "TICKET-001", action_type: "integrate", status: "ready", owner_role: "integrator" },
          { node_id: "node:done", task_id: "TICKET-003", action_type: "validate", status: "completed", owner_role: "hardener" },
        ],
        edges: [],
      },
      active_execution_groups: [{ execution_group_id: "group:1", mode: "write_workers", status: "running", item_count: 1, reason: "Compatible path ownership." }],
      active_leases: [{ lease_id: "lease:1", path: "src/app.ts" }],
      queued_worker_patches: [{ patch_id: "patch:1", status: "queued", patch_path: ".diffmogger/patches/patch-1.diff" }],
      worker_patch_integration_preflight: { safe_count: 1, queued_patch_count: 1, records: [{ preflight_id: "preflight:1", patch_id: "patch:1", status: "direct_apply" }] },
      recent_outcomes: [{ event_id: 1, event_type: "scheduler_decision", status: "recorded", occurred_at: "2026-05-21T12:10:00+00:00", summary: "Selected write group." }],
    },
    tickets: { items: [], remaining: [], counts: {} },
    human_input: {
      pending_requests: 1,
      unhandled_records: 0,
      outbound_records: 2,
      notification_mode: "file_only",
      notifier_status: { status: "file_only", detail: "File-only handoff is active." },
    },
    validation_repair: {
      validation: { counts: { pass: 1, fail: 1 } },
      validation_receipts: [
        { receipt_id: "receipt:pass", kind: "test", command: "npm test", status: "passed", required: true, log_artifact_id: "logs/test.log" },
        { receipt_id: "receipt:advisory", kind: "lint", command: "npm run lint", status: "failed", required: false },
      ],
      repair_actions: [{ action_id: "repair:1", kind: "repair", status: "planned", reason: "Repair failing required check." }],
    },
    controls: {
      is_scaffolded: true,
      can_start_automation: true,
      can_stop_automation: false,
      can_run_safety_check: true,
      automation: {
        state: "stopped",
        message: "Ready.",
        ready: true,
        ready_reason: "Ready.",
        runner: { state: "stopped", supervisor: "portable-subprocess", launchd_available: false },
      },
    },
  } as ProjectSnapshot;
}

function pathPoints(path: string): Array<{ x: number; y: number }> {
  return Array.from(path.matchAll(/[ML] (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)/g)).map((match) => ({
    x: Number(match[1]),
    y: Number(match[2]),
  }));
}

describe("buildAutomationViewModel", () => {
  it("maps typed read-model state into compact operator sections", () => {
    const model = buildRunModel(snapshot());
    const view = buildAutomationViewModel(snapshot(), model);

    expect(view.statusBand.facts.map((fact) => fact.label)).toContain("Supervisor");
    expect(view.statusBand.facts.find((fact) => fact.id === "last-cycle")?.value).toContain("2026-05-21");
    expect(view.progressLanes.find((lane) => lane.id === "running")?.count).toBe(1);
    expect(view.progressLanes.find((lane) => lane.id === "repair")?.count).toBe(1);
    expect(view.progressLanes.find((lane) => lane.id === "integration")?.count).toBeGreaterThanOrEqual(1);
    expect(view.schedulerDecision.selected).toMatchObject({ label: "Start write workers", fanout: 1, confidence: "82%" });
    expect(view.schedulerDecision.alternatives[0]).toMatchObject({ status: "Not Selected", tone: "quiet" });
    expect(view.schedulerDecision.whyParallel.summary).toContain("Fanout reduced");
    expect(view.validationEvidence.requiredPassed).toBe(1);
    expect(view.validationEvidence.advisoryFailed).toBe(1);
    expect(view.validationEvidence.evidencePaths).toContain("logs/test.log");
    expect(view.queueIntegration.metrics.find((metric) => metric.id === "leases")?.value).toBe("1");
    expect(view.notification).toMatchObject({ pending: 1, outbound: 2, mode: "file only" });
    expect(view.timeline.map((event) => event.category)).toContain("scheduler");
  });

  it("sorts typed ticket progress ahead of projection fallback statuses", () => {
    const data = snapshot();
    data.tickets = {
      items: [
        { id: "TICKET-004", summary: "Completed work", status: "done", evidence: ["logs/4.txt"] },
        { id: "TICKET-002", summary: "Ready work", status: "ready" },
        { id: "TICKET-003", summary: "Waiting work", status: "waiting", depends_on: ["TICKET-001"] },
        {
          id: "TICKET-001",
          summary: "Running work",
          status: "running",
          acceptance_criteria: ["Running ticket has a clear acceptance target."],
          verification_commands: ["npm test"],
          blocker: "Waiting on generated fixture.",
          related_commits: ["abc1234"],
          runtime_payload: { status: "worker_running" },
        },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));

    expect(view.ticketProgress.rows.map((row) => row.id)).toEqual([
      "TICKET-001",
      "TICKET-002",
      "TICKET-003",
      "TICKET-004",
    ]);
    expect(view.ticketProgress.counts.map((count) => [count.id, count.count])).toEqual([
      ["building", 1],
      ["scoping", 0],
      ["running", 0],
      ["ready", 1],
      ["waiting", 1],
      ["candidate_done", 0],
      ["blocked", 0],
      ["done", 1],
    ]);
    expect(view.ticketProgress.summary).toContain("1/4 done");
    expect(view.ticketProgress.summary).toContain("1 active");
    expect(view.ticketProgress.rows[0]).toMatchObject({
      acceptanceCriteria: ["Running ticket has a clear acceptance target."],
      verificationCommands: ["npm test"],
      blocker: "Waiting on generated fixture.",
      relatedCommits: ["abc1234"],
      runtimeStatus: "worker_running",
    });
    expect(view.ticketGraph.nodes.find((node) => node.id === "TICKET-001")).toMatchObject({
      acceptanceCriteria: ["Running ticket has a clear acceptance target."],
      verificationCommands: ["npm test"],
      relatedCommits: ["abc1234"],
      runtimeStatus: "worker_running",
    });
  });

  it("shows active read-only ticket workers as scoping without changing canonical status", () => {
    const data = snapshot();
    data.dag.execution_dag = {
      nodes: [
        { node_id: "dag-node:TICKET-010:scope", task_id: "TICKET-010", action_type: "scope", status: "ready", owner_role: "planner" },
        { node_id: "dag-node:TICKET-010:build", task_id: "TICKET-010", action_type: "build", status: "waiting", owner_role: "builder" },
      ],
      edges: [],
    };
    data.dag.active_read_only_workers = [
      {
        worker_id: "active-lease:scope-010",
        execution_group_id: "group:scope",
        ticket_id: "TICKET-010",
        task_id: "TICKET-010",
        role: "planner",
        action_kind: "launch_scope_work",
        status: "running",
        display_status: "scoping",
        status_label: "Scoping",
      },
    ];
    data.tickets = {
      items: [{ id: "TICKET-010", summary: "Scope ownership", status: "ready" }],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const row = view.ticketProgress.rows.find((ticket) => ticket.id === "TICKET-010");
    const graphNode = view.ticketGraph.nodes.find((node) => node.id === "TICKET-010");

    expect(row).toMatchObject({
      status: "scoping",
      statusLabel: "Scoping",
      runtimeStatus: "Scoping",
      stage: "Plan scoping",
    });
    expect(graphNode).toMatchObject({
      status: "scoping",
      statusLabel: "Scoping",
    });
    expect(view.ticketProgress.counts.find((count) => count.id === "scoping")?.count).toBe(1);
    expect(view.ticketGraph.active).toBe(1);
  });

  it("lays ticket graph nodes left-to-right by topological dependencies", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [
        { id: "TICKET-003", summary: "Third", status: "waiting", depends_on: ["TICKET-002"] },
        { id: "TICKET-001", summary: "First", status: "done" },
        { id: "TICKET-002", summary: "Second", status: "ready", depends_on: ["TICKET-001"] },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const layerById = Object.fromEntries(view.ticketGraph.nodes.map((node) => [node.id, node.layer]));

    expect(layerById).toMatchObject({
      "TICKET-001": 0,
      "TICKET-002": 1,
      "TICKET-003": 2,
    });
    expect(view.ticketGraph.edges.map((edge) => `${edge.source}->${edge.target}`).sort()).toEqual([
      "TICKET-001->TICKET-002",
      "TICKET-002->TICKET-003",
    ]);
    expect(view.ticketGraph.layers.map((layer) => layer.count)).toEqual([1, 1, 1]);
  });

  it("orders ticket graph layers by dependency neighbors to reduce edge crossings", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [
        { id: "TICKET-001", summary: "First root", status: "done" },
        { id: "TICKET-002", summary: "Second root", status: "done" },
        { id: "TICKET-003", summary: "Depends on second root", status: "waiting", depends_on: ["TICKET-002"] },
        { id: "TICKET-004", summary: "Depends on first root", status: "waiting", depends_on: ["TICKET-001"] },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const nodeById = new Map(view.ticketGraph.nodes.map((node) => [node.id, node]));

    expect(nodeById.get("TICKET-001")!.y).toBeLessThan(nodeById.get("TICKET-002")!.y);
    expect(nodeById.get("TICKET-004")!.y).toBeLessThan(nodeById.get("TICKET-003")!.y);
    for (const edge of view.ticketGraph.edges) {
      expect(nodeById.get(edge.source)!.x).toBeLessThan(nodeById.get(edge.target)!.x);
      expect(edge.path).not.toContain("C");
    }
  });

  it("routes long ticket graph edges through row-gap lanes instead of node bodies", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [
        { id: "TICKET-001", summary: "Root", status: "done" },
        { id: "TICKET-002", summary: "Middle one", status: "done", depends_on: ["TICKET-001"] },
        { id: "TICKET-003", summary: "Middle two", status: "done", depends_on: ["TICKET-002"] },
        { id: "TICKET-004", summary: "Long target", status: "waiting", depends_on: ["TICKET-001", "TICKET-003"] },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const longEdge = view.ticketGraph.edges.find((edge) => edge.id === "TICKET-001->TICKET-004");
    const nodes = view.ticketGraph.nodes;
    const points = pathPoints(longEdge?.path || "");
    const segments = points.slice(1).map((point, index) => ({ from: points[index], to: point }));
    const longestHorizontal = segments
      .filter((segment) => segment.from.y === segment.to.y)
      .sort((first, second) => Math.abs(second.to.x - second.from.x) - Math.abs(first.to.x - first.from.x))[0];

    expect(longEdge?.path).toMatch(/^M /);
    expect(longEdge?.path).not.toContain("C");
    expect(points.length).toBeGreaterThan(4);
    for (const segment of segments) {
      expect(segment.from.x === segment.to.x || segment.from.y === segment.to.y).toBe(true);
    }
    expect(Math.abs(longestHorizontal.to.x - longestHorizontal.from.x)).toBeGreaterThan(190);
    for (const node of nodes) {
      expect(longestHorizontal.from.y <= node.y || longestHorizontal.from.y >= node.y + node.height).toBe(true);
    }
  });

  it("aligns sparse ticket graph layers near their dependency median instead of pinning them to the top", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [
        { id: "TICKET-001", summary: "Top root", status: "done" },
        { id: "TICKET-002", summary: "Middle root", status: "done" },
        { id: "TICKET-003", summary: "Lower root", status: "done" },
        { id: "TICKET-004", summary: "Bottom root", status: "done" },
        { id: "TICKET-005", summary: "Lower dependent", status: "waiting", depends_on: ["TICKET-004"] },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const nodeById = new Map(view.ticketGraph.nodes.map((node) => [node.id, node]));

    expect(nodeById.get("TICKET-005")!.y).toBe(nodeById.get("TICKET-004")!.y);
    expect(nodeById.get("TICKET-005")!.y).toBeGreaterThan(nodeById.get("TICKET-001")!.y);
  });

  it("renders missing ticket dependencies as muted placeholder nodes", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [{ id: "TICKET-002", summary: "Depends on absent work", status: "waiting", depends_on: ["TICKET-404"] }],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const placeholder = view.ticketGraph.nodes.find((node) => node.id === "TICKET-404");

    expect(placeholder).toMatchObject({
      status: "missing",
      statusLabel: "Missing dependency",
      tone: "quiet",
      placeholder: true,
      layer: 0,
    });
    expect(view.ticketGraph.edges).toContainEqual(expect.objectContaining({
      id: "TICKET-404->TICKET-002",
      source: "TICKET-404",
      target: "TICKET-002",
      cyclic: false,
    }));
  });

  it("places dependency cycles in a warning layer instead of breaking layout", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [
        { id: "TICKET-001", summary: "Cycle first", status: "waiting", depends_on: ["TICKET-002"] },
        { id: "TICKET-002", summary: "Cycle second", status: "waiting", depends_on: ["TICKET-001"] },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));

    expect(view.ticketGraph.cyclicCount).toBe(2);
    expect(view.ticketGraph.nodes.every((node) => node.cyclic)).toBe(true);
    expect(view.ticketGraph.edges.every((edge) => edge.cyclic)).toBe(true);
    expect(view.ticketGraph.layers).toEqual([
      expect.objectContaining({ label: "Cycle / unresolved", count: 2, cyclic: true }),
    ]);
  });

  it("assigns graph status tones for completed, active, ready, waiting, and follow-up work", () => {
    const data = snapshot();
    data.dag.execution_dag = { nodes: [], edges: [] };
    data.tickets = {
      items: [
        { id: "TICKET-001", summary: "Done", status: "done" },
        { id: "TICKET-002", summary: "Running", status: "running" },
        { id: "TICKET-003", summary: "Ready", status: "ready" },
        { id: "TICKET-004", summary: "Waiting", status: "waiting" },
        { id: "TICKET-005", summary: "Blocked", status: "blocked" },
      ],
      remaining: [],
      counts: {},
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));
    const toneById = Object.fromEntries(view.ticketGraph.nodes.map((node) => [node.id, node.tone]));

    expect(toneById).toMatchObject({
      "TICKET-001": "good",
      "TICKET-002": "info",
      "TICKET-003": "info",
      "TICKET-004": "quiet",
      "TICKET-005": "warn",
    });
  });

  it("keeps raw DAG node identifiers out of ticket progress", () => {
    const data = snapshot();
    data.tickets = { items: [], remaining: [], counts: {} };
    data.dag.execution_dag = {
      nodes: [
        { node_id: "node:internal", task_id: "node:internal", action_type: "build", status: "ready", owner_role: "builder" },
        { node_id: "dag-node:internal", task_id: "dag-node:internal", action_type: "build", status: "ready", owner_role: "builder" },
        { node_id: "dag-node:ticket", task_id: "TICKET-010", action_type: "build", status: "ready", owner_role: "builder" },
      ],
      edges: [],
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));

    expect(view.ticketProgress.rows.map((row) => row.id)).toEqual(["TICKET-010"]);
  });

  it("does not render launchd's placeholder pid as a real process", () => {
    const data = snapshot();
    data.controls.automation = {
      ...data.controls.automation,
      state: "running",
      pid: 0,
      runner: { state: "running", supervisor: "launchd", pid: 0 },
    };

    const view = buildAutomationViewModel(data, buildRunModel(data));

    expect(view.statusBand.facts.find((fact) => fact.id === "pid")).toMatchObject({
      label: "Process",
      value: "no pid",
    });
  });
});
