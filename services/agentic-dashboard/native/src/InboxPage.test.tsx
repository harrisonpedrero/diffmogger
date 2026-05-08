import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { InboxPage } from "./InboxPage";
import type { InboxSnapshot, ProjectSnapshot } from "./api/backend";

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
    files: [],
    home: {
      title: "Project",
      automation_status: "ACTIVE",
      current_horizon: "H1",
      next_action: "Run Once Now",
      pending_human_requests: 0,
      unhandled_inbox: 0,
      queued_patches: 0,
      deferred_patches: 0,
    },
  };
}

function inboxSnapshot(): InboxSnapshot {
  return {
    target: projectSnapshot().target,
    bridge_mode: "file_only",
    requests: [],
    active_requests: [],
    notes: [],
    active_notes: [],
    archive: [],
    outbox: [],
    counts: {
      pending_requests: 0,
      queued_notes: 0,
      failed_notes: 0,
      archived_items: 0,
      outbound_records: 0,
    },
    raw_file_keys: ["human.inbox", "human.requests"],
  };
}

describe("InboxPage", () => {
  it("renders the note-to-next-run send form", () => {
    const html = renderToStaticMarkup(
      <InboxPage
        snapshot={projectSnapshot()}
        loading={false}
        onRefresh={() => undefined}
        initialSnapshot={inboxSnapshot()}
        initialTab="Notes to next run"
      />,
    );

    expect(html).toContain("Notes to next run");
    expect(html).toContain("New note");
    expect(html).toContain("Related request, ticket, file, or run");
    expect(html).toContain("Message body");
    expect(html).toContain("Send To Next Run");
    expect(html).not.toContain("docs/HUMAN_INBOX.md");
  });
});
