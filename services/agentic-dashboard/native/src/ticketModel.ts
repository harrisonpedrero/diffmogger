export type TicketStatus = "pending" | "in_progress" | "candidate_done" | "done" | "blocked";

export type Ticket = {
  id: string;
  summary: string;
  depends_on: string[];
  status: TicketStatus;
  acceptance_criteria: string[];
  verification_commands: string[];
  evidence: string[];
  related_commits: string[];
  blocker: string;
};

export type TicketValidationIssue = {
  level: "error" | "warning" | string;
  type: string;
  ticket_id?: string;
  ticket_ids?: string[];
  depends_on?: string;
  detail: string;
};

export type TicketSnapshot = {
  ticket_file?: string;
  tickets?: Ticket[];
  summary?: {
    counts?: Record<string, number>;
    total?: number;
  };
  dependency_report?: Record<string, unknown>;
  next?: {
    status?: string;
    reason?: string;
    ticket?: Partial<Ticket> | null;
  };
  validation_issues?: TicketValidationIssue[];
};

export const TICKET_STATUSES: TicketStatus[] = [
  "pending",
  "in_progress",
  "candidate_done",
  "done",
  "blocked",
];

export type TicketImportFormat = "markdown" | "csv" | "json";

export const PLACEHOLDER_TICKET_ID = "TICKET-001";
export const PLACEHOLDER_TICKET_SUMMARY = "Replace this sample with the first startup ticket.";

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : value == null ? "" : String(value).trim();
}

export function listValue(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => stringValue(item)).filter(Boolean);
  }
  const text = stringValue(value);
  if (!text) return [];
  return text
    .split(/\r?\n|[;|]/)
    .flatMap((part) => (part.includes(",") ? part.split(",") : [part]))
    .map((part) => part.trim().replace(/^[-*]\s+/, ""))
    .filter(Boolean);
}

export function normalizeTicket(input: Partial<Ticket> | Record<string, unknown> = {}, fallbackId = ""): Ticket {
  const statusText = stringValue(input.status).toLowerCase();
  const status = TICKET_STATUSES.includes(statusText as TicketStatus) ? (statusText as TicketStatus) : "pending";
  return {
    id: stringValue(input.id) || fallbackId,
    summary: stringValue(input.summary),
    depends_on: listValue(input.depends_on),
    status,
    acceptance_criteria: listValue(input.acceptance_criteria),
    verification_commands: listValue(input.verification_commands),
    evidence: listValue(input.evidence),
    related_commits: listValue(input.related_commits),
    blocker: stringValue(input.blocker),
  };
}

export function nextTicketId(tickets: Array<Partial<Ticket> | Record<string, unknown>>, prefix = "TICKET"): string {
  const used = new Set(tickets.map((ticket) => stringValue(ticket.id)).filter(Boolean));
  const highest = [...used].reduce((max, id) => {
    const match = id.match(/(\d+)$/);
    return match ? Math.max(max, Number(match[1])) : max;
  }, 0);
  let index = highest + 1;
  while (used.has(`${prefix}-${String(index).padStart(3, "0")}`)) {
    index += 1;
  }
  return `${prefix}-${String(index).padStart(3, "0")}`;
}

export function emptyTicket(tickets: Array<Partial<Ticket> | Record<string, unknown>> = []): Ticket {
  return normalizeTicket(
    {
      id: nextTicketId(tickets),
      status: "pending",
    },
  );
}

export function normalizeTickets(input: unknown): Ticket[] {
  if (!Array.isArray(input)) return [];
  return input
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item, index) => normalizeTicket(item, stringValue(item.id) || `TICKET-${String(index + 1).padStart(3, "0")}`));
}

export function ticketToJson(ticket: Partial<Ticket> | Record<string, unknown>): string {
  return JSON.stringify(normalizeTicket(ticket), null, 2);
}

