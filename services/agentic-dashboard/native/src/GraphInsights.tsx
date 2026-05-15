import type { ReactNode } from "react";
import type { ProjectSnapshot } from "./api/backend";

type Tone = "good" | "warn" | "critical" | "info" | "quiet";

type GraphStat = {
  label: string;
  value: string | number;
  tone: Tone;
};

type GraphListItem = {
  id: string;
  title: string;
  detail: string;
  meta: string;
  confidence?: string;
  reason?: string;
  tone: Tone;
};

export type GraphInsightsModel = {
  hasGraphData: boolean;
  codebaseStats: GraphStat[];
  taskStats: GraphStat[];
  impactItems: GraphListItem[];
  contextItems: GraphListItem[];
  leaseItems: GraphListItem[];
  conflictItems: GraphListItem[];
  warningItems: GraphListItem[];
  schedulerItems: GraphListItem[];
  selectedCandidate: GraphListItem | null;
  fallbackUsed: boolean;
};

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) {
    return Number(value);
  }
  return 0;
}

function firstText(values: unknown[], fallback = ""): string {
  for (const value of values) {
    const rendered = text(value);
    if (rendered) return rendered;
  }
  return fallback;
}

function compactStatus(value: unknown, fallback = "unknown"): string {
  return text(value, fallback).replace(/_/g, " ").toLowerCase();
}

function confidenceLabel(value: unknown): string {
  const confidence = Math.max(0, Math.min(1, number(value)));
  return `${Math.round(confidence * 100)}%`;
}

function graphState(snapshot: ProjectSnapshot | null): Record<string, unknown> {
  return record(snapshot?.run.state);
}

function graphExists(summary: Record<string, unknown>): boolean {
  return Boolean(summary.exists) || Object.keys(record(summary.node_counts)).length > 0;
}

function itemTone(options: { stale?: boolean; blocked?: boolean; conflict?: boolean; selected?: boolean }): Tone {
  if (options.conflict) return "critical";
  if (options.stale || options.blocked) return "warn";
  if (options.selected) return "good";
  return "info";
}

function graphPath(item: Record<string, unknown>): string {
  return firstText([item.path, item.name, item.node_id], "Unlabeled node");
}

function contextItem(raw: unknown, index: number): GraphListItem {
  const item = record(raw);
  const stale = item.is_stale === true;
  return {
    id: firstText([item.node_id, item.path, item.name], `context-${index}`),
    title: graphPath(item),
    detail: compactStatus(item.category ?? item.kind, "context"),
    meta: stale ? "stale" : compactStatus(item.kind, "node"),
    confidence: confidenceLabel(item.confidence),
    reason: text(item.reason, "No reason recorded."),
    tone: itemTone({ stale }),
  };
}

function impactItem(raw: unknown, index: number): GraphListItem {
  const impact = record(raw);
  const task = record(impact.task);
  const node = record(impact.node);
  return {
    id: firstText([task.node_id, node.node_id], `impact-${index}`),
    title: graphPath(node),
    detail: firstText([task.id, task.name], "current task"),
    meta: compactStatus(impact.edge_kind, "impact"),
    confidence: confidenceLabel(impact.confidence),
    reason: text(impact.reason, "No reason recorded."),
    tone: itemTone({ stale: node.is_stale === true }),
  };
}

function scopeLabel(scope: Record<string, unknown>, fallback = "Unscoped resource"): string {
  return firstText([scope.path, scope.name, scope.scope_node_id], fallback);
}

function leaseItem(raw: unknown, index: number): GraphListItem {
  const lease = record(raw);
  const scope = record(lease.scope);
  return {
    id: text(lease.lease_id, `lease-${index}`),
    title: scopeLabel(scope),
    detail: `${compactStatus(lease.scope_kind, "scope")} lease`,
    meta: firstText([lease.owner_role, lease.task_id, lease.run_id], "unowned"),
    tone: "info",
  };
}

function conflictItem(raw: unknown, index: number): GraphListItem {
  const conflict = record(raw);
  const lease = record(conflict.lease);
  const other = record(conflict.conflicting_lease ?? conflict.candidate);
  const leaseScope = record(lease.scope);
  const otherScope = record(record(other).scope);
  return {
    id: firstText([lease.lease_id, other.lease_id], `conflict-${index}`),
    title: scopeLabel(leaseScope, "Conflicting lease"),
    detail: text(conflict.reason, "Lease scopes overlap."),
    meta: scopeLabel(otherScope, firstText([other.owner_role, other.task_id], "other owner")),
    tone: "critical",
  };
}

