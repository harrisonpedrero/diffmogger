import { describe, expect, it } from "vitest";
import {
  defaultImportMode,
  emptyTicket,
  localTicketIssues,
  normalizeTicket,
  parseTicketImportText,
  PLACEHOLDER_TICKET_SUMMARY,
} from "./ticketModel";

describe("ticket model helpers", () => {
  it("normalizes manual tickets with pending defaults", () => {
    const ticket = normalizeTicket({ id: "TICKET-007", summary: "  Build queue  " });

    expect(ticket.status).toBe("pending");
    expect(ticket.summary).toBe("Build queue");
    expect(ticket.depends_on).toEqual([]);
  });

  it("chooses replace-placeholder only for the sample ticket", () => {
    expect(defaultImportMode([{ id: "TICKET-001", summary: PLACEHOLDER_TICKET_SUMMARY }])).toBe("replace-placeholder");
    expect(defaultImportMode([emptyTicket([])])).toBe("append");
  });

  it("parses markdown and csv imports into tickets", () => {
    const markdown = parseTicketImportText("## TICKET-001: Build local queue\n- verification: npm test", "markdown");
    const csv = parseTicketImportText("id,summary,depends_on\nTICKET-002,Document queue,TICKET-001\n", "csv");

    expect(markdown.tickets?.[0].verification_commands).toEqual(["npm test"]);
    expect(csv.tickets?.[0].depends_on).toEqual(["TICKET-001"]);
  });

  it("reports duplicate ids and missing dependencies before scaffold", () => {
    const issues = localTicketIssues([
      { id: "TICKET-001", summary: "First", depends_on: ["TICKET-999"] },
      { id: "TICKET-001", summary: "Duplicate" },
    ]);

    expect(issues.map((issue) => issue.type)).toContain("duplicate_id");
    expect(issues.map((issue) => issue.type)).toContain("missing_dependency");
  });
});
