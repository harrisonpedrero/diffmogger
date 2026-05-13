import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileDown,
  FilePlus2,
  Pause,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Trash2,
  Users,
  WandSparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot } from "./api/backend";
import {
  listenBackendLogs,
  runBackendCommand,
  runBackendCommandStreamed,
  selectTicketImportFile,
} from "./api/backend";
import { buildRunModel, type RunAction, type RunRoute, type RunSafetyRow } from "./runModel";
import { TicketFields } from "./TicketFields";
import {
  defaultImportMode,
  emptyTicket,
  issueLabel,
  normalizeTickets,
  parseTicketJson,
  ticketImportExample,
  ticketToJson,
  type Ticket,
  type TicketImportFormat,
  type TicketSnapshot,
} from "./ticketModel";

type RunLogEvent = BackendLogEvent & { capturedAt: string };
type TicketDraftState = {
  draft_id?: string;
  generation_mode?: string;
  message?: string;
  candidate_count?: number;
  dropped_existing_count?: number;
  renumbered_count?: number;
  dropped_dependency_count?: number;
  candidates: Ticket[];
};

function routeFromRun(route: RunRoute): "Brief" | "Run" | "Review" | "Advanced" | "Inbox" {
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

export function ticketSnapshotReloadKey(snapshot: ProjectSnapshot | null): string {
  const run = asRecord(snapshot?.run);
  const state = asRecord(run.state);
  const ticketRun = asRecord(state.ticket_run);
  const counts = asRecord(ticketRun.counts);
  const countKey = ["pending", "in_progress", "candidate_done", "done", "blocked"]
    .map((status) => `${status}:${counts[status] ?? 0}`)
    .join(",");
  return [
    textValue(run.snapshot_generated_at),
    textValue(ticketRun.run_id),
    textValue(ticketRun.status),
    String(ticketRun.total ?? ""),
    countKey,
  ].join("|");
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

function QueueActionButton(props: {
  children: ReactNode;
  tooltip: string;
  onClick: () => void;
  disabled?: boolean;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <button
      className={`${props.className ?? "icon-text-button"} queue-action-button`}
      data-tooltip={props.tooltip}
      title={props.tooltip}
      aria-label={props.ariaLabel}
      onClick={props.onClick}
      disabled={props.disabled}
    >
      {props.children}
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

function RunTonePill(props: { tone: string; children: ReactNode }) {
  return <span className={`run-tone-pill ${props.tone}`}>{props.children}</span>;
}

function RunStatusHero(props: {
  model: ReturnType<typeof buildRunModel>;
}) {
  const showHeadline =
    props.model.banner.headline.toLowerCase() !== props.model.banner.badge.toLowerCase();
  return (
    <header className={`run-status-hero ${props.model.banner.tone}`} aria-label="Run Control status" data-testid="run-status-hero">
      <div className={`run-status-main ${showHeadline ? "" : "badge-only"}`}>
        <RunTonePill tone={props.model.banner.tone}>{props.model.banner.badge}</RunTonePill>
        {showHeadline && <h1>{props.model.banner.headline}</h1>}
        <p>{props.model.banner.subheadline}</p>
      </div>
      <div className="run-status-facts" aria-label="Run state facts">
        <DetailRow label="Status" value={props.model.latestRun.status} />
        <DetailRow label="Process" value={props.model.automation.state} />
        <DetailRow label="PID" value={props.model.automation.pid || "Not running"} />
      </div>
    </header>
  );
}

function RunSafetyMatrix(props: { rows: RunSafetyRow[]; busy: boolean; onRun: (action: RunAction) => void }) {
  return (
    <article className="panel run-safety-panel" aria-label="Run safety">
      <div className="panel-heading-row">
        <h2>Safety</h2>
      </div>
      <div className="run-safety-list">
        {props.rows.map((row) => (
          <div className={`run-safety-row ${row.tone}`} key={row.label}>
            <div>
              <strong>{row.label}</strong>
              <span>{row.source}</span>
            </div>
            <RunTonePill tone={row.tone}>{row.status}</RunTonePill>
            <p>{row.summary}</p>
            <button
              className="ledger-action"
              disabled={props.busy || !row.action.enabled}
              onClick={() => props.onRun(row.action)}
            >
              {row.action.label}
            </button>
          </div>
        ))}
      </div>
    </article>
  );
}

function RunStateMachinePanel(props: {
  model: ReturnType<typeof buildRunModel>;
}) {
  return (
    <article className="panel run-state-machine-panel" aria-label="Typed conveyor state machine">
      <div className="panel-heading-row">
        <div>
          <h2>State Machine</h2>
          <p>{props.model.stateMachine.continuationToken || "No continuation token recorded yet."}</p>
        </div>
        <RunTonePill tone={props.model.banner.tone}>{props.model.stateMachine.stageStatus}</RunTonePill>
      </div>
      <div className="state-machine-grid">
        <DetailRow label="Stage" value={props.model.stateMachine.stage} />
        <DetailRow label="Owner" value={props.model.stateMachine.ownerRole} />
        <DetailRow label="Validation" value={props.model.stateMachine.validationStatus} />
        <DetailRow label="Capabilities" value={props.model.stateMachine.capability} />
      </div>
      <div className="state-machine-next">
        {props.model.stateMachine.nextActions.length ? (
          props.model.stateMachine.nextActions.map((item, index) => (
            <div className="state-machine-action" key={`${item.role}-${index}`}>
              <strong>{item.role}</strong>
              <span>{item.state}</span>
              <p>{item.reason}</p>
            </div>
          ))
        ) : (
          <p className="empty-copy">No typed next action is queued yet.</p>
        )}
      </div>
    </article>
  );
}

export function RunPage(props: {
  snapshot: ProjectSnapshot | null;
  loading: boolean;
  onChoose: () => void;
  onNavigate: (route: "Brief" | "Run" | "Review" | "Advanced" | "Inbox") => void;
  onRefresh: () => void;
  onDirtyChange?: (message: string | null) => void;
  onBusyChange?: (busy: boolean) => void;
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
  const [ticketImportFormat, setTicketImportFormat] = useState<TicketImportFormat>("markdown");
  const [ticketImportMode, setTicketImportMode] = useState<"append" | "replace-placeholder" | "replace-all">("append");
  const [ticketImportText, setTicketImportText] = useState("");
  const [ticketImportFile, setTicketImportFile] = useState("");
  const [ticketImportPreview, setTicketImportPreview] = useState<TicketSnapshot | null>(null);
  const [ticketDraftDirection, setTicketDraftDirection] = useState("");
  const [ticketDraft, setTicketDraft] = useState<TicketDraftState | null>(null);
  const [ticketDraftLogs, setTicketDraftLogs] = useState<RunLogEvent[]>([]);
  const [ticketPendingAction, setTicketPendingAction] = useState<
    | { kind: "delete"; ticketId: string }
    | { kind: "import"; mode: "append" | "replace-placeholder" | "replace-all" }
    | null
  >(null);
  const ticketDraftSectionRef = useRef<HTMLElement | null>(null);
  const isBusy = props.loading || busyCommand !== null;

  const target = props.snapshot?.target.path;
  const ticketCampaign = isTicketCampaign(props.snapshot);
  const ticketReloadKey = ticketSnapshotReloadKey(props.snapshot);
  const ticketTickets = normalizeTickets(ticketSnapshot?.tickets ?? []);
  const ticketIssues = ticketSnapshot?.validation_issues ?? [];
  const ticketCounts = ticketSnapshot?.summary?.counts ?? {};
  const ticketDraftBusy = ticketBusy === "ticket.draft_from_intake";
  const ticketWriteBusy = ticketBusy !== null;
  const ticketDraftCandidates = ticketDraft?.candidates ?? [];
  const selectedTicketJson = useMemo(() => {
    if (!ticketEditorId) return "";
    const ticket = ticketTickets.find((item) => item.id === ticketEditorId);
    return ticket ? ticketToJson(ticket) : "";
  }, [ticketEditorId, ticketTickets]);
  const ticketEditorTicket = useMemo(() => {
    const parsed = parseTicketJson(ticketEditorJson);
    return parsed.ticket ?? emptyTicket(ticketTickets);
  }, [ticketEditorJson, ticketTickets]);
  const ticketEditorDirty = Boolean(ticketEditorJson.trim() && ticketEditorJson !== selectedTicketJson);
  const ticketImportDirty = Boolean(
    ticketImportText.trim() ||
      ticketImportFile ||
      ticketImportPreview ||
      ticketDraftDirection.trim() ||
      ticketDraft,
  );
  const routeDirtyMessage = ticketEditorDirty
    ? "Run Control has unsaved ticket editor changes."
    : ticketImportDirty
      ? "Run Control has pending ticket import or draft state."
      : null;

  useEffect(() => {
    if (!target || !model.isScaffolded || !ticketCampaign) {
      setTicketSnapshot(null);
      return;
    }
    void loadTickets();
  }, [target, model.isScaffolded, ticketCampaign, ticketReloadKey]);

  useEffect(() => {
    props.onDirtyChange?.(routeDirtyMessage);
    return () => props.onDirtyChange?.(null);
  }, [props.onDirtyChange, routeDirtyMessage]);

  useEffect(() => {
    props.onBusyChange?.(busyCommand !== null);
    return () => props.onBusyChange?.(false);
  }, [busyCommand]);

  useEffect(() => {
    if (!routeDirtyMessage) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = routeDirtyMessage;
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [routeDirtyMessage]);

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

  function focusTicketDraftSection() {
    window.requestAnimationFrame(() => {
      const element = ticketDraftSectionRef.current;
      if (!element) return;
      element.scrollIntoView({ behavior: "smooth", block: "nearest" });
      element.focus({ preventScroll: true });
    });
  }

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
    setCommandMessage(`${action.label} requested.`);
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
      } else {
        setCommandMessage(`${action.label} completed.`);
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
    setTicketPendingAction(null);
  }

  function updateTicketEditor(ticket: Ticket) {
    setTicketEditorJson(ticketToJson(ticket));
  }

  async function saveTicket() {
    if (!target) return;
    const parsed = parseTicketJson(ticketEditorJson);
    if (!parsed.ticket) {
      setTicketError(parsed.error ?? "Ticket fields did not parse.");
      return;
    }
    const command = ticketEditorId ? "ticket.update" : "ticket.add";
    setTicketBusy(command);
    setTicketError(null);
    setTicketPendingAction(null);
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
    if (ticketPendingAction?.kind !== "delete" || ticketPendingAction.ticketId !== ticketId) {
      setTicketPendingAction({ kind: "delete", ticketId });
      setTicketError(null);
      setTicketMessage(`Click delete again to remove ${ticketId}.`);
      return;
    }
    setTicketBusy(`delete-${ticketId}`);
    setTicketError(null);
    setTicketPendingAction(null);
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
      if (file) {
        setTicketImportFile(file);
        setTicketPendingAction(null);
      }
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    }
  }

  async function importTickets(preview: boolean) {
    if (!target) return;
    if (
      !preview &&
      (ticketPendingAction?.kind !== "import" || ticketPendingAction.mode !== ticketImportMode)
    ) {
      setTicketPendingAction({ kind: "import", mode: ticketImportMode });
      setTicketError(null);
      setTicketMessage(
        ticketImportMode === "replace-all"
          ? "Click Apply Import again to replace the full ticket queue."
          : "Click Apply Import again to write these tickets.",
      );
      return;
    }
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
        setTicketImportText("");
        setTicketImportFile("");
        setTicketPendingAction(null);
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
    const direction = ticketDraftDirection.trim();
    setTicketBusy("ticket.draft_from_intake");
    setTicketError(null);
    setTicketDraft(null);
    setTicketDraftLogs([]);
    setTicketMessage("Drafting new ticket candidates.");
    setTicketPendingAction(null);
    focusTicketDraftSection();
    const runId = `ticket-draft-${Date.now()}`;
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setTicketDraftLogs((current) => [...current, { ...event, capturedAt: new Date().toISOString() }].slice(-20));
      });
      const payload = await runBackendCommandStreamed<TicketDraftState>({
        runId,
        command: "ticket.draft_from_intake",
        target,
        body: direction || undefined,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Ticket draft failed.");
        return;
      }
      const candidates = normalizeTickets(payload.data.candidates ?? []);
      setTicketDraft({
        ...payload.data,
        draft_id: payload.data.draft_id,
        candidates,
      });
      setTicketMessage(
        payload.data.message ??
          (candidates.length
            ? `${candidates.length} draft ticket candidate${candidates.length === 1 ? "" : "s"} ready to add.`
            : "No new draft tickets were found."),
      );
      focusTicketDraftSection();
    } catch (error) {
      setTicketError(error instanceof Error ? error.message : String(error));
    } finally {
      unlisten?.();
      setTicketBusy(null);
    }
  }

  async function acceptTicketDraft() {
    if (!target || !ticketDraft?.draft_id || ticketDraftCandidates.length === 0) return;
    setTicketBusy("ticket.accept_draft");
    setTicketError(null);
    try {
      const payload = await runBackendCommand<TicketSnapshot>({
        command: "ticket.accept_draft",
        target,
        draftId: ticketDraft.draft_id,
        importMode: "append",
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Could not accept the draft tickets.");
        return;
      }
      setTicketSnapshot(payload.data);
      setTicketDraft(null);
      setTicketDraftLogs([]);
      setTicketDraftDirection("");
      setTicketMessage("Draft tickets added to the queue.");
      setTicketPendingAction(null);
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

  const writeDisabled =
    !model.worker.actions.write.enabled || isBusy || !writeOwnership.trim();
  const helperControlsAvailable =
    model.worker.actions.readOnly.enabled ||
    model.worker.actions.write.enabled ||
    model.worker.actions.integrator.enabled;

  return (
    <section className="run-page run-control-page" aria-label="Run Control">
      <RunStatusHero model={model} />

      {commandError && (
        <div className="brief-error" role="alert">
          <AlertTriangle size={16} />
          {commandError}
        </div>
      )}

      {commandMessage && (
        <div className="success-callout quiet" role="status" aria-live="polite">
          <CheckCircle2 size={16} />
          <div>
            <strong>{commandMessage}</strong>
          </div>
        </div>
      )}

      <div className="run-control-layout">
        <article className="panel run-readiness">
          <h2>Readiness Facts</h2>
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
            <ActionButton
              action={model.controls.exportReview}
              onRun={runAction}
              disabled={isBusy || !model.controls.exportReview.enabled}
              icon={<FileDown size={16} />}
            />
          </div>
        </article>

        <article className="panel run-process-panel">
          <h2>Process</h2>
          <DetailRow label="State" value={model.automation.state} />
          <DetailRow label="PID" value={model.automation.pid || "Not running"} />
          <DetailRow label="Started" value={model.automation.startedAt || "Not running"} />
          <DetailRow label="Log directory" value={model.automation.logDir || "Not recorded"} />
          <p className="empty-copy">{model.automation.message}</p>
        </article>

        <RunSafetyMatrix rows={model.safety} busy={isBusy} onRun={runAction} />

        <RunStateMachinePanel model={model} />

        {ticketCampaign && (
          <article className="panel ticket-queue-panel run-ticket-panel">
            <div className="panel-heading-row">
              <div>
                <h2>Ticket Queue</h2>
                <p>{ticketSnapshot?.ticket_file ?? "Ticket file not loaded yet."}</p>
              </div>
              <div className="inline-actions">
                <QueueActionButton
                  tooltip="Reload the ticket queue from the local ticket-run file."
                  onClick={loadTickets}
                  disabled={ticketBusy !== null}
                >
                  <RefreshCw size={14} />
                  Refresh
                </QueueActionButton>
              </div>
            </div>

            {ticketError && (
              <div className="brief-error" role="alert">
                <AlertTriangle size={16} />
                {ticketError}
              </div>
            )}
            {ticketMessage && (
              <div className="success-callout quiet" role="status" aria-live="polite">
                <CheckCircle2 size={16} />
                <strong>{ticketMessage}</strong>
              </div>
            )}

            <section className="ticket-workflow-section ticket-draft-section" ref={ticketDraftSectionRef} tabIndex={-1}>
              <div className="ticket-section-heading">
                <div>
                  <h3>Draft candidates</h3>
                  <span>{ticketDraftBusy ? "Drafting" : ticketDraft ? `${ticketDraftCandidates.length} ready` : "None"}</span>
                </div>
              </div>

              <div className="ticket-draft-controls">
                <label className="brief-field ticket-draft-direction">
                  <span>Agent direction (optional)</span>
                  <textarea
                    rows={3}
                    maxLength={4000}
                    value={ticketDraftDirection}
                    onChange={(event) => setTicketDraftDirection(event.target.value)}
                    placeholder="Focus the draft on a feature area, workflow, or constraint."
                    disabled={ticketWriteBusy}
                  />
                </label>
                <div className="inline-actions">
                  <QueueActionButton
                    tooltip="Run Codex to propose only new pending tickets. Nothing is written until you add the draft tickets."
                    onClick={draftTickets}
                    disabled={ticketWriteBusy}
                  >
                    {ticketDraftBusy ? <RefreshCw className="spin" size={14} /> : <WandSparkles size={14} />}
                    {ticketDraftBusy ? "Drafting" : "Draft New Tickets"}
                  </QueueActionButton>
                  <QueueActionButton
                    className="secondary-action"
                    tooltip="Append the visible draft candidates to the ticket queue."
                    onClick={acceptTicketDraft}
                    disabled={ticketWriteBusy || !ticketDraft?.draft_id || ticketDraftCandidates.length === 0}
                  >
                    <FilePlus2 size={14} />
                    Add Draft Tickets
                  </QueueActionButton>
                </div>
              </div>

              {ticketDraftBusy && (
                <div className="ticket-draft-progress" role="status" aria-live="polite">
                  <div>
                    <RefreshCw className="spin" size={15} />
                    <strong>Drafting with Codex</strong>
                  </div>
                  <div className="ticket-draft-log">
                    {ticketDraftLogs.length ? (
                      ticketDraftLogs.map((line, index) => (
                        <code key={`${line.capturedAt}-${index}`}>[{line.stage}] {line.message}</code>
                      ))
                    ) : (
                      <code>Starting ticket draft...</code>
                    )}
                  </div>
                </div>
              )}

              {!ticketDraftBusy && ticketDraft && (
                <>
                  {ticketDraftCandidates.length ? (
                    <div className="ticket-candidate-list">
                      {ticketDraftCandidates.map((ticket) => (
                        <div className="ticket-candidate-row" key={ticket.id}>
                          <div>
                            <strong>{ticket.id || "Untitled"}</strong>
                            <span>{ticket.summary || "No summary recorded."}</span>
                          </div>
                          <em>{ticket.depends_on.length ? `depends on ${ticket.depends_on.join(", ")}` : "no dependencies"}</em>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="empty-copy">{ticketDraft.message ?? "No new draft tickets were found."}</p>
                  )}
                  <div className="ticket-draft-meta">
                    <span>{ticketDraft.generation_mode ?? "append"}</span>
                    <span>{ticketDraft.dropped_existing_count ?? 0} skipped</span>
                    <span>{ticketDraft.renumbered_count ?? 0} renumbered</span>
                    <span>{ticketDraft.dropped_dependency_count ?? 0} deps dropped</span>
                  </div>
                  <details className="ticket-draft-details">
                    <summary>Raw draft JSON</summary>
                    <pre className="raw-json">{JSON.stringify(ticketDraft, null, 2)}</pre>
                  </details>
                </>
              )}

              {!ticketDraftBusy && !ticketDraft && <p className="empty-copy">No draft candidates ready.</p>}
            </section>

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
                    <div className="ticket-row-main">
                      <strong>{ticket.id || "Untitled"}</strong>
                      <span>{ticket.summary || "No summary recorded."}</span>
                    </div>
                    <em>{ticket.status}</em>
                    <div className="ticket-row-actions" role="group" aria-label={`Actions for ${ticket.id || "Untitled"}`}>
                      <QueueActionButton
                        tooltip="Load this ticket into the editor without writing changes."
                        onClick={() => editTicket(ticket)}
                      >
                        Inspect
                      </QueueActionButton>
                      <QueueActionButton
                        className="icon-button danger"
                        ariaLabel={`Delete ticket ${ticket.id || "Untitled"}`}
                        tooltip="Remove this ticket from the queue after a second confirmation click."
                        onClick={() => deleteTicket(ticket.id)}
                        disabled={ticketWriteBusy}
                      >
                        <Trash2 size={14} />
                      </QueueActionButton>
                    </div>
                  </div>
                ))
              ) : (
                <p className="empty-copy">No tickets loaded yet.</p>
              )}
            </div>

            <section className="ticket-workflow-section ticket-manual-section">
              <div className="ticket-section-heading">
                <div>
                  <h3>Manual ticket</h3>
                  <span>{ticketEditorId ? `Editing ${ticketEditorId}` : ticketEditorJson.trim() ? "Unsaved" : "Ready"}</span>
                </div>
                <QueueActionButton
                  tooltip="Create a blank pending ticket in the editor. Nothing is written until Save Ticket."
                  onClick={newTicket}
                  disabled={ticketWriteBusy}
                >
                  <FilePlus2 size={14} />
                  New Ticket
                </QueueActionButton>
              </div>
              <div className="ticket-editor-panel">
                <TicketFields
                  ticket={ticketEditorTicket}
                  onChange={updateTicketEditor}
                  title={ticketEditorId ? `Editing ${ticketEditorId}` : "Ticket fields"}
                />
                <div className="inline-actions">
                  <QueueActionButton
                    className="secondary-action"
                    tooltip="Write the ticket currently shown in the editor to the queue."
                    onClick={saveTicket}
                    disabled={ticketWriteBusy || !ticketEditorJson.trim()}
                  >
                    Save Ticket
                  </QueueActionButton>
                </div>
              </div>
            </section>

            <section className="ticket-workflow-section ticket-import-section">
              <div className="ticket-section-heading">
                <div>
                  <h3>Bulk import</h3>
                  <span>{ticketImportMode}</span>
                </div>
              </div>
              <div className="ticket-import-box">
                <div className="brief-form-grid two">
                  <label className="brief-field">
                    <span>Import format</span>
                    <select
                      value={ticketImportFormat}
                      onChange={(event) => {
                        setTicketImportFormat(event.target.value as TicketImportFormat);
                        setTicketPendingAction(null);
                      }}
                    >
                      <option value="markdown">Markdown</option>
                      <option value="csv">CSV</option>
                      <option value="json">JSON</option>
                    </select>
                  </label>
                  <label className="brief-field">
                    <span>Import mode</span>
                    <select
                      value={ticketImportMode}
                      onChange={(event) => {
                        setTicketImportMode(event.target.value as "append" | "replace-placeholder" | "replace-all");
                        setTicketPendingAction(null);
                      }}
                    >
                      <option value="replace-placeholder">Replace placeholder</option>
                      <option value="append">Append</option>
                      <option value="replace-all">Replace all</option>
                    </select>
                  </label>
                </div>
                <label className="brief-field">
                  <span>Import text</span>
                  <textarea
                    className="ticket-import-textarea"
                    rows={7}
                    value={ticketImportText}
                    onChange={(event) => {
                      setTicketImportText(event.target.value);
                      if (event.target.value.trim()) setTicketImportFile("");
                      setTicketPendingAction(null);
                    }}
                    placeholder={ticketImportExample(ticketImportFormat)}
                  />
                </label>
                {ticketImportFile && <p className="log-path">{ticketImportFile}</p>}
                <div className="inline-actions">
                  <QueueActionButton
                    className="secondary-action"
                    tooltip="Choose a Markdown, CSV, JSON, or text file to import."
                    onClick={pickTicketImportFile}
                    disabled={ticketWriteBusy}
                  >
                    Pick File
                  </QueueActionButton>
                  <QueueActionButton
                    className="secondary-action"
                    tooltip="Preview the parsed import without writing to the ticket queue."
                    onClick={() => importTickets(true)}
                    disabled={ticketWriteBusy || (!ticketImportText.trim() && !ticketImportFile)}
                  >
                    Preview Import
                  </QueueActionButton>
                  <QueueActionButton
                    className="secondary-action"
                    tooltip="Apply the import using the selected import mode."
                    onClick={() => importTickets(false)}
                    disabled={ticketWriteBusy || (!ticketImportText.trim() && !ticketImportFile)}
                  >
                    Apply Import
                  </QueueActionButton>
                </div>
              </div>
            </section>

            {ticketImportPreview && (
              <details className="ticket-draft-details" open>
                <summary>Import preview</summary>
                <pre className="raw-json">{JSON.stringify(ticketImportPreview.tickets ?? [], null, 2)}</pre>
              </details>
            )}
          </article>
        )}

        <article className="panel run-log-panel">
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
          <div className="panel-heading-row helper-heading">
            <div>
              <h2>Helper Strategy</h2>
              <p>Automation-first; manual helper runs are advanced.</p>
            </div>
            <RunTonePill tone={model.worker.tone}>{model.worker.mode}</RunTonePill>
          </div>
          <div className="worker-headline">
            <Users size={18} />
            <div>
              <span>{model.worker.focus}</span>
              <strong>{model.worker.headline}</strong>
            </div>
          </div>
          <p className="empty-copy">{model.worker.summary}</p>
          <DetailRow label="Latest result" value={model.worker.latest} />
          <DetailRow label="Helper output" value={model.worker.output} />
          <details className="helper-advanced">
            <summary>Advanced helper controls</summary>
            {helperControlsAvailable ? (
              <div className="worker-actions">
                {model.worker.actions.readOnly.enabled && (
                  <ActionButton
                    action={model.worker.actions.readOnly}
                    onRun={runAction}
                    primary={!model.worker.actions.write.enabled && !model.worker.actions.integrator.enabled}
                    disabled={isBusy}
                  />
                )}
                {model.worker.actions.write.enabled && (
                  <div className="write-worker-row">
                    <input
                      value={writeOwnership}
                      onChange={(event) => setWriteOwnership(event.target.value)}
                      placeholder="Ownership scope, e.g. docs/** only"
                      disabled={isBusy}
                    />
                    <ActionButton
                      action={model.worker.actions.write}
                      onRun={runAction}
                      primary
                      disabled={writeDisabled}
                    />
                  </div>
                )}
                {model.worker.actions.integrator.enabled && (
                  <ActionButton
                    action={model.worker.actions.integrator}
                    onRun={runAction}
                    primary
                    disabled={isBusy}
                  />
                )}
              </div>
            ) : (
              <p className="helper-unavailable">No manual helper launch is available for this strategy.</p>
            )}
            <details className="strategy-json">
              <summary>Strategy JSON</summary>
              <pre className="raw-json">{JSON.stringify(model.worker.raw, null, 2)}</pre>
            </details>
          </details>
        </article>

        <article className="panel blockers-card">
          <h2>Blockers</h2>
          {model.blockers.length > 0 ? (
            <div className="blocker-list">
              {model.blockers.map((blocker) => (
                <div className="blocker-row" key={blocker.name}>
                  <div>
                    <strong>{blocker.name}</strong>
                    <span>{value(blocker.detail, "No detail recorded.")}</span>
                  </div>
                  {blocker.canRecheck && blocker.recheckCommand && (
                    <button
                      className="ledger-action"
                      disabled={isBusy}
                      onClick={() =>
                        runAction({
                          label: blocker.recheckLabel || "Recheck blocker",
                          kind: "backend",
                          command: blocker.recheckCommand,
                          enabled: true,
                          reason: "Rerun baseline verification in a freshly loaded automation environment.",
                        })
                      }
                    >
                      <RefreshCw size={14} />
                      {blocker.recheckLabel || "Recheck blocker"}
                    </button>
                  )}
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
