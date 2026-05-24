import {
  AlertTriangle,
  Bell,
  CheckCircle2,
  Clipboard,
  FileText,
  FolderOpen,
  GitBranch,
  GitPullRequest,
  HelpCircle,
  ListFilter,
  Maximize2,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Route,
  Search,
  Server,
  ShieldCheck,
  Square,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot } from "./api/backend";
import { listenBackendLogs, runBackendCommandStreamed } from "./api/backend";
import {
  buildAutomationViewModel,
  type AutomationEvidenceRow,
  type AutomationQueueRow,
  type AutomationSchedulerCandidateRow,
  type AutomationTicketGraphNode,
  type AutomationTicketProgressRow,
  type AutomationTimelineCategory,
  type AutomationTimelineEvent,
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

type TicketProgressTab = "list" | "graph";
type TicketDetailRecord = AutomationTicketProgressRow | AutomationTicketGraphNode;

function defaultTicketId(view: ReturnType<typeof buildAutomationViewModel>): string {
  return view.ticketProgress.rows.find((ticket) => ticket.status === "building")?.id ||
    view.ticketProgress.rows.find((ticket) => ticket.status === "scoping")?.id ||
    view.ticketProgress.rows.find((ticket) => ticket.status === "running")?.id ||
    view.ticketProgress.rows.find((ticket) => ticket.status === "ready")?.id ||
    view.ticketProgress.rows.find((ticket) => ticket.status === "waiting")?.id ||
    view.ticketProgress.rows[0]?.id ||
    view.ticketGraph.nodes[0]?.id ||
    "";
}

function DetailList(props: { items: string[]; empty: string }) {
  if (!props.items.length) return <p className="empty-copy">{props.empty}</p>;
  return (
    <ul className="ticket-detail-list">
      {props.items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
    </ul>
  );
}

function DetailTags(props: { items: string[]; empty: string }) {
  if (!props.items.length) return <p className="empty-copy">{props.empty}</p>;
  return (
    <div className="ticket-detail-tags">
      {props.items.map((item) => <span key={item}>{item}</span>)}
    </div>
  );
}

function TicketDetailInspector(props: { ticket: TicketDetailRecord | undefined }) {
  const ticket = props.ticket;
  if (!ticket) {
    return (
      <aside className="ticket-detail-inspector">
        <h3>Ticket Detail</h3>
        <p className="empty-copy">Select a ticket to inspect details.</p>
      </aside>
    );
  }
  const placeholder = "placeholder" in ticket && ticket.placeholder;
  const cyclic = "cyclic" in ticket && ticket.cyclic;
  return (
    <aside className="ticket-detail-inspector">
      <div className="ticket-detail-title">
        <span>{placeholder ? "Dependency Detail" : "Ticket Detail"}</span>
        <h3>{ticket.id}</h3>
        <TonePill tone={ticket.tone}>{ticket.statusLabel}</TonePill>
      </div>
      <p>{ticket.summary}</p>
      <div className="ticket-detail-grid">
        <div>
          <span>Current phase</span>
          <strong>{ticket.stage}</strong>
        </div>
        <div>
          <span>Runtime status</span>
          <strong>{ticket.runtimeStatus || String(ticket.status)}</strong>
        </div>
        <div>
          <span>Evidence</span>
          <strong>{ticket.evidenceCount}</strong>
        </div>
        <div>
          <span>Commits</span>
          <strong>{ticket.commitCount}</strong>
        </div>
      </div>
      {cyclic && <div className="ticket-detail-warning">Dependency cycle detected for this ticket.</div>}
      {ticket.blocker && <div className="ticket-detail-warning">{ticket.blocker}</div>}
      <section className="ticket-detail-section">
        <span>Dependencies</span>
        <DetailTags items={ticket.dependsOn} empty="No dependencies recorded." />
      </section>
      <section className="ticket-detail-section">
        <span>Acceptance criteria</span>
        <DetailList items={ticket.acceptanceCriteria} empty="No acceptance criteria recorded." />
      </section>
      <section className="ticket-detail-section">
        <span>Verification commands</span>
        <DetailList items={ticket.verificationCommands} empty="No verification commands recorded." />
      </section>
      <section className="ticket-detail-section">
        <span>Related commits</span>
        <DetailTags items={ticket.relatedCommits} empty="No related commits recorded." />
      </section>
      <small title={ticket.detail}>{ticket.detail}</small>
    </aside>
  );
}

function TicketProgressListTab(props: {
  view: ReturnType<typeof buildAutomationViewModel>;
  selectedTicketId: string;
  selectedTicket: TicketDetailRecord | undefined;
  onSelect: (ticketId: string) => void;
}) {
  return (
    <div className="ticket-progress-workspace">
      <div className="ticket-progress-list-pane">
        <div className="ticket-progress-counts">
          {props.view.ticketProgress.counts.map((item) => (
            <div className={`ticket-progress-count ${item.id}`} key={item.id}>
              <span>{item.label}</span>
              <strong>{item.count}</strong>
            </div>
          ))}
        </div>
        <div className="ticket-progress-table" aria-label="Tickets">
          <div className="ticket-progress-header">
            <span>Ticket</span>
            <span>Status</span>
            <span>Current phase</span>
            <span>Title</span>
            <span>Dependencies / evidence</span>
          </div>
          <div className="ticket-progress-scroll">
            {props.view.ticketProgress.rows.map((ticket) => (
              <button
                type="button"
                className={`ticket-progress-row ${ticket.status} ${props.selectedTicketId === ticket.id ? "selected" : ""}`}
                onClick={() => props.onSelect(ticket.id)}
                key={ticket.id}
              >
                <strong>{ticket.id}</strong>
                <span>{ticket.statusLabel}</span>
                <span>{ticket.stage}</span>
                <p>{ticket.summary}</p>
                <p>{ticket.evidenceCount ? `${ticket.evidenceCount} evidence item${ticket.evidenceCount === 1 ? "" : "s"}` : ticket.dependsOn.length ? `Depends on ${ticket.dependsOn.slice(0, 4).join(", ")}` : ticket.detail}</p>
              </button>
            ))}
          </div>
        </div>
      </div>
      <TicketDetailInspector ticket={props.selectedTicket} />
    </div>
  );
}

function TicketDependencyGraphTab(props: {
  view: ReturnType<typeof buildAutomationViewModel>;
  selectedTicketId: string;
  selectedTicket: TicketDetailRecord | undefined;
  onSelect: (ticketId: string) => void;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  const [search, setSearch] = useState("");
  const graph = props.view.ticketGraph;

  function setBoundedZoom(value: number) {
    setZoom(Math.max(0.45, Math.min(1.8, Number(value.toFixed(2)))));
  }

  function scrollToNode(node: AutomationTicketGraphNode, nextZoom = zoom) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTo({
      left: Math.max(0, node.x * nextZoom - 120),
      top: Math.max(0, node.y * nextZoom - 80),
      behavior: "smooth",
    });
  }

  function fitGraph() {
    const viewport = viewportRef.current;
    if (!viewport || !graph.width) return;
    const nextZoom = Math.max(0.45, Math.min(1.15, (viewport.clientWidth - 36) / graph.width));
    setBoundedZoom(nextZoom);
    viewport.scrollTo({ left: 0, top: 0, behavior: "smooth" });
  }

  function resetGraph() {
    setBoundedZoom(1);
    viewportRef.current?.scrollTo({ left: 0, top: 0, behavior: "smooth" });
  }

  function selectSearchMatch() {
    const query = search.trim().toLowerCase();
    if (!query) return;
    const match = graph.nodes.find((node) =>
      node.id.toLowerCase().includes(query) || node.summary.toLowerCase().includes(query)
    );
    if (!match) return;
    props.onSelect(match.id);
    scrollToNode(match);
  }

  return (
    <div className="ticket-graph-workspace">
      <div className="ticket-graph-main">
        <div className="ticket-graph-toolbar">
          <div className="ticket-graph-summary">
            <strong>{graph.summary}</strong>
            <span>{graph.completed} done / {graph.active} active / {graph.ready} ready / {graph.waiting} waiting{graph.cyclicCount ? ` / ${graph.cyclicCount} cyclic` : ""}</span>
          </div>
          <div className="ticket-graph-search">
            <Search size={14} />
            <input
              aria-label="Search tickets"
              placeholder="Search ticket"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") selectSearchMatch();
              }}
            />
          </div>
          <button className="secondary-action icon-only-action" type="button" title="Fit graph" onClick={fitGraph}><Maximize2 size={15} /></button>
          <button className="secondary-action icon-only-action" type="button" title="Zoom out" onClick={() => setBoundedZoom(zoom - 0.12)}><ZoomOut size={15} /></button>
          <button className="secondary-action icon-only-action" type="button" title="Zoom in" onClick={() => setBoundedZoom(zoom + 0.12)}><ZoomIn size={15} /></button>
          <button className="secondary-action icon-only-action" type="button" title="Reset graph" onClick={resetGraph}><RotateCcw size={15} /></button>
        </div>
        <div className="ticket-graph-viewport" ref={viewportRef} aria-label="Ticket dependency graph">
          {graph.nodes.length ? (
            <div className="ticket-graph-canvas" style={{ width: graph.width * zoom, height: graph.height * zoom }}>
              <div className="ticket-graph-scaled" style={{ width: graph.width, height: graph.height, transform: `scale(${zoom})` }}>
                <svg className="ticket-graph-svg" viewBox={`0 0 ${graph.width} ${graph.height}`} role="presentation">
                  <defs>
                    <marker id="ticket-graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                      <path d="M 0 0 L 8 4 L 0 8 z" />
                    </marker>
                  </defs>
                  {graph.layers.map((layer) => (
                    <g className={`ticket-graph-layer ${layer.cyclic ? "cyclic" : ""}`} key={layer.id}>
                      <line x1={layer.x - 14} y1="24" x2={layer.x - 14} y2={graph.height - 18} />
                      <text x={layer.x} y="24">{layer.label} · {layer.count}</text>
                    </g>
                  ))}
                  {graph.edges.map((edge) => (
                    <path
                      className={`ticket-graph-edge ${edge.cyclic ? "cyclic" : ""}`}
                      d={edge.path}
                      markerEnd="url(#ticket-graph-arrow)"
                      key={edge.id}
                    />
                  ))}
                </svg>
                {graph.nodes.map((node) => (
                  <button
                    type="button"
                    className={`ticket-graph-node ${node.status} ${node.placeholder ? "placeholder" : ""} ${node.cyclic ? "cyclic" : ""} ${props.selectedTicketId === node.id ? "selected" : ""}`}
                    style={{ left: node.x, top: node.y, width: node.width, height: node.height }}
                    title={`${node.id}: ${node.summary}`}
                    onClick={() => props.onSelect(node.id)}
                    key={node.id}
                  >
                    <span>{node.id}</span>
                    <strong>{node.summary}</strong>
                    <small>{node.statusLabel} · {node.dependsOn.length} deps</small>
                  </button>
                ))}
              </div>
            </div>
          ) : <div className="pipeline-empty-state">No tickets are loaded.</div>}
        </div>
      </div>
      <TicketDetailInspector ticket={props.selectedTicket} />
    </div>
  );
}

