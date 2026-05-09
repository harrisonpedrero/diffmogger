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
      label: "Blocker",
      value: text(snapshot?.mission.known_issue, "No active issue summary."),
      tone: knownIssue ? "warn" : "quiet",
    },
  ];

  return (
    <section className="obs-mission-strip" aria-label="Target state">
      {items.map((item) => (
        <div className={`obs-mission-strip-item ${item.tone}`} key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </section>
  );
}

function RoleCard(props: { role: ObservatoryRoleCard }) {
  const counts = props.role.counts ?? {};
  return (
    <div className={`obs-role ${props.role.status}`}>
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
    </div>
  );
}

function ConveyorSection(props: {
  snapshot: ObservatorySnapshot | null;
  activeRun: Record<string, unknown>;
  health: Record<string, unknown>;
  className?: string;
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
                  <RoleCard role={role} />
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

      {error && <div className="observatory-error">{error}</div>}

      <div className="obs-tabs" role="tablist" aria-label="Activity sections">
        {tabs.map((tab) => (
          <button
            key={tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => setActiveTab(tab)}
            type="button"
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Summary" && (
        <main className="obs-summary-layout">
          <ConveyorSection snapshot={snapshot} activeRun={activeRun} health={health} className="obs-summary-conveyor" />
          <LandedWorkSection snapshot={snapshot} className="obs-summary-landed" />
          <div className="obs-summary-lower">
            <RecentOutcomesSection snapshot={snapshot} />
            <RuntimeMetricsSection snapshot={snapshot} />
          </div>
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