function warningItem(raw: unknown, index: number): GraphListItem {
  const warning = record(raw);
  return {
    id: firstText([warning.kind, warning.message], `warning-${index}`),
    title: text(warning.message, "Graph staleness warning."),
    detail: compactStatus(warning.kind, "stale graph"),
    meta: firstText([warning.source, warning.count], "state.snapshot"),
    tone: warning.severity === "critical" ? "critical" : "warn",
  };
}

function normalizeWarnings(state: Record<string, unknown>): GraphListItem[] {
  const warnings = list(state.stale_graph_warnings).map(warningItem);
  const seen = new Set(warnings.map((item) => item.title));
  const staleContext = text(state.stale_context_warning);
  if (staleContext && !seen.has(staleContext)) {
    warnings.push({
      id: "stale-context-warning",
      title: staleContext,
      detail: "stale context",
      meta: "impact graph",
      tone: "warn",
    });
  }
  const staleCount = number(state.stale_node_count);
  if (staleCount && !warnings.some((item) => item.detail === "codebase stale nodes")) {
    warnings.push({
      id: "stale-node-count",
      title: `${staleCount} indexed codebase node${staleCount === 1 ? " is" : "s are"} stale.`,
      detail: "codebase stale nodes",
      meta: "codebase graph",
      tone: "warn",
    });
  }
  return warnings.slice(0, 4);
}

function candidateItem(raw: unknown, index: number): GraphListItem {
  const candidate = record(raw);
  const reasons = list(candidate.reasons).map((item) => text(item)).filter(Boolean);
  const blockers = list(candidate.blockers).map((item) => text(item)).filter(Boolean);
  const state = compactStatus(candidate.state, candidate.skipped_reason ? "skipped" : "candidate");
  const selected = state === "selected";
  const blocked = blockers.length > 0 || Boolean(candidate.skipped_reason);
  return {
    id: firstText([candidate.candidate_id, candidate.task_id], `candidate-${index}`),
    title: firstText([candidate.task_id, candidate.graph_task_node_id, candidate.role], "scheduler candidate"),
    detail: `${firstText([candidate.role], "role")} / ${firstText([candidate.action_kind], "action")}`,
    meta: `${state} / score ${number(candidate.score).toFixed(2)}`,
    reason: firstText([candidate.skipped_reason, reasons.join("; "), blockers.join("; ")], "No reason recorded."),
    tone: itemTone({ selected, blocked }),
  };
}

export function buildGraphInsightsModel(snapshot: ProjectSnapshot | null): GraphInsightsModel {
  const state = graphState(snapshot);
  const codebase = record(state.codebase_graph_summary);
  const task = record(state.task_graph_summary);
  const contextPack = record(state.context_pack_preview);
  const selectedCandidate = record(state.selected_candidate);
  const candidates = list(state.scheduling_candidates);

  const codebaseStats: GraphStat[] = [
    { label: "Files", value: number(state.indexed_file_count ?? codebase.indexed_file_count), tone: "info" },
    { label: "Tests", value: number(state.test_node_count ?? codebase.test_node_count), tone: "info" },
    { label: "Commands", value: number(state.command_node_count ?? codebase.command_node_count), tone: "info" },
    {
      label: "Stale",
      value: number(state.stale_node_count ?? codebase.stale_node_count),
      tone: number(state.stale_node_count ?? codebase.stale_node_count) ? "warn" : "good",
    },
  ];

  const taskStats: GraphStat[] = [
    { label: "Ready", value: number(task.ready_task_count), tone: number(task.ready_task_count) ? "good" : "quiet" },
    { label: "Blocked", value: number(task.blocked_task_count), tone: number(task.blocked_task_count) ? "warn" : "quiet" },
    { label: "Cycles", value: number(task.dependency_cycle_count), tone: number(task.dependency_cycle_count) ? "critical" : "good" },
    { label: "Nodes", value: Object.values(record(task.node_counts)).reduce<number>((total, value) => total + number(value), 0), tone: "info" },
  ];

  const selected = Object.keys(selectedCandidate).length ? candidateItem(selectedCandidate, 0) : null;

  return {
    hasGraphData:
      graphExists(codebase) ||
      graphExists(task) ||
      list(state.active_task_code_impacts).length > 0 ||
      list(contextPack.items).length > 0,
    codebaseStats,
    taskStats,
    impactItems: list(state.active_task_code_impacts).slice(0, 5).map(impactItem),
    contextItems: list(contextPack.items).slice(0, 6).map(contextItem),
    leaseItems: list(state.active_leases).slice(0, 5).map(leaseItem),
    conflictItems: list(state.conflicting_leases).slice(0, 4).map(conflictItem),
    warningItems: normalizeWarnings(state),
    schedulerItems: candidates.slice(0, 5).map(candidateItem),
    selectedCandidate: selected,
    fallbackUsed: state.scheduler_fallback_used === true,
  };
}