function TicketProgressPanel(props: { view: ReturnType<typeof buildAutomationViewModel> }) {
  const [tab, setTab] = useState<TicketProgressTab>("list");
  const [selectedTicketId, setSelectedTicketId] = useState("");
  const done = props.view.ticketProgress.counts.find((item) => item.id === "done")?.count ?? 0;
  const total = props.view.ticketProgress.total;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const fallbackTicketId = defaultTicketId(props.view);
  const effectiveSelectedTicketId = props.view.ticketGraph.nodes.some((node) => node.id === selectedTicketId)
    ? selectedTicketId
    : fallbackTicketId;
  const selectedTicket = props.view.ticketProgress.rows.find((ticket) => ticket.id === effectiveSelectedTicketId) ||
    props.view.ticketGraph.nodes.find((node) => node.id === effectiveSelectedTicketId);
  return (
    <article className="automation-panel ticket-progress-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Ticket Progress</h2>
          <p>{props.view.ticketProgress.summary}</p>
        </div>
        <TonePill tone={done === total && total ? "good" : "info"}>{pct}%</TonePill>
      </div>
      <div className="ticket-progress-meter" aria-label="Ticket completion">
        <span style={{ width: `${pct}%` }} />
      </div>
      <div className="feed-tabs ticket-progress-tabs" role="tablist" aria-label="Ticket progress views">
        <button type="button" role="tab" aria-selected={tab === "list"} className={tab === "list" ? "active" : ""} onClick={() => setTab("list")}>List</button>
        <button type="button" role="tab" aria-selected={tab === "graph"} className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>Graph</button>
      </div>
      {tab === "list" ? (
        <TicketProgressListTab
          view={props.view}
          selectedTicketId={effectiveSelectedTicketId}
          selectedTicket={selectedTicket}
          onSelect={setSelectedTicketId}
        />
      ) : (
        <TicketDependencyGraphTab
          view={props.view}
          selectedTicketId={effectiveSelectedTicketId}
          selectedTicket={selectedTicket}
          onSelect={setSelectedTicketId}
        />
      )}
    </article>
  );
}

