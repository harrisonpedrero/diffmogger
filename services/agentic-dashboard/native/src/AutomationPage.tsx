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
  LocateFixed,
  ListFilter,
  Maximize2,
  Minimize2,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Route,
  Search,
  Server,
  ShieldCheck,
  Shrink,
  Square,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
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
const TICKET_GRAPH_MIN_ZOOM = 0.01;
const TICKET_GRAPH_MAX_ZOOM = 1.8;
const TICKET_GRAPH_FIT_MAX_ZOOM = 1.15;
const TICKET_GRAPH_FIT_PADDING = 36;

const CURRENT_PROGRESS_STATUS_GROUPS: AutomationTicketGraphNode["status"][][] = [
  ["building", "scoping", "running", "in_progress", "candidate_done"],
  ["ready"],
  ["waiting", "pending"],
  ["done"],
];

function clampNumber(value: number, min: number, max: number): number {
  if (max < min) return min;
  return Math.max(min, Math.min(max, value));
}

function percentileNumber(values: number[], percentile: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((first, second) => first - second);
  if (sorted.length === 1) return sorted[0];
  const rawIndex = clampNumber(percentile, 0, 1) * (sorted.length - 1);
  const lower = Math.floor(rawIndex);
  const upper = Math.ceil(rawIndex);
  if (lower === upper) return sorted[lower];
  const weight = rawIndex - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function currentProgressNodes(nodes: AutomationTicketGraphNode[]): AutomationTicketGraphNode[] {
  for (const statuses of CURRENT_PROGRESS_STATUS_GROUPS) {
    const statusSet = new Set(statuses);
    const matches = nodes.filter((node) => !node.placeholder && statusSet.has(node.status));
    if (matches.length) return matches;
  }
  return [];
}

function ticketGraphFitZoom(
  graph: ReturnType<typeof buildAutomationViewModel>["ticketGraph"],
  viewport: HTMLDivElement,
): number {
  if (!graph.width || !graph.height) return 1;
  const widthZoom = Math.max(1, viewport.clientWidth - TICKET_GRAPH_FIT_PADDING) / graph.width;
  const heightZoom = Math.max(1, viewport.clientHeight - TICKET_GRAPH_FIT_PADDING) / graph.height;
  return clampNumber(
    Number(Math.min(widthZoom, heightZoom, TICKET_GRAPH_FIT_MAX_ZOOM).toFixed(2)),
    TICKET_GRAPH_MIN_ZOOM,
    TICKET_GRAPH_MAX_ZOOM,
  );
}

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
  fullscreen?: boolean;
  onEnterFullscreen?: () => void;
  onExitFullscreen?: () => void;
  onSelect: (ticketId: string) => void;
}) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const markerId = `ticket-graph-arrow-${useId().replace(/:/g, "")}`;
  const [zoom, setZoom] = useState(TICKET_GRAPH_MIN_ZOOM);
  const [search, setSearch] = useState("");
  const [trackCurrentProgress, setTrackCurrentProgress] = useState(false);
  const programmaticScrollUntilRef = useRef(0);
  const programmaticScrollTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const graph = props.view.ticketGraph;
  const focusNodes = useMemo(() => currentProgressNodes(graph.nodes), [graph.nodes]);
  const focusKey = focusNodes.map((node) => `${node.id}:${node.status}:${node.x}:${node.y}`).join("|");
  const focusPoint = useMemo(() => {
    if (!focusNodes.length) return null;
    return {
      x: percentileNumber(focusNodes.map((node) => node.x), 0.72) ?? focusNodes[0].x,
      y: percentileNumber(focusNodes.map((node) => node.y), 0.5) ?? focusNodes[0].y,
    };
  }, [focusKey, focusNodes]);

  function setBoundedZoom(value: number) {
    setZoom(clampNumber(Number(value.toFixed(2)), TICKET_GRAPH_MIN_ZOOM, TICKET_GRAPH_MAX_ZOOM));
  }

  const runProgrammaticScroll = useCallback((left: number, top: number, behavior: ScrollBehavior = "smooth") => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    programmaticScrollUntilRef.current = Date.now() + 1500;
    if (programmaticScrollTimerRef.current) window.clearTimeout(programmaticScrollTimerRef.current);
    programmaticScrollTimerRef.current = window.setTimeout(() => {
      programmaticScrollUntilRef.current = 0;
      programmaticScrollTimerRef.current = null;
    }, 1550);
    viewport.scrollTo({ left, top, behavior });
  }, []);

  function scrollToNode(node: AutomationTicketGraphNode, nextZoom = zoom) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const left = clampNumber(node.x * nextZoom - 120, 0, viewport.scrollWidth - viewport.clientWidth);
    const top = clampNumber(node.y * nextZoom - 80, 0, viewport.scrollHeight - viewport.clientHeight);
    runProgrammaticScroll(left, top);
  }

  const centerCurrentProgress = useCallback((behavior: ScrollBehavior = "smooth") => {
    const viewport = viewportRef.current;
    if (!viewport || !focusPoint) return;
    const left = clampNumber(focusPoint.x * zoom - viewport.clientWidth * 0.32, 0, viewport.scrollWidth - viewport.clientWidth);
    const top = clampNumber(focusPoint.y * zoom - viewport.clientHeight * 0.45, 0, viewport.scrollHeight - viewport.clientHeight);
    runProgrammaticScroll(left, top, behavior);
  }, [focusPoint, runProgrammaticScroll, zoom]);

  function fitGraph() {
    const viewport = viewportRef.current;
    if (!viewport || !graph.width) return;
    setTrackCurrentProgress(false);
    setZoom(ticketGraphFitZoom(graph, viewport));
    runProgrammaticScroll(0, 0);
  }

  function resetGraph() {
    setTrackCurrentProgress(false);
    setBoundedZoom(1);
    runProgrammaticScroll(0, 0);
  }

  function recenterCurrentProgress() {
    setTrackCurrentProgress(true);
    centerCurrentProgress();
  }

  function selectSearchMatch() {
    const query = search.trim().toLowerCase();
    if (!query) return;
    const match = graph.nodes.find((node) =>
      node.id.toLowerCase().includes(query) || node.summary.toLowerCase().includes(query)
    );
    if (!match) return;
    setTrackCurrentProgress(false);
    props.onSelect(match.id);
    scrollToNode(match);
  }

  function handleViewportScroll() {
    if (Date.now() <= programmaticScrollUntilRef.current) return;
    setTrackCurrentProgress(false);
  }

  useEffect(() => {
    if (!trackCurrentProgress) return;
    centerCurrentProgress("smooth");
  }, [centerCurrentProgress, focusKey, props.fullscreen, trackCurrentProgress, zoom]);

  useEffect(() => {
    if (!graph.nodes.length || !graph.width || !graph.height) return;
    const frame = window.requestAnimationFrame(() => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      setTrackCurrentProgress(false);
      setZoom(ticketGraphFitZoom(graph, viewport));
      runProgrammaticScroll(0, 0, "auto");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [graph.height, graph.nodes.length, graph.width, props.fullscreen, runProgrammaticScroll]);

  useEffect(() => () => {
    if (programmaticScrollTimerRef.current) window.clearTimeout(programmaticScrollTimerRef.current);
  }, []);

  return (
    <div className={`ticket-graph-workspace ${props.fullscreen ? "fullscreen" : ""}`}>
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
          <button
            className={`secondary-action icon-only-action ${trackCurrentProgress ? "active" : ""}`}
            type="button"
            title={trackCurrentProgress ? "Following current progress" : "Re-center current progress"}
            aria-label="Re-center current progress"
            disabled={!focusNodes.length}
            onClick={recenterCurrentProgress}
          >
            <LocateFixed size={15} />
          </button>
          <button className="secondary-action icon-only-action" type="button" title="Fit full graph" onClick={fitGraph}><Shrink size={15} /></button>
          {!props.fullscreen && props.onEnterFullscreen && (
            <button className="secondary-action icon-only-action" type="button" title="Fullscreen graph" aria-label="Fullscreen graph" onClick={props.onEnterFullscreen}><Maximize2 size={15} /></button>
          )}
          {props.fullscreen && props.onExitFullscreen && (
            <button className="secondary-action icon-only-action" type="button" title="Exit fullscreen" aria-label="Exit fullscreen" onClick={props.onExitFullscreen}><Minimize2 size={15} /></button>
          )}
          <button className="secondary-action icon-only-action" type="button" title="Zoom out" onClick={() => setBoundedZoom(zoom - 0.12)}><ZoomOut size={15} /></button>
          <button className="secondary-action icon-only-action" type="button" title="Zoom in" onClick={() => setBoundedZoom(zoom + 0.12)}><ZoomIn size={15} /></button>
          <button className="secondary-action icon-only-action" type="button" title="Reset graph" onClick={resetGraph}><RotateCcw size={15} /></button>
        </div>
        <div className="ticket-graph-viewport" ref={viewportRef} aria-label="Ticket dependency graph" onScroll={handleViewportScroll}>
          {graph.nodes.length ? (
            <div className="ticket-graph-canvas" style={{ width: graph.width * zoom, height: graph.height * zoom }}>
              <div className="ticket-graph-scaled" style={{ width: graph.width, height: graph.height, transform: `scale(${zoom})` }}>
                <svg className="ticket-graph-svg" viewBox={`0 0 ${graph.width} ${graph.height}`} role="presentation">
                  <defs>
                    <marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
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
                      markerEnd={`url(#${markerId})`}
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
  const [graphFullscreen, setGraphFullscreen] = useState(false);
  const fullscreenRef = useRef<HTMLDivElement>(null);
  const done = props.view.ticketProgress.counts.find((item) => item.id === "done")?.count ?? 0;
  const total = props.view.ticketProgress.total;
  const pct = total ? Math.round((done / total) * 100) : 0;
  const fallbackTicketId = defaultTicketId(props.view);
  const effectiveSelectedTicketId = props.view.ticketGraph.nodes.some((node) => node.id === selectedTicketId)
    ? selectedTicketId
    : fallbackTicketId;
  const selectedTicket = props.view.ticketProgress.rows.find((ticket) => ticket.id === effectiveSelectedTicketId) ||
    props.view.ticketGraph.nodes.find((node) => node.id === effectiveSelectedTicketId);

  function openGraphFullscreen() {
    flushSync(() => setGraphFullscreen(true));
    const fullscreenTarget = fullscreenRef.current;
    if (fullscreenTarget?.requestFullscreen && document.fullscreenElement !== fullscreenTarget) {
      void fullscreenTarget.requestFullscreen().catch(() => undefined);
    }
  }

  function closeGraphFullscreen() {
    const fullscreenTarget = fullscreenRef.current;
    if (document.fullscreenElement === fullscreenTarget && document.exitFullscreen) {
      void document.exitFullscreen().catch(() => undefined);
    }
    setGraphFullscreen(false);
  }

  useEffect(() => {
    if (!graphFullscreen) return;
    document.body.classList.add("ticket-graph-fullscreen-open");
    function handleFullscreenChange() {
      if (!document.fullscreenElement) setGraphFullscreen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeGraphFullscreen();
    }
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      const fullscreenTarget = fullscreenRef.current;
      document.body.classList.remove("ticket-graph-fullscreen-open");
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      document.removeEventListener("keydown", handleKeyDown);
      if (document.fullscreenElement === fullscreenTarget && document.exitFullscreen) {
        void document.exitFullscreen().catch(() => undefined);
      }
    };
  }, [graphFullscreen]);

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
      <div className="ticket-progress-tabbar">
        <div className="feed-tabs ticket-progress-tabs" role="tablist" aria-label="Ticket progress views">
          <button type="button" role="tab" aria-selected={tab === "list"} className={tab === "list" ? "active" : ""} onClick={() => setTab("list")}>List</button>
          <button type="button" role="tab" aria-selected={tab === "graph"} className={tab === "graph" ? "active" : ""} onClick={() => setTab("graph")}>Graph</button>
        </div>
        <button className="secondary-action compact-copy" type="button" title="Open ticket graph fullscreen" disabled={!props.view.ticketGraph.nodes.length} onClick={openGraphFullscreen}>
          <Maximize2 size={15} />
          Fullscreen graph
        </button>
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
          onEnterFullscreen={openGraphFullscreen}
          onSelect={setSelectedTicketId}
        />
      )}
      <div className={`ticket-graph-fullscreen-shell ${graphFullscreen ? "open" : ""}`} ref={fullscreenRef} aria-hidden={!graphFullscreen}>
        {graphFullscreen && (
          <TicketDependencyGraphTab
            view={props.view}
            selectedTicketId={effectiveSelectedTicketId}
            selectedTicket={selectedTicket}
            fullscreen
            onExitFullscreen={closeGraphFullscreen}
            onSelect={setSelectedTicketId}
          />
        )}
      </div>
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