function StatStrip(props: { label: string; stats: GraphStat[] }) {
  return (
    <section className="graph-summary-block" aria-label={`${props.label} summary`}>
      <h3>{props.label}</h3>
      <div className="graph-stat-grid">
        {props.stats.map((stat) => (
          <div className={`graph-stat ${stat.tone}`} key={stat.label}>
            <span>{stat.label}</span>
            <strong>{stat.value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function GraphItemList(props: {
  items: GraphListItem[];
  empty: string;
  className?: string;
}) {
  if (!props.items.length) {
    return <p className="empty-copy">{props.empty}</p>;
  }
  return (
    <div className={`graph-item-list ${props.className ?? ""}`}>
      {props.items.map((item) => (
        <div className={`graph-item ${item.tone}`} key={item.id}>
          <div className="graph-item-main">
            <strong title={item.title}>{item.title}</strong>
            <span title={item.detail}>{item.detail}</span>
          </div>
          <div className="graph-item-meta">
            {item.confidence && <em>{item.confidence}</em>}
            <span title={item.meta}>{item.meta}</span>
          </div>
          {item.reason && <p title={item.reason}>{item.reason}</p>}
        </div>
      ))}
    </div>
  );
}

function GraphSection(props: {
  title: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <section className="graph-section" aria-label={props.label}>
      <h3>{props.title}</h3>
      {props.children}
    </section>
  );
}

export function GraphInsightsPanel(props: { snapshot: ProjectSnapshot | null }) {
  const model = buildGraphInsightsModel(props.snapshot);
  const statusTone = model.warningItems.length || model.conflictItems.length ? "warn" : model.hasGraphData ? "good" : "quiet";

  return (
    <article className="panel graph-insights-panel" aria-label="Graph insights" data-testid="graph-insights-panel">
      <div className="panel-heading-row">
        <div>
          <h2>Graph Insights</h2>
          <p>{model.hasGraphData ? "state.snapshot" : "No graph snapshot indexed yet."}</p>
        </div>
        <span className={`graph-status-pill ${statusTone}`}>
          {model.conflictItems.length ? "Conflicts" : model.warningItems.length ? "Stale" : model.hasGraphData ? "Ready" : "Empty"}
        </span>
      </div>

      <div className="graph-summary-strip">
        <StatStrip label="Codebase Graph" stats={model.codebaseStats} />
        <StatStrip label="Task Graph" stats={model.taskStats} />
      </div>

      {model.warningItems.length > 0 && (
        <section className="graph-warning-card" aria-label="Stale graph warning">
          <h3>Stale graph warning</h3>
          <GraphItemList
            items={model.warningItems}
            empty="No stale graph warnings."
          />
        </section>
      )}

      <div className="graph-insights-sections">
        <GraphSection title="Impact View" label="Impact View for current or next task">
          <GraphItemList
            items={model.impactItems}
            empty="No task-codebase impact edges are exposed yet."
          />
        </GraphSection>

        <GraphSection title="Why these files?" label="Why these files context pack">
          <GraphItemList
            items={model.contextItems}
            empty="No context pack preview is exposed yet."
          />
        </GraphSection>

        <GraphSection title="Active leases" label="Active leases and conflicts">
          {model.conflictItems.length > 0 && (
            <GraphItemList
              className="conflicts"
              items={model.conflictItems}
              empty="No lease conflicts."
            />
          )}
          <GraphItemList
            items={model.leaseItems}
            empty="No active leases."
          />
        </GraphSection>

        <GraphSection title="Scheduler" label="Scheduling candidates">
          {model.selectedCandidate && (
            <div className="graph-selected-candidate">
              <span>Selected</span>
              <strong>{model.selectedCandidate.title}</strong>
              <p>{model.selectedCandidate.reason}</p>
            </div>
          )}
          <GraphItemList
            items={model.schedulerItems}
            empty={model.fallbackUsed ? "Graph scheduler fell back to the legacy decision path." : "No scheduling candidates recorded yet."}
          />
        </GraphSection>
      </div>
    </article>
  );
}
