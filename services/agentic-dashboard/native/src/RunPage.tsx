import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileDown,
  FilePlus2,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Trash2,
  Users,
  WandSparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot } from "./api/backend";
import {
  listenBackendLogs,
  runBackendCommand,
  runBackendCommandStreamed,
  selectTicketImportFile,
} from "./api/backend";
import { buildRunModel, type RunAction, type RunRoute } from "./runModel";
import {
  defaultImportMode,
  emptyTicket,
  issueLabel,
  normalizeTickets,
  parseTicketJson,
  ticketToJson,
  type Ticket,
  type TicketSnapshot,
} from "./ticketModel";

type RunLogEvent = BackendLogEvent & { capturedAt: string };

function routeFromRun(route: RunRoute): "Brief" | "Run" | "Review" | "Advanced" {
  return route;
}

function formatTime(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function value(value: string, fallback = "Not recorded"): string {
  return value.trim() ? value : fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function textValue(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function isTicketCampaign(snapshot: ProjectSnapshot | null): boolean {
  const records = [
    asRecord(snapshot?.brief?.intake),
    asRecord(snapshot?.brief?.draft_intake),
    asRecord(snapshot?.brief?.dashboard_state),
  ];
  return records.some((record) => textValue(record.automation_run_mode) === "ticket_campaign");
}

function ActionButton(props: {
  action: RunAction;
  onRun: (action: RunAction) => void;
  icon?: ReactNode;
  primary?: boolean;
  disabled?: boolean;
}) {
  const disabled = props.disabled ?? !props.action.enabled;
  return (
    <button
      className={props.primary ? "primary-action" : "secondary-action"}
      disabled={disabled}
      title={disabled ? props.action.reason : undefined}
      onClick={() => props.onRun(props.action)}
    >
      {props.icon}
      {props.action.label}
    </button>
  );
}

function DetailRow(props: { label: string; value: string | number }) {
  return (
    <div className="data-row">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

export function RunPage(props: {
  snapshot: ProjectSnapshot | null;
  loading: boolean;
  onChoose: () => void;
  onNavigate: (route: "Brief" | "Run" | "Review" | "Advanced") => void;
  onRefresh: () => void;
}) {
  const model = useMemo(() => buildRunModel(props.snapshot), [props.snapshot]);
  const [busyCommand, setBusyCommand] = useState<string | null>(null);
  const [logs, setLogs] = useState<RunLogEvent[]>([]);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandMessage, setCommandMessage] = useState<string | null>(null);
  const [logOverride, setLogOverride] = useState<Record<string, unknown> | null>(null);
  const [writeOwnership, setWriteOwnership] = useState("");
  const [ticketSnapshot, setTicketSnapshot] = useState<TicketSnapshot | null>(null);
  const [ticketBusy, setTicketBusy] = useState<string | null>(null);
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [ticketMessage, setTicketMessage] = useState<string | null>(null);
  const [ticketEditorId, setTicketEditorId] = useState<string | null>(null);
  const [ticketEditorJson, setTicketEditorJson] = useState("");
  const [ticketImportFormat, setTicketImportFormat] = useState<"markdown" | "csv" | "json">("markdown");
  const [ticketImportMode, setTicketImportMode] = useState<"append" | "replace-placeholder" | "replace-all">("append");
  const [ticketImportText, setTicketImportText] = useState("");
  const [ticketImportFile, setTicketImportFile] = useState("");
  const [ticketImportPreview, setTicketImportPreview] = useState<TicketSnapshot | null>(null);
  const [ticketDraft, setTicketDraft] = useState<{ draft_id?: string; candidates: Ticket[] } | null>(null);
  const isBusy = props.loading || busyCommand !== null;

  const target = props.snapshot?.target.path;
  const ticketCampaign = isTicketCampaign(props.snapshot);
  const ticketTickets = normalizeTickets(ticketSnapshot?.tickets ?? []);
  const ticketIssues = ticketSnapshot?.validation_issues ?? [];
  const ticketCounts = ticketSnapshot?.summary?.counts ?? {};

  useEffect(() => {
    if (!target || !model.isScaffolded || !ticketCampaign) {
      setTicketSnapshot(null);
      return;
    }
    void loadTickets();
  }, [target, model.isScaffolded, ticketCampaign]);
  const displayedLog = logOverride
    ? {
        exists: logOverride.exists === true,
        path: String(logOverride.rel_path || logOverride.path || ""),
        modifiedAt: String(logOverride.modified_at || ""),
        content: String(logOverride.content || ""),
        lines: Array.isArray(logOverride.lines)
          ? logOverride.lines
              .map((line) => (typeof line === "object" && line ? (line as Record<string, unknown>) : {}))
              .map((line) => ({
                timestamp: String(line.timestamp || logOverride.modified_at || ""),
                text: String(line.text || ""),
              }))
              .filter((line) => line.text)
          : [],
      }
    : model.runLog;
  const terminalLines =
    logs.length > 0
      ? logs.map((line) => ({
          timestamp: line.capturedAt,
          text: `[${line.stage}] ${line.message}`,
          level: line.level,
        }))
      : displayedLog.lines.map((line) => ({ ...line, level: "info" }));

  async function runAction(action: RunAction) {
    setCommandError(null);
    setCommandMessage(null);
    if (action.kind === "choose-project") {
      props.onChoose();
      return;
    }
    if (action.kind === "navigate" && action.route) {
      if (action.route === "Run") props.onRefresh();
      else props.onNavigate(routeFromRun(action.route));
      return;
    }
    if (!action.command || !target || !action.enabled) return;
    const command = action.command;
    if (command === "worker.run_write" && !writeOwnership.trim()) {
      setCommandError("Enter a disjoint ownership scope before launching a write worker.");
      return;
    }
    const runId = `${command}-${Date.now()}`;
    setBusyCommand(command);
    setLogs([]);
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setLogs((current) => [...current, { ...event, capturedAt: new Date().toISOString() }]);
      });
      const payload: BackendEnvelope<Record<string, unknown>> = await runBackendCommandStreamed({
        runId,
        command,
        target,
        ownership: command === "worker.run_write" ? writeOwnership.trim() : undefined,
      });
      if (!payload.ok) {
        setCommandError(payload.message ?? "Backend command failed.");
      }
      props.onRefresh();
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : String(error));
    } finally {
      unlisten?.();
      setBusyCommand(null);
    }
  }

  async function loadTickets() {
    if (!target) return;
    setTicketError(null);
    try {
      const payload = await runBackendCommand<TicketSnapshot>({
        command: "ticket.load",
        target,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Could not load the ticket queue.");
        return;
      }
      const data = payload.data;
      setTicketSnapshot(data);
      setTicketImportMode(defaultImportMode(normalizeTickets(data.tickets ?? [])));
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    }
  }

  function editTicket(ticket: Ticket) {
    setTicketEditorId(ticket.id);
    setTicketEditorJson(ticketToJson(ticket));
    setTicketMessage(null);
    setTicketError(null);
  }

  function newTicket() {
    const ticket = emptyTicket(ticketTickets);
    setTicketEditorId(null);
    setTicketEditorJson(ticketToJson(ticket));
    setTicketMessage("New ticket is ready to save.");
  }

  async function saveTicket() {
    if (!target) return;
    const parsed = parseTicketJson(ticketEditorJson);
    if (!parsed.ticket) {
      setTicketError(parsed.error ?? "Ticket JSON did not parse.");
      return;
    }
    const command = ticketEditorId ? "ticket.update" : "ticket.add";
    setTicketBusy(command);
    setTicketError(null);
    try {
      const payload = await runBackendCommand<TicketSnapshot>({
        command,
        target,
        ticketId: ticketEditorId ?? undefined,
        ticketJson: JSON.stringify(parsed.ticket),
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Ticket write failed.");
        return;
      }
      setTicketSnapshot(payload.data);
      setTicketMessage(ticketEditorId ? "Ticket updated." : "Ticket added.");
      setTicketEditorId(parsed.ticket.id);
      await Promise.resolve(props.onRefresh());
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTicketBusy(null);
    }
  }

  async function deleteTicket(ticketId: string) {
    if (!target) return;
    setTicketBusy(`delete-${ticketId}`);
    setTicketError(null);
    try {
      const payload = await runBackendCommand<TicketSnapshot>({
        command: "ticket.delete",
        target,
        ticketId,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Ticket delete failed.");
        return;
      }
      setTicketSnapshot(payload.data);
      if (ticketEditorId === ticketId) {
        setTicketEditorId(null);
        setTicketEditorJson("");
      }
      setTicketMessage("Ticket deleted.");
      await Promise.resolve(props.onRefresh());
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTicketBusy(null);
    }
  }

  async function pickTicketImportFile() {
    try {
      const file = await selectTicketImportFile();
      if (file) setTicketImportFile(file);
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    }
  }

  async function importTickets(preview: boolean) {
    if (!target) return;
    setTicketBusy(preview ? "ticket.import.preview" : "ticket.import");
    setTicketError(null);
    try {
      const source =
        ticketImportFile.trim()
          ? { inputFile: ticketImportFile.trim() }
          : ticketImportFormat === "json"
            ? { inputJson: ticketImportText }
            : { inputText: ticketImportText };
      const payload = await runBackendCommand<TicketSnapshot>({
        command: "ticket.import",
        target,
        importFormat: ticketImportFormat,
        importMode: ticketImportMode,
        preview,
        ...source,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Ticket import failed.");
        return;
      }
      if (preview) {
        setTicketImportPreview(payload.data);
        setTicketMessage("Import preview ready.");
      } else {
        setTicketSnapshot(payload.data);
        setTicketImportPreview(null);
        setTicketMessage("Ticket import applied.");
        await Promise.resolve(props.onRefresh());
      }
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTicketBusy(null);
    }
  }

  async function draftTickets() {
    if (!target) return;
    setTicketBusy("ticket.draft_from_intake");
    setTicketError(null);
    try {
      const payload = await runBackendCommand<{ draft_id?: string; candidates?: Ticket[] }>({
        command: "ticket.draft_from_intake",
        target,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Ticket draft failed.");
        return;
      }
      setTicketDraft({
        draft_id: payload.data.draft_id,
        candidates: normalizeTickets(payload.data.candidates ?? []),
      });
      setTicketMessage("Draft candidates are ready to review.");
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTicketBusy(null);
    }
  }

  async function acceptTicketDraft() {
    if (!target || !ticketDraft?.draft_id) return;
    setTicketBusy("ticket.accept_draft");
    setTicketError(null);
    try {
      const payload = await runBackendCommand<TicketSnapshot>({
        command: "ticket.accept_draft",
        target,
        draftId: ticketDraft.draft_id,
        importMode: ticketImportMode,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Could not accept the draft tickets.");
        return;
      }
      setTicketSnapshot(payload.data);
      setTicketDraft(null);
      setTicketMessage("Draft tickets accepted.");
      await Promise.resolve(props.onRefresh());
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    } finally {
      setTicketBusy(null);
    }
  }

  async function openLogFile() {
    if (!target) return;
    setCommandError(null);
    try {
      const payload = await runBackendCommand<{ run_log?: Record<string, unknown> }>({
        command: "run.load_log",
        target,
      });
      if (!payload.ok) {
        setCommandError(payload.message ?? "Could not load the latest run log.");
        return;
      }
      setLogOverride(payload.data?.run_log ?? null);
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : String(error));
    }
  }

  async function copyLog() {
    const content =
      terminalLines.map((line) => `${formatTime(line.timestamp)} ${line.text}`).join("\n") ||
      displayedLog.content;
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      setCommandError("Could not copy the run log from this environment.");
    }
  }

  if (!model.isScaffolded) {
    return (
      <section className="run-page">
        <div className={`run-banner ${model.banner.tone}`}>
          <div>
            <h1>{model.banner.headline}</h1>
            <p>{model.banner.subheadline}</p>
          </div>
          <ActionButton action={model.banner.primaryAction} onRun={runAction} primary icon={<Play size={16} />} />
        </div>
      </section>
    );
  }

  const writeDisabled =
    !model.worker.actions.write.enabled || isBusy || !writeOwnership.trim();

  return (
    <section className="run-page">
      <div className={`run-banner ${model.banner.tone}`}>
        <div>
          <h1>{model.banner.headline}</h1>
          <p>{model.banner.subheadline}</p>
        </div>
        <ActionButton
          action={model.banner.primaryAction}
          onRun={runAction}
          primary
          disabled={isBusy || !model.banner.primaryAction.enabled}
          icon={<Play size={16} />}
        />
      </div>

      {commandError && (
        <div className="brief-error">
          <AlertTriangle size={16} />
          {commandError}
        </div>
      )}

      {commandMessage && (
        <div className="success-callout quiet">
          <CheckCircle2 size={16} />
          <div>
            <strong>{commandMessage}</strong>
          </div>
        </div>
      )}

      <div className="run-layout">
        <article className="panel run-readiness">
          <h2>Readiness</h2>
          <DetailRow label="Current status" value={model.latestRun.status} />
          <DetailRow label="Plan" value={model.latestRun.horizon} />
          <DetailRow label="Last updated" value={model.latestRun.lastUpdated} />
          <p className="empty-copy">{model.latestRun.summary}</p>
        </article>

        <article className="panel run-controls-panel">
          <h2>Controls</h2>
          <div className="run-control-grid">
            <ActionButton
              action={model.controls.startAutomation}
              onRun={runAction}
              disabled={isBusy || !model.controls.startAutomation.enabled}
              icon={<RefreshCw size={16} />}
            />
            <ActionButton
              action={model.controls.stopAutomation}
              onRun={runAction}
              disabled={isBusy || !model.controls.stopAutomation.enabled}
              icon={<Pause size={16} />}
            />
            <ActionButton
              action={model.controls.safetyCheck}
              onRun={runAction}
              disabled={isBusy || !model.controls.safetyCheck.enabled}
              icon={<ShieldCheck size={16} />}
            />
          </div>
          <button className="link-action" onClick={() => props.onNavigate("Review")}>
            <FileDown size={14} />
            Review export
          </button>
        </article>

        {ticketCampaign && (
          <article className="panel span-2 ticket-queue-panel">
            <div className="panel-heading-row">
              <div>
                <h2>Ticket Queue</h2>
                <p>{ticketSnapshot?.ticket_file ?? "Ticket file not loaded yet."}</p>
              </div>
              <div className="inline-actions">
                <button className="icon-text-button" onClick={loadTickets} disabled={ticketBusy !== null}>
                  <RefreshCw size={14} />
                  Refresh
                </button>
                <button className="icon-text-button" onClick={draftTickets} disabled={ticketBusy !== null}>
                  <WandSparkles size={14} />
                  Draft
                </button>
                <button className="icon-text-button" onClick={newTicket} disabled={ticketBusy !== null}>
                  <FilePlus2 size={14} />
                  Add
                </button>
              </div>
            </div>

            {ticketError && (
              <div className="brief-error">
                <AlertTriangle size={16} />
                {ticketError}
              </div>
            )}
            {ticketMessage && (
              <div className="success-callout quiet">
                <CheckCircle2 size={16} />
                <strong>{ticketMessage}</strong>
              </div>
            )}

            <div className="ticket-summary-row">
              <DetailRow label="Pending" value={ticketCounts.pending ?? 0} />
              <DetailRow label="In progress" value={ticketCounts.in_progress ?? 0} />
              <DetailRow label="Done" value={ticketCounts.done ?? 0} />
              <DetailRow label="Blocked" value={ticketCounts.blocked ?? 0} />
            </div>

            <div className="ticket-next-row">
              <strong>Next</strong>
              <span>
                {ticketSnapshot?.next?.ticket?.id
                  ? `${ticketSnapshot.next.ticket.id}: ${ticketSnapshot.next.ticket.summary ?? ""}`
                  : ticketSnapshot?.next?.reason ?? "No ticket selected yet."}
              </span>
            </div>

            {ticketIssues.length > 0 && (
              <div className="ticket-issue-list">
                {ticketIssues.map((issue, index) => (
                  <div className={`ticket-issue ${issue.level}`} key={`${issue.type}-${issue.ticket_id ?? index}`}>
                    <AlertTriangle size={14} />
                    <span>{issueLabel(issue)}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="ticket-list">
              {ticketTickets.length ? (
                ticketTickets.map((ticket) => (
                  <div className="ticket-row" key={ticket.id}>
                    <div>
                      <strong>{ticket.id || "Untitled"}</strong>
                      <span>{ticket.summary || "No summary recorded."}</span>
                    </div>
                    <em>{ticket.status}</em>
                    <button className="icon-text-button" onClick={() => editTicket(ticket)}>Inspect</button>
                    <button className="icon-button danger" title="Delete ticket" onClick={() => deleteTicket(ticket.id)} disabled={ticketBusy !== null}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))
              ) : (
                <p className="empty-copy">No tickets loaded yet.</p>
              )}
            </div>

            <div className="ticket-edit-grid">
              <label className="brief-field">
                <span>{ticketEditorId ? `Editing ${ticketEditorId}` : "Ticket JSON"}</span>
                <textarea
                  rows={11}
                  value={ticketEditorJson}
                  onChange={(event) => setTicketEditorJson(event.target.value)}
                  placeholder={ticketToJson(emptyTicket(ticketTickets))}
                />
              </label>
              <div className="ticket-import-box">
                <div className="brief-form-grid two">
                  <label className="brief-field">
                    <span>Import format</span>
                    <select value={ticketImportFormat} onChange={(event) => setTicketImportFormat(event.target.value as "markdown" | "csv" | "json")}>
                      <option value="markdown">Markdown</option>
                      <option value="csv">CSV</option>
                      <option value="json">JSON</option>
                    </select>
                  </label>
                  <label className="brief-field">
                    <span>Import mode</span>
                    <select value={ticketImportMode} onChange={(event) => setTicketImportMode(event.target.value as "append" | "replace-placeholder" | "replace-all")}>
                      <option value="replace-placeholder">Replace placeholder</option>
                      <option value="append">Append</option>
                      <option value="replace-all">Replace all</option>
                    </select>
                  </label>
                </div>
                <label className="brief-field">
                  <span>Import text</span>
                  <textarea
                    rows={7}
                    value={ticketImportText}
                    onChange={(event) => {
                      setTicketImportText(event.target.value);
                      if (event.target.value.trim()) setTicketImportFile("");
                    }}
                    placeholder="TICKET-002: Add a focused local workflow"
                  />
                </label>
                {ticketImportFile && <p className="log-path">{ticketImportFile}</p>}
                <div className="inline-actions">
                  <button className="secondary-action" onClick={saveTicket} disabled={ticketBusy !== null || !ticketEditorJson.trim()}>
                    Save Ticket
                  </button>
                  <button className="secondary-action" onClick={pickTicketImportFile} disabled={ticketBusy !== null}>
                    Pick File
                  </button>
                  <button className="secondary-action" onClick={() => importTickets(true)} disabled={ticketBusy !== null || (!ticketImportText.trim() && !ticketImportFile)}>
                    Preview Import
                  </button>
                  <button className="secondary-action" onClick={() => importTickets(false)} disabled={ticketBusy !== null || (!ticketImportText.trim() && !ticketImportFile)}>
                    Apply Import
                  </button>
                </div>
              </div>
            </div>

            {ticketImportPreview && (
              <details className="ticket-draft-details" open>
                <summary>Import preview</summary>
                <pre className="raw-json">{JSON.stringify(ticketImportPreview.tickets ?? [], null, 2)}</pre>
              </details>
            )}

            {ticketDraft && (
              <details className="ticket-draft-details" open>
                <summary>Codex draft candidates</summary>
                <pre className="raw-json">{JSON.stringify(ticketDraft.candidates, null, 2)}</pre>
                <button className="secondary-action" onClick={acceptTicketDraft} disabled={ticketBusy !== null || !ticketDraft.draft_id}>
                  Accept Draft
                </button>
              </details>
            )}
          </article>
        )}

        <article className="panel">
          <h2>Automation</h2>
          <DetailRow label="State" value={model.automation.state} />
          <DetailRow label="PID" value={model.automation.pid || "Not running"} />
          <DetailRow label="Started" value={model.automation.startedAt || "Not running"} />
          <p className="empty-copy">{model.automation.message}</p>
        </article>

        <article className="panel span-2">
          <div className="panel-heading-row">
            <h2>Log</h2>
            <div className="inline-actions">
              <button className="icon-text-button" disabled={terminalLines.length === 0 && !displayedLog.content} onClick={copyLog}>
                <Clipboard size={14} />
                Copy
              </button>
              <button className="icon-text-button" disabled={!displayedLog.exists} onClick={openLogFile}>
                <ExternalLink size={14} />
                Open Log File
              </button>
            </div>
          </div>
          <div className="terminal-log">
            {terminalLines.length > 0 ? (
              terminalLines.map((line, index) => (
                <div className={`terminal-line ${line.level}`} key={`${line.timestamp}-${index}`}>
                  <span>{formatTime(line.timestamp)}</span>
                  <code>{line.text}</code>
                </div>
              ))
            ) : (
              <div className="terminal-empty">
                <Terminal size={16} />
                No log recorded yet.
              </div>
            )}
          </div>
          {displayedLog.path && <p className="log-path">{displayedLog.path}</p>}
        </article>

        <article className="panel worker-card">
          <h2>Workers</h2>
          <div className="worker-headline">
            <Users size={18} />
            <strong>{model.worker.headline}</strong>
          </div>
          <p className="empty-copy">{model.worker.summary}</p>
          <DetailRow label="Latest result" value={model.worker.latest} />
          <details>
            <summary>Raw details</summary>
            <pre className="raw-json">{JSON.stringify(model.worker.raw, null, 2)}</pre>
          </details>
          <div className="worker-actions">
            <ActionButton
              action={model.worker.actions.readOnly}
              onRun={runAction}
              disabled={isBusy || !model.worker.actions.readOnly.enabled}
            />
            <div className="write-worker-row">
              <input
                value={writeOwnership}
                onChange={(event) => setWriteOwnership(event.target.value)}
                placeholder="Ownership scope, e.g. docs/** only"
                disabled={!model.worker.actions.write.enabled || isBusy}
              />
              <ActionButton
                action={model.worker.actions.write}
                onRun={runAction}
                disabled={writeDisabled}
              />
            </div>
            <ActionButton
              action={model.worker.actions.integrator}
              onRun={runAction}
              disabled={isBusy || !model.worker.actions.integrator.enabled}
            />
          </div>
        </article>

        <article className="panel blockers-card">
          <h2>Blockers</h2>
          {model.blockers.length > 0 ? (
            <div className="blocker-list">
              {model.blockers.map((blocker) => (
                <div className="blocker-row" key={blocker.name}>
                  <strong>{blocker.name}</strong>
                  <span>{value(blocker.detail, "No detail recorded.")}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-copy">No blockers recorded.</p>
          )}
        </article>
      </div>
    </section>
  );
}
