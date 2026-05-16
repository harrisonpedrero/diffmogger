import { describe, expect, it } from "vitest";
import {
  type IntakeDraft,
  applyAutomationScope,
  automationScopeForDraft,
  lowCortisolDraftFromGeneratedIntake,
  lowCortisolProgressLabel,
  setupRunState,
  visibleScaffoldPreviewFiles,
} from "./BriefWizard";

function draft(overrides: Partial<IntakeDraft> = {}): IntakeDraft {
  return {
    project_name: "Project",
    project_mode: "fresh_project",
    product_goal: "Build a useful project.",
    target_user: "Builders",
    desired_first_demo: "A working demo.",
    tech_preferences: [],
    hard_constraints: [],
    safety_constraints: [],
    automation_must_never_do: [],
    external_services: [],
    env_access_policy: "project_commands_only",
    verification_commands: [],
    human_bridge_enabled: true,
    human_bridge_mode: "file_only",
    human_requested_text_responses: true,
    local_notifications_enabled: true,
    worker_agents_allowed: true,
    codex_cli_workers_expected_on_broad_runs: true,
    write_worker_agents_allowed: true,
    max_write_worker_count: 3,
    write_worker_guidance: "",
    parallel_execution_mode: "aggressive",
    symbol_graph_languages: ["python", "typescript", "javascript"],
    parallel_write_min_confidence: 0.75,
    parallel_write_direct_confidence: 0.75,
    max_parallel_write_workers: 3,
    max_parallel_scope_workers: 2,
    multi_role_automations_allowed: true,
    automation_role_profile: "planner_builder_hardener_integrator",
    automation_checkpoint_commits: true,
    multi_role_allow_remotes: false,
    optional_mcp_servers: [],
    campaign_mode: "ongoing",
    ticket_run_file: "",
    ticket_run_seed_tickets: [],
    ticket_completion_notify: true,
    meaningful_deliverable: "A useful change.",
    beyond_mvp: "Keep improving.",
    assumptions: [],
    additional_context_files: [],
    overwrite_existing_scaffold_files: false,
    ...overrides,
  };
}

