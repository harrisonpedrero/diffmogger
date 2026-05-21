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
import { useMemo, useState, type CSSProperties } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot } from "./api/backend";
import { listenBackendLogs, runBackendCommandStreamed } from "./api/backend";
import {
  buildAutomationViewModel,
  type AutomationGraphEdge,
  type AutomationGraphGroup,
  type AutomationGraphNode,
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

function graphEdgePath(edge: AutomationGraphEdge): string {
  const { x1, y1, cx1, cy1, cx2, cy2, x2, y2 } = edge.points;
  return `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`;
}

function GraphNodeButton(props: {
  node: AutomationGraphNode;
  selected: boolean;
  onSelect: (nodeId: string) => void;
}) {
  const style: CSSProperties = {
    left: props.node.x,
    top: props.node.y,
    width: props.node.width,
    height: props.node.height,
  };
  return (
    <button
      type="button"
      className={`dag-graph-node ${props.node.sourceKind} ${props.node.status}${props.selected ? " selected" : ""}`}
      style={style}
      aria-pressed={props.selected}
      aria-label={`${props.node.title} ${props.node.subtitle} ${props.node.statusLabel}`}
      title={props.node.detail}
      onClick={() => props.onSelect(props.node.id)}
    >
      <span>{props.node.title}</span>
      <small>{props.node.subtitle}</small>
      <em>{props.node.statusLabel}</em>
    </button>
  );
}

function groupBounds(group: AutomationGraphGroup, nodes: AutomationGraphNode[]) {
  const groupNodes = group.nodeIds
    .map((nodeId) => nodes.find((node) => node.id === nodeId))
    .filter((node): node is AutomationGraphNode => Boolean(node));
  if (!groupNodes.length) return null;
  const padding = 10;
  const minX = Math.min(...groupNodes.map((node) => node.x)) - padding;
  const minY = Math.min(...groupNodes.map((node) => node.y)) - padding;
  const maxX = Math.max(...groupNodes.map((node) => node.x + node.width)) + padding;
  const maxY = Math.max(...groupNodes.map((node) => node.y + node.height)) + padding;
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

function ExecutionGraphPanel(props: {
  dag: ReturnType<typeof buildAutomationViewModel>["dag"];
  nextAction: ReturnType<typeof buildAutomationViewModel>["nextAction"];
  selectedNodeId: string;
  onSelect: (nodeId: string) => void;
}) {
  const graphStyle: CSSProperties = {
    width: props.dag.width,
    height: props.dag.height,
  };
  const groupBoxes = props.dag.groups
    .map((group) => ({ group, bounds: groupBounds(group, props.dag.nodes) }))
    .filter((item): item is { group: AutomationGraphGroup; bounds: NonNullable<ReturnType<typeof groupBounds>> } => Boolean(item.bounds));
  return (
    <article className="automation-panel dag-inspector-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Execution Graph</h2>
          <p>{props.dag.summary}</p>
        </div>
        <TonePill tone={props.nextAction.tone}>{props.dag.modeLabel}</TonePill>
      </div>
      <div className="next-action-strip">
        <GitBranch size={16} />
        <span>Next</span>
        <strong>{props.nextAction.title}</strong>
        <p>{props.nextAction.detail}</p>
      </div>
      <div className="dag-graph-scroll" aria-label="Execution graph">
        <div className={`dag-graph-canvas ${props.dag.mode}`} style={graphStyle}>
          <svg
            className="dag-graph-svg"
            role="img"
            aria-label={`${props.dag.modeLabel}: ${props.dag.summary}`}
            viewBox={`0 0 ${props.dag.width} ${props.dag.height}`}
          >
            <defs>
              <marker id="dag-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            </defs>
            {props.dag.columns.map((column) => (
              <g className="dag-column-guide" key={column.id}>
                <rect x={column.x - 8} y="30" width={column.width + 16} height={Math.max(0, props.dag.height - 42)} />
                <text x={column.x + column.width / 2} y="20">{column.label}</text>
              </g>
            ))}
            {groupBoxes.map(({ group, bounds }) => (
              <g className={`dag-wave-outline ${group.kind}`} key={group.id}>
                <rect x={bounds.x} y={bounds.y} width={bounds.width} height={bounds.height} />
                <text x={bounds.x + 8} y={Math.max(18, bounds.y - 4)}>{group.label}</text>
              </g>
            ))}
            {props.dag.edges.map((edge) => (
              <g className={`dag-edge ${edge.presentationKind}`} key={edge.id}>
                <path d={graphEdgePath(edge)} markerEnd="url(#dag-arrow)" />
                {edge.count > 1 && (
                  <text x={(edge.points.x1 + edge.points.x2) / 2} y={(edge.points.y1 + edge.points.y2) / 2 - 5}>{edge.label}</text>
                )}
              </g>
            ))}
          </svg>
          {props.dag.nodes.map((node) => (
            <GraphNodeButton
              node={node}
              selected={node.id === props.selectedNodeId}
              onSelect={props.onSelect}
              key={node.id}
            />
          ))}
        </div>
      </div>
      <div className="dag-graph-legend">
        <span><i className="edge-hard" /> Hard dependency</span>
        <span><i className="edge-advisory" /> Advisory</span>
        <span><i className="edge-blocker" /> Blocker/follow-up</span>
        {props.dag.hiddenSummary && <strong>{props.dag.hiddenSummary}</strong>}
      </div>
    </article>
  );
}

function SelectedWorkDetail(props: {
  node: AutomationGraphNode | null;
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
              <span>{props.node.sourceKind === "cluster" ? "Cluster" : "Ticket"}</span>
              <strong>{props.node.sourceKind === "cluster" ? props.node.subtitle : props.node.ticketId || "Automation work"}</strong>
            </div>
            <div>
              <span>Stage</span>
              <strong>{props.node.phaseLabel}</strong>
            </div>
            <div>
              <span>Status</span>
              <strong>{props.node.statusLabel}</strong>
            </div>
            <div>
              <span>Role</span>
              <strong>{props.node.role}</strong>
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
          {(props.node.samples.length > 0 || props.node.badges.length > 0) && (
            <div className="selected-work-tags">
              {[...props.node.badges, ...props.node.samples].slice(0, 6).map((tag) => <span key={tag}>{tag}</span>)}
            </div>
          )}
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

function ExecutionWavesPanel(props: { model: ReturnType<typeof buildRunModel> }) {
  const waves = props.model.operations.concurrencyWaves;
  const integration = props.model.operations.integrationBacklog;
  return (
    <article className="automation-panel wave-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>DAG Flow</h2>
          <p>
            {props.model.executionDag.parallel.activeGroups} running wave / {props.model.executionDag.parallel.proposedGroups} planned / {props.model.executionDag.parallel.completedGroups} recently done
          </p>
        </div>
        <TonePill tone={integration.tone}>{integration.queuedCount} queued patches</TonePill>
      </div>
      <div className="wave-metrics">
        <div><span>Active nodes</span><strong>{props.model.executionDag.parallel.activeNodeCount}</strong></div>
        <div><span>Planned nodes</span><strong>{props.model.executionDag.parallel.plannedNodeCount}</strong></div>
        <div><span>Safe patches</span><strong>{integration.safeCount}</strong></div>
        <div><span>Follow-up</span><strong>{integration.blockedCount}</strong></div>
      </div>
      <div className="wave-list">
        {waves.length ? waves.slice(0, 8).map((wave) => (
          <div className={`wave-card ${wave.kind}`} key={`${wave.kind}:${wave.id}`}>
            <div>
              <strong>{wave.label}</strong>
              <TonePill tone={wave.tone}>{wave.status}</TonePill>
            </div>
            <p>{wave.detail}</p>
            <div className="wave-card-meta">
              <span>{wave.mode}</span>
              <span>{wave.itemCount} item{wave.itemCount === 1 ? "" : "s"}</span>
              {wave.owners.length > 0 && <span>{wave.owners.join(", ")}</span>}
              {wave.leases.length > 0 && <span>{wave.leases.join(", ")}</span>}
            </div>
          </div>
        )) : <div className="empty-copy">No execution waves are recorded yet.</div>}
      </div>
    </article>
  );
}

type FeedTab = "activity" | "checks" | "command" | "input";

function OperationalFeedPanel(props: {
  view: ReturnType<typeof buildAutomationViewModel>;
  logs: AutomationLogEvent[];
  busyCommand: string;
  startCommand: string;
}) {
  const [tab, setTab] = useState<FeedTab>("activity");
  const tabs: Array<{ id: FeedTab; label: string; badge?: string }> = [
    { id: "activity", label: "Activity", badge: props.view.activityLog.length ? String(props.view.activityLog.length) : undefined },
    { id: "checks", label: "Checks & Repair", badge: props.view.validationRepair.rows.length ? String(props.view.validationRepair.rows.length) : undefined },
    { id: "command", label: "Command Output", badge: props.busyCommand || undefined },
    { id: "input", label: "Input Records", badge: props.view.humanInput.total ? props.view.humanInput.badge : undefined },
  ];
  return (
    <article className="automation-panel operational-feed-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Operational Feed</h2>
          <p>{props.view.activityLog.length} activity / {props.view.validationRepair.rows.length} checks / {props.logs.length} command lines</p>
        </div>
      </div>
      <div className="feed-tabs" role="tablist" aria-label="Operational feed sections">
        {tabs.map((item) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
            key={item.id}
          >
            <span>{item.label}</span>
            {item.badge && <strong>{item.badge}</strong>}
          </button>
        ))}
      </div>
      <div className="automation-table feed-content" hidden={tab !== "activity"}>
        {props.view.activityLog.length
          ? props.view.activityLog.map((row) => <ActivityRow row={row} key={row.id} />)
          : <div className="empty-copy">No useful activity has been recorded yet.</div>}
      </div>
      <div className="automation-table feed-content" hidden={tab !== "checks"}>
        {props.view.validationRepair.rows.length
          ? props.view.validationRepair.rows.map((row) => <ValidationRow row={row} key={row.id} />)
          : <div className="empty-copy">No validation or repair work is active.</div>}
      </div>
      <div className="feed-command" hidden={tab !== "command"}>
        <div className="automation-log">
          {props.logs.length ? props.logs.map((line, index) => (
            <div className={`automation-log-line ${line.level}`} key={`${line.stage}-${line.message}-${index}`}>
              <span>{line.stage}</span>
              <p>{line.message}</p>
            </div>
          )) : (
            <div className="empty-copy">No command output captured.</div>
          )}
        </div>
        <button
          className="secondary-action"
          onClick={() => navigator.clipboard?.writeText(props.startCommand)}
        >
          <Clipboard size={15} />
          Copy start command
        </button>
      </div>
      <div className="feed-input" hidden={tab !== "input"}>
        <div className="human-compact-counts">
          <div><span>Requests</span><strong>{props.view.humanInput.requests}</strong></div>
          <div><span>Records</span><strong>{props.view.humanInput.records}</strong></div>
          <div><span>Outbound</span><strong>{props.view.humanInput.outbound}</strong></div>
        </div>
        <p>{props.view.humanInput.detail}</p>
      </div>
    </article>
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
        <ExecutionGraphPanel
          dag={view.dag}
          nextAction={view.nextAction}
          selectedNodeId={effectiveSelectedNodeId}
          onSelect={setSelectedNodeId}
        />

        <SelectedWorkDetail node={selectedNode} nextAction={view.nextAction} ticket={selectedTicket} />

        <article className="automation-panel queue-summary-panel">
          <div className="panel-heading-row compact">
            <h2>Now & Next</h2>
          </div>
          <div className="queue-buckets">
            {view.queueBuckets.map((bucket) => <QueueBucketCard bucket={bucket} key={bucket.id} />)}
          </div>
        </article>

        <ExecutionWavesPanel model={model} />

        <TicketProgressPanel tickets={view.ticketProgress} />

        <OperationalFeedPanel
          view={view}
          logs={logs}
          busyCommand={busyCommand}
          startCommand={model.controls.startAutomation.command || automationCommandFallbacks.start}
        />
      </section>
    </section>
  );
}
