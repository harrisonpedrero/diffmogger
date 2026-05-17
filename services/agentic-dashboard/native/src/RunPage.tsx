import {
  Activity,
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileDown,
  FilePlus2,
  Pause,
  RefreshCw,
  Scissors,
  ShieldCheck,
  Terminal,
  Trash2,
  UnlockKeyhole,
  Users,
  WandSparkles,
} from "lucide-react";
import { Component, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot, RuntimeStateEvent } from "./api/backend";
import {
  listenBackendLogs,
  listenRuntimeStateEvents,
  runBackendCommand,
  runBackendCommandStreamed,
  selectTicketImportFile,
  startRuntimeStateWatch,
  stopRuntimeStateWatch,
} from "./api/backend";
import { GraphInsightsPanel } from "./GraphInsights";
import {
  buildRunModel,
  type RunAction,
  type RunConcurrencyWave,
  type RunDagCluster,
  type RunDagClusterEdge,
  type RunDagEdge,
  type RunDagNode,
  type RunOperationItem,
  type RunProgressColumnId,
  type RunProgressRow,
  type RunRoute,
  type RunSafetyRow,
} from "./runModel";
import { TicketFields } from "./TicketFields";
import {
  canSplitTicket,
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
  quality_warning_count?: number;
  source_ticket_id?: string;
  source_ticket_summary?: string;
  remap_dependency_to?: string;
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

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value
        .map((item) => asRecord(item))
        .filter((item) => Object.keys(item).length > 0)
    : [];
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];
}