describe("Brief automation mode mapping", () => {
  it("defaults to the continuous DAG scheduler role profile", () => {
    const next = draft();

    expect(next.multi_role_automations_allowed).toBe(true);
    expect(next.automation_role_profile).toBe("planner_builder_hardener_integrator");
  });

  it("maps legacy single-lane drafts back to the DAG scheduler role profile", () => {
    const next = draft({
      multi_role_automations_allowed: false,
    });

    const generated = lowCortisolDraftFromGeneratedIntake(
      { automation_role_profile: "single_lane", multi_role_automations_allowed: false },
      next,
    );
    expect(generated.multi_role_automations_allowed).toBe(true);
    expect(generated.automation_role_profile).toBe("planner_builder_hardener_integrator");
  });

  it("treats automation_role_profile as canonical over the legacy boolean", () => {
    const next = lowCortisolDraftFromGeneratedIntake(
      {
        automation_role_profile: "planner_builder_hardener_integrator",
        multi_role_automations_allowed: false,
      },
      draft(),
    );

    expect(next.automation_role_profile).toBe("planner_builder_hardener_integrator");
    expect(next.multi_role_automations_allowed).toBe(true);
  });

  it("maps campaign scope between ongoing and bounded", () => {
    const ticket = applyAutomationScope(draft(), "bounded");
    const ongoing = applyAutomationScope(ticket, "ongoing");

    expect(ticket.campaign_mode).toBe("bounded");
    expect(automationScopeForDraft(ticket)).toBe("bounded");
    expect(ongoing.campaign_mode).toBe("ongoing");
    expect(automationScopeForDraft(ongoing)).toBe("ongoing");
  });

  it("carries seed tickets in ticket-campaign drafts", () => {
    const ticket = draft({
      campaign_mode: "bounded",
      ticket_run_seed_tickets: [{ id: "TICKET-001", summary: "Inspect queue", status: "pending", depends_on: [], acceptance_criteria: [], verification_commands: [], evidence: [], related_commits: [], blocker: "" }],
    });

    expect(ticket.ticket_run_seed_tickets).toHaveLength(1);
    expect(ticket.ticket_run_seed_tickets[0].status).toBe("pending");
  });

  it("normalizes low cortisol generated intake to SQLite ticket queue defaults", () => {
    const next = lowCortisolDraftFromGeneratedIntake(
      {
        project_name: "Gentle Builder",
        product_goal: "Build a small planning app.",
        target_user: "Solo builders",
        desired_first_demo: "A user can add a plan.",
        human_bridge_mode: "local_notifier",
        optional_mcp_servers: ["context7", "playwright"],
        campaign_mode: "ongoing",
        automation_role_profile: "single_lane",
        ticket_run_seed_tickets: [
          {
            id: "TICKET-001",
            summary: "Create the first planning screen",
            status: "pending",
          },
        ],
      },
      draft({ additional_context_files: [".diffmogger/context/notes.md"] }),
      "Target",
    );

    expect(next.campaign_mode).toBe("bounded");
    expect(next.ticket_run_file).toBe("");
    expect(next.optional_mcp_servers).toEqual([]);
    expect(next.human_bridge_mode).toBe("file_only");
    expect(next.ticket_run_seed_tickets).toHaveLength(1);
    expect(next.additional_context_files).toEqual([".diffmogger/context/notes.md"]);
  });

  it("labels low cortisol two-pass generation progress", () => {
    expect(lowCortisolProgressLabel([])).toBe("Generating Intake");
    expect(lowCortisolProgressLabel([
      { runId: "run", command: "brief.generate_intake", stage: "intake-generate", level: "info", message: "Generating intake." },
    ])).toBe("Generating Intake");
    expect(lowCortisolProgressLabel([
      { runId: "run", command: "brief.generate_intake", stage: "ticket-generate", level: "info", message: "Generating tickets." },
    ])).toBe("Generating Tickets");
  });

  it("hides preserved sidecar files from the setup review file list", () => {
    const visible = visibleScaffoldPreviewFiles([
      {
        rel_path: ".diffmogger/state/PROJECT_CONTEXT.md",
        action: "skip_existing",
        exists: true,
        managed_section: false,
        detail: "Will not overwrite the existing sidecar file with force disabled.",
      },
      {
        rel_path: ".diffmogger/state/AGENTS.md",
        action: "create",
        exists: false,
        managed_section: true,
        detail: "Will create this target-local generated file.",
      },
    ]);

    expect(visible.map((file) => file.rel_path)).toEqual([".diffmogger/state/AGENTS.md"]);
  });

  it("enables Run after scaffold and treats pending bootstrap as a first-run phase", () => {
    const unscaffolded = setupRunState({
      target: { path: "/tmp/app", name: "app", is_diffmogger_project: false, project_intake_exists: false, dashboard_state_exists: false, automation_task_exists: false },
      brief: {},
      run: { task: {} },
      files: [],
      home: { title: "app", automation_status: "UNKNOWN", current_horizon: "", next_action: "", pending_human_requests: 0, unhandled_inbox: 0, queued_patches: 0, deferred_patches: 0 },
    });
    expect(unscaffolded.enabled).toBe(false);
    expect(unscaffolded.reason).toContain("Scaffold");

    const pending = setupRunState({
      target: { path: "/tmp/app", name: "app", is_diffmogger_project: true, project_intake_exists: true, dashboard_state_exists: true, automation_task_exists: true },
      brief: { dashboard_state: {} },
      run: { task: { bootstrap_status: "pending" } },
      files: [],
      home: { title: "app", automation_status: "ACTIVE", current_horizon: "", next_action: "", pending_human_requests: 0, unhandled_inbox: 0, queued_patches: 0, deferred_patches: 0 },
    });
    expect(pending.enabled).toBe(true);
    expect(pending.status).toBe("First run will prepare target");
    expect(pending.reason).toContain("first Start");

    const completed = setupRunState({
      target: { path: "/tmp/app", name: "app", is_diffmogger_project: true, project_intake_exists: true, dashboard_state_exists: true, automation_task_exists: true },
      brief: { dashboard_state: { initial_bootstrap_status: "pass" } },
      run: { task: { bootstrap_status: "bootstrapped" } },
      files: [],
      home: { title: "app", automation_status: "ACTIVE", current_horizon: "", next_action: "", pending_human_requests: 0, unhandled_inbox: 0, queued_patches: 0, deferred_patches: 0 },
    });
    expect(completed.enabled).toBe(true);
    expect(completed.bootstrapCompleted).toBe(true);
    expect(completed.status).toBe("Ready");
  });
});