function StatusBand(props: {
  view: ReturnType<typeof buildAutomationViewModel>;
  model: ReturnType<typeof buildRunModel>;
  retryFailed: AutomationCommandAction;
  busy: boolean;
  loading: boolean;
  onRun: (action: AutomationCommandAction) => void;
  onRefresh: () => void;
}) {
  return (
    <header className="automation-status-band">
      <div className="status-band-target">
        <TonePill tone={props.view.statusBand.tone}>{props.view.statusBand.headline}</TonePill>
        <div>
          <h1>{props.view.statusBand.targetName}</h1>
          <p title={props.view.statusBand.targetPath}>{props.view.statusBand.targetPath}</p>
        </div>
      </div>
      <div className="status-band-facts" aria-label="Automation status facts">
        {props.view.statusBand.facts.map((fact) => (
          <div className={`status-band-fact ${fact.tone}`} title={fact.detail} key={fact.id}>
            <span>{fact.label}</span>
            <strong>{fact.value}</strong>
          </div>
        ))}
      </div>
      <div className="status-band-actions" aria-label="Automation commands">
        <CommandButton action={props.model.controls.startAutomation} busy={props.busy} icon={<PlayCircle size={16} />} onRun={props.onRun} primary />
        <CommandButton action={props.model.controls.stopAutomation} busy={props.busy} icon={<Square size={15} />} onRun={props.onRun} />
        <CommandButton action={props.retryFailed} busy={props.busy} icon={<RotateCcw size={16} />} onRun={props.onRun} />
        <CommandButton action={props.model.controls.safetyCheck} busy={props.busy} icon={<ShieldCheck size={16} />} onRun={props.onRun} />
        <button className="secondary-action" disabled={props.loading} title="Refresh automation state." onClick={props.onRefresh}>
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>
      <p className="status-band-readiness">{props.view.statusBand.readinessReason}</p>
    </header>
  );
}

