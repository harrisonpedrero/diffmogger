import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  FolderOpen,
  GitBranch,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Square,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot } from "./api/backend";
import { listenBackendLogs, runBackendCommandStreamed } from "./api/backend";
import {
  buildAutomationViewModel,
  type AutomationPipelineNode,
  type AutomationQueueBucket,
  type AutomationTicketProgressRow,
  type AutomationValidationRow,
  type AutomationActivityRow,
} from "./automationViewModel";
import { buildRunModel, type RunAction, type RunTone } from "./runModel";

type AutomationLogEvent = BackendLogEvent & { capturedAt: string };
type AutomationCommandAction = RunAction & { executionGroupId?: string };

const automationCommandFallbacks = {
  start: "automation.start",
};

function TonePill(props: { tone: RunTone | string; children: React.ReactNode }) {
  return <span className={`run-tone-pill ${props.tone}`}>{props.children}</span>;
}

function CommandButton(props: {
  action: RunAction;
  icon: React.ReactNode;
  primary?: boolean;
  busy: boolean;
  onRun: (action: AutomationCommandAction) => void;
}) {
  return (
    <button
      className={props.primary ? "primary-action" : "secondary-action"}
      disabled={props.busy || !props.action.enabled}
      title={props.action.reason}
      onClick={() => props.onRun(props.action)}
    >
      {props.icon}
      {props.action.label}
    </button>
  );
}

function retryFailedAction(model: ReturnType<typeof buildRunModel>): AutomationCommandAction {
  const retryGroup = model.operations.concurrencyWaves.find((wave) =>
    wave.kind === "blocked" || /fail|error|cancel/i.test(wave.status),
  );
  return {
    label: "Retry",
    kind: retryGroup ? "backend" : "disabled",
    command: "execution_group.retry_failed",
    executionGroupId: retryGroup?.id,
    enabled: Boolean(retryGroup),
    reason: retryGroup
      ? `Retry failed work group ${retryGroup.id}.`
      : "No failed execution group is available to retry.",
  };
}

function PipelineNodeButton(props: {
  node: AutomationPipelineNode;
  selected: boolean;
  onSelect: (nodeId: string) => void;
}) {
  return (
    <button
      type="button"
      className={`pipeline-node ${props.node.status}${props.selected ? " selected" : ""}`}
      aria-pressed={props.selected}
      aria-label={`${props.node.title} for ${props.node.ticketId || "automation work"}`}
      title={props.node.detail}
      onClick={() => props.onSelect(props.node.id)}
    >
      <span>{props.node.title}</span>
      <small>{props.node.statusLabel}</small>
    </button>
  );
}

function SelectedWorkDetail(props: {
  node: AutomationPipelineNode | null;
  nextAction: ReturnType<typeof buildAutomationViewModel>["nextAction"];
  ticket?: AutomationTicketProgressRow;
}) {
  const usefulScope = props.node?.scope && props.node.scope !== "No ownership scope recorded" ? props.node.scope : "";
  return (
    <article className="automation-panel selected-work-panel">
      <div className="panel-heading-row compact">
        <h2>Selected Work</h2>
        <TonePill tone={props.node?.tone || props.nextAction.tone}>{props.node?.statusLabel || props.nextAction.status}</TonePill>
      </div>
      {props.node ? (
        <div className="selected-work-detail">
          <span>{props.node.role}</span>
          <strong>{props.node.title}</strong>
          <p>{props.node.detail}</p>
          {props.ticket && <p className="selected-work-ticket-summary">{props.ticket.summary}</p>}
          <div className="selected-work-meta">
            <div>
              <span>Ticket</span>
              <strong>{props.node.ticketId || "Automation work"}</strong>
            </div>
            <div>
              <span>Stage</span>
              <strong>{props.node.phase}</strong>
            </div>
            {props.ticket && (
              <>
                <div>
                  <span>Ticket status</span>
                  <strong>{props.ticket.statusLabel}</strong>
                </div>
                <div>
                  <span>Evidence</span>
                  <strong>{props.ticket.evidenceCount}</strong>
                </div>
              </>
            )}
          </div>
          {usefulScope && <p className="selected-work-scope">{usefulScope}</p>}
        </div>
      ) : (
        <div className="selected-work-detail">
          <span>{props.nextAction.role}</span>
          <strong>{props.nextAction.title}</strong>
          <p>{props.nextAction.detail}</p>
        </div>
      )}
    </article>
  );
}