function textValue(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function compactValue(value: unknown, fallback = "Not recorded"): string {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function toneForStatus(status: unknown): string {
  const value = String(status ?? "").toLowerCase();
  if (["completed", "passed", "pass", "released"].includes(value)) return "good";
  if (["failed", "blocked", "conflict", "critical"].includes(value)) return "critical";
  if (["warning", "warn", "cancelled", "expired"].includes(value)) return "warn";
  if ([
    "running",
    "queued",
    "proposed",
    "active",
    "serial_fallback",
    "awaiting_integrator_reconciliation",
    "awaiting_integrator_review",
    "waiting_validation",
    "parallel_not_worth_it",
  ].includes(value)) return "info";
  return "quiet";
}

function displayGroupMode(group: Record<string, unknown>, fallback = "Planning preview"): string {
  const payload = asRecord(group.payload);
  return compactValue(
    group.display_mode_label ||
      payload.display_mode_label ||
      group.execution_mode_label ||
      payload.execution_mode_label ||
      payload.execution_mode ||
      group.mode,
    fallback,
  );
}

function debugReason(group: Record<string, unknown>): string {
  const raw = stringList(group.raw_reason_kinds)[0];
  return compactValue(group.debug_reason_kind || raw || group.raw_reason_kind || group.reason_kind, "debug");
}

function isTicketCampaign(snapshot: ProjectSnapshot | null): boolean {
  const records = [
    asRecord(snapshot?.brief?.intake),
    asRecord(snapshot?.brief?.draft_intake),
    asRecord(snapshot?.brief?.dashboard_state),
  ];
  return records.some((record) => {
    const mode = textValue(record.campaign_mode || record.automation_run_mode).replace(/[-\s]+/g, "_");
    return mode === "bounded" || mode === "ticket_campaign";
  });
}

function ticketSnapshotFromProjectSnapshot(snapshot: ProjectSnapshot | null): TicketSnapshot | null {
  const run = asRecord(snapshot?.run);
  const state = asRecord(run.state);
  const ticketRun = asRecord(state.ticket_run);
  const tickets = normalizeTickets(ticketRun.tickets);
  if (!tickets.length) return null;
  return {
    tickets,
    summary: {
      counts: asRecord(ticketRun.counts) as Record<string, number>,
      total: typeof ticketRun.total === "number" ? ticketRun.total : tickets.length,
    },
    next: asRecord(ticketRun.next) as TicketSnapshot["next"],
    validation_issues: Array.isArray(ticketRun.validation_issues) ? ticketRun.validation_issues as TicketSnapshot["validation_issues"] : [],
  };
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

function svgText(value: string, limit: number): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > limit ? `${compact.slice(0, Math.max(0, limit - 1)).trim()}...` : compact;
}

function dagNodeLabel(node: RunDagNode): string {
  const action = (node.canonicalActionType || node.actionType).replace(/_/g, " ");
  return action.charAt(0).toUpperCase() + action.slice(1);
}

function dagNodeMeta(node: RunDagNode): string {
  return `${node.ticketId || "system"} / ${node.ownerRole} / ${node.confidenceLabel}`;
}

function dagStreamTone(state: string): string {
  if (state === "live") return "good";
  if (state === "connecting") return "info";
  if (state === "disconnected") return "warn";
  return "quiet";
}

function liveNodeIds(events: RuntimeStateEvent[], nodes: RunDagNode[]): Set<string> {
  const keys = new Set<string>();
  for (const event of events.slice(-80)) {
    const runtimeEvent = asRecord(event.runtimeEvent);
    const taskId = textValue(runtimeEvent.task_id);
    const phase = textValue(runtimeEvent.phase || runtimeEvent.event_type).toLowerCase();
    for (const node of nodes) {
      if ((taskId && node.ticketId === taskId) || (phase && [node.actionType, node.canonicalActionType, node.phase].some((value) => value.toLowerCase().includes(phase)))) {
        keys.add(node.id);
      }
    }
  }
  return keys;
}

type DagLayout = {
  width: number;
  height: number;
  nodeWidth: number;
  nodeHeight: number;
  positions: Map<string, { x: number; y: number }>;
  groupBounds: Array<{ id: string; label: string; kind: string; detail: string; x: number; y: number; width: number; height: number }>;
};

function buildDagLayout(dag: ReturnType<typeof buildRunModel>["executionDag"], selectedNodeId: string): DagLayout {
  const nodeWidth = 158;
  const nodeHeight = 72;
  const columnGap = 30;
  const rowGap = 16;
  const marginX = 24;
  const firstNodeY = 68;
  const columns = dag.columns;
  const rowIds = Array.from(new Set(dag.visibleNodes.map((node) => node.ticketId || node.id))).sort((first, second) => {
    const firstActive = dag.visibleNodes.some((node) => (node.ticketId || node.id) === first && ["running", "ready", "blocked", "failed"].includes(node.statusKind));
    const secondActive = dag.visibleNodes.some((node) => (node.ticketId || node.id) === second && ["running", "ready", "blocked", "failed"].includes(node.statusKind));
    return Number(secondActive) - Number(firstActive) || first.localeCompare(second);
  });
  if (selectedNodeId) {
    const selected = dag.visibleNodes.find((node) => node.id === selectedNodeId);
    const selectedRow = selected ? selected.ticketId || selected.id : "";
    if (selectedRow) {
      rowIds.sort((first, second) => Number(second === selectedRow) - Number(first === selectedRow));
    }
  }
  const rowIndex = new Map(rowIds.map((id, index) => [id, index]));
  const columnIndex = new Map(columns.map((column, index) => [column.id, index]));
  const positions = new Map<string, { x: number; y: number }>();
  for (const node of dag.visibleNodes) {
    positions.set(node.id, {
      x: marginX + (columnIndex.get(node.phase) ?? columns.length - 1) * (nodeWidth + columnGap),
      y: firstNodeY + (rowIndex.get(node.ticketId || node.id) ?? 0) * (nodeHeight + rowGap),
    });
  }
  const groupBounds: DagLayout["groupBounds"] = [];
  for (const group of dag.groups) {
    const points = group.nodeIds.map((id) => positions.get(id)).filter((point): point is { x: number; y: number } => Boolean(point));
    if (!points.length) continue;
    const minX = Math.min(...points.map((point) => point.x)) - 10;
    const minY = Math.min(...points.map((point) => point.y)) - 10;
    const maxX = Math.max(...points.map((point) => point.x)) + nodeWidth + 10;
    const maxY = Math.max(...points.map((point) => point.y)) + nodeHeight + 10;
    groupBounds.push({ id: group.id, label: group.label, kind: group.kind, detail: group.detail, x: minX, y: minY, width: maxX - minX, height: maxY - minY });
  }
  return {
    width: marginX * 2 + columns.length * nodeWidth + (columns.length - 1) * columnGap,
    height: firstNodeY + Math.max(1, rowIds.length) * (nodeHeight + rowGap) + 28,
    nodeWidth,
    nodeHeight,
    positions,
    groupBounds,
  };
}

function DagLiveSvg(props: {
  dag: ReturnType<typeof buildRunModel>["executionDag"];
  layout: DagLayout;
  selectedNodeId: string;
  liveIds: Set<string>;
  onSelect: (nodeId: string) => void;
}) {
  const connected = useMemo(() => {
    const ids = new Set<string>();
    if (!props.selectedNodeId) return ids;
    ids.add(props.selectedNodeId);
    for (const edge of props.dag.visibleEdges) {
      if (edge.source === props.selectedNodeId || edge.target === props.selectedNodeId) {
        ids.add(edge.source);
        ids.add(edge.target);
      }
    }
    return ids;
  }, [props.dag.visibleEdges, props.selectedNodeId]);

  function edgePath(edge: RunDagEdge): string {
    const source = props.layout.positions.get(edge.source);
    const target = props.layout.positions.get(edge.target);
    if (!source || !target) return "";
    const startX = source.x + props.layout.nodeWidth;
    const startY = source.y + props.layout.nodeHeight / 2;
    const endX = target.x;
    const endY = target.y + props.layout.nodeHeight / 2;
    const curve = Math.max(28, Math.abs(endX - startX) * 0.42);
    return `M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`;
  }

  return (
    <svg className="dag-live-svg" viewBox={`0 0 ${props.layout.width} ${props.layout.height}`} role="img" aria-label="Live Execution Graph">
      <defs>
        <marker id="dag-live-arrow" markerWidth="9" markerHeight="9" refX="7" refY="3.5" orient="auto">
          <path d="M0,0 L0,7 L8,3.5 z" />
        </marker>
      </defs>
      {props.dag.columns.map((column, index) => {
        const x = 24 + index * (props.layout.nodeWidth + 30);
        return (
          <g className="dag-phase-heading" key={column.id}>
            <text x={x} y="28">{column.label}</text>
            <line x1={x} y1="39" x2={x + props.layout.nodeWidth} y2="39" />
          </g>
        );
      })}
      <g className="dag-group-layer">
        {props.layout.groupBounds.map((group) => (
          <g className={`dag-wave dag-wave-${group.kind}`} key={group.id}>
            <rect x={group.x} y={group.y} width={group.width} height={group.height} rx="10" />
            <text x={group.x + 10} y={group.y + 16}>{group.label}</text>
            <title>{group.detail}</title>
          </g>
        ))}
      </g>
      <g className="dag-edge-layer">
        {props.dag.visibleEdges.map((edge) => {
          const path = edgePath(edge);
          if (!path) return null;
          const dimmed = connected.size > 0 && !connected.has(edge.source) && !connected.has(edge.target);
          return (
            <path
              className={`dag-edge ${edge.presentationKind} ${dimmed ? "is-dimmed" : ""}`}
              d={path}
              key={edge.id || `${edge.source}-${edge.target}-${edge.dependencyKind}`}
              markerEnd="url(#dag-live-arrow)"
            >
              <title>{edge.detail}</title>
            </path>
          );
        })}
      </g>
      <g className="dag-node-layer">
        {props.dag.visibleNodes.map((node) => {
          const position = props.layout.positions.get(node.id);
          if (!position) return null;
          const selected = props.selectedNodeId === node.id;
          const dimmed = connected.size > 0 && !connected.has(node.id);
          const live = props.liveIds.has(node.id);
          return (
            <g
              className={`dag-node status-${node.statusKind} ${selected ? "is-selected" : ""} ${dimmed ? "is-dimmed" : ""} ${live ? "is-live" : ""}`}
              key={node.id}
              transform={`translate(${position.x} ${position.y})`}
              tabIndex={0}
              role="button"
              aria-label={node.detail}
              onClick={() => props.onSelect(node.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  props.onSelect(node.id);
                }
              }}
            >
              <title>{node.detail}</title>
              <rect width={props.layout.nodeWidth} height={props.layout.nodeHeight} rx="7" />
              <circle className="dag-node-pulse" cx="14" cy="16" r="5" />
              <text className="dag-node-action" x="28" y="19">{svgText(dagNodeLabel(node), 18)}</text>
              <text className="dag-node-ticket" x="12" y="39">{svgText(dagNodeMeta(node), 24)}</text>
              <text className="dag-node-owner" x="12" y="58">{svgText(node.ownershipScope, 28)}</text>
              <text className="dag-node-status" x={props.layout.nodeWidth - 10} y="58" textAnchor="end">{node.statusKind}</text>
              {node.badges.slice(0, 3).map((badge, index) => (
                <g className={`dag-node-badge tone-${badge.tone}`} key={`${node.id}-${badge.kind}`} transform={`translate(${12 + index * 42} 63)`}>
                  <rect width="36" height="13" rx="6" />
                  <text x="18" y="10" textAnchor="middle">{svgText(badge.label, 5)}</text>
                </g>
              ))}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

type DagClusterLayout = {
  width: number;
  height: number;
  clusterWidth: number;
  clusterHeight: number;
  positions: Map<string, { x: number; y: number }>;
};

const CLUSTER_STATUS_ORDER = ["running", "ready", "blocked", "failed", "pending", "completed", "skipped"];

function buildDagClusterLayout(dag: ReturnType<typeof buildRunModel>["executionDag"], selectedClusterId: string): DagClusterLayout {
  const clusterWidth = 172;
  const clusterHeight = 88;
  const columnGap = 24;
  const rowGap = 16;
  const marginX = 24;
  const firstClusterY = 68;
  const positions = new Map<string, { x: number; y: number }>();
  let maxRows = 1;
  for (const [columnIndex, column] of dag.columns.entries()) {
    const clusters = dag.clusters
      .filter((cluster) => cluster.phase === column.id)
      .sort((first, second) => {
        if (first.id === selectedClusterId) return -1;
        if (second.id === selectedClusterId) return 1;
        return CLUSTER_STATUS_ORDER.indexOf(first.statusKind) - CLUSTER_STATUS_ORDER.indexOf(second.statusKind) || second.nodeCount - first.nodeCount;
      });
    maxRows = Math.max(maxRows, clusters.length);
    clusters.forEach((cluster, rowIndex) => {
      positions.set(cluster.id, {
        x: marginX + columnIndex * (clusterWidth + columnGap),
        y: firstClusterY + rowIndex * (clusterHeight + rowGap),
      });
    });
  }
  return {
    width: marginX * 2 + dag.columns.length * clusterWidth + (dag.columns.length - 1) * columnGap,
    height: firstClusterY + maxRows * (clusterHeight + rowGap) + 28,
    clusterWidth,
    clusterHeight,
    positions,
  };
}

function clusterLiveIds(liveIds: Set<string>, clusters: RunDagCluster[]): Set<string> {
  const ids = new Set<string>();
  for (const cluster of clusters) {
    if (cluster.nodeIds.some((nodeId) => liveIds.has(nodeId))) ids.add(cluster.id);
  }
  return ids;
}

function clusterEdgePath(edge: RunDagClusterEdge, layout: DagClusterLayout): string {
  const source = layout.positions.get(edge.source);
  const target = layout.positions.get(edge.target);
  if (!source || !target) return "";
  const startX = source.x + layout.clusterWidth;
  const startY = source.y + layout.clusterHeight / 2;
  const endX = target.x;
  const endY = target.y + layout.clusterHeight / 2;
  const curve = Math.max(30, Math.abs(endX - startX) * 0.42);
  return `M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`;
}

function DagClusterSvg(props: {
  dag: ReturnType<typeof buildRunModel>["executionDag"];
  layout: DagClusterLayout;
  selectedClusterId: string;
  liveClusterIds: Set<string>;
  onSelect: (clusterId: string) => void;
}) {
  const connected = useMemo(() => {
    const ids = new Set<string>();
    if (!props.selectedClusterId) return ids;
    ids.add(props.selectedClusterId);
    for (const edge of props.dag.clusterEdges) {
      if (edge.source === props.selectedClusterId || edge.target === props.selectedClusterId) {
        ids.add(edge.source);
        ids.add(edge.target);
      }
    }
    return ids;
  }, [props.dag.clusterEdges, props.selectedClusterId]);

  return (
    <svg className="dag-live-svg dag-cluster-svg" viewBox={`0 0 ${props.layout.width} ${props.layout.height}`} role="img" aria-label="Multi-resolution Execution Graph">
      <defs>
        <marker id="dag-cluster-arrow" markerWidth="9" markerHeight="9" refX="7" refY="3.5" orient="auto">
          <path d="M0,0 L0,7 L8,3.5 z" />
        </marker>
      </defs>
      {props.dag.columns.map((column, index) => {
        const x = 24 + index * (props.layout.clusterWidth + 24);
        return (
          <g className="dag-phase-heading" key={column.id}>
            <text x={x} y="28">{column.label}</text>
            <line x1={x} y1="39" x2={x + props.layout.clusterWidth} y2="39" />
          </g>
        );
      })}
      <g className="dag-edge-layer">
        {props.dag.clusterEdges.map((edge) => {
          const path = clusterEdgePath(edge, props.layout);
          if (!path) return null;
          const dimmed = connected.size > 0 && !connected.has(edge.source) && !connected.has(edge.target);
          return (
            <path
              className={`dag-edge ${edge.presentationKind} ${dimmed ? "is-dimmed" : ""}`}
              d={path}
              key={edge.id}
              markerEnd="url(#dag-cluster-arrow)"
              strokeWidth={Math.min(5, 1.2 + edge.count / 16)}
            >
              <title>{edge.detail}</title>
            </path>
          );
        })}
      </g>
      <g className="dag-node-layer">
        {props.dag.clusters.map((cluster) => {
          const position = props.layout.positions.get(cluster.id);
          if (!position) return null;
          const selected = props.selectedClusterId === cluster.id;
          const dimmed = connected.size > 0 && !connected.has(cluster.id);
          const live = props.liveClusterIds.has(cluster.id);
          const heatStatuses = CLUSTER_STATUS_ORDER.filter((status) => cluster.statusCounts[status as keyof typeof cluster.statusCounts] > 0);
          let heatX = 10;
          return (
            <g
              className={`dag-cluster status-${cluster.statusKind} ${selected ? "is-selected" : ""} ${dimmed ? "is-dimmed" : ""} ${live ? "is-live" : ""}`}
              key={cluster.id}
              transform={`translate(${position.x} ${position.y})`}
              tabIndex={0}
              role="button"
              aria-label={cluster.detail}
              onClick={() => props.onSelect(cluster.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  props.onSelect(cluster.id);
                }
              }}
            >
              <title>{cluster.detail}</title>
              <rect className="dag-cluster-shell" width={props.layout.clusterWidth} height={props.layout.clusterHeight} rx="8" />
              <circle className="dag-node-pulse" cx="14" cy="16" r="5" />
              <text className="dag-node-action" x="28" y="19">{svgText(cluster.label, 20)}</text>
              <text className="dag-node-ticket" x="10" y="40">{cluster.nodeCount} nodes / {svgText(cluster.ownerSamples.join(", ") || "mixed owners", 20)}</text>
              <text className="dag-node-owner" x="10" y="59">{svgText(cluster.ticketSamples.join(", ") || "system", 28)}</text>
              <g className="dag-cluster-heat" transform="translate(0 70)">
                {heatStatuses.map((status) => {
                  const count = cluster.statusCounts[status as keyof typeof cluster.statusCounts];
                  const width = Math.max(8, Math.round((count / Math.max(1, cluster.nodeCount)) * 148));
                  const x = heatX;
                  heatX += width + 2;
                  return <rect className={`status-${status}`} x={x} y="0" width={width} height="8" rx="4" key={`${cluster.id}-${status}`} />;
                })}
              </g>
              {(cluster.activeGroupNodeCount > 0 || cluster.plannedGroupNodeCount > 0) && (
                <text className="dag-cluster-wave-count" x={props.layout.clusterWidth - 10} y="59" textAnchor="end">
                  {cluster.activeGroupNodeCount ? `${cluster.activeGroupNodeCount} live` : `${cluster.plannedGroupNodeCount} wave`}
                </text>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}

class LiveGraphErrorBoundary extends Component<{ resetKey: string; children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidUpdate(previous: { resetKey: string }) {
    if (previous.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }
  render() {
    if (this.state.hasError) {
      return (
        <article className="panel run-dag-panel" aria-label="Execution DAG Topology">
          <div className="dag-empty-state critical" role="alert">
            <AlertTriangle size={18} />
            <strong>Execution DAG Topology could not render</strong>
            <p>The rest of the dashboard is still available. Refreshing the snapshot will retry the topology renderer.</p>
          </div>
        </article>
      );
    }
    return this.props.children;
  }
}

export function AutomationActivityGraphPanel(props: {
  model: ReturnType<typeof buildRunModel>;
  liveEvents: RuntimeStateEvent[];
  streamState: "snapshot" | "connecting" | "live" | "disconnected";
  eventCount: number;
}) {
  const dag = props.model.executionDag;
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const abstracted = dag.abstraction.enabled;
  const selectedNode = abstracted ? undefined : dag.nodes.find((node) => node.id === selectedNodeId) ?? dag.visibleNodes[0];
  const selectedCluster = abstracted ? dag.clusters.find((cluster) => cluster.id === selectedNodeId) ?? dag.clusters[0] : undefined;
  const layout = useMemo(() => buildDagLayout(dag, selectedNodeId), [dag.digest, dag.renderMode, dag.renderLimit.visibleNodeCount, dag.renderLimit.visibleEdgeCount, selectedNodeId]);
  const clusterLayout = useMemo(() => buildDagClusterLayout(dag, selectedNodeId), [dag.digest, dag.abstraction.clusterCount, dag.abstraction.bundledEdgeCount, selectedNodeId]);
  const liveIds = useMemo(() => liveNodeIds(props.liveEvents, abstracted ? dag.nodes : dag.visibleNodes), [props.liveEvents, abstracted, dag.nodes, dag.visibleNodes]);
  const liveClusterIdSet = useMemo(() => clusterLiveIds(liveIds, dag.clusters), [liveIds, dag.clusters]);
  const streamLabel = props.streamState === "live" ? "Live stream" : props.streamState === "connecting" ? "Connecting" : props.streamState === "disconnected" ? "Snapshot mode" : "Snapshot";
  const graphTone = dag.summary.blocked || dag.summary.failed ? "warn" : dag.summary.running ? "info" : dag.summary.ready ? "good" : "quiet";

  return (
    <LiveGraphErrorBoundary resetKey={`${dag.digest}-${dag.renderMode}`}>
      <article className="panel run-dag-panel live-dag-panel" aria-label="Execution DAG Topology">
        <div className="panel-heading-row">
          <div>
            <h2>Execution DAG Topology</h2>
            <p>{dag.hasData ? `${dag.authority || "runtime"} / ${dag.digest || "digest pending"} · dependencies and ownership` : "No topology data for this run"}</p>
          </div>
          <div className="dag-heading-pills">
            <RunTonePill tone={dagStreamTone(props.streamState)}><Activity size={12} />{streamLabel}</RunTonePill>
            <RunTonePill tone={graphTone}>{dag.summary.total} nodes</RunTonePill>
          </div>
        </div>
        <div className="dag-summary-strip" aria-label="Topology status summary">
          <DetailRow label="Ready" value={dag.summary.ready} />
          <DetailRow label="Running" value={dag.summary.running} />
          <DetailRow label="Blocked" value={dag.summary.blocked + dag.summary.failed} />
          <DetailRow label="Completed" value={dag.summary.completed + dag.summary.skipped} />
          <DetailRow label="Planned waves" value={dag.parallel.proposedGroups} />
          <DetailRow label="Running groups" value={dag.parallel.activeGroups} />
          <DetailRow label={abstracted ? "Clusters" : "Visible"} value={abstracted ? dag.abstraction.clusterCount : dag.renderLimit.visibleNodeCount} />
          <DetailRow label={abstracted ? "Bundled edges" : "Edges"} value={abstracted ? dag.abstraction.bundledEdgeCount : dag.renderLimit.visibleEdgeCount} />
        </div>
        {dag.hasData && abstracted ? (
          <div className="dag-live-layout">
            <div className="dag-scroll-frame">
              <DagClusterSvg
                dag={dag}
                layout={clusterLayout}
                selectedClusterId={selectedCluster?.id ?? ""}
                liveClusterIds={liveClusterIdSet}
                onSelect={setSelectedNodeId}
              />
            </div>
            <aside className="dag-detail-rail" aria-label="Selected activity cluster details">
              {selectedCluster ? (
                <>
                  <div className={`dag-detail-card status-${selectedCluster.statusKind}`}>
                    <strong>{selectedCluster.label}</strong>
                    <span>{selectedCluster.nodeCount} nodes / {selectedCluster.actionSamples.join(", ") || "mixed actions"}</span>
                    <p>{selectedCluster.detail}</p>
                  </div>
                  <div className="dag-badge-list">
                    {CLUSTER_STATUS_ORDER.filter((status) => selectedCluster.statusCounts[status as keyof typeof selectedCluster.statusCounts] > 0).map((status) => (
                      <span className={`dag-badge tone-${toneForStatus(status)}`} key={`${selectedCluster.id}-${status}`}>
                        {status}: {selectedCluster.statusCounts[status as keyof typeof selectedCluster.statusCounts]}
                      </span>
                    ))}
                    {selectedCluster.activeGroupNodeCount > 0 && <span className="dag-badge tone-good">{selectedCluster.activeGroupNodeCount} active group nodes</span>}
                    {selectedCluster.plannedGroupNodeCount > 0 && <span className="dag-badge tone-info">{selectedCluster.plannedGroupNodeCount} planned wave nodes</span>}
                  </div>
                </>
              ) : (
                <p className="empty-copy">Select a cluster to inspect its aggregate runtime evidence.</p>
              )}
            </aside>
          </div>
        ) : dag.hasData ? (
          <div className="dag-live-layout">
            <div className="dag-scroll-frame">
              <DagLiveSvg dag={dag} layout={layout} selectedNodeId={selectedNode?.id ?? ""} liveIds={liveIds} onSelect={setSelectedNodeId} />
            </div>
            <aside className="dag-detail-rail" aria-label="Selected activity node details">
              {selectedNode ? (
                <>
                  <div className={`dag-detail-card status-${selectedNode.statusKind}`}>
                    <strong>{selectedNode.ticketId || selectedNode.id}</strong>
                    <span>{dagNodeLabel(selectedNode)} / {selectedNode.ownerRole}</span>
                    <p>{selectedNode.detail}</p>
                  </div>
                  <div className="dag-badge-list">
                    {selectedNode.badges.length ? selectedNode.badges.map((badge) => (
                      <span className={`dag-badge tone-${badge.tone}`} key={`${selectedNode.id}-${badge.kind}`}>{badge.label}</span>
                    )) : <span className="dag-badge tone-quiet">no badges</span>}
                  </div>
                </>
              ) : (
                <p className="empty-copy">Select a node to inspect its runtime evidence.</p>
              )}
            </aside>
          </div>
        ) : (
          <div className="dag-empty-state">
            <Activity size={18} />
            <strong>No topology data for this run</strong>
            <p>Fresh snapshots will show execution DAG nodes and edges here once the runtime has materialized scheduler state.</p>
          </div>
        )}
        {dag.hasData && (
          <div className="dag-legend" aria-label="Activity status legend">
            {["pending", "ready", "running", "completed", "blocked", "failed", "skipped"].map((status) => (
              <span className={`dag-legend-item status-${status}`} key={status}>
                <i />
                {status}
              </span>
            ))}
            <span className="dag-legend-item"><i />{dag.renderMode} mode</span>
            {abstracted && <span className="dag-legend-item"><i />{dag.abstraction.level} lens</span>}
            <span className="dag-legend-item"><i />{props.eventCount} live events</span>
            {dag.renderLimit.hiddenNodeCount > 0 && <span className="dag-legend-item"><i />{dag.renderLimit.hiddenNodeCount} hidden nodes</span>}
          </div>
        )}
      </article>
    </LiveGraphErrorBoundary>
  );
}

const PROGRESS_MATRIX_COLUMNS: Array<{ id: RunProgressColumnId; label: string }> = [
  { id: "scope", label: "Scope" },
  { id: "build", label: "Build" },
  { id: "review", label: "Review" },
  { id: "validate", label: "Validate" },
  { id: "integrate", label: "Integrate" },
  { id: "done", label: "Done" },
];

function operationSourceLabel(item: RunOperationItem): string {
  return [item.source.replace(/_/g, " "), item.groupId ? `group ${item.groupId}` : ""].filter(Boolean).join(" / ");
}

function OperationsCockpitPanel(props: { model: ReturnType<typeof buildRunModel> }) {
  const operations = props.model.operations;
  return (
    <article className="panel operations-cockpit-panel" aria-label="Operations cockpit">
      <div className="panel-heading-row">
        <div>
          <h2>Operations Cockpit</h2>
          <p>Live runtime lanes, next scheduler unlock, and serialized integration queue.</p>
        </div>
        <RunTonePill tone={operations.nextUnlock.tone}>{operations.nextUnlock.source.replace(/_/g, " ")}</RunTonePill>
      </div>

      <div className="operations-cockpit-grid">
        <section className="operations-card running-now-card" aria-label="Running Now">
          <h3>Running Now</h3>
          <div className="operations-lane-list">
            {operations.runningNow.map((item) => (
              <div className={`operations-lane ${item.tone}`} key={item.id}>
                <div>
                  <strong>{item.role}</strong>
                  <span>{item.action.replace(/_/g, " ")}{item.taskId ? ` / ${item.taskId}` : ""}</span>
                </div>
                <RunTonePill tone={item.tone}>{item.status}</RunTonePill>
                <p>{item.detail}</p>
                <em>{operationSourceLabel(item)}</em>
              </div>
            ))}
          </div>
        </section>

        <section className={`operations-card next-unlock-card ${operations.nextUnlock.tone}`} aria-label="Next unlock">
          <h3>Next Unlock</h3>
          <strong>{operations.nextUnlock.title}</strong>
          <p>{operations.nextUnlock.detail}</p>
          <div className="operations-meta-line">
            <span>{operations.nextUnlock.role}</span>
            <span>{operations.nextUnlock.action || "scheduler"}</span>
            {operations.nextUnlock.taskId && <span>{operations.nextUnlock.taskId}</span>}
          </div>
        </section>

        <section className={`operations-card integration-backlog-card ${operations.integrationBacklog.tone}`} aria-label="Integration backlog">
          <h3>Integration Backlog</h3>
          <div className="operations-backlog-counts">
            <DetailRow label="Queued" value={operations.integrationBacklog.queuedCount} />
            <DetailRow label="Safe" value={operations.integrationBacklog.safeCount} />
            <DetailRow label="Blocked" value={operations.integrationBacklog.blockedCount} />
          </div>
          <p>{operations.integrationBacklog.summary}</p>
          <div className="operations-chip-row">
            {operations.integrationBacklog.patchSamples.length ? operations.integrationBacklog.patchSamples.map((patch) => (
              <code key={patch}>{patch}</code>
            )) : <span>No queued patches</span>}
          </div>
        </section>
      </div>

      <div className="role-action-explainer" aria-label="Role action mapping">
        <span><strong>planner</strong> scope/decompose</span>
        <span><strong>builder</strong> build/repair</span>
        <span><strong>hardener</strong> review/validate/audit</span>
        <span><strong>integrator</strong> integrate</span>
      </div>
    </article>
  );
}

function ProgressMatrixPanel(props: { rows: RunProgressRow[] }) {
  return (
    <article className="panel progress-matrix-panel" aria-label="Progress matrix">
      <div className="panel-heading-row">
        <div>
          <h2>Progress Matrix</h2>
          <p>Per-ticket state from execution DAG action nodes.</p>
        </div>
        <RunTonePill tone={props.rows.length ? "info" : "quiet"}>{props.rows.length} rows</RunTonePill>
      </div>
      {props.rows.length ? (
        <div className="progress-matrix-scroll">
          <table className="progress-matrix-table">
            <thead>
              <tr>
                <th>Work item</th>
                {PROGRESS_MATRIX_COLUMNS.map((column) => <th key={column.id}>{column.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {props.rows.map((row) => (
                <tr className={row.compatibility ? "compatibility" : ""} key={row.taskId}>
                  <th>
                    <strong>{row.label}</strong>
                    <span>{row.compatibility ? row.taskId : row.summary}</span>
                    {row.compatibility && <em>compatibility fallback</em>}
                  </th>
                  {PROGRESS_MATRIX_COLUMNS.map((column) => {
                    const cell = row.cells[column.id];
                    return (
                      <td key={`${row.taskId}-${column.id}`}>
                        {cell ? (
                          <span className={`progress-cell status-${cell.statusKind}`} title={cell.detail}>
                            <strong>{cell.statusKind}</strong>
                            <em>{cell.role}</em>
                          </span>
                        ) : (
                          <span className="progress-cell empty">
                            <strong>none</strong>
                            <em>not planned</em>
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="matrix-empty-state">
          <strong>No progress rows yet</strong>
          <p>Fresh snapshots will populate ticket/work-item progress after the execution DAG is materialized.</p>
        </div>
      )}
    </article>
  );
}

function waveLabel(wave: RunConcurrencyWave): string {
  const parts = [
    wave.mode.replace(/_/g, " "),
    `${wave.itemCount} item${wave.itemCount === 1 ? "" : "s"}`,
    wave.owners.length ? wave.owners.join(", ") : "",
  ].filter(Boolean);
  return parts.join(" / ");
}

function ConcurrencyStripPanel(props: { waves: RunConcurrencyWave[] }) {
  return (
    <article className="panel concurrency-strip-panel" aria-label="Concurrency strip">
      <div className="panel-heading-row">
        <div>
          <h2>Concurrency Strip</h2>
          <p>Planned waves, active groups, blocked candidates, and serialized integration.</p>
        </div>
        <RunTonePill tone={props.waves.some((wave) => wave.kind === "active") ? "info" : props.waves.length ? "quiet" : "quiet"}>
          {props.waves.length} waves
        </RunTonePill>
      </div>
      <div className="concurrency-wave-list">
        {props.waves.length ? props.waves.map((wave) => (
          <div className={`concurrency-wave ${wave.kind} ${wave.tone}`} key={`${wave.kind}-${wave.id}`}>
            <div className="concurrency-wave-main">
              <strong>{wave.label}</strong>
              <span>{wave.id}</span>
            </div>
            <RunTonePill tone={wave.tone}>{wave.status}</RunTonePill>
            <code>{wave.kind}</code>
            <p>{wave.detail}</p>
            <div className="concurrency-wave-meta">
              <span>{waveLabel(wave)}</span>
              {wave.tasks.length > 0 && <span>tasks {wave.tasks.join(", ")}</span>}
              {wave.leases.length > 0 && <span>leases {wave.leases.join(", ")}</span>}
            </div>
          </div>
        )) : (
          <div className="matrix-empty-state">
            <strong>No concurrency waves recorded</strong>
            <p>Scheduler snapshots will show proposed, active, blocked, or integration waves here.</p>
          </div>
        )}
      </div>
    </article>
  );
}

function firstGroupId(groups: Array<Record<string, unknown>>, mode: string): string {
  for (const group of groups) {
    const payload = asRecord(group.payload);
    const executionMode = textValue(payload.execution_mode || group.mode);
    const id = textValue(group.execution_group_id);
    if (id && (executionMode === mode || group.mode === mode)) return id;
  }
  return textValue(groups[0]?.execution_group_id);
}

function groupItems(group: Record<string, unknown>): Array<Record<string, unknown>> {
  return asRecords(group.items).slice(0, 4);
}

function leaseTarget(lease: Record<string, unknown>): string {
  return compactValue(lease.path || lease.scope_node_id || lease.name || lease.lease_id);
}

function leaseLooksStale(lease: Record<string, unknown>): boolean {
  const status = String(lease.status ?? "").toLowerCase();
  if (["expired", "stale"].includes(status)) return true;
  const expiresAt = textValue(lease.expires_at);
  if (!expiresAt) return false;
  const timestamp = new Date(expiresAt).getTime();
  return Number.isFinite(timestamp) && timestamp < Date.now();
}

function ParallelExecutionPanel(props: {
  snapshot: ProjectSnapshot | null;
  details: Record<string, unknown> | null;
  busy: boolean;
  onLoad: () => void;
  onStartReadOnly: (groupId: string) => void;
  onStartValidation: () => void;
  onCancelGroup: (groupId: string) => void;
  onReleaseLease: (leaseId: string) => void;
  onExportBundle: () => void;
}) {
  const state = asRecord(props.snapshot?.run?.state);
  const details = asRecord(props.details);
  const parallelSummary = asRecord(details.parallelization_summary || state.parallelization_summary);
  const parallelExecution = asRecord(details.parallel_execution || state.parallel_execution);
  const proposed = [
    ...asRecords(parallelExecution.proposed_groups),
    ...asRecords(details.proposed_execution_group_rows),
    ...asRecords(state.proposed_execution_groups),
  ];
  const activeGroups = [
    ...asRecords(parallelExecution.running_groups),
    ...asRecords(details.active_execution_groups),
    ...asRecords(state.active_execution_groups),
  ];
  const recentGroups = [
    ...asRecords(parallelExecution.recently_completed_groups),
    ...asRecords(details.recent_execution_groups),
    ...asRecords(state.recent_execution_groups),
    ...asRecords(state.recently_completed_execution_groups),
  ].slice(0, 4);
  const skipped = [
    ...asRecords(details.blocked_parallel_candidates),
    ...asRecords(state.blocked_parallel_candidates),
  ].slice(0, 6);
  const whyNotParallel = asRecord(
    details.why_not_parallel ||
    state.why_not_parallel ||
    asRecord(state.scheduler_parallel_dry_run).why_not_parallel,
  );
  const whyReasonGroups = asRecords(whyNotParallel.reason_groups).slice(0, 5);
  const whyNextImprovements = asRecords(whyNotParallel.next_improvements).slice(0, 3);
  const activeLeases = [
    ...asRecords(details.active_leases),
    ...asRecords(state.active_leases),
  ].slice(0, 6);
  const conflictingLeases = [
    ...asRecords(details.conflicting_leases),
    ...asRecords(state.conflicting_leases),
  ].slice(0, 4);
  const contracts = asRecords(details.worker_contracts).slice(0, 5);
  const workerReportsModel = asRecord(details.worker_reports);
  const completedWorkerReports = [
    ...asRecords(workerReportsModel.completed_worker_reports),
    ...asRecords(state.completed_worker_reports),
  ].slice(0, 5);
  const validationJobsModel = asRecord(details.validation_jobs || state.validation_job_summary);
  const validationSummary = asRecord(validationJobsModel.validation_job_summary || state.validation_job_summary);
  const validationJobs = [
    ...asRecords(validationJobsModel.active_validation_jobs),
    ...asRecords(state.active_validation_jobs),
    ...asRecords(validationSummary.latest),
  ].slice(0, 5);
  const integrationBacklog = [
    ...asRecords(details.integration_backlog_from_parallel_workers),
    ...asRecords(state.integration_backlog_from_parallel_workers),
  ].slice(0, 6);
  const integrationPreflight = asRecord(
    details.worker_patch_integration_preflight || state.worker_patch_integration_preflight,
  );
  const integrationPreflightOrder = asRecords(integrationPreflight.safe_order).slice(0, 5);
  const integrationPreflightConflicts = asRecords(integrationPreflight.likely_conflicts).slice(0, 4);
  const staleLeaseWarnings = activeLeases
    .filter(leaseLooksStale)
    .map((lease) => ({
      kind: "stale_lease",
      severity: "warn",
      message: `Stale lease: ${leaseTarget(lease)}`,
    }));
  const warnings: Array<Record<string, unknown>> = [
    ...staleLeaseWarnings,
    ...asRecords(details.warnings),
    ...asRecords(state.stale_graph_warnings),
    ...asRecords(state.budget_exhaustion_reasons).map((item) => ({
      kind: "budget_exhausted",
      severity: "warn",
      message: item.reason,
    })),
  ].slice(0, 6);
  const readOnlyGroupId = firstGroupId(proposed, "read_only");
  const activeCounts = asRecord(state.active_parallel_counts);
  const budgetStatus = asRecord(state.validation_budget_status);

  return (
    <article className="panel parallel-execution-panel" aria-label="Parallel execution">
      <div className="panel-heading-row">
        <div>
          <h2>Parallel Execution</h2>
          <p>{compactValue(parallelSummary.display_mode_label || parallelSummary.display_mode, "Planning preview")} · {numberValue(parallelSummary.group_count)} proposed groups · {activeGroups.length} running · {recentGroups.length} recently completed</p>
        </div>
        <div className="inline-actions">
          <button className="icon-text-button" onClick={props.onLoad} disabled={props.busy}>
            <RefreshCw size={14} />
            Refresh Details
          </button>
          <button className="icon-text-button" onClick={props.onExportBundle} disabled={props.busy}>
            <FileDown size={14} />
            Export Debug Bundle
          </button>
        </div>
      </div>

      <div className="parallel-summary-grid">
        <DetailRow label="Proposed" value={numberValue(parallelSummary.group_count)} />
        <DetailRow label="Recently completed" value={recentGroups.length} />
        <DetailRow label="Active jobs" value={numberValue(activeCounts.active_validation_jobs)} />
        <DetailRow label="Running workers" value={numberValue(activeCounts.active_read_only_workers) + numberValue(activeCounts.active_write_workers)} />
      </div>

      {warnings.length > 0 && (
        <div className="parallel-warning-list">
          {warnings.map((warning, index) => (
            <div className={`parallel-warning ${toneForStatus(warning.severity || warning.reason_kind)}`} key={`${warning.kind ?? "warning"}-${index}`}>
              <AlertTriangle size={14} />
              <span>{compactValue(warning.message || warning.reason || warning.kind, "Parallel warning")}</span>
            </div>
          ))}
        </div>
      )}

      <div className="parallel-control-strip">
        <button className="secondary-action" disabled={props.busy || !readOnlyGroupId} onClick={() => props.onStartReadOnly(readOnlyGroupId)}>
          <Users size={14} />
          Start Read-Only Group
        </button>
        <button className="secondary-action" disabled={props.busy || budgetStatus.allowed === false} onClick={props.onStartValidation}>
          <ShieldCheck size={14} />
          Start Validation Group
        </button>
      </div>

      <section className="parallel-section">
        <h3>Why Not Parallel?</h3>
        <div className="parallel-row-list">
          {whyReasonGroups.length ? whyReasonGroups.map((group, index) => (
            <div className="parallel-row compact" key={`${group.reason_kind ?? "reason"}-${index}`}>
              <div>
                <strong>{compactValue(group.label || group.reason_kind)}</strong>
                <span>{numberValue(group.count)} candidate(s) · {compactValue(group.human_summary || group.display_reason || group.next_action)}</span>
              </div>
              <RunTonePill tone={toneForStatus(group.reason_kind)}>{debugReason(group)}</RunTonePill>
            </div>
          )) : (
            <div className="parallel-row compact">
              <div>
                <strong>{compactValue(whyNotParallel.status, "clear")}</strong>
                <span>{compactValue(whyNotParallel.summary, "No parallel candidate reasons recorded.")}</span>
              </div>
              <RunTonePill tone="good">clear</RunTonePill>
            </div>
          )}
          {whyNextImprovements.map((item, index) => (
            <div className="parallel-row compact" key={`next-improvement-${index}`}>
              <div>
                <strong>{compactValue(item.improvement_kind || item.reason_kind, "next improvement")}</strong>
                <span>{compactValue(item.next_action)}</span>
              </div>
              <RunTonePill tone="info">{numberValue(item.count)} candidate(s)</RunTonePill>
            </div>
          ))}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Proposed groups</h3>
        <div className="parallel-row-list">
          {proposed.length ? proposed.slice(0, 4).map((group, index) => {
            const id = textValue(group.execution_group_id, `group-${index}`);
            return (
              <div className="parallel-row" key={`${id}-${index}`}>
                <div>
                  <strong>{id}</strong>
                  <span>{displayGroupMode(group)} · {groupItems(group).length || numberValue(group.item_count)} item(s)</span>
                </div>
                <RunTonePill tone={toneForStatus(group.status || "proposed")}>{compactValue(group.status || "proposed")}</RunTonePill>
                <p>{compactValue(group.reason || asRecord(group.payload).why_together, "No grouping reason recorded.")}</p>
                {groupItems(group).map((item) => (
                  <code key={textValue(item.item_id) || textValue(item.task_id)}>
                    {compactValue(item.task_id || item.graph_task_node_id)} · {compactValue(item.owner_role)} · {compactValue(item.action_kind)}
                  </code>
                ))}
              </div>
            );
          }) : <p className="empty-copy">No proposed groups recorded yet.</p>}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Running groups</h3>
        <div className="parallel-row-list">
          {activeGroups.length ? activeGroups.map((group, index) => {
            const id = textValue(group.execution_group_id, `active-${index}`);
            return (
              <div className="parallel-row" key={id}>
                <div>
                  <strong>{id}</strong>
                  <span>{displayGroupMode(group, "Runtime work")} · {compactValue(group.selected_by)}</span>
                </div>
                <RunTonePill tone="info">{compactValue(group.status, "running")}</RunTonePill>
                <button className="ledger-action" disabled={props.busy} onClick={() => props.onCancelGroup(id)}>
                  <Ban size={14} />
                  Cancel
                </button>
              </div>
            );
          }) : <p className="empty-copy">No active execution groups.</p>}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Validation jobs</h3>
        <div className="parallel-row-list">
          <div className="parallel-row compact">
            <div>
              <strong>{compactValue(validationSummary.aggregate_status, "not_run")}</strong>
              <span>{numberValue(validationSummary.job_count)} total · {numberValue(validationSummary.active_count)} active</span>
            </div>
            <RunTonePill tone={toneForStatus(validationSummary.aggregate_status)}>{compactValue(validationSummary.aggregate_status, "not_run")}</RunTonePill>
          </div>
          {validationJobs.map((job, index) => (
            <div className="parallel-row compact" key={textValue(job.job_id, `validation-${index}`)}>
              <div>
                <strong>{compactValue(job.gate_id || job.job_id)}</strong>
                <span>{compactValue(job.command)} </span>
              </div>
              <RunTonePill tone={toneForStatus(job.status)}>{compactValue(job.status)}</RunTonePill>
            </div>
          ))}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Worker reports</h3>
        <div className="parallel-row-list">
          {completedWorkerReports.length ? completedWorkerReports.map((report, index) => (
            <div className="parallel-row compact" key={textValue(report.worker_id || report.report_id, `worker-report-${index}`)}>
              <div>
                <strong>{compactValue(report.worker_id || report.report_id)}</strong>
                <span>{compactValue(report.disposition_summary || report.failure_reason || report.report_artifact_id, "Worker report completed.")}</span>
              </div>
              <RunTonePill tone={toneForStatus(report.disposition_status || report.status)}>{compactValue(report.disposition_label || report.disposition_status || report.status)}</RunTonePill>
            </div>
          )) : <p className="empty-copy">No completed worker reports recorded yet.</p>}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Leases</h3>
        <div className="parallel-row-list">
          {activeLeases.length ? activeLeases.map((lease, index) => {
            const id = textValue(lease.lease_id, `lease-${index}`);
            return (
              <div className="parallel-row compact" key={id}>
                <div>
                  <strong>{leaseTarget(lease)}</strong>
                  <span>{compactValue(lease.owner_role)} · {compactValue(lease.expires_at, "no expiry")}</span>
                </div>
                <button className="ledger-action" disabled={props.busy} onClick={() => props.onReleaseLease(id)}>
                  <UnlockKeyhole size={14} />
                  Release
                </button>
              </div>
            );
          }) : <p className="empty-copy">No active leases.</p>}
          {conflictingLeases.map((conflict, index) => (
            <div className="parallel-warning critical" key={`conflict-${index}`}>
              <AlertTriangle size={14} />
              <span>{compactValue(conflict.reason || conflict.overlap_reason, "Lease conflict detected.")}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Worker contracts</h3>
        <div className="parallel-row-list">
          {contracts.length ? contracts.map((contract, index) => (
            <div className="parallel-row compact" key={textValue(contract.contract_id, `contract-${index}`)}>
              <div>
                <strong>{compactValue(contract.worker_id || contract.contract_id)}</strong>
                <span>{compactValue(contract.ownership_scope || asRecords(contract.allowed_paths).join(", "), "read-only contract")}</span>
              </div>
              <RunTonePill tone="info">{contract.no_spawn_workers === false ? "spawn allowed" : "no spawn"}</RunTonePill>
            </div>
          )) : <p className="empty-copy">No worker contracts recorded yet.</p>}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Integration backlog</h3>
        <div className="parallel-row-list">
          <div className="parallel-row compact">
            <div>
              <strong>{numberValue(integrationPreflight.safe_count)} safe patch(es)</strong>
              <span>{numberValue(integrationPreflight.likely_conflict_count)} conflict risk · {numberValue(integrationPreflight.stale_base_count)} stale base · {numberValue(integrationPreflight.missing_metadata_count)} missing metadata</span>
            </div>
            <RunTonePill tone={numberValue(integrationPreflight.likely_conflict_count) > 0 ? "warn" : "good"}>preflight</RunTonePill>
          </div>
          {integrationPreflightOrder.map((item, index) => (
            <div className="parallel-row compact" key={`preflight-order-${textValue(item.patch_id, String(index))}`}>
              <div>
                <strong>{compactValue(item.patch_id)}</strong>
                <span>order {numberValue(item.safe_order)} · {compactValue(item.reason_kind || item.status)}</span>
              </div>
              <RunTonePill tone={toneForStatus(item.status)}>{compactValue(item.status)}</RunTonePill>
            </div>
          ))}
          {integrationPreflightConflicts.map((item, index) => (
            <div className="parallel-warning" key={`preflight-conflict-${textValue(item.patch_id, String(index))}`}>
              <AlertTriangle size={14} />
              <span>{compactValue(item.patch_id)} overlaps {stringList(item.conflict_patch_ids).join(", ") || compactValue(item.reason_kind, "another patch")}</span>
            </div>
          ))}
          {integrationBacklog.length ? integrationBacklog.map((patch, index) => (
            <div className="parallel-row compact" key={textValue(patch.patch_id, `patch-${index}`)}>
              <div>
                <strong>{compactValue(patch.patch_id)}</strong>
                <span>{asRecords(patch.changed_files).length ? `${asRecords(patch.changed_files).length} file(s)` : compactValue(patch.manifest_path)}</span>
              </div>
              <RunTonePill tone={toneForStatus(patch.status)}>{compactValue(patch.status)}</RunTonePill>
            </div>
          )) : <p className="empty-copy">No parallel worker patches are queued.</p>}
        </div>
      </section>

      <section className="parallel-section">
        <h3>Skipped candidates</h3>
        <div className="parallel-row-list">
          {skipped.length ? skipped.map((candidate, index) => (
            <div className="parallel-row compact" key={`${candidate.task_id ?? candidate.graph_task_node_id ?? index}`}>
              <div>
                <strong>{compactValue(candidate.task_id || candidate.graph_task_node_id)}</strong>
                <span>{compactValue(candidate.reason || candidate.reason_kind)}</span>
              </div>
              <RunTonePill tone="warn">skipped</RunTonePill>
            </div>
          )) : <p className="empty-copy">No skipped parallel candidates.</p>}
        </div>
      </section>

      {recentGroups.length > 0 && (
        <section className="parallel-section">
          <h3>Recently Completed</h3>
          <div className="parallel-row-list">
            {recentGroups.map((group, index) => (
              <div className="parallel-row compact" key={textValue(group.execution_group_id, `recent-${index}`)}>
                <div>
                  <strong>{compactValue(group.execution_group_id)}</strong>
                  <span>{displayGroupMode(group, "Runtime work")} · {compactValue(group.finished_at || group.started_at)}</span>
                </div>
                <RunTonePill tone={toneForStatus(group.status)}>{compactValue(group.status)}</RunTonePill>
              </div>
            ))}
          </div>
        </section>
      )}
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
  const [ticketSnapshot, setTicketSnapshot] = useState<TicketSnapshot | null>(() => ticketSnapshotFromProjectSnapshot(props.snapshot));
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
  const [parallelDetails, setParallelDetails] = useState<Record<string, unknown> | null>(null);
  const [dagLiveEvents, setDagLiveEvents] = useState<RuntimeStateEvent[]>([]);
  const [dagStreamState, setDagStreamState] = useState<"snapshot" | "connecting" | "live" | "disconnected">("snapshot");
  const [dagEventCount, setDagEventCount] = useState(0);
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
  const ticketSplitBusy = ticketBusy === "ticket.split_preview";
  const ticketCandidateBusy = ticketDraftBusy || ticketSplitBusy;
  const ticketWriteBusy = ticketBusy !== null;
  const ticketDraftCandidates = ticketDraft?.candidates ?? [];
  const ticketDraftIsSplit = ticketDraft?.generation_mode === "split";
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
    const embedded = ticketSnapshotFromProjectSnapshot(props.snapshot);
    if (embedded) setTicketSnapshot(embedded);
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
    if (!target || !model.isScaffolded) {
      setDagStreamState("snapshot");
      setDagLiveEvents([]);
      setDagEventCount(0);
      return;
    }
    const state = asRecord(props.snapshot?.run.state);
    const lastEvent = asRecord(state.last_event);
    const afterEventId = numberValue(lastEvent.event_id);
    const watchId = `run-dag-${Math.abs(target.split("").reduce((total, char) => total + char.charCodeAt(0), 0))}-${Date.now()}`;
    let disposed = false;
    let unlisten: (() => void) | null = null;
    let pending: RuntimeStateEvent[] = [];
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;

    function flushEvents() {
      flushTimer = null;
      if (!pending.length || disposed) return;
      const batch = pending;
      pending = [];
      setDagLiveEvents((current) => [...current, ...batch].slice(-160));
      setDagEventCount((count) => count + batch.filter((event) => event.event === "runtime_state").length);
    }

    function scheduleFlush(event: RuntimeStateEvent) {
      pending.push(event);
      if (pending.length >= 100) {
        if (flushTimer) clearTimeout(flushTimer);
        flushEvents();
        return;
      }
      if (!flushTimer) flushTimer = setTimeout(flushEvents, 250);
    }

    function scheduleRefresh() {
      if (refreshTimer) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        if (!disposed) props.onRefresh();
      }, 2000);
    }

    setDagStreamState("connecting");
    void listenRuntimeStateEvents(watchId, (event) => {
      if (event.event === "runtime_state_error" || event.event === "runtime_state_closed") {
        setDagStreamState("disconnected");
        return;
      }
      if (event.event === "runtime_state_heartbeat") {
        setDagStreamState("live");
        return;
      }
      if (event.event === "runtime_state") {
        setDagStreamState("live");
        scheduleFlush(event);
        scheduleRefresh();
      }
    }).then((dispose) => {
      if (disposed) dispose();
      else unlisten = dispose;
    });
    void startRuntimeStateWatch({ watchId, target, afterEventId }).catch(() => {
      if (!disposed) setDagStreamState("disconnected");
    });
    return () => {
      disposed = true;
      if (flushTimer) clearTimeout(flushTimer);
      if (refreshTimer) clearTimeout(refreshTimer);
      unlisten?.();
      void stopRuntimeStateWatch(watchId);
    };
  }, [target, model.isScaffolded]);

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

  async function runBootstrapThenStart(action: RunAction) {
    if (!target) return;
    const command = "automation.bootstrap_start";
    const runId = `${command}-${Date.now()}`;
    setBusyCommand(command);
    setCommandMessage("Preparing target before start.");
    setLogs([]);
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setLogs((current) => [...current, { ...event, capturedAt: new Date().toISOString() }]);
      });
      const bootstrapPayload: BackendEnvelope<Record<string, unknown>> = await runBackendCommandStreamed({
        runId,
        command: "brief.run_bootstrap",
        target,
      });
      const bootstrapAlreadyCompleted = bootstrapPayload.error?.type === "bootstrap_already_completed";
      if (!bootstrapPayload.ok && !bootstrapAlreadyCompleted) {
        setCommandError(bootstrapPayload.message ?? "First-run preparation failed.");
        props.onRefresh();
        return;
      }
      setCommandMessage("Preparation completed. Starting automation.");
      const startPayload: BackendEnvelope<Record<string, unknown>> = await runBackendCommandStreamed({
        runId,
        command: "automation.start",
        target,
      });
      if (!startPayload.ok) {
        setCommandError(startPayload.message ?? "Automation start failed.");
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
    if (command === "automation.bootstrap_start") {
      await runBootstrapThenStart(action);
      return;
    }
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

  async function runParallelCommand(
    command: string,
    label: string,
    options: {
      executionGroupId?: string;
      leaseId?: string;
      groupMode?: string;
      maxWorkers?: number;
    } = {},
  ) {
    if (!target) return;
    setCommandError(null);
    setCommandMessage(`${label} requested.`);
    setBusyCommand(command);
    try {
      const payload = await runBackendCommand<Record<string, unknown>>({
        command,
        target,
        ...options,
      });
      if (!payload.ok || !payload.data) {
        setCommandError(payload.message ?? `${label} failed.`);
        return;
      }
      setCommandMessage(`${label} completed.`);
      if (command === "execution_group.load") {
        setParallelDetails(payload.data);
      } else {
        const refreshed = await runBackendCommand<Record<string, unknown>>({
          command: "execution_group.load",
          target,
        });
        if (refreshed.ok && refreshed.data) setParallelDetails(refreshed.data);
        props.onRefresh();
      }
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : String(error));
    } finally {
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

  async function splitTicket(ticket: Ticket) {
    if (!target || !canSplitTicket(ticket)) {
      setTicketMessage("Only pending tickets can be split.");
      return;
    }
    setTicketBusy("ticket.split_preview");
    setTicketError(null);
    setTicketDraft(null);
    setTicketDraftLogs([]);
    setTicketMessage(`Drafting split preview for ${ticket.id}.`);
    setTicketPendingAction(null);
    focusTicketDraftSection();
    const runId = `ticket-split-${ticket.id}-${Date.now()}`;
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setTicketDraftLogs((current) => [...current, { ...event, capturedAt: new Date().toISOString() }].slice(-20));
      });
      const payload = await runBackendCommandStreamed<TicketDraftState>({
        runId,
        command: "ticket.split_preview",
        target,
        ticketId: ticket.id,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Ticket split preview failed.");
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
          `Split preview ready for ${ticket.id}: ${candidates.length} child ticket${candidates.length === 1 ? "" : "s"}.`,
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
    const command = ticketDraft.generation_mode === "split" ? "ticket.accept_split" : "ticket.accept_draft";
    setTicketBusy(command);
    setTicketError(null);
    try {
      const payload = await runBackendCommand<TicketSnapshot>({
        command,
        target,
        draftId: ticketDraft.draft_id,
        importMode: command === "ticket.accept_draft" ? "append" : undefined,
      });
      if (!payload.ok || !payload.data) {
        setTicketError(payload.message ?? "Could not accept the ticket preview.");
        return;
      }
      setTicketSnapshot(payload.data);
      setTicketDraft(null);
      setTicketDraftLogs([]);
      setTicketDraftDirection("");
      setTicketMessage(command === "ticket.accept_split" ? "Split applied to the queue." : "Draft tickets added to the queue.");
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

        <OperationsCockpitPanel model={model} />

        <ProgressMatrixPanel rows={model.operations.progressRows} />

        <ConcurrencyStripPanel waves={model.operations.concurrencyWaves} />

        <AutomationActivityGraphPanel
          model={model}
          liveEvents={dagLiveEvents}
          streamState={dagStreamState}
          eventCount={dagEventCount}
        />

        <RunSafetyMatrix rows={model.safety} busy={isBusy} onRun={runAction} />

        <GraphInsightsPanel snapshot={props.snapshot} />

        <ParallelExecutionPanel
          snapshot={props.snapshot}
          details={parallelDetails}
          busy={isBusy}
          onLoad={() => void runParallelCommand("execution_group.load", "Parallel details refresh")}
          onStartReadOnly={(groupId) =>
            void runParallelCommand("execution_group.start", "Read-only group start", {
              executionGroupId: groupId,
              groupMode: "read_only",
              maxWorkers: 2,
            })
          }
          onStartValidation={() =>
            void runParallelCommand("execution_group.start", "Validation group start", {
              groupMode: "validation",
            })
          }
          onCancelGroup={(groupId) =>
            void runParallelCommand("execution_group.cancel", "Execution group cancel", {
              executionGroupId: groupId,
            })
          }
          onReleaseLease={(leaseId) =>
            void runParallelCommand("lease.release_stale", "Lease release", {
              leaseId,
            })
          }
          onExportBundle={() => void runParallelCommand("execution_group.export_debug_bundle", "Parallel debug bundle export")}
        />

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
                  <span>{ticketCandidateBusy ? (ticketSplitBusy ? "Splitting" : "Drafting") : ticketDraft ? `${ticketDraftCandidates.length} ready` : "None"}</span>
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
                    tooltip="Run Codex to propose grounded follow-up tickets. Nothing is written until you add the draft tickets."
                    onClick={draftTickets}
                    disabled={ticketWriteBusy}
                  >
                    {ticketDraftBusy ? <RefreshCw className="spin" size={14} /> : <WandSparkles size={14} />}
                    {ticketDraftBusy ? "Drafting" : "Draft New Tickets"}
                  </QueueActionButton>
                  <QueueActionButton
                    className="secondary-action"
                    tooltip={ticketDraftIsSplit ? "Replace the selected pending ticket with the visible child tickets." : "Append the visible draft candidates to the ticket queue."}
                    onClick={acceptTicketDraft}
                    disabled={ticketWriteBusy || !ticketDraft?.draft_id || ticketDraftCandidates.length === 0}
                  >
                    <FilePlus2 size={14} />
                    {ticketDraftIsSplit ? "Apply Split" : "Add Draft Tickets"}
                  </QueueActionButton>
                </div>
              </div>

              {ticketCandidateBusy && (
                <div className="ticket-draft-progress" role="status" aria-live="polite">
                  <div>
                    <RefreshCw className="spin" size={15} />
                    <strong>{ticketSplitBusy ? "Splitting with Codex" : "Drafting with Codex"}</strong>
                  </div>
                  <div className="ticket-draft-log">
                    {ticketDraftLogs.length ? (
                      ticketDraftLogs.map((line, index) => (
                        <code key={`${line.capturedAt}-${index}`}>[{line.stage}] {line.message}</code>
                      ))
                    ) : (
                      <code>{ticketSplitBusy ? "Starting ticket split..." : "Starting ticket draft..."}</code>
                    )}
                  </div>
                </div>
              )}

              {!ticketCandidateBusy && ticketDraft && (
                <>
                  {ticketDraftIsSplit && (
                    <p className="empty-copy">
                      Replaces {ticketDraft.source_ticket_id ?? "the selected ticket"}
                      {ticketDraft.remap_dependency_to ? `; downstream dependencies remap to ${ticketDraft.remap_dependency_to}.` : "."}
                    </p>
                  )}
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
                    <span>{ticketDraft.quality_warning_count ?? 0} warnings</span>
                  </div>
                  <details className="ticket-draft-details">
                    <summary>Raw draft JSON</summary>
                    <pre className="raw-json">{JSON.stringify(ticketDraft, null, 2)}</pre>
                  </details>
                </>
              )}

              {!ticketCandidateBusy && !ticketDraft && <p className="empty-copy">No draft candidates ready.</p>}
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
                        tooltip={canSplitTicket(ticket) ? "Preview smaller replacement tickets without changing the queue." : "Only pending tickets can be split."}
                        onClick={() => void splitTicket(ticket)}
                        disabled={ticketWriteBusy || !canSplitTicket(ticket)}
                      >
                        <Scissors size={14} />
                        Split Ticket
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