function CandidateRow(props: { candidate: AutomationSchedulerCandidateRow }) {
  return (
    <div className="scheduler-candidate-row">
      <strong>{props.candidate.label}</strong>
      <TonePill tone={props.candidate.tone}>{props.candidate.status}</TonePill>
      <span>{props.candidate.owner}</span>
      <span>{props.candidate.fanout}x</span>
      <span>{props.candidate.confidence}</span>
      <p title={props.candidate.detail}>{props.candidate.detail}</p>
    </div>
  );
}

function SchedulerDecisionPanel(props: { view: ReturnType<typeof buildAutomationViewModel> }) {
  const decision = props.view.schedulerDecision;
  return (
    <article className="automation-panel scheduler-decision-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Scheduler Decision</h2>
          <p>Selected next action and parallelism telemetry.</p>
        </div>
        <TonePill tone={decision.selected.tone}>{decision.selected.status}</TonePill>
      </div>
      <div className="scheduler-selected-card">
        <GitBranch size={16} />
        <span>Next</span>
        <strong>{decision.selected.label}</strong>
        <p>{decision.selected.detail}</p>
      </div>
      <div className="scheduler-decision-metrics">
        <div><span>Fanout</span><strong>{decision.fanout}</strong></div>
        <div><span>Ownership</span><strong title={decision.ownership}>{decision.ownership}</strong></div>
        <div><span>Confidence</span><strong>{decision.confidence}</strong></div>
      </div>
      <div className="scheduler-parallel-note">
        <HelpCircle size={15} />
        <div>
          <strong>{decision.whyParallel.status}</strong>
          <p>{decision.whyParallel.summary}</p>
          <small>{decision.whyParallel.next}</small>
        </div>
      </div>
      <div className="scheduler-candidate-list">
        {decision.alternatives.length ? decision.alternatives.map((candidate) => (
          <CandidateRow candidate={candidate} key={candidate.id} />
        )) : <div className="empty-copy">No alternate candidates recorded.</div>}
      </div>
    </article>
  );
}