export function ticketImportExample(format: TicketImportFormat | string): string {
  if (format === "csv") {
    return [
      "id,summary,status,depends_on,acceptance_criteria,verification_commands,evidence,related_commits,blocker",
      "TICKET-001,\"Build the first local workflow\",pending,\"\",\"App opens locally; Primary flow works\",\"npm test; npm run build\",\"Manual smoke pass\",\"\",\"\"",
      "TICKET-002,\"Add setup validation\",pending,\"TICKET-001\",\"Invalid input is shown clearly\",\"npm test\",\"\",\"\",\"\"",
    ].join("\n");
  }
  if (format === "json") {
    return JSON.stringify(
      [
        {
          id: "TICKET-001",
          summary: "Build the first local workflow",
          depends_on: [],
          status: "pending",
          acceptance_criteria: ["App opens locally", "Primary flow works"],
          verification_commands: ["npm test", "npm run build"],
          evidence: ["Manual smoke pass"],
          related_commits: [],
          blocker: "",
        },
      ],
      null,
      2,
    );
  }
  return [
    "## TICKET-001: Build the first local workflow",
    "status: pending",
    "depends_on: TICKET-000",
    "acceptance: App opens locally; Primary flow works",
    "verification: npm test; npm run build",
    "evidence: Manual smoke pass",
    "blocker: none",
    "",
    "## TICKET-002: Add setup validation",
    "status: pending",
    "depends_on: TICKET-001",
    "acceptance: Invalid input is shown clearly",
    "verification: npm test",
  ].join("\n");
}

export function ticketsToJson(tickets: Array<Partial<Ticket> | Record<string, unknown>>): string {
  return JSON.stringify(tickets.map((ticket) => normalizeTicket(ticket)), null, 2);
}

export function parseTicketJson(text: string): { ticket?: Ticket; error?: string } {
  try {
    const payload = JSON.parse(text);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return { error: "Ticket JSON must be an object." };
    }
    return { ticket: normalizeTicket(payload as Record<string, unknown>) };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

export function parseTicketArrayJson(text: string): { tickets?: Ticket[]; error?: string } {
  try {
    const payload = JSON.parse(text);
    const raw = Array.isArray(payload)
      ? payload
      : payload && typeof payload === "object" && Array.isArray((payload as Record<string, unknown>).tickets)
        ? (payload as { tickets: unknown[] }).tickets
        : null;
    if (!raw) return { error: "Ticket import JSON must be an array or an object with a tickets array." };
    return { tickets: normalizeTickets(raw) };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

function ticketFromLine(line: string): Partial<Ticket> | null {
  const cleaned = line
    .replace(/^\s*(?:[-*]|\d+[.)])\s+/, "")
    .replace(/^\[[ xX-]\]\s+/, "")
    .trim();
  if (!cleaned) return null;
  const match = cleaned.match(/^([A-Za-z][A-Za-z0-9_-]*-\d+)\s*(?::|-|\s+-\s+)\s*(.+)$/);
  if (match) {
    return { id: match[1], summary: match[2].trim(), status: "pending" };
  }
  return cleaned.length >= 8 ? { summary: cleaned, status: "pending" } : null;
}

export function parseMarkdownTickets(text: string): Ticket[] {
  const parsed: Partial<Ticket>[] = [];
  let current: Partial<Ticket> | null = null;
  const finish = () => {
    if (current) parsed.push(current);
    current = null;
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    if (heading) {
      const candidate = ticketFromLine(heading[1]);
      if (candidate) {
        finish();
        current = candidate;
      }
      continue;
    }
    const field = line.match(/^(?:[-*]\s*)?(depends_on|depends on|acceptance|acceptance_criteria|criteria|verification|verification_commands|evidence|related_commits|commits|blocker|status)\s*:\s*(.+)$/i);
    if (field && current) {
      const key = field[1].toLowerCase().replace(/\s+/g, "_");
      const normalizedKey =
        key === "acceptance" || key === "criteria"
          ? "acceptance_criteria"
          : key === "verification"
            ? "verification_commands"
            : key === "commits"
              ? "related_commits"
              : key;
      const value = field[2].trim();
      if (["depends_on", "acceptance_criteria", "verification_commands", "evidence", "related_commits"].includes(normalizedKey)) {
        current = { ...current, [normalizedKey]: [...listValue((current as Record<string, unknown>)[normalizedKey]), ...listValue(value)] };
      } else {
        current = { ...current, [normalizedKey]: value };
      }
      continue;
    }
    const bullet = ticketFromLine(line);
    if (bullet && (/^\s*[-*]\s+/.test(raw) || /^\s*\d+[.)]\s+/.test(raw))) {
      finish();
      current = bullet;
    }
  }
  finish();
  const fallback = parsed.length ? parsed : text.split(/\r?\n/).map(ticketFromLine).filter(Boolean) as Partial<Ticket>[];
  return fallback.map((ticket, index) => normalizeTicket(ticket, stringValue(ticket.id) || `TICKET-${String(index + 1).padStart(3, "0")}`));
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"' && line[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += char;
    }
  }
  cells.push(cell);
  return cells.map((value) => value.trim());
}

