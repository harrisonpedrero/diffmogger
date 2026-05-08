import { describe, expect, it } from "vitest";
import {
  type IntakeDraft,
  applyAutomationLane,
  applyAutomationScope,
  automationLaneForDraft,
  automationScopeForDraft,
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
    desired_cadence: "every 60 minutes",
    human_bridge_enabled: true,
    human_bridge_mode: "file_only",
    human_requested_text_responses: true,
    local_notifications_enabled: true,
    worker_agents_allowed: true,
    codex_cli_workers_expected_on_broad_runs: true,
    write_worker_agents_allowed: false,
    max_write_worker_count: 0,
    write_worker_guidance: "",
    multi_role_automations_allowed: false,
    automation_role_profile: "single_lane",
    automation_checkpoint_commits: true,
    multi_role_base_cadence_minutes: 30,
    automation_schedule_strategy: "single_lane_interval",
    multi_role_allow_remotes: false,
    automation_signals_enabled: false,
    optional_mcp_servers: [],
    automation_run_mode: "continuous_improvement",
    ticket_run_file: ".diffmogger/state/TICKET_RUN.md",
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
  it("maps the simplified single-lane choice to legacy backend fields", () => {
    const next = applyAutomationLane(
      draft({
        multi_role_automations_allowed: true,
        automation_role_profile: "planner_builder_hardener_integrator",
        automation_schedule_strategy: "continuous_conveyor",
      }),
      "single_scheduled_lane",
    );

    expect(next.multi_role_automations_allowed).toBe(false);
    expect(next.automation_role_profile).toBe("single_lane");
    expect(next.automation_schedule_strategy).toBe("single_lane_interval");
    expect(automationLaneForDraft(next)).toBe("single_scheduled_lane");
  });

  it("maps the P/B/H/I conveyor choice to legacy backend fields", () => {
    const next = applyAutomationLane(draft(), "multi_role_conveyor");

    expect(next.multi_role_automations_allowed).toBe(true);
    expect(next.automation_role_profile).toBe("planner_builder_hardener_integrator");
    expect(next.automation_schedule_strategy).toBe("continuous_conveyor");
    expect(automationLaneForDraft(next)).toBe("multi_role_conveyor");
  });

  it("normalizes legacy conveyor combinations for display", () => {
    expect(
      automationLaneForDraft(
        draft({
          multi_role_automations_allowed: false,
          automation_role_profile: "single_lane",
          automation_schedule_strategy: "continuous_conveyor",
        }),
      ),
    ).toBe("multi_role_conveyor");
    expect(
      automationLaneForDraft(
        draft({
          multi_role_automations_allowed: false,
          automation_role_profile: "planner_builder_hardener_integrator",
          automation_schedule_strategy: "single_lane_interval",
        }),
      ),
    ).toBe("multi_role_conveyor");
  });

  it("maps build scope between boundless build and ticket campaign", () => {
    const ticket = applyAutomationScope(draft(), "ticket_campaign");
    const boundless = applyAutomationScope(ticket, "boundless_build");

    expect(ticket.automation_run_mode).toBe("ticket_campaign");
    expect(automationScopeForDraft(ticket)).toBe("ticket_campaign");
    expect(boundless.automation_run_mode).toBe("continuous_improvement");
    expect(automationScopeForDraft(boundless)).toBe("boundless_build");
  });
});
