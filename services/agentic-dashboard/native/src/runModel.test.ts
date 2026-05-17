import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { buildRunModel } from "./runModel";

function snapshot(overrides: Partial<ProjectSnapshot> = {}): ProjectSnapshot {
  const base: ProjectSnapshot = {
    target: {
      path: "/tmp/project",
      name: "project",
      is_diffmogger_project: true,
      project_intake_exists: true,
      dashboard_state_exists: true,
      automation_task_exists: true,
    },
    brief: { project_name: "Project", project_mode: "fresh_project" },
    run: {
      task: {
        status: "ACTIVE",
        horizon: "H1 Runnable baseline",
        last_updated: "2026-05-06T12:00:00+00:00",
      },
      controls: {
        is_scaffolded: true,
        is_running: false,
        can_start_automation: true,
        can_stop_automation: false,
        can_run_safety_check: true,
      },
      automation: {
        state: "stopped",
        message: "Continuous automation is ready to start.",
      },
      worker_strategy: {
        strategy: "NO_WORKERS",
        parallelism_budget: 0,
        action_lane: "builder",
      },
      worker_controls: {
        can_run_read_only: false,
        can_run_write: false,
        can_run_integrator: false,
      },
      latest_worker_result: { label: "Latest worker result: none yet." },
      environment_blockers: [],
    },
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1 Runnable baseline",
      next_action: "Continue builder work.",
      pending_human_requests: 0,
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
  };
}

