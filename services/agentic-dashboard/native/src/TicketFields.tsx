import { listValue, normalizeTicket, TICKET_STATUSES, type Ticket } from "./ticketModel";

function listToText(values: string[]): string {
  return values.join("\n");
}

export function TicketFields(props: {
  ticket: Ticket;
  onChange: (ticket: Ticket) => void;
  title: string;
}) {
  function update(patch: Partial<Ticket>) {
    props.onChange(normalizeTicket({ ...props.ticket, ...patch }));
  }

  function updateList(key: keyof Pick<
    Ticket,
    "depends_on" | "acceptance_criteria" | "verification_commands" | "evidence" | "related_commits"
  >, value: string) {
    update({ [key]: listValue(value) } as Partial<Ticket>);
  }

  return (
    <section className="ticket-fields" aria-label={props.title}>
      <div className="ticket-field-header">
        <h3>{props.title}</h3>
        <span>{props.ticket.id || "New ticket"}</span>
      </div>
      <div className="brief-form-grid two">
        <label className="brief-field">
          <span>Ticket ID</span>
          <input value={props.ticket.id} onChange={(event) => update({ id: event.target.value })} placeholder="TICKET-001" />
        </label>
        <label className="brief-field">
          <span>Status</span>
          <select value={props.ticket.status} onChange={(event) => update({ status: event.target.value as Ticket["status"] })}>
            {TICKET_STATUSES.map((status) => (
              <option value={status} key={status}>{status}</option>
            ))}
          </select>
        </label>
      </div>
      <label className="brief-field">
        <span>Summary</span>
        <input
          value={props.ticket.summary}
          onChange={(event) => update({ summary: event.target.value })}
          placeholder="Build the first local workflow"
        />
      </label>
      <div className="brief-form-grid two ticket-list-fields">
        <label className="brief-field">
          <span>Depends on</span>
          <textarea
            rows={3}
            value={listToText(props.ticket.depends_on)}
            onChange={(event) => updateList("depends_on", event.target.value)}
            placeholder="TICKET-000"
          />
        </label>
        <label className="brief-field">
          <span>Acceptance criteria</span>
          <textarea
            rows={3}
            value={listToText(props.ticket.acceptance_criteria)}
            onChange={(event) => updateList("acceptance_criteria", event.target.value)}
            placeholder={"App opens locally\nPrimary flow works"}
          />
        </label>
        <label className="brief-field">
          <span>Verification commands</span>
          <textarea
            rows={3}
            value={listToText(props.ticket.verification_commands)}
            onChange={(event) => updateList("verification_commands", event.target.value)}
            placeholder={"npm test\nnpm run build"}
          />
        </label>
        <label className="brief-field">
          <span>Evidence</span>
          <textarea
            rows={3}
            value={listToText(props.ticket.evidence)}
            onChange={(event) => updateList("evidence", event.target.value)}
            placeholder="Manual smoke pass"
          />
        </label>
        <label className="brief-field">
          <span>Related commits</span>
          <textarea
            rows={3}
            value={listToText(props.ticket.related_commits)}
            onChange={(event) => updateList("related_commits", event.target.value)}
            placeholder="abc1234"
          />
        </label>
        <label className="brief-field">
          <span>Blocker</span>
          <textarea
            rows={3}
            value={props.ticket.blocker}
            onChange={(event) => update({ blocker: event.target.value })}
            placeholder="Waiting on API key"
          />
        </label>
      </div>
    </section>
  );
}
