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
        snapshot={snapshot({ brief: { intake: { automation_run_mode: "ticket_campaign" } } })}
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
    expect(html).toContain("Run Codex to propose only new pending tickets");
    expect(html).toContain("Create a blank pending ticket in the editor");
  });

  it("renders split ticket action for pending queue tickets from snapshot state", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          brief: { intake: { automation_run_mode: "ticket_campaign" } },
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

  it("renders the typed conveyor state machine panel", () => {
    const html = renderToStaticMarkup(
      <RunPage
        snapshot={snapshot({
          run: {
            state: {
              next_actions: [{ owner_role: "builder", status: "next", reason: "Implement the selected work item." }],
              conveyor_machine: {
                current_stage: "implementation",
                stage_status: "ready",
                owner_role: "builder",
                work_item: {
                  id: "workitem:default",
                  status: "ACTIVE",
                  current_stage: "implementation",
                  stage_status: "ready",
                  owner_role: "builder",
                  capability_manifest_id: "capability:repo",
                  capability_manifest_version: 2,
                  validation_status: "passed",
                  continuation_token: "workitem:default:implementation:42",
                },
                capability_manifest: {
                  languages: { primary: "TypeScript" },
                  commands: [{ kind: "test", command: "npm test" }],
                },
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

    expect(html).toContain("State Machine");
    expect(html).toContain("workitem:default:implementation:42");
    expect(html).toContain("TypeScript / 1 command");
    expect(html).toContain("Implement the selected work item.");
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