describe("buildRunModel", () => {
  it("disables run controls when no target is selected", () => {
    const model = buildRunModel(null);

    expect(model.banner.primaryAction.label).toBe("Choose project");
    expect(model.controls.startAutomation.enabled).toBe(false);
    expect(model.controls.stopAutomation.enabled).toBe(false);
  });

  it("maps unscaffolded targets to the Brief gate", () => {
    const model = buildRunModel(
      snapshot({
        target: {
          path: "/tmp/project",
          name: "project",
          is_diffmogger_project: false,
          project_intake_exists: false,
          dashboard_state_exists: false,
          automation_task_exists: false,
        },
        run: {
          controls: {
            is_scaffolded: false,
            can_start_automation: false,
            can_stop_automation: false,
            can_run_safety_check: false,
          },
        },
      }),
    );

    expect(model.banner.headline).toBe("Unknown");
    expect(model.banner.primaryAction.label).toBe("Open setup");
    expect(model.controls.startAutomation.enabled).toBe(false);
    expect(model.controls.safetyCheck.enabled).toBe(false);
  });

  it("enables Start for ready scaffolded targets", () => {
    const model = buildRunModel(snapshot());

    expect(model.banner.primaryAction.label).toBe("Start");
    expect(model.controls.startAutomation.enabled).toBe(true);
    expect(model.controls.stopAutomation.enabled).toBe(false);
    expect(model.controls.safetyCheck.enabled).toBe(true);
  });

  it("lets Start handle pending bootstrap as first-run preparation", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          task: {
            status: "ACTIVE",
            bootstrap_status: "pending",
            bootstrap_pending: true,
          },
          controls: {
            is_scaffolded: true,
            is_running: false,
            can_start_automation: false,
            start_automation_reason: "Continuous automation is not ready. Bootstrap has not completed yet.",
            can_bootstrap_and_start: true,
            bootstrap_start_reason: "Ready to run initial bootstrap before starting automation.",
            can_stop_automation: false,
            can_run_safety_check: true,
          },
          automation: {
            state: "not_ready",
            message: "Continuous automation is not ready. Bootstrap has not completed yet.",
          },
        },
      }),
    );

    expect(model.banner.badge).toBe("Ready");
    expect(model.banner.subheadline).toContain("prepare the target");
    expect(model.banner.primaryAction.label).toBe("Start");
    expect(model.controls.startAutomation.command).toBe("automation.bootstrap_start");
    expect(model.controls.startAutomation.enabled).toBe(true);
  });

  it("labels a missing first safety result as pending", () => {
    const model = buildRunModel(snapshot());
    const safety = model.safety.find((row) => row.label === "Integration safety");

    expect(safety).toMatchObject({
      status: "pending",
      summary: "Integration-safety check has not run yet.",
      tone: "warn",
    });
  });

  it("uses warning banner color when active work is environment blocked", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          task: {
            status: "ACTIVE",
            validation: {
              counts: { pass: 6, fail: 1, pending: 0 },
              summary: "1 validation failure.",
            },
            integration_safety: {
              status: "pass",
              summary: "Integration safety passed.",
            },
          },
          controls: {
            can_start_automation: false,
            can_stop_automation: false,
            can_run_safety_check: true,
          },
        },
      }),
    );

    expect(model.banner.headline).toBe("Env blocked");
    expect(model.banner.badge).toBe("Env blocked");
    expect(model.banner.tone).toBe("warn");
  });

  it("disables start controls while automation is active", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            is_running: true,
            can_start_automation: false,
            can_stop_automation: true,
            can_run_safety_check: true,
          },
          automation: { state: "running", message: "Continuous automation is running." },
          task: { status: "RUNNING" },
        },
      }),
    );

    expect(model.isRunning).toBe(true);
    expect(model.controls.startAutomation.enabled).toBe(false);
    expect(model.controls.stopAutomation.enabled).toBe(true);
  });

  it("enables Stop only when automation is running", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_start_automation: false,
            can_stop_automation: true,
            can_run_safety_check: true,
          },
          automation: { state: "running", message: "Continuous automation is running." },
        },
      }),
    );

    expect(model.controls.stopAutomation.enabled).toBe(true);
  });

  it("keeps Stop disabled when automation is stopped", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_start_automation: true,
            can_stop_automation: false,
            stop_automation_reason: "No automation is running.",
            can_run_safety_check: true,
          },
          automation: { state: "stopped", message: "Continuous automation is ready to start." },
        },
      }),
    );

    expect(model.controls.stopAutomation.enabled).toBe(false);
  });

  it("translates read-only worker strategy strings into human copy", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          worker_strategy: {
            strategy: "READ_ONLY_REPORTS",
            parallelism_budget: 1,
            action_lane: "builder",
          },
          worker_controls: {
            can_run_read_only: true,
            read_only_reason: "Supported by current worker strategy.",
          },
        },
      }),
    );

    expect(model.worker.headline).toBe("Recommended: one read-only builder report");
    expect(model.worker.mode).toBe("Read-only report");
    expect(model.worker.focus).toBe("builder lane");
    expect(model.worker.output).toBe(".diffmogger/runtime/agent_runs/<run-id>/worker_builder_strategy.md");
    expect(model.worker.actions.readOnly.enabled).toBe(true);
    expect(model.worker.actions.write.enabled).toBe(false);
  });

  it("maps execution DAG data into the run model", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              authority: "sqlite",
              digest: "dag123",
              nodes: [
                {
                  node_id: "dag-node:scope",
                  task_id: "TICKET-001",
                  action_type: "scoping",
                  status: "done",
                  owner_role: "planner",
                  attempt_count: 1,
                  confidence: 0.92,
                  metadata: { paths: ["src/app.ts"] },
                },
                {
                  node_id: "dag-node:build",
                  task_id: "TICKET-001",
                  action_type: "building",
                  status: "ready",
                  owner_role: "builder",
                  attempt_count: 2,
                  confidence: 0.82,
                  patch: { id: "patch:1", path: "target/changes.patch" },
                  metadata: { paths: ["src/app.ts"] },
                },
              ],
              edges: [
                {
                  edge_id: "edge:scope-build",
                  source: "dag-node:scope",
                  target: "dag-node:build",
                  dependency_kind: "depends_on",
                  dependency_mode: "hard",
                  confidence: 0.95,
                  reason: "scope before build",
                },
              ],
            },
          },
        },
      }),
    );

    expect(model.executionDag.hasData).toBe(true);
    expect(model.executionDag.authority).toBe("sqlite");
    expect(model.executionDag.summary).toMatchObject({ total: 2, ready: 1, completed: 1 });
    expect(model.executionDag.columns.find((column) => column.id === "scope")?.nodes[0].id).toBe("dag-node:scope");
    expect(model.executionDag.columns.find((column) => column.id === "build")?.nodes[0]).toMatchObject({
      ticketId: "TICKET-001",
      actionType: "building",
      confidenceLabel: "82%",
      patchId: "patch:1",
    });
    expect(model.executionDag.edges[0]).toMatchObject({ dependencyKind: "depends_on", confidenceLabel: "95%" });
  });

  it("maps execution groups into live graph overlays", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              nodes: [
                {
                  node_id: "dag-node:T1:build",
                  task_id: "T1",
                  action_type: "build",
                  status: "ready",
                  owner_role: "builder",
                  confidence: 0.9,
                },
                {
                  node_id: "dag-node:T2:build",
                  task_id: "T2",
                  action_type: "build",
                  status: "ready",
                  owner_role: "builder",
                  confidence: 0.91,
                },
              ],
              edges: [],
            },
            proposed_execution_groups: [
              {
                execution_group_id: "group:1",
                mode: "dry_run",
                status: "proposed",
                items: [
                  { task_id: "T1", action_kind: "build", payload: { dag_node_id: "dag-node:T1:build" } },
                  { task_id: "T2", action_kind: "build", payload: { dag_node_id: "dag-node:T2:build" } },
                ],
              },
            ],
            active_write_workers: [{ execution_group_id: "group:1", task_id: "T1" }],
          },
        },
      }),
    );

    expect(model.executionDag.groups.some((group) => group.kind === "proposed" && group.nodeIds.length === 2)).toBe(true);
    expect(model.executionDag.groups.some((group) => group.kind === "active")).toBe(true);
    expect(model.executionDag.parallel.proposedGroups).toBe(1);
    expect(model.executionDag.parallel.activeGroups).toBe(1);
  });

  it("surfaces an active role run when no DAG node is active", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          conveyor: {
            active_role_run: {
              role: "builder",
              action_kind: "run_serial_role",
              run_id: "run:builder",
              status: "running",
              reason: "dependency-ready ticket needs serialized builder work",
            },
          },
          state: {
            execution_dag: {
              nodes: [
                {
                  node_id: "dag-node:T1:build",
                  task_id: "T1",
                  action_type: "build",
                  status: "ready",
                  owner_role: "builder",
                },
              ],
              edges: [],
            },
          },
        },
      }),
    );

    expect(model.operations.runningNow[0]).toMatchObject({
      role: "builder",
      action: "run_serial_role",
      source: "active_role_run",
      tone: "info",
    });
  });

  it("summarizes multiple active workers in one execution group", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              nodes: [
                { node_id: "dag-node:T1:scope", task_id: "T1", action_type: "scope", status: "running", owner_role: "planner" },
                { node_id: "dag-node:T2:scope", task_id: "T2", action_type: "scope", status: "running", owner_role: "planner" },
              ],
              edges: [],
            },
            active_read_only_workers: [
              { worker_id: "worker:1", execution_group_id: "group:scope", task_id: "T1", role: "planner", status: "running" },
              { worker_id: "worker:2", execution_group_id: "group:scope", task_id: "T2", role: "planner", status: "running" },
            ],
          },
        },
      }),
    );

    expect(model.operations.runningNow.filter((item) => item.source === "worker_agent")).toHaveLength(2);
    expect(model.operations.concurrencyWaves.find((wave) => wave.id === "group:scope" && wave.kind === "active")).toMatchObject({
      itemCount: 2,
      status: "running",
      tone: "info",
    });
  });

  it("summarizes proposed write waves with disjoint leases", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            proposed_execution_groups: [
              {
                execution_group_id: "group:write",
                status: "proposed",
                mode: "dry_run",
                payload: { execution_mode: "write_workers", why_together: "write candidates have disjoint likely_touches" },
                items: [
                  {
                    task_id: "T1",
                    owner_role: "builder",
                    action_kind: "build",
                    required_leases: [{ scope_node_id: "file:src/a.ts", path: "src/a.ts" }],
                  },
                  {
                    task_id: "T2",
                    owner_role: "builder",
                    action_kind: "build",
                    required_leases: [{ scope_node_id: "file:src/b.ts", path: "src/b.ts" }],
                  },
                ],
              },
            ],
          },
        },
      }),
    );

    expect(model.operations.concurrencyWaves[0]).toMatchObject({
      id: "group:write",
      kind: "proposed",
      mode: "write_workers",
      itemCount: 2,
      owners: ["builder"],
      leases: ["src/a.ts", "src/b.ts"],
    });
  });

  it("shows queued worker patches waiting for serialized integration", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            queued_worker_patches: [
              { patch_id: "patch:1", status: "queued" },
              { patch_id: "patch:2", status: "queued" },
            ],
            worker_patch_integration_preflight: {
              safe_count: 1,
              safe_patch_ids: ["patch:1"],
              likely_conflict_count: 1,
            },
          },
        },
      }),
    );

    expect(model.operations.integrationBacklog).toMatchObject({
      queuedCount: 2,
      safeCount: 1,
      blockedCount: 1,
      tone: "warn",
    });
    expect(model.operations.concurrencyWaves.some((wave) => wave.kind === "integration" && wave.id === "integration-backlog")).toBe(true);
  });

  it("uses why-not-parallel as the next unlock when no candidate is selected", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            why_not_parallel: {
              status: "blocked",
              top_reason_kind: "missing_direct_write_signal",
              top_next_action: "Add direct path metadata.",
            },
            blocked_parallel_candidates: [
              {
                candidate_id: "candidate:T9",
                task_id: "T9",
                execution_mode: "write_workers",
                reason: "write DAG node has no confident likely_touches surface",
              },
            ],
          },
        },
      }),
    );

    expect(model.operations.nextUnlock).toMatchObject({
      source: "why_not_parallel",
      title: "missing direct write signal",
      detail: "Add direct path metadata.",
      tone: "warn",
    });
    expect(model.operations.concurrencyWaves.some((wave) => wave.kind === "blocked" && wave.id === "candidate:T9")).toBe(true);
  });

  it("labels default compatibility task progress as fallback", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              nodes: [
                {
                  node_id: "dag-node:task:automation:build",
                  task_id: "task:automation",
                  action_type: "build",
                  status: "running",
                  owner_role: "builder",
                },
              ],
              edges: [],
            },
          },
        },
      }),
    );

    expect(model.operations.progressRows[0]).toMatchObject({
      taskId: "task:automation",
      label: "Compatibility fallback",
      compatibility: true,
    });
    expect(model.operations.progressRows[0].cells.build?.statusKind).toBe("running");
  });

  it("bounds large and oversized DAG rendering", () => {
    const boundedNodes = Array.from({ length: 300 }, (_, index) => ({
      node_id: `dag-node:large:${index}`,
      task_id: `T${index}`,
      action_type: index % 2 === 0 ? "build" : "validate",
      status: index < 6 ? "ready" : "pending",
      owner_role: "builder",
      confidence: 0.8,
    }));
    const bounded = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              nodes: boundedNodes,
              edges: Array.from({ length: 30 }, (_, index) => ({
                edge_id: `edge:large:${index}`,
                source: `dag-node:large:${index}`,
                target: `dag-node:large:${index + 31}`,
                dependency_kind: "depends_on",
                dependency_mode: "hard",
                reason: "large graph dependency",
              })),
            },
          },
        },
      }),
    );

    expect(bounded.executionDag.renderMode).toBe("large");
    expect(bounded.executionDag.abstraction).toMatchObject({ enabled: true, level: "phase-status" });
    expect(bounded.executionDag.clusters.length).toBeGreaterThan(0);
    expect(bounded.executionDag.clusterEdges.some((edge) => edge.count > 1)).toBe(true);
    expect(bounded.executionDag.visibleNodes.length).toBeLessThanOrEqual(250);
    expect(bounded.executionDag.visibleNodes.some((node) => node.statusKind === "ready")).toBe(true);

    const largeNodes = Array.from({ length: 820 }, (_, index) => ({
      node_id: `dag-node:${index}`,
      task_id: `T${index}`,
      action_type: index % 2 === 0 ? "build" : "validate",
      status: index < 6 ? "ready" : "pending",
      owner_role: "builder",
      confidence: 0.8,
    }));
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              nodes: largeNodes,
              edges: [],
            },
          },
        },
      }),
    );

    expect(model.executionDag.renderMode).toBe("oversized");
    expect(model.executionDag.abstraction.enabled).toBe(true);
    expect(model.executionDag.clusters.length).toBeGreaterThan(0);
    expect(model.executionDag.clusters.some((cluster) => cluster.nodeCount > 1)).toBe(true);
    expect(model.executionDag.visibleNodes).toHaveLength(0);
    expect(model.executionDag.renderLimit.hiddenNodeCount).toBe(820);
  });

  it("keeps empty execution DAG snapshots compact", () => {
    const model = buildRunModel(snapshot({ run: { state: { execution_dag: { nodes: [], edges: [] } } } }));

    expect(model.executionDag.hasData).toBe(false);
    expect(model.executionDag.summary.total).toBe(0);
    expect(model.executionDag.columns.map((column) => column.label)).toEqual([
      "Orchestrate",
      "Decompose",
      "Scope",
      "Build",
      "Review",
      "Validate",
      "Repair",
      "Integrate",
      "Audit/Calibrate",
      "Done",
    ]);
  });

  it("normalizes blocked and failed DAG nodes for progress counts", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          state: {
            execution_dag: {
              nodes: [
                {
                  node_id: "dag-node:validation",
                  task_id: "TICKET-002",
                  action_type: "validation",
                  status: "failed",
                  owner_role: "hardener",
                  confidence: 0.7,
                  blocker_reason: "pytest failed",
                  validation_receipt_refs: ["receipt:validation-job"],
                  metadata: { paths: ["tests/test_app.py"] },
                },
                {
                  node_id: "dag-node:blocker",
                  task_id: "TICKET-002",
                  action_type: "blocker",
                  status: "blocked",
                  owner_role: "planner",
                  confidence: 0.95,
                  blocker_reason: "retry limit exhausted",
                },
              ],
              edges: [],
            },
          },
        },
      }),
    );

    expect(model.executionDag.summary.failed).toBe(1);
    expect(model.executionDag.summary.blocked).toBe(1);
    expect(model.executionDag.columns.find((column) => column.id === "validate")?.nodes).toHaveLength(1);
    expect(model.executionDag.columns.find((column) => column.id === "done")?.nodes).toHaveLength(1);
    expect(model.executionDag.nodes[0].detail).toContain("validation receipts receipt:validation-job");
  });

  it("maps baseline blockers to the recheck command instead of generic diagnostics", () => {
    const model = buildRunModel(
      snapshot({
        run: {
          controls: {
            can_start_automation: false,
            can_stop_automation: false,
            can_run_safety_check: true,
          },
          environment_blockers: [
            {
              name: "Baseline verification",
              detail: "Baseline requires DATABASE_URL.",
              required: true,
              can_recheck: true,
              recheck_command: "blocker.recheck_baseline",
              recheck_label: "Recheck blocker",
            },
          ],
        },
      }),
    );

    const environment = model.safety.find((row) => row.label === "Environment");
    expect(environment?.action.label).toBe("Recheck blocker");
    expect(environment?.action.command).toBe("blocker.recheck_baseline");
    expect(model.blockers[0]).toMatchObject({ canRecheck: true, recheckLabel: "Recheck blocker" });
  });
});