function TicketProgressPanel(props: { tickets: ReturnType<typeof buildAutomationViewModel>["ticketProgress"] }) {
  return (
    <article className="automation-panel ticket-progress-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Ticket Progress</h2>
          <p>{props.tickets.summary}</p>
        </div>
      </div>
      <div className="ticket-progress-counts" aria-label="Ticket status counts">
        {props.tickets.counts.map((count) => (
          <div className={`ticket-progress-count ${count.id}`} key={count.id}>
            <span>{count.label}</span>
            <strong>{count.count}</strong>
          </div>
        ))}
      </div>
      <div className="ticket-progress-table" role="table" aria-label="Ticket progress">
        <div className="ticket-progress-header" role="row">
          <span>Ticket</span>
          <span>Status</span>
          <span>Stage</span>
          <span>Evidence</span>
          <span>Summary</span>
        </div>
        <div className="ticket-progress-scroll">
          {props.tickets.rows.length ? props.tickets.rows.map((ticket) => (
            <div className={`ticket-progress-row ${ticket.status}`} role="row" key={ticket.id}>
              <strong>{ticket.id}</strong>
              <TonePill tone={ticket.tone}>{ticket.statusLabel}</TonePill>
              <span>{ticket.stage}</span>
              <span>{ticket.evidenceCount} evidence / {ticket.commitCount} commits</span>
              <p>{ticket.summary}</p>
            </div>
          )) : <div className="empty-copy">No tickets are loaded.</div>}
        </div>
      </div>
    </article>
  );
}

function QueueBucketCard(props: { bucket: AutomationQueueBucket }) {
  return (
    <div className={`queue-bucket ${props.bucket.id}`}>
      <div>
        <span>{props.bucket.label}</span>
        <strong>{props.bucket.count}</strong>
      </div>
      <div className="queue-bucket-items">
        {props.bucket.items.length ? props.bucket.items.map((item) => (
          <p key={item.id}>
            <b>{item.title}</b>
            <span>{item.detail}</span>
          </p>
        )) : <p className="empty-copy">None</p>}
      </div>
    </div>
  );
}

function ValidationRow(props: { row: AutomationValidationRow }) {
  return (
    <div className="automation-row validation-row">
      <strong>{props.row.title}</strong>
      <TonePill tone={props.row.tone}>{props.row.status}</TonePill>
      <span>{props.row.detail}</span>
    </div>
  );
}

function ActivityRow(props: { row: AutomationActivityRow }) {
  return (
    <div className="automation-row activity-row">
      <strong>{props.row.title}</strong>
      <TonePill tone={props.row.tone}>{props.row.status}</TonePill>
      <span>{props.row.detail}</span>
    </div>
  );
}

