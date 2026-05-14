import { describe, expect, it } from "vitest";
import {
  type IntakeDraft,
  applyAutomationScope,
  automationScopeForDraft,
  lowCortisolDraftFromGeneratedIntake,
  lowCortisolProgressLabel,
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
    write_worker_agents_allowed: false,
    max_write_worker_count: 0,
    write_worker_guidance: "",
    multi_role_automations_allowed: true,
    automation_role_profile: "planner_builder_hardener_integrator",
    automation_checkpoint_commits: true,
    multi_role_allow_remotes: false,
    optional_mcp_servers: [],
    automation_run_mode: "continuous_improvement",
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
  it("defaults to the continuous role conveyor", () => {
    const next = draft();

    expect(next.multi_role_automations_allowed).toBe(true);
    expect(next.automation_role_profile).toBe("planner_builder_hardener_integrator");
  });

  it("keeps single-lane drafts single-role", () => {
    const next = draft({
      multi_role_automations_allowed: false,
      automation_role_profile: "single_lane",
    });

    expect(next.multi_role_automations_allowed).toBe(false);
    expect(next.automation_role_profile).toBe("single_lane");
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

  it("maps build scope between boundless build and ticket campaign", () => {
    const ticket = applyAutomationScope(draft(), "ticket_campaign");
    const boundless = applyAutomationScope(ticket, "boundless_build");

    expect(ticket.automation_run_mode).toBe("ticket_campaign");
    expect(automationScopeForDraft(ticket)).toBe("ticket_campaign");
    expect(boundless.automation_run_mode).toBe("continuous_improvement");
    expect(automationScopeForDraft(boundless)).toBe("boundless_build");
  });

  it("carries seed tickets in ticket-campaign drafts", () => {
    const ticket = draft({
      automation_run_mode: "ticket_campaign",
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
        automation_run_mode: "continuous_improvement",
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

    expect(next.automation_run_mode).toBe("ticket_campaign");
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
});
