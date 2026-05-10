import {
  FileDown,
  Loader2,
  RefreshCw,
  Telescope,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type {
  BackendEnvelope,
  ObservatoryCommit,
  ObservatoryRoleCard,
  ObservatorySnapshot,
  ProjectSnapshot,
} from "./api/backend";
import { runBackendCommand } from "./api/backend";
import type { ObservatoryTab } from "./observatoryModel";
import { useChunkedLimit } from "./performance";

type ReviewExportData = {
  html_path: string;
  markdown_path: string;
  snapshot_generated_at?: string;
};

const tabs: ObservatoryTab[] = ["Summary", "Events", "Queue", "Metrics"];
const roleFilters = ["planner", "builder", "hardener", "integrator"] as const;

type ActivityFilter = "all" | typeof roleFilters[number] | "system";

type ActivityEvent = {
  id: string;
  time: string;
  type: string;
  lane: string;
  message: string;
  artifact: string;
  status: string;
  tone: string;
  detail: string;
};

function targetSubdir(target: string, leaf: string): string {
  return `${target.replace(/[\\/]+$/, "")}/target/${leaf}`;
}

function text(value: unknown, fallback = "Not recorded"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function readableState(value: unknown, fallback: string): string {
  const raw = text(value, "");
  if (!raw || raw.toUpperCase() === "UNKNOWN") return fallback;
  return raw;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function tone(value: unknown): string {
  const raw = text(value, "info").toLowerCase();
  if (["good", "warn", "warning", "critical", "bad", "info", "quiet", "running", "next", "failed"].includes(raw)) return raw;
  return "info";
}

function roleLabel(value: unknown): string {
  const raw = text(value, "role");
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function compactLabel(value: unknown, fallback: string): string {
  return roleLabel(text(value, fallback).replace(/_/g, " "));
}

function laneLabel(snapshot: ObservatorySnapshot | null, activeRun: Record<string, unknown>): string {
  if (text(activeRun.role, "")) {
    return `${text(activeRun.status, "running") === "running" ? "Running" : "Last active"}: ${roleLabel(activeRun.role)}`;
  }
  const next = snapshot?.conveyor.roles.find((role) => role.status === "next");
  if (next) return `Next: ${roleLabel(next.role)}`;
  const running = snapshot?.conveyor.roles.find((role) => role.status === "running");
  if (running) return `Running: ${roleLabel(running.role)}`;
  return "No active lane";
}

function hasKnownIssue(value: unknown): boolean {
  const raw = text(value, "").toLowerCase();
  return Boolean(raw && !["no active issue summary.", "no active issue summary", "no active issue", "none"].includes(raw));
}

function missionIssueLabel(status: string, knownIssue: boolean): string {
  if (!knownIssue) return "Known issue";
  return status.includes("BLOCKED") || status.includes("CRITICAL") ? "Blocker" : "Known issue";
}

function eventTime(item: Record<string, unknown>): string {
  return text(item.finished_at ?? item.timestamp ?? item.time ?? item.updated_at ?? item.created_at ?? item.generated_at, "No time");
}

function eventLane(item: Record<string, unknown>, fallback = "system"): string {
  return text(item.role ?? item.lane ?? item.source_lane ?? item.owner ?? item.kind, fallback).toLowerCase();
}

function eventStatus(item: Record<string, unknown>, fallback = "info"): string {
  return text(item.status ?? item.state ?? item.result ?? item.baseline_status ?? item.kind, fallback);
}

function eventMessage(item: Record<string, unknown>, fallback: string): string {
  return text(item.reason ?? item.summary ?? item.message ?? item.title ?? item.subject ?? item.detail ?? item.deferral_reason, fallback);
}

function eventArtifact(item: Record<string, unknown>): string {
  return text(item.artifact ?? item.path ?? item.file ?? item.run_id ?? item.hash ?? item.request_id, "");
}

function buildActivityEvents(snapshot: ObservatorySnapshot | null): ActivityEvent[] {
  if (!snapshot) return [];
  const events: ActivityEvent[] = [];
  const push = (source: string, index: number, item: Record<string, unknown>, type: string, fallback: string) => {
    const status = eventStatus(item);
    const lane = eventLane(item);
    events.push({
      id: `${source}-${text(item.run_id ?? item.id ?? item.hash ?? item.timestamp ?? index, String(index))}`,
      time: eventTime(item),
      type,
      lane,
      message: eventMessage(item, fallback),
      artifact: eventArtifact(item),
      status,
      tone: tone(status),
      detail: text(item.detail ?? item.body ?? item.summary ?? item.reason, "No additional detail recorded."),
    });
  };

  snapshot.timeline.forEach((item, index) => push("timeline", index, item, "event", "Run event recorded."));
  snapshot.progress.recent_outcomes.forEach((item, index) => push("outcome", index, item, "role result", "Role result recorded."));
  snapshot.patches.manifests.forEach((item, index) => push("patch", index, item, "patch", "Patch queued or deferred."));
  snapshot.patches.recent_outcomes.forEach((item, index) => push("patch-result", index, item, "patch result", "Patch result recorded."));
  snapshot.signals.nudges.forEach((item, index) => push("signal", index, item, "signal", "Signal recorded."));
  snapshot.signals.recent_completed.forEach((item, index) => push("signal-done", index, item, "signal done", "Signal completed."));
  snapshot.progress.landed_work_feed.forEach((commit, index) => {
    const status = text(commit.role, "commit");
    events.push({
      id: `commit-${text(commit.hash, String(index))}`,
      time: text(commit.time, "No time"),
      type: "commit",
      lane: text(commit.role, "system").toLowerCase(),
      message: text(commit.subject, "Commit recorded."),
      artifact: text(commit.hash, ""),
      status,
      tone: "good",
      detail: text(commit.summary, "No commit summary recorded."),
    });
  });
  (snapshot.review?.items ?? []).forEach((item, index) => push("review", index, item, "review", "Review item recorded."));
  (snapshot.review?.known_issues ?? []).forEach((item, index) => push("review-issue", index, item, "review issue", "Known issue recorded."));

  return events.sort((left, right) => {
    const leftDate = Date.parse(left.time);
    const rightDate = Date.parse(right.time);
    if (Number.isNaN(leftDate) && Number.isNaN(rightDate)) return 0;
    if (Number.isNaN(leftDate)) return 1;
    if (Number.isNaN(rightDate)) return -1;
    return rightDate - leftDate;
  });
}

function filteredActivityEvents(events: ActivityEvent[], filter: ActivityFilter): ActivityEvent[] {
  if (filter === "all") return events;
  if (filter === "system") return events.filter((event) => !roleFilters.includes(event.lane as typeof roleFilters[number]));
  return events.filter((event) => event.lane === filter);
}

function CompactBadge(props: { label?: string; value: unknown; tone?: string }) {
  return (
    <span className={`obs-chip ${tone(props.tone)}`}>
      {props.label ? `${props.label}: ` : ""}
      {text(props.value, "none")}
    </span>
  );
}

function ObsSection(props: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`obs-section ${props.className ?? ""}`}>
      <h2>{props.title}</h2>
      <div className="obs-content">{props.children}</div>
    </section>
  );
}

function MissionStrip(props: {
  snapshot: ObservatorySnapshot | null;
  activeRun: Record<string, unknown>;
}) {
  const snapshot = props.snapshot;
  const knownIssue = hasKnownIssue(snapshot?.mission.known_issue);
  const status = text(snapshot?.mission.automation_status, "").toUpperCase();
  const issueLabel = missionIssueLabel(status, knownIssue);
  const items = [
    ...(status && status !== "ACTIVE" && status !== "UNKNOWN"
      ? [{
          label: "Status",
          value: readableState(snapshot?.mission.automation_status, "No status recorded"),
          tone: tone(snapshot?.mission.automation_status),
        }]
      : []),
    {
      label: "Plan",
      value: readableState(snapshot?.mission.current_horizon, "No plan recorded"),
      tone: "info",
    },
    { label: "Running / next lane", value: laneLabel(snapshot, props.activeRun), tone: text(props.activeRun.role, "") ? "running" : "next" },
    {
      label: "Next milestone",
      value: text(snapshot?.mission.best_next_milestone, "No milestone recorded yet."),
      tone: "good",
    },
    {
      label: issueLabel,
      value: text(snapshot?.mission.known_issue, "No active issue summary."),
      tone: knownIssue ? "warn" : "quiet",
    },
  ];

  return (
    <section className={`obs-mission-strip count-${items.length}`} aria-label="Target state">
      {items.map((item) => (
        <div className={`obs-mission-strip-item ${item.tone} ${item.label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`} key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </section>
  );
}

function RoleCard(props: {
  role: ObservatoryRoleCard;
  selected?: boolean;
  onSelect?: (role: ObservatoryRoleCard) => void;
}) {
  const counts = props.role.counts ?? {};
  return (
    <button
      aria-pressed={props.selected}
      className={`obs-role ${props.role.status} ${props.selected ? "selected" : ""}`}
      onClick={() => props.onSelect?.(props.role)}
      type="button"
    >
      <div className="obs-role-head">
        <h3>{props.role.role}</h3>
        <CompactBadge value={props.role.badge} tone={props.role.status} />
      </div>
      <p>{text(props.role.reason, "Awaiting conveyor decision.")}</p>
      <div className="obs-role-counts">
        {["queued", "deferred", "applied", "failed", "skipped"].map((key) => (
          <span key={key}>{key}: {number(counts[key])}</span>
        ))}
      </div>
    </button>
  );
}

function ConveyorSection(props: {
  snapshot: ObservatorySnapshot | null;
  activeRun: Record<string, unknown>;
  health: Record<string, unknown>;
  className?: string;
  selectedRole?: string;
  onSelectRole?: (role: ObservatoryRoleCard) => void;
}) {
  const roles = props.snapshot?.conveyor.roles ?? [];
  return (
    <ObsSection title="Conveyor" className={`obs-conveyor-section ${props.className ?? ""}`}>
      <div className="obs-conveyor-layout">
        <div className="obs-horizontal-scroll" aria-label="Roles">
          <div className="obs-belt">
            {roles.length ? (
              roles.map((role, index) => (
                <div className="obs-belt-step" key={role.role}>
                  <RoleCard
                    role={role}
                    selected={props.selectedRole === role.role}
                    onSelect={props.onSelectRole}
                  />
                  {index < roles.length - 1 && <span className="obs-belt-arrow" aria-hidden="true">→</span>}
                </div>
              ))
            ) : (
              <p className="obs-muted">No role state recorded.</p>
            )}
          </div>
        </div>
        <div className="obs-conveyor-meta-row">
          {text(props.activeRun.role, "") ? (
            <div className="obs-running-banner">
              <strong>
                {text(props.activeRun.status, "running") === "running" ? "Running now" : "Last active"}:{" "}
                {text(props.activeRun.role, "role")}
              </strong>
              <div>{text(props.activeRun.run_id, "unknown")} · {text(props.activeRun.reason, "No reason recorded.")}</div>
            </div>
          ) : (
            <div className="obs-running-banner quiet">
              <strong>No role running now</strong>
              <div>Conveyor idle.</div>
            </div>
          )}
          <div className={`obs-health ${tone(props.health.status)}`}>
            <strong>{text(props.health.status, "ok").toUpperCase()}</strong>
            <p>{text(props.health.summary, "Conveyor policy active.")}</p>
          </div>
          <div className="obs-conveyor-kpis">
            <div>
              <span>Cycles</span>
              <strong>{number(props.snapshot?.conveyor.cycles)}</strong>
            </div>
            <div>
              <span>Queued</span>
              <strong>{number(props.snapshot?.patches.queue_totals.queued)}</strong>
            </div>
          </div>
        </div>
      </div>
    </ObsSection>
  );
}

function CommitCard(props: { commit: ObservatoryCommit; compact?: boolean; rail?: boolean }) {
  const commit = props.commit;
  const showFiles = (!props.compact || props.rail) && Array.isArray(commit.files) && commit.files.length > 0;
  return (
    <div className={`obs-commit-card ${props.rail ? "rail" : ""}`}>
      <div className="obs-commit-title">{text(commit.subject, "Commit")}</div>
      <div className="obs-commit-summary">{text(commit.summary, "No commit summary recorded.")}</div>
      <div className="obs-commit-meta">
        <code>{text(commit.hash, "no-hash")}</code>
        <span>{text(commit.role, "commit")}</span>
        {text(commit.time, "") && <span>{text(commit.time, "")}</span>}
        <span>{number(commit.file_count)} files</span>
        <span className="obs-stat">+{number(commit.additions)} / -{number(commit.deletions)}</span>
      </div>
      {showFiles && (
        <div className="obs-file-list">
          {commit.files?.slice(0, props.rail ? 3 : 5).map((file, index) => (
            <div className="obs-file-row" key={`${text(file.path, "file")}-${index}`}>
              <span className="obs-stat">+{number(file.additions)} / -{number(file.deletions)}</span>
              <code>{text(file.path, "file")}</code>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LandedWorkSection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  return (
    <ObsSection title="Commits" className={props.className}>
      <div className="obs-horizontal-scroll" aria-label="Commits">
        <div className="obs-landed-rail">
          {(props.snapshot?.progress.landed_work_feed ?? []).length ? (
            props.snapshot?.progress.landed_work_feed.slice(0, 6).map((commit, index) => (
              <CommitCard commit={commit} rail key={`${commit.hash}-${index}`} />
            ))
          ) : (
            <p className="obs-muted">No commits recorded.</p>
          )}
        </div>
      </div>
    </ObsSection>
  );
}

function ManifestRow(props: { item: Record<string, unknown> }) {
  return (
    <div className="obs-item-row">
      <div className="obs-item-title">
        <strong>{text(props.item.role, "role")} / {text(props.item.run_id, "run")}</strong>
        <CompactBadge value={props.item.status ?? "queued"} tone={text(props.item.status, "info")} />
      </div>
      <p>{text(props.item.summary, "No summary recorded.")}</p>
      <small>{text(props.item.deferral_reason || props.item.baseline_status || props.item.timestamp, "No metadata recorded.")}</small>
    </div>
  );
}

function RecentOutcomesSection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  return (
    <ObsSection title="Recent role results" className={props.className}>
      <div className="obs-list">
        {(props.snapshot?.progress.recent_outcomes ?? []).length ? (
          props.snapshot?.progress.recent_outcomes.slice(0, 5).map((item, index) => (
            <ManifestRow item={item} key={`${text(item.run_id, "outcome")}-${index}`} />
          ))
        ) : (
          <p className="obs-muted">No role results yet.</p>
        )}
      </div>
    </ObsSection>
  );
}

function MetricTable(props: { rows: Array<Record<string, unknown>> }) {
  if (!props.rows.length) return <p className="obs-muted">No scorecard metrics recorded yet.</p>;
  return (
    <div className="obs-metric-table">
      {props.rows.map((item, index) => (
        <div className={`obs-metric-row ${tone(item.kind)}`} key={`${text(item.label, "metric")}-${index}`}>
          <b>{text(item.value, "0")}</b>
          <strong>{text(item.label, "Metric")}</strong>
          <span>{text(item.detail, "No detail recorded.")}</span>
        </div>
      ))}
    </div>
  );
}

function RuntimeMetricsSection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  const metricEntries = useMemo(() => Object.entries(props.snapshot?.metrics ?? {}), [props.snapshot?.metrics]);
  return (
    <ObsSection title="Runtime" className={props.className}>
      <div className="obs-compact-table">
        {metricEntries.length ? (
          metricEntries.map(([key, value]) => (
            <div key={key}><span>{key.replace(/_/g, " ")}</span><strong>{value}</strong></div>
          ))
        ) : (
          <p className="obs-muted">No runtime metrics recorded yet.</p>
        )}
      </div>
    </ObsSection>
  );
}

function TimelineSection(props: { snapshot: ObservatorySnapshot | null }) {
  const timeline = props.snapshot?.timeline ?? [];
  const limit = useChunkedLimit(timeline.length, 80, 180, timeline);
  const visibleTimeline = useMemo(() => timeline.slice(0, limit), [limit, timeline]);

  return (
    <ObsSection title="Events" className="obs-tab-section">
      <div className="obs-timeline">
        {timeline.length ? (
          visibleTimeline.map((item, index) => (
            <div className="obs-timeline-row" key={`${text(item.run_id, "event")}-${index}`}>
              <CompactBadge value={item.role ?? "role"} tone={text(item.status, "info")} />
              <strong>{text(item.reason, "No reason recorded.")}</strong>
              <span>{text(item.finished_at, "unknown")} · exit {text(item.exit_code, "unknown")}</span>
            </div>
          ))
        ) : (
          <p className="obs-muted">No events recorded.</p>
        )}
        {limit < timeline.length && <p className="obs-muted">Rendering more events...</p>}
      </div>
    </ObsSection>
  );
}

function PatchesSection(props: { snapshot: ObservatorySnapshot | null }) {
  const manifests = props.snapshot?.patches.manifests ?? [];
  const outcomes = props.snapshot?.patches.recent_outcomes ?? [];
  const queueEntries = useMemo(() => Object.entries(props.snapshot?.patches.queue_totals ?? {}), [props.snapshot?.patches.queue_totals]);
  const manifestLimit = useChunkedLimit(manifests.length, 80, 160, manifests);
  const outcomeLimit = useChunkedLimit(outcomes.length, 80, 160, outcomes);
  const visibleManifests = useMemo(() => manifests.slice(0, manifestLimit), [manifestLimit, manifests]);
  const visibleOutcomes = useMemo(() => outcomes.slice(0, outcomeLimit), [outcomeLimit, outcomes]);

  return (
    <div className="obs-tab-grid">
      <ObsSection title="Patch queue" className="span-2">
        <div className="obs-list">
          {manifests.length ? (
            visibleManifests.map((item, index) => (
              <ManifestRow item={item} key={`${text(item.run_id, "patch")}-${index}`} />
            ))
          ) : (
            <p className="obs-muted">No queued or deferred patches yet.</p>
          )}
          {manifestLimit < manifests.length && <p className="obs-muted">Rendering more patches...</p>}
        </div>
      </ObsSection>
      <ObsSection title="Queue Totals">
        <div className="obs-compact-table">
          {queueEntries.map(([key, value]) => (
            <div key={key}><span>{key}</span><strong>{value}</strong></div>
          ))}
        </div>
      </ObsSection>
      <ObsSection title="Recent results" className="span-3">
        <div className="obs-list two">
          {visibleOutcomes.map((item, index) => (
            <ManifestRow item={item} key={`${text(item.run_id, "outcome")}-${index}`} />
          ))}
        </div>
        {outcomeLimit < outcomes.length && <p className="obs-muted">Rendering more results...</p>}
      </ObsSection>
    </div>
  );
}

function ValidationSafetySection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  const safety = props.snapshot?.validation_safety ?? {};
  const cards = [
    { label: "Validation", record: safety.validation },
    { label: "Integration safety", record: safety.integration_safety },
    { label: "Baseline verification", record: safety.baseline_verification },
    { label: "Review", record: safety.first_review },
  ];

  return (
    <ObsSection title="Checks" className={props.className}>
      <div className="obs-validation-grid">
        {cards.map((card) => {
          const status = text(card.record?.status ?? card.record?.state ?? card.record?.result, "not recorded");
          return (
            <div className="obs-validation-card" key={card.label}>
              <div className="obs-validation-title">
                <strong>{card.label}</strong>
                <CompactBadge value={status} tone={status} />
              </div>
              <p>{text(card.record?.summary ?? card.record?.detail ?? card.record?.message, "No details recorded yet.")}</p>
            </div>
          );
        })}
      </div>
    </ObsSection>
  );
}

function ActiveRunSection(props: {
  activeRun: Record<string, unknown>;
  health: Record<string, unknown>;
  className?: string;
}) {
  const hasActiveRun = Boolean(text(props.activeRun.role, ""));
  return (
    <ObsSection title="Active run" className={props.className}>
      <div className="activity-run-panel">
        <div className={`activity-run-state ${hasActiveRun ? tone(props.activeRun.status) : "quiet"}`}>
          <span>{hasActiveRun ? compactLabel(props.activeRun.role, "Role") : "Idle"}</span>
          <strong>{hasActiveRun ? text(props.activeRun.status, "running") : "No role running now"}</strong>
          <p>{text(props.activeRun.reason, "Conveyor idle.")}</p>
        </div>
        <div className="activity-run-facts">
          <div><span>Run</span><strong>{text(props.activeRun.run_id, "none")}</strong></div>
          <div><span>Health</span><strong>{text(props.health.status, "ok")}</strong></div>
          <div><span>Policy</span><strong>{text(props.health.summary, "Conveyor policy active.")}</strong></div>
        </div>
      </div>
    </ObsSection>
  );
}

function SelectedRoleInspector(props: {
  role: ObservatoryRoleCard | null;
  events: ActivityEvent[];
  className?: string;
}) {
  if (!props.role) {
    return (
      <ObsSection title="Lane inspector" className={props.className}>
        <p className="obs-muted">Select a conveyor lane to inspect role counts and recent matching events.</p>
      </ObsSection>
    );
  }
  const counts = props.role.counts ?? {};
  const roleEvents = props.events.filter((event) => event.lane === props.role?.role).slice(0, 3);
  return (
    <ObsSection title={`${compactLabel(props.role.role, "Lane")} lane`} className={props.className}>
      <div className="activity-role-inspector">
        <div className="activity-role-reason">
          <CompactBadge value={props.role.status} tone={props.role.status} />
          <p>{text(props.role.reason, "Awaiting conveyor decision.")}</p>
        </div>
        <div className="obs-compact-table">
          {["queued", "deferred", "applied", "failed", "skipped"].map((key) => (
            <div key={key}><span>{key}</span><strong>{number(counts[key])}</strong></div>
          ))}
        </div>
        <div className="activity-mini-list">
          {roleEvents.length ? roleEvents.map((event) => (
            <div key={event.id}>
              <strong>{event.message}</strong>
              <span>{event.time} · {event.status}</span>
            </div>
          )) : <p className="obs-muted">No recent events for this lane.</p>}
        </div>
      </div>
    </ObsSection>
  );
}

function ActivityFilterBar(props: {
  events: ActivityEvent[];
  filter: ActivityFilter;
  onFilter: (filter: ActivityFilter) => void;
}) {
  const filters: Array<{ key: ActivityFilter; label: string }> = [
    { key: "all", label: "All" },
    ...roleFilters.map((key) => ({ key, label: compactLabel(key, key) })),
    { key: "system", label: "System" },
  ];
  const countFor = (filter: ActivityFilter) => filteredActivityEvents(props.events, filter).length;
  return (
    <div className="activity-filter-bar" aria-label="Filter event ledger">
      {filters.map((filter) => (
        <button
          className={props.filter === filter.key ? "active" : ""}
          key={filter.key}
          onClick={() => props.onFilter(filter.key)}
          type="button"
        >
          <span>{filter.label}</span>
          <strong>{countFor(filter.key)}</strong>
        </button>
      ))}
    </div>
  );
}

function ActivityEventLedger(props: {
  events: ActivityEvent[];
  filter: ActivityFilter;
  selectedId: string;
  onFilter: (filter: ActivityFilter) => void;
  onSelect: (id: string) => void;
  className?: string;
}) {
  const visibleEvents = filteredActivityEvents(props.events, props.filter).slice(0, 18);
  const selectedEvent = props.events.find((event) => event.id === props.selectedId) ?? visibleEvents[0];
  return (
    <ObsSection title="Event ledger" className={`activity-event-section ${props.className ?? ""}`}>
      <ActivityFilterBar events={props.events} filter={props.filter} onFilter={props.onFilter} />
      <div className="activity-event-layout">
        <div className="activity-event-ledger" role="list">
          {visibleEvents.length ? visibleEvents.map((event) => (
            <button
              className={`activity-event-row ${event.tone} ${selectedEvent?.id === event.id ? "selected" : ""}`}
              key={event.id}
              onClick={() => props.onSelect(event.id)}
              type="button"
            >
              <code>{event.time}</code>
              <span>{event.type}</span>
              <strong>{event.message}</strong>
              <em>{compactLabel(event.lane, "System")}</em>
              <CompactBadge value={event.status} tone={event.tone} />
            </button>
          )) : (
            <div className="activity-empty compact">
              <strong>No events recorded</strong>
              <p>Refresh after a run to populate the activity ledger.</p>
            </div>
          )}
        </div>
        <aside className="activity-event-detail" aria-label="Selected event detail">
          {selectedEvent ? (
            <>
              <div className="obs-item-title">
                <strong>{selectedEvent.message}</strong>
                <CompactBadge value={selectedEvent.status} tone={selectedEvent.tone} />
              </div>
              <p>{selectedEvent.detail}</p>
              <div className="obs-commit-meta">
                <span>{selectedEvent.type}</span>
                <span>{compactLabel(selectedEvent.lane, "System")}</span>
                {selectedEvent.artifact && <code>{selectedEvent.artifact}</code>}
              </div>
            </>
          ) : (
            <p className="obs-muted">Select an event to inspect source details.</p>
          )}
        </aside>
      </div>
    </ObsSection>
  );
}

function PatchSignalSection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  const queueEntries = Object.entries(props.snapshot?.patches.queue_totals ?? {});
  const signals = props.snapshot?.signals ?? { active_count: 0, nudges: [], recent_completed: [] };
  const nudges = signals.nudges.slice(0, 3);
  const completed = signals.recent_completed.slice(0, 3);
  return (
    <ObsSection title="Patches and signals" className={props.className}>
      <div className="activity-patch-signal-grid">
        <div className="obs-compact-table">
          {queueEntries.length ? queueEntries.map(([key, value]) => (
            <div key={key}><span>{key}</span><strong>{value}</strong></div>
          )) : <p className="obs-muted">No patch queue totals recorded.</p>}
        </div>
        <div className="activity-signal-list">
          <div className="obs-item-title">
            <strong>Signals</strong>
            <CompactBadge label="active" value={signals.active_count} tone={number(signals.active_count) > 0 ? "warn" : "quiet"} />
          </div>
          {[...nudges, ...completed].length ? (
            [...nudges, ...completed].map((item, index) => (
              <ManifestRow item={item} key={`${text(item.id ?? item.run_id, "signal")}-${index}`} />
            ))
          ) : (
            <p className="obs-muted">No active or recently completed signals.</p>
          )}
        </div>
      </div>
    </ObsSection>
  );
}

function ReviewSummarySection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  const review = props.snapshot?.review ?? {};
  const items = review.items ?? [];
  const issues = review.known_issues ?? [];
  const firstReview: Record<string, unknown> = props.snapshot?.validation_safety.first_review ?? {};
  const firstReviewStatus = text(firstReview.status ?? firstReview.state, "not recorded");
  return (
    <ObsSection title="Review summary" className={props.className}>
      <div className="activity-review-grid">
        <div className="obs-validation-card">
          <div className="obs-validation-title">
            <strong>Scorecard</strong>
            <CompactBadge value={props.snapshot?.scorecard.status ?? "not recorded"} tone={props.snapshot?.scorecard.status ?? "info"} />
          </div>
          <p>{text(props.snapshot?.scorecard.summary, "No scorecard summary recorded.")}</p>
        </div>
        <div className="obs-validation-card">
          <div className="obs-validation-title">
            <strong>First review</strong>
            <CompactBadge value={firstReviewStatus} tone={firstReviewStatus} />
          </div>
          <p>{text(firstReview.summary ?? firstReview.detail ?? firstReview.message, "No review check recorded.")}</p>
        </div>
        <div className="obs-compact-table">
          <div><span>Items</span><strong>{items.length}</strong></div>
          <div><span>Known issues</span><strong>{issues.length}</strong></div>
        </div>
      </div>
    </ObsSection>
  );
}

export function ObservatoryPage(props: {
  snapshot: ProjectSnapshot | null;
  loading: boolean;
  onChoose: () => void;
  onRefresh: () => void;
  initialSnapshot?: ObservatorySnapshot | null;
}) {
  const target = props.snapshot?.target.path ?? "";
  const generatedMarker = props.snapshot?.run.snapshot_generated_at ?? "";
  const exportDir = useMemo(() => (target ? targetSubdir(target, "first-review") : ""), [target]);
  const [snapshot, setSnapshot] = useState<ObservatorySnapshot | null>(props.initialSnapshot ?? null);
  const [activeTab, setActiveTab] = useState<ObservatoryTab>("Summary");
  const [selectedRoleName, setSelectedRoleName] = useState("");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("all");
  const [selectedEventId, setSelectedEventId] = useState("");
  const [busy, setBusy] = useState<"refresh" | "export" | null>(null);
  const [error, setError] = useState("");

  async function loadSnapshot(options: { refreshProject?: boolean } = {}) {
    if (!target) return;
    setBusy("refresh");
    setError("");
    try {
      const payload: BackendEnvelope<ObservatorySnapshot> = await runBackendCommand({
        command: "observatory.snapshot",
        target,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not load activity.");
        return;
      }
      setSnapshot(payload.data);
      if (options.refreshProject) props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function exportBundle() {
    if (!target) return;
    setBusy("export");
    setError("");
    try {
      const payload: BackendEnvelope<ReviewExportData> = await runBackendCommand({
        command: "review.export_bundle",
        target,
        reviewDir: exportDir,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not export review files.");
        return;
      }
      props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (!target) {
      setSnapshot(null);
      return;
    }
    void loadSnapshot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, generatedMarker]);

  const activityEvents = useMemo(() => buildActivityEvents(snapshot), [snapshot]);

  useEffect(() => {
    const roles = snapshot?.conveyor.roles ?? [];
    if (!roles.length) {
      setSelectedRoleName("");
      return;
    }
    if (selectedRoleName && roles.some((role) => role.role === selectedRoleName)) return;
    const activeRole = text(snapshot?.conveyor.active_run?.role, "");
    const defaultRole = activeRole || roles.find((role) => role.status === "running")?.role || roles.find((role) => role.status === "next")?.role || roles[0].role;
    setSelectedRoleName(defaultRole);
  }, [selectedRoleName, snapshot]);

  if (!target || !props.snapshot) {
    return (
      <section className="observatory-page native">
        <div className="observatory-shell empty">
          <Telescope size={22} />
          <h1>Activity</h1>
          <p>Choose a project folder to load activity.</p>
          <button className="primary-action" onClick={props.onChoose}>Choose project</button>
        </div>
      </section>
    );
  }

  const disabled = props.loading || busy !== null;
  const activeRun = snapshot?.conveyor.active_run ?? {};
  const health = snapshot?.conveyor.health ?? {};
  const selectedRole = snapshot?.conveyor.roles.find((role) => role.role === selectedRoleName) ?? null;

  return (
    <section className="observatory-page native">
      <header className="obs-page-header">
        <div className="obs-page-title">
          <h1>Activity</h1>
          <p>Run, queue, commit, and check state from the selected target.</p>
        </div>
        <aside className="obs-project-panel actions-only">
          <div className="observatory-actions">
            <button className="icon-text-button" disabled={disabled} onClick={() => loadSnapshot({ refreshProject: true })}>
              {busy === "refresh" ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              Refresh
            </button>
            <button className="icon-text-button" disabled={disabled} onClick={exportBundle}>
              {busy === "export" ? <Loader2 size={14} className="spin" /> : <FileDown size={14} />}
              Export review
            </button>
          </div>
        </aside>
      </header>

      <MissionStrip snapshot={snapshot} activeRun={activeRun} />

      {error && <div className="observatory-error" role="alert">{error}</div>}

      <div className="obs-tabs" role="tablist" aria-label="Activity sections">
        {tabs.map((tab) => (
          <button
            aria-selected={activeTab === tab}
            key={tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => setActiveTab(tab)}
            role="tab"
            type="button"
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Summary" && (
        <main className="obs-summary-layout activity-overview">
          <ConveyorSection
            snapshot={snapshot}
            activeRun={activeRun}
            health={health}
            className="obs-summary-conveyor"
            selectedRole={selectedRoleName}
            onSelectRole={(role) => {
              setSelectedRoleName(role.role);
              setActivityFilter(roleFilters.includes(role.role as typeof roleFilters[number]) ? role.role as ActivityFilter : "system");
            }}
          />
          <div className="activity-side-grid">
            <ActiveRunSection activeRun={activeRun} health={health} />
            <SelectedRoleInspector role={selectedRole} events={activityEvents} />
          </div>
          <ActivityEventLedger
            events={activityEvents}
            filter={activityFilter}
            selectedId={selectedEventId}
            onFilter={setActivityFilter}
            onSelect={setSelectedEventId}
            className="activity-main-ledger"
          />
          <div className="obs-summary-lower activity-bottom-grid">
            <PatchSignalSection snapshot={snapshot} />
            <ValidationSafetySection snapshot={snapshot} />
            <RuntimeMetricsSection snapshot={snapshot} />
            <ReviewSummarySection snapshot={snapshot} />
            <RecentOutcomesSection snapshot={snapshot} className="activity-wide-section" />
          </div>
          <LandedWorkSection snapshot={snapshot} className="obs-summary-landed" />
        </main>
      )}

      {activeTab === "Events" && <TimelineSection snapshot={snapshot} />}

      {activeTab === "Queue" && <PatchesSection snapshot={snapshot} />}

      {activeTab === "Metrics" && (
        <div className="obs-tab-grid">
          <ObsSection title="Scorecard" className="span-2">
            <MetricTable rows={snapshot?.scorecard.counts ?? []} />
          </ObsSection>
          <RuntimeMetricsSection snapshot={snapshot} />
          <ValidationSafetySection snapshot={snapshot} className="span-3" />
        </div>
      )}
    </section>
  );
}
