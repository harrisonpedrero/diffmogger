import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ProjectSnapshot } from "./api/backend";
import { RunPage, ticketSnapshotReloadKey } from "./RunPage";

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
      task: { status: "ACTIVE", horizon: "H1", last_updated: "2026-05-07T12:00:00+00:00" },
      controls: {
        is_scaffolded: true,
        is_running: false,
        can_start_automation: false,
        can_stop_automation: true,
        can_run_safety_check: true,
      },
      automation: {
        state: "running",
        message: "Continuous automation is running.",
        pid: 1234,
        started_at: "2026-05-07T12:00:00+00:00",
      },
      worker_strategy: { strategy: "NO_WORKERS" },
      worker_controls: { can_run_read_only: false, can_run_write: false, can_run_integrator: false },
      latest_worker_result: { label: "Latest worker result: none yet." },
      environment_blockers: [],
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
  return {
    ...base,
    ...overrides,
    target: { ...base.target, ...overrides.target },
    run: { ...base.run, ...overrides.run },
    home: { ...base.home, ...overrides.home },
    files: overrides.files ?? base.files,
  };
}

function executionDag(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    authority: "sqlite",
    digest: "dag-render-test",
    nodes: [
      {
        node_id: "dag-node:scope",
        task_id: "TICKET-001",
        action_type: "scoping",
        status: "completed",
        owner_role: "planner",
        attempt_count: 1,
        confidence: 0.91,
        metadata: { paths: ["docs/plan.md"] },
      },
      {
        node_id: "dag-node:build",
        task_id: "TICKET-001",
        action_type: "building",
        status: "ready",
        owner_role: "builder",
        attempt_count: 2,
        confidence: 0.82,
        patch: { id: "patch:worker-1", path: "target/automation_queue/changes.patch" },
        metadata: { paths: ["src/app.ts"], execution_mode: "write_workers" },
      },
      {
        node_id: "dag-node:review",
        task_id: "TICKET-001",
        action_type: "reviewing",
        status: "running",
        owner_role: "hardener",
        attempt_count: 1,
        confidence: 0.88,
        metadata: { paths: ["src/app.ts"], execution_mode: "read_only" },
      },
      {
        node_id: "dag-node:completion",
        task_id: "TICKET-001",
        action_type: "completion",
        status: "skipped",
        owner_role: "integrator",
        attempt_count: 0,
        confidence: 0.4,
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
        reason: "scope must finish before build",
      },
      {
        edge_id: "edge:build-review",
        source: "dag-node:build",
        target: "dag-node:review",
        dependency_kind: "reviews",
        dependency_mode: "hard",
        confidence: 0.9,
        reason: "review completed worker patch",
      },
    ],
    ...overrides,
  };
}