function EvidenceRow(props: { row: AutomationEvidenceRow }) {
  return (
    <div className={`evidence-row ${props.row.scope}`}>
      <strong>{props.row.label}</strong>
      <TonePill tone={props.row.tone}>{props.row.status}</TonePill>
      <span>{props.row.scope}</span>
      <p>{props.row.detail}</p>
      <small title={props.row.evidencePath}>{props.row.evidencePath || props.row.repairWork || "No evidence path"}</small>
    </div>
  );
}

function ValidationEvidencePanel(props: { view: ReturnType<typeof buildAutomationViewModel> }) {
  const evidence = props.view.validationEvidence;
  return (
    <article className="automation-panel validation-evidence-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Validation & Evidence</h2>
          <p>{evidence.summary}</p>
        </div>
        <TonePill tone={evidence.tone}>{evidence.requiredFailed ? "Repair queued" : "Evidence"}</TonePill>
      </div>
      <div className="evidence-metric-strip">
        <div><span>Required passed</span><strong>{evidence.requiredPassed}</strong></div>
        <div><span>Required failed</span><strong>{evidence.requiredFailed}</strong></div>
        <div><span>Advisory failed</span><strong>{evidence.advisoryFailed}</strong></div>
        <div><span>Repair work</span><strong>{evidence.repairCreated}</strong></div>
        <div><span>Evidence paths</span><strong>{evidence.evidencePaths.length}</strong></div>
      </div>
      <div className="evidence-row-list">
        {evidence.rows.length ? evidence.rows.map((row) => <EvidenceRow row={row} key={row.id} />) : <div className="empty-copy">No validation evidence recorded yet.</div>}
      </div>
    </article>
  );
}

function QueueRow(props: { row: AutomationQueueRow }) {
  return (
    <div className="queue-integration-row">
      <strong>{props.row.label}</strong>
      <TonePill tone={props.row.tone}>{props.row.status}</TonePill>
      <span title={props.row.meta}>{props.row.meta}</span>
      <p title={props.row.detail}>{props.row.detail}</p>
    </div>
  );
}

function QueueIntegrationPanel(props: { view: ReturnType<typeof buildAutomationViewModel> }) {
  return (
    <article className="automation-panel queue-integration-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Queue & Integration</h2>
          <p>Execution groups, leases, worker runs, patches, and serialized integration.</p>
        </div>
      </div>
      <div className="queue-integration-metrics">
        {props.view.queueIntegration.metrics.map((metric) => (
          <div className={metric.tone} title={metric.detail} key={metric.id}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
          </div>
        ))}
      </div>
      <div className="queue-integration-list">
        {props.view.queueIntegration.rows.map((row) => <QueueRow row={row} key={`${row.id}:${row.label}`} />)}
      </div>
    </article>
  );
}

function timelineIcon(category: AutomationTimelineCategory) {
  if (category === "worker") return <Server size={14} />;
  if (category === "validation") return <ShieldCheck size={14} />;
  if (category === "integration") return <GitPullRequest size={14} />;
  if (category === "notification") return <Bell size={14} />;
  if (category === "human") return <FileText size={14} />;
  return <Route size={14} />;
}

function logTimelineEvents(logs: AutomationLogEvent[]): AutomationTimelineEvent[] {
  return logs.map((line, index) => {
    const stage = line.stage.toLowerCase();
    const category: AutomationTimelineCategory = stage.includes("validation") || stage.includes("safety")
      ? "validation"
      : stage.includes("integr")
      ? "integration"
      : stage.includes("worker")
      ? "worker"
      : "scheduler";
    return {
      id: `command-log-${index}`,
      category,
      title: line.stage,
      status: line.level,
      time: line.capturedAt.slice(11, 19),
      detail: line.message,
      tone: line.level === "error" ? "warn" : line.level === "warning" ? "warn" : "info",
    };
  });
}