export function parseCsvTickets(text: string): Ticket[] {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) return [];
  const headers = parseCsvLine(lines[0]).map((header) => header.toLowerCase().replace(/[-\s]+/g, "_"));
  return lines.slice(1).map((line, index) => {
    const cells = parseCsvLine(line);
    const raw: Record<string, unknown> = {};
    headers.forEach((header, cellIndex) => {
      const key =
        header === "depends" || header === "depends_on"
          ? "depends_on"
          : header === "acceptance" || header === "criteria"
            ? "acceptance_criteria"
            : header === "verification" || header === "checks"
              ? "verification_commands"
              : header === "commits"
                ? "related_commits"
                : header;
      raw[key] = cells[cellIndex] ?? "";
    });
    return normalizeTicket(raw, stringValue(raw.id) || `TICKET-${String(index + 1).padStart(3, "0")}`);
  });
}

export function parseTicketImportText(
  text: string,
  format: "markdown" | "csv" | "json" | string,
): { tickets?: Ticket[]; error?: string } {
  try {
    if (format === "json") return parseTicketArrayJson(text);
    if (format === "csv") return { tickets: parseCsvTickets(text) };
    return { tickets: parseMarkdownTickets(text) };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

export function isPlaceholderTicket(ticket: Partial<Ticket> | Record<string, unknown>): boolean {
  return stringValue(ticket.id) === PLACEHOLDER_TICKET_ID && stringValue(ticket.summary) === PLACEHOLDER_TICKET_SUMMARY;
}

export function defaultImportMode(tickets: Array<Partial<Ticket> | Record<string, unknown>>): "append" | "replace-placeholder" {
  return tickets.length > 0 && tickets.every(isPlaceholderTicket) ? "replace-placeholder" : "append";
}

export function canSplitTicket(ticket: Partial<Ticket> | Record<string, unknown>): boolean {
  return normalizeTicket(ticket).status === "pending";
}

export function localTicketIssues(tickets: Array<Partial<Ticket> | Record<string, unknown>>): TicketValidationIssue[] {
  const normalized = tickets.map((ticket) => normalizeTicket(ticket));
  const issues: TicketValidationIssue[] = [];
  const seen = new Map<string, number>();
  for (const ticket of normalized) {
    if (!ticket.id) {
      issues.push({ level: "error", type: "missing_id", detail: "Ticket is missing an id." });
    }
    if (!ticket.summary) {
      issues.push({ level: "error", type: "missing_summary", ticket_id: ticket.id, detail: "Ticket is missing a summary." });
    }
    if (ticket.id) seen.set(ticket.id, (seen.get(ticket.id) ?? 0) + 1);
  }
  for (const [id, count] of seen) {
    if (count > 1) {
      issues.push({ level: "error", type: "duplicate_id", ticket_id: id, detail: "Ticket id is duplicated." });
    }
  }
  const ids = new Set(normalized.map((ticket) => ticket.id).filter(Boolean));
  for (const ticket of normalized) {
    for (const dependency of ticket.depends_on) {
      if (!ids.has(dependency)) {
        issues.push({
          level: "error",
          type: "missing_dependency",
          ticket_id: ticket.id,
          depends_on: dependency,
          detail: "Ticket depends on an unknown ticket id.",
        });
      }
    }
  }
  return issues;
}

export function issueLabel(issue: TicketValidationIssue): string {
  const ticket = issue.ticket_id ? `${issue.ticket_id}: ` : "";
  return `${ticket}${issue.detail || issue.type}`;
}