describe("RunPage", () => {
  it("renders Start and Stop automation controls when backend allows them", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot()}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Start");
    expect(html).toContain("Stop");
    const controlGridStart = html.indexOf('class="run-control-grid"');
    const nextPanelStart = html.indexOf('class="panel run-process-panel"', controlGridStart);
    expect(controlGridStart).toBeGreaterThan(-1);
    expect(nextPanelStart).toBeGreaterThan(controlGridStart);
    expect(html.slice(controlGridStart, nextPanelStart)).toContain("Review export");
    expect(html).not.toContain("run-status-actions");
    expect(html).not.toContain(">Run</button>");
    expect(html).toContain("Continuous automation is running.");
  });

  it("renders ticket queue controls for ticket campaign targets", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({ brief: { intake: { campaign_mode: "bounded" } } })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Ticket Queue");
    expect(html).toContain("Draft candidates");
    expect(html).toContain("Agent direction (optional)");
    expect(html).toContain("Focus the draft on a feature area, workflow, or constraint.");
    expect(html).toContain("Draft New Tickets");
    expect(html).toContain("Manual ticket");
    expect(html).toContain("New Ticket");
    expect(html).toContain("Preview Import");
    expect(html).toContain("Apply Import");
    expect(html).toContain("Run Codex to propose grounded follow-up tickets");
    expect(html).toContain("Create a blank pending ticket in the editor");
  });

  it("renders split ticket action for pending queue tickets from snapshot state", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          brief: { intake: { campaign_mode: "bounded" } },
          run: {
            state: {
              ticket_run: {
                total: 1,
                counts: { pending: 1 },
                tickets: [
                  {
                    id: "TICKET-001",
                    summary: "Build broad queue and controls",
                    status: "pending",
                    depends_on: [],
                    acceptance_criteria: [],
                    verification_commands: [],
                    evidence: [],
                    related_commits: [],
                    blocker: "",
                  },
                ],
              },
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Split Ticket");
    expect(html).toContain("Preview smaller replacement tickets without changing the queue.");
  });

  it("changes the ticket reload key when the parent snapshot advances canonical ticket state", () => {
    const first = snapshot({
      run: {
        snapshot_generated_at: "2026-05-07T12:00:00+00:00",
        state: {
          ticket_run: {
            run_id: "campaign",
            status: "active",
            total: 5,
            counts: { pending: 5, done: 0 },
          },
        },
      },
    });
    const refreshed = snapshot({
      run: {
        snapshot_generated_at: "2026-05-07T12:05:00+00:00",
        state: {
          ticket_run: {
            run_id: "campaign",
            status: "active",
            total: 5,
            counts: { pending: 3, done: 2 },
          },
        },
      },
    });

    expect(ticketSnapshotReloadKey(first)).not.toEqual(ticketSnapshotReloadKey(refreshed));
    expect(ticketSnapshotReloadKey(refreshed)).toContain("done:2");
  });

  it("keeps the ready run banner badge-only instead of duplicating the headline", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            controls: {
              is_scaffolded: true,
              is_running: false,
              can_start_automation: true,
              can_stop_automation: false,
              can_run_safety_check: true,
            },
            automation: { state: "stopped", message: "No automation is running." },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("run-status-main badge-only");
    expect(html).toContain(">Ready</span>");
    expect(html).not.toContain("<h1>Ready</h1>");
  });

  it("renders direct Start readiness without first-run preparation copy", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            task: { status: "ACTIVE", bootstrap_status: "pending", bootstrap_pending: true },
            controls: {
              is_scaffolded: true,
              is_running: false,
              can_start_automation: true,
              start_automation_reason: "Continuous automation is ready to start.",
              can_bootstrap_and_start: true,
              can_stop_automation: false,
              can_run_safety_check: true,
            },
            automation: { state: "stopped", message: "Continuous automation is ready to start." },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain(">Ready</span>");
    expect(html).toContain("continuous automation can start");
    expect(html).toContain("Start");
  });

  it("renders helper strategy as an advanced manual control", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            worker_strategy: {
              strategy: "READ_ONLY_REPORTS",
              parallelism_budget: 1,
              action_lane: "builder",
              summary: "Use one read-only report for broad builder work; keep edits in the main agent.",
            },
            worker_controls: {
              can_run_read_only: true,
              can_run_write: false,
              can_run_integrator: false,
              read_only_reason: "Supported by current worker strategy.",
            },
            latest_worker_result: { label: "Latest worker result: none yet." },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Helper Strategy");
    expect(html).toContain("Recommended: one read-only builder report");
    expect(html).toContain(".diffmogger/runtime/agent_runs/&lt;run-id&gt;/worker_builder_strategy.md");
    expect(html).toContain("Advanced helper controls");
    expect(html).toContain("Run read-only worker");
    expect(html).not.toContain("Run write worker");
    expect(html).not.toContain("Run integrator");
  });

  it("renders the live execution graph as a native SVG", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              execution_dag: executionDag(),
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Live Execution Graph");
    expect(html).toContain("<svg");
    expect(html).toContain("Orchestrate");
    expect(html).toContain("Decompose");
    expect(html).toContain("Scope");
    expect(html).toContain("Build");
    expect(html).toContain("Review");
    expect(html).toContain("Validate");
    expect(html).toContain("Repair");
    expect(html).toContain("Integrate");
    expect(html).toContain("Audit/Calibrate");
    expect(html).toContain("Done");
    expect(html).toContain("Build");
    expect(html).toContain("TICKET-001 / builder /...");
    expect(html).toContain("patch patch:worker-1 target/automation_queue/changes.patch");
    expect(html).toContain("dag-edge hard");
    expect(html).not.toContain("State Machine");
  });

  it("renders the operations cockpit before the topology graph", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
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
              execution_dag: executionDag(),
              selected_candidate: {
                role: "integrator",
                action_kind: "run_serial_integration",
                task_id: "TICKET-001",
                state: "selected",
                reasons: ["queued worker patch passed integration preflight"],
              },
              queued_worker_patches: [{ patch_id: "patch:worker-1", status: "queued" }],
              worker_patch_integration_preflight: { safe_count: 1, safe_patch_ids: ["patch:worker-1"] },
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Operations Cockpit");
    expect(html).toContain("Running Now");
    expect(html).toContain("run serial role");
    expect(html).toContain("Next Unlock");
    expect(html).toContain("run serial integration");
    expect(html).toContain("Integration Backlog");
    expect(html).toContain("patch:worker-1");
    expect(html.indexOf("Operations Cockpit")).toBeLessThan(html.indexOf("Execution DAG Topology"));
  });

  it("renders the progress matrix from per-ticket DAG action states", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              execution_dag: executionDag({
                nodes: [
                  { node_id: "dag-node:T1:scope", task_id: "T1", action_type: "scope", status: "completed", owner_role: "planner" },
                  { node_id: "dag-node:T1:build", task_id: "T1", action_type: "build", status: "running", owner_role: "builder" },
                  { node_id: "dag-node:compat:build", task_id: "task:automation", action_type: "build", status: "ready", owner_role: "builder" },
                ],
                edges: [],
              }),
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Progress Matrix");
    expect(html).toContain("T1");
    expect(html).toContain("Compatibility fallback");
    expect(html).toContain("compatibility fallback");
    expect(html).toContain("status-running");
    expect(html).toContain("status-ready");
  });

  it("renders concurrency waves with active and proposed states", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              proposed_execution_groups: [
                {
                  execution_group_id: "group:planned",
                  status: "proposed",
                  mode: "dry_run",
                  payload: { execution_mode: "write_workers", why_together: "write candidates have disjoint likely_touches" },
                  items: [
                    {
                      task_id: "T1",
                      owner_role: "builder",
                      action_kind: "build",
                      required_leases: [{ path: "src/a.ts", scope_node_id: "file:src/a.ts" }],
                    },
                  ],
                },
              ],
              active_write_workers: [
                { worker_id: "worker:1", execution_group_id: "group:active", task_id: "T2", role: "builder", status: "running" },
              ],
              blocked_parallel_candidates: [
                { candidate_id: "candidate:T3", task_id: "T3", execution_mode: "write_workers", reason: "missing direct write signal" },
              ],
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Concurrency Strip");
    expect(html).toContain("group:planned");
    expect(html).toContain("group:active");
    expect(html).toContain("candidate:T3");
    expect(html).toContain("write candidates have disjoint likely_touches");
    expect(html).toContain("missing direct write signal");
    expect(html).toContain("src/a.ts");
  });

  it("renders operator empty states for empty runtime snapshots", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({ run: { state: { execution_dag: { nodes: [], edges: [] } } } })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("No active role, worker, validation job, or selected scheduler candidate is recorded.");
    expect(html).toContain("No progress rows yet");
    expect(html).toContain("No concurrency waves recorded");
  });

  it("renders blocked and failed DAG details", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              execution_dag: executionDag({
                nodes: [
                  {
                    node_id: "dag-node:failed-validation",
                    task_id: "TICKET-002",
                    action_type: "validation",
                    status: "failed",
                    owner_role: "hardener",
                    attempt_count: 3,
                    confidence: 0.76,
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
                    attempt_count: 1,
                    confidence: 0.96,
                    blocker_reason: "retry limit exhausted",
                  },
                ],
                edges: [
                  {
                    edge_id: "edge:blocker-validation",
                    source: "dag-node:blocker",
                    target: "dag-node:failed-validation",
                    dependency_kind: "blocks",
                    dependency_mode: "hard",
                    confidence: 0.96,
                    reason: "validation retry limit is exhausted",
                  },
                ],
              }),
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("status-failed");
    expect(html).toContain("status-blocked");
    expect(html).toContain("pytest failed");
    expect(html).toContain("retry limit exhausted");
    expect(html).toContain("validation receipts receipt:validation-job");
  });

  it("renders a compact empty DAG state when snapshots have no DAG nodes", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({ run: { state: { execution_dag: { nodes: [], edges: [] } } } })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("No topology data for this run");
    expect(html).not.toContain("Execution DAG progress graph");
    expect(html).not.toContain("State Machine");
  });

  it("renders oversized DAGs as a multi-resolution cluster view", () => {
    const nodes = Array.from({ length: 820 }, (_, index) => ({
      node_id: `dag-node:${index}`,
      task_id: `T${index}`,
      action_type: "build",
      status: index === 0 ? "running" : "pending",
      owner_role: "builder",
      confidence: 0.8,
    }));
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              execution_dag: executionDag({ nodes, edges: [] }),
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Multi-resolution Execution Graph");
    expect(html).toContain("phase-status lens");
    expect(html).toContain("Clusters");
    expect(html).toContain("820 nodes");
    expect(html).toContain("dag-cluster");
  });

  it("renders DAG summary counts", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              execution_dag: executionDag(),
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Topology status summary");
    expect(html).toContain("<span>Ready</span><strong>1</strong>");
    expect(html).toContain("<span>Running</span><strong>1</strong>");
    expect(html).toContain("<span>Blocked</span><strong>0</strong>");
    expect(html).toContain("<span>Completed</span><strong>2</strong>");
  });

  it("renders graph insight surfaces from canonical state", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              codebase_graph_summary: {
                exists: true,
                indexed_file_count: 3,
                command_node_count: 1,
                test_node_count: 1,
                stale_node_count: 0,
              },
              task_graph_summary: {
                exists: true,
                ready_task_count: 1,
                blocked_task_count: 0,
                dependency_cycle_count: 0,
                node_counts: { ticket: 1 },
              },
              context_pack_preview: {
                items: [
                  {
                    node_id: "file:src/auth.ts",
                    kind: "file",
                    category: "files",
                    path: "src/auth.ts",
                    confidence: 0.9,
                    reason: "path mention in ticket summary",
                  },
                ],
              },
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Graph Insights");
    expect(html).toContain("Codebase Graph");
    expect(html).toContain("Task Graph");
    expect(html).toContain("Why these files?");
    expect(html).toContain("path mention in ticket summary");
  });

  it("renders execution group, validation, lease, and backlog fixtures", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              proposed_execution_groups: [
                {
                  execution_group_id: "execution-group:read-only-demo",
                  status: "proposed",
                  mode: "dry_run",
                  display_mode_label: "Planning preview",
                  execution_mode_label: "Read-only workers",
                  reason: "read-only reviews can run together",
                  payload: { execution_mode: "read_only", why_together: "read-only surfaces do not write" },
                  items: [
                    {
                      item_id: "item:docs",
                      task_id: "TICKET-001",
                      owner_role: "hardener",
                      action_kind: "review",
                    },
                  ],
                },
              ],
              active_execution_groups: [
                {
                  execution_group_id: "execution-group:running-validation",
                  status: "running",
                  mode: "validation",
                  display_mode_label: "Validation jobs",
                  selected_by: "dashboard",
                },
              ],
              recent_execution_groups: [
                {
                  execution_group_id: "execution-group:recent-read-only",
                  status: "completed",
                  mode: "read_only",
                  display_mode_label: "Read-only workers",
                  finished_at: "2026-05-17T00:00:00+00:00",
                },
              ],
              active_parallel_counts: {
                active_validation_jobs: 1,
                active_read_only_workers: 2,
                active_write_workers: 0,
              },
              parallelization_summary: { mode: "dry_run", display_mode_label: "Planning preview", group_count: 1 },
              why_not_parallel: {
                status: "serial_fallback",
                summary: "1 parallel candidate is using serialized handling.",
                reason_groups: [
                  {
                    reason_kind: "serial_fallback",
                    raw_reason_kinds: ["scope_fanout_exhausted"],
                    label: "Serial fallback",
                    count: 1,
                    human_summary: "No promotable ownership evidence; using serial fallback.",
                    next_action: "No promotable ownership evidence; using serial fallback.",
                  },
                ],
                next_improvements: [
                  {
                    reason_kind: "serial_fallback",
                    improvement_kind: "serial_fallback",
                    count: 1,
                    next_action: "No promotable ownership evidence; using serial fallback.",
                  },
                ],
              },
              completed_worker_reports: [
                {
                  worker_id: "worker:review",
                  status: "completed",
                  disposition_status: "awaiting_integrator_review",
                  disposition_label: "Awaiting integrator review",
                  disposition_summary: "Worker patch is queued for serialized integrator reconciliation.",
                },
              ],
              active_leases: [
                {
                  lease_id: "lease:old",
                  scope_node_id: "file:src/demo.ts",
                  owner_role: "builder",
                  status: "active",
                  expires_at: "2000-01-01T00:00:00+00:00",
                },
              ],
              validation_job_summary: {
                aggregate_status: "warning",
                job_count: 2,
                active_count: 1,
                latest: [{ job_id: "job:test", gate_id: "gate:test", command: "npm test", status: "running" }],
              },
              integration_backlog_from_parallel_workers: [
                { patch_id: "patch:worker-1", status: "queued", manifest_path: "target/automation_queue/patch.json" },
              ],
              blocked_parallel_candidates: [
                { task_id: "TICKET-009", reason: "unknown impact write task is serial" },
              ],
            },
          },
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Parallel Execution");
    expect(html).toContain("Planning preview");
    expect(html).toContain("execution-group:read-only-demo");
    expect(html).toContain("Start Read-Only Group");
    expect(html).toContain("Start Validation Group");
    expect(html).toContain("Stale lease: file:src/demo.ts");
    expect(html).toContain("Validation jobs");
    expect(html).toContain("Running groups");
    expect(html).toContain("Recently Completed");
    expect(html).toContain("execution-group:recent-read-only");
    expect(html).toContain("Awaiting integrator review");
    expect(html).toContain("patch:worker-1");
    expect(html).toContain("Why Not Parallel?");
    expect(html).toContain("No promotable ownership evidence; using serial fallback.");
    expect(html).toContain("scope_fanout_exhausted");
    expect(html).toContain("unknown impact write task is serial");
    expect(html).toContain("Cancel");
    expect(html).toContain("Release");
  });

  it("renders a recheck action for baseline blockers", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
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
        })}
        loading={false}
        onChoose={() => undefined}
        onNavigate={() => undefined}
        onRefresh={() => undefined}
      />,
    );

    expect(html).toContain("Baseline verification");
    expect(html).toContain("Baseline requires DATABASE_URL.");
    expect(html).toContain("Recheck blocker");
  });

});
