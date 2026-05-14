import { describe, expect, it } from "vitest";
import {
  canSplitTicket,
  defaultImportMode,
  emptyTicket,
  localTicketIssues,
  normalizeTicket,
  parseTicketImportText,
  PLACEHOLDER_TICKET_SUMMARY,
  ticketImportExample,
  type TicketImportFormat,
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

  it("only allows pending tickets to be split", () => {
    expect(canSplitTicket({ id: "TICKET-001", status: "pending" })).toBe(true);
    expect(canSplitTicket({ id: "TICKET-002", status: "done" })).toBe(false);
  });

  it("parses markdown and csv imports into tickets", () => {
    const markdown = parseTicketImportText("## TICKET-001: Build local queue\n- verification: npm test", "markdown");
    const csv = parseTicketImportText("id,summary,depends_on\nTICKET-002,Document queue,TICKET-001\n", "csv");

    expect(markdown.tickets?.[0].verification_commands).toEqual(["npm test"]);
    expect(csv.tickets?.[0].depends_on).toEqual(["TICKET-001"]);
  });

  it("keeps displayed import examples parseable", () => {
    const formats: TicketImportFormat[] = ["markdown", "csv", "json"];

    formats.forEach((format) => {
      const parsed = parseTicketImportText(ticketImportExample(format), format);

      expect(parsed.error).toBeUndefined();
      expect(parsed.tickets?.[0]).toMatchObject({
        id: "TICKET-001",
        summary: "Build the first local workflow",
      });
    });
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