export function AutomationPage(props: {
  snapshot: ProjectSnapshot | null;
  loading: boolean;
  onChoose: () => void;
  onNavigate: (route: "Setup" | "Automation") => void;
  onRefresh: () => void;
  onBusyChange?: (busy: boolean) => void;
}) {
  const model = useMemo(() => buildRunModel(props.snapshot), [props.snapshot]);
  const view = useMemo(() => buildAutomationViewModel(props.snapshot, model), [props.snapshot, model]);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [busyCommand, setBusyCommand] = useState("");
  const [logs, setLogs] = useState<AutomationLogEvent[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const target = props.snapshot?.target.path ?? "";
  const retryFailed = retryFailedAction(model);
  const commandBusy = props.loading || Boolean(busyCommand);
  const effectiveSelectedNodeId = selectedNodeId || view.dag.defaultSelectedNodeId;
  const selectedNode = view.dag.nodes.find((node) => node.id === effectiveSelectedNodeId) || null;
  const selectedTicket = selectedNode?.ticketId
    ? view.ticketProgress.rows.find((ticket) => ticket.id === selectedNode.ticketId)
    : undefined;

  async function runAction(action: AutomationCommandAction) {
    setError("");
    setMessage("");
    if (action.kind === "choose-project") {
      props.onChoose();
      return;
    }
    if (action.kind === "navigate") {
      props.onNavigate(action.route === "Setup" ? "Setup" : "Automation");
      if (action.route === "Automation") props.onRefresh();
      return;
    }
    if (!action.enabled || !action.command || !target) return;
    const runId = `${action.command}-${Date.now()}`;
    setBusyCommand(action.command);
    props.onBusyChange?.(true);
    setLogs([]);
    setMessage(`${action.label} requested.`);
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setLogs((current) => [...current, { ...event, capturedAt: new Date().toISOString() }].slice(-24));
      });
      const payload: BackendEnvelope<Record<string, unknown>> = await runBackendCommandStreamed({
        runId,
        command: action.command,
        target,
        executionGroupId: action.executionGroupId,
      });
      if (!payload.ok) {
        setError(payload.message ?? `${action.label} failed.`);
      } else {
        setMessage(`${action.label} completed.`);
      }
      props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      unlisten?.();
      setBusyCommand("");
      props.onBusyChange?.(false);
    }
  }

  if (!props.snapshot) {
    return (
      <section className="automation-page no-target" aria-label="Automation">
        <div className="automation-empty">
          <FolderOpen size={22} />
          <h1>Choose Project</h1>
          <p>Select a target folder before inspecting scheduler state or starting automation.</p>
          <button className="primary-action" onClick={props.onChoose}>
            <FolderOpen size={17} />
            Choose project
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="automation-page" aria-label="Automation" data-testid="automation-page">
      <header className="automation-header">
        <div>
          <h1>Automation</h1>
          <p>{model.automation.message}</p>
        </div>
        <div className="automation-command-row" aria-label="Automation commands">
          <CommandButton action={model.controls.startAutomation} busy={commandBusy} icon={<PlayCircle size={16} />} onRun={runAction} primary />
          <CommandButton action={model.controls.stopAutomation} busy={commandBusy} icon={<Square size={15} />} onRun={runAction} />
          <CommandButton action={retryFailed} busy={commandBusy} icon={<RotateCcw size={16} />} onRun={runAction} />
          <CommandButton action={model.controls.safetyCheck} busy={commandBusy} icon={<ShieldCheck size={16} />} onRun={runAction} />
          <button className="secondary-action" disabled={props.loading} onClick={props.onRefresh}>
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </header>

      {(message || error) && (
        <div className={`automation-message ${error ? "critical" : "good"}`} role="status">
          {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{error || message}</span>
        </div>
      )}

      <section className="automation-main-grid" aria-label="Automation state">
        <article className="automation-panel dag-inspector-panel">
          <div className="panel-heading-row compact">
            <div>
              <h2>Execution Graph</h2>
              <p>{view.dag.summary}</p>
            </div>
            <TonePill tone={view.nextAction.tone}>{view.nextAction.status}</TonePill>
          </div>
          <div className="next-action-strip">
            <GitBranch size={16} />
            <span>Next</span>
            <strong>{view.nextAction.title}</strong>
            <p>{view.nextAction.detail}</p>
          </div>
          <div className="pipeline-dag" role="table" aria-label="Execution graph">
            <div className="pipeline-header" role="row">
              <span />
              {view.dag.columns.map((column) => <strong key={column.id}>{column.label}</strong>)}
            </div>
            {view.dag.rows.length ? view.dag.rows.map((row) => (
              <div className="pipeline-row" role="row" key={row.id}>
                <div className="pipeline-row-label">
                  <strong>{row.label}</strong>
                  <span>{row.summary}</span>
                </div>
                <div className="pipeline-cells">
                  {view.dag.columns.map((column) => {
                    const node = row.cells[column.id];
                    return (
                      <div className={`pipeline-cell${node ? " has-node" : ""}`} role="cell" key={`${row.id}:${column.id}`}>
                        {node ? (
                          <PipelineNodeButton
                            node={node}
                            selected={node.id === effectiveSelectedNodeId}
                            onSelect={setSelectedNodeId}
                          />
                        ) : <span className="pipeline-empty-cell" aria-label={`${column.label} not recorded`} />}
                      </div>
                    );
                  })}
                </div>
              </div>
            )) : (
              <div className="pipeline-empty-state">
                <span>No execution graph data is recorded yet.</span>
              </div>
            )}
          </div>
        </article>

        <SelectedWorkDetail node={selectedNode} nextAction={view.nextAction} ticket={selectedTicket} />

        <TicketProgressPanel tickets={view.ticketProgress} />

        <article className="automation-panel queue-summary-panel">
          <div className="panel-heading-row compact">
            <h2>Now & Next</h2>
          </div>
          <div className="queue-buckets">
            {view.queueBuckets.map((bucket) => <QueueBucketCard bucket={bucket} key={bucket.id} />)}
          </div>
        </article>

        <article className="automation-panel human-compact-panel">
          <div className="panel-heading-row compact">
            <h2>Human Input</h2>
            <TonePill tone={view.humanInput.tone}>{view.humanInput.badge}</TonePill>
          </div>
          <div className="human-compact-counts">
            <div><span>Requests</span><strong>{view.humanInput.requests}</strong></div>
            <div><span>Records</span><strong>{view.humanInput.records}</strong></div>
            <div><span>Outbound</span><strong>{view.humanInput.outbound}</strong></div>
          </div>
          <p>{view.humanInput.detail}</p>
        </article>

        <article className="automation-panel validation-panel">
          <div className="panel-heading-row compact">
            <h2>Checks & Repair</h2>
            <TonePill tone={view.validationRepair.tone}>{view.validationRepair.summary}</TonePill>
          </div>
          <div className="automation-table">
            {view.validationRepair.rows.length
              ? view.validationRepair.rows.map((row) => <ValidationRow row={row} key={row.id} />)
              : <div className="empty-copy">No validation or repair work is active.</div>}
          </div>
        </article>

        <article className="automation-panel activity-panel">
          <div className="panel-heading-row compact">
            <h2>Activity Log</h2>
          </div>
          <div className="automation-table">
            {view.activityLog.length
              ? view.activityLog.map((row) => <ActivityRow row={row} key={row.id} />)
              : <div className="empty-copy">No useful activity has been recorded yet.</div>}
          </div>
        </article>

        <article className="automation-panel log-panel">
          <div className="panel-heading-row compact">
            <h2>Command Output</h2>
            {busyCommand && <TonePill tone="info">{busyCommand}</TonePill>}
          </div>
          <div className="automation-log">
            {logs.length ? logs.map((line, index) => (
              <div className={`automation-log-line ${line.level}`} key={`${line.stage}-${line.message}-${index}`}>
                <span>{line.stage}</span>
                <p>{line.message}</p>
              </div>
            )) : (
              <div className="empty-copy">Start, stop, and safety-check output appears here.</div>
            )}
          </div>
          <button
            className="secondary-action"
            onClick={() => navigator.clipboard?.writeText(model.controls.startAutomation.command || automationCommandFallbacks.start)}
          >
            <Clipboard size={15} />
            Copy start command
          </button>
        </article>
      </section>
    </section>
  );
}