function TimelinePanel(props: {
  view: ReturnType<typeof buildAutomationViewModel>;
  logs: AutomationLogEvent[];
  busyCommand: string;
  startCommand: string;
}) {
  const [category, setCategory] = useState<AutomationTimelineCategory | "all">("all");
  const events = useMemo(() => [...logTimelineEvents(props.logs), ...props.view.timeline], [props.logs, props.view.timeline]);
  const eventCategories = useMemo(() => new Set<AutomationTimelineCategory>(events.map((event) => event.category)), [events]);
  const allCategories: Array<{ id: AutomationTimelineCategory | "all"; label: string }> = [
    { id: "all", label: "All" },
    { id: "scheduler", label: "Scheduler" },
    { id: "worker", label: "Worker" },
    { id: "validation", label: "Validation" },
    { id: "integration", label: "Integration" },
    { id: "notification", label: "Notification" },
    { id: "human", label: "Human input" },
  ];
  const categories = allCategories.filter((item) => item.id === "all" || eventCategories.has(item.id));
  useEffect(() => {
    if (category !== "all" && !eventCategories.has(category)) setCategory("all");
  }, [category, eventCategories]);
  const filtered = category === "all" ? events : events.filter((event) => event.category === category);
  return (
    <article className="automation-panel timeline-panel">
      <div className="panel-heading-row compact">
        <div>
          <h2>Timeline</h2>
          <p>{events.length} recent event{events.length === 1 ? "" : "s"} / {props.logs.length} live command line{props.logs.length === 1 ? "" : "s"}</p>
        </div>
        {props.busyCommand && <TonePill tone="info">{props.busyCommand}</TonePill>}
        <button className="secondary-action compact-copy" onClick={() => navigator.clipboard?.writeText(props.startCommand)}>
          <Clipboard size={15} />
          Copy start command
        </button>
      </div>
      <div className="feed-tabs timeline-filters" role="tablist" aria-label="Timeline filters">
        <ListFilter size={14} />
        {categories.map((item) => (
          <button
            type="button"
            role="tab"
            aria-selected={category === item.id}
            className={category === item.id ? "active" : ""}
            onClick={() => setCategory(item.id)}
            key={item.id}
          >
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      <div className="timeline-list">
        {filtered.length ? filtered.map((event) => (
          <div className={`timeline-row ${event.category}`} key={event.id}>
            <span>{timelineIcon(event.category)}{event.category}</span>
            <strong>{event.title}</strong>
            <TonePill tone={event.tone}>{event.status}</TonePill>
            <time>{event.time || "recent"}</time>
            <p>{event.detail}</p>
          </div>
        )) : <div className="empty-copy">No events match this filter.</div>}
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
  const [busyCommand, setBusyCommand] = useState("");
  const [logs, setLogs] = useState<AutomationLogEvent[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const target = props.snapshot?.target.path ?? "";
  const retryFailed = retryFailedAction(model);
  const commandBusy = props.loading || Boolean(busyCommand);

  useEffect(() => {
    if (!busyCommand) {
      setMessage("");
      setError("");
    }
  }, [props.snapshot, busyCommand]);

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
      <StatusBand
        view={view}
        model={model}
        retryFailed={retryFailed}
        busy={commandBusy}
        loading={props.loading}
        onRun={runAction}
        onRefresh={props.onRefresh}
      />

      {(message || error) && (
        <div className={`automation-message ${error ? "critical" : "good"}`} role="status">
          {error ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          <span>{error || message}</span>
        </div>
      )}

      <section className="automation-main-grid" aria-label="Automation state">
        <TicketProgressPanel view={view} />

        <SchedulerDecisionPanel view={view} />

        <QueueIntegrationPanel view={view} />

        <ValidationEvidencePanel view={view} />

        <TimelinePanel
          view={view}
          logs={logs}
          busyCommand={busyCommand}
          startCommand={model.controls.startAutomation.command || automationCommandFallbacks.start}
        />
      </section>
    </section>
  );
}
