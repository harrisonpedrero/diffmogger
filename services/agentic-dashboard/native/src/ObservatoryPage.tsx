import {
  Clipboard,
  ExternalLink,
  FileDown,
  FolderOpen,
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
import { openObservatoryFile, revealReviewArtifact, runBackendCommand } from "./api/backend";
import { buildObservatoryViewModel, type ObservatoryTab } from "./observatoryModel";
import { useChunkedLimit } from "./performance";

type ObservatoryHtmlData = {
  html_path: string;
  snapshot_generated_at?: string;
};

type ReviewExportData = {
  html_path: string;
  markdown_path: string;
  snapshot_generated_at?: string;
};

const tabs: ObservatoryTab[] = ["Summary", "Timeline", "Patches", "Metrics"];

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

function tagValue(snapshot: ObservatorySnapshot | null, label: string): string {
  const normalized = label.toLowerCase();
  const tag = snapshot?.mission.tags.find((item) => item.label.toLowerCase() === normalized);
  return text(tag?.value, "");
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
  projectSnapshot: ProjectSnapshot;
  activeRun: Record<string, unknown>;
}) {
  const snapshot = props.snapshot;
  const branch = text(props.projectSnapshot.run.git?.branch ?? tagValue(snapshot, "Branch"), "No branch recorded");
  const knownIssue = hasKnownIssue(snapshot?.mission.known_issue);
  const items = [
    {
      label: "Status",
      value: readableState(snapshot?.mission.automation_status, "No automation status recorded yet"),
      tone: tone(snapshot?.mission.automation_status),
    },
    {
      label: "Current horizon",
      value: readableState(snapshot?.mission.current_horizon, "No horizon recorded yet"),
      tone: "info",
    },
    { label: "Branch", value: branch, tone: "quiet" },
    { label: "Running / next lane", value: laneLabel(snapshot, props.activeRun), tone: text(props.activeRun.role, "") ? "running" : "next" },
    {
      label: "Best next milestone",
      value: text(snapshot?.mission.best_next_milestone, "No milestone recorded yet."),
      tone: "good",
    },
    {
      label: "Known issue / blocker",
      value: text(snapshot?.mission.known_issue, "No active issue summary."),
      tone: knownIssue ? "warn" : "quiet",
    },
  ];

  return (
    <section className="obs-mission-strip" aria-label="Mission State">
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
    <ObsSection title="Conveyor Belt" className={`obs-conveyor-section ${props.className ?? ""}`}>
      <div className="obs-conveyor-layout">
        <div className="obs-horizontal-scroll" aria-label="Conveyor roles">
          <div className="obs-belt">
            {roles.length ? (
              roles.map((role, index) => (
                <div className="obs-belt-step" key={role.role}>
                  <RoleCard role={role} />
                  {index < roles.length - 1 && <span className="obs-belt-arrow" aria-hidden="true">→</span>}
                </div>
              ))
            ) : (
              <p className="obs-muted">No conveyor roles recorded yet.</p>
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
              <div>The conveyor is waiting for the next eligible automation decision.</div>
            </div>
          )}
          <div className={`obs-health ${tone(props.health.status)}`}>
            <strong>{text(props.health.status, "ok").toUpperCase()}</strong>
            <p>{text(props.health.summary, "builder-first conveyor policy active.")}</p>
          </div>
          <div className="obs-conveyor-kpis">
            <div>
              <span>Cycles</span>
              <strong>{number(props.snapshot?.conveyor.cycles)}</strong>
            </div>
            <div>
              <span>Signals</span>
              <strong>{number(props.snapshot?.signals.active_count)}</strong>
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
      <div className="obs-commit-title">{text(commit.subject, "Commit landed")}</div>
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
    <ObsSection title="Landed Work" className={props.className}>
      <div className="obs-horizontal-scroll" aria-label="Landed work">
        <div className="obs-landed-rail">
          {(props.snapshot?.progress.landed_work_feed ?? []).length ? (
            props.snapshot?.progress.landed_work_feed.slice(0, 6).map((commit, index) => (
              <CommitCard commit={commit} rail key={`${commit.hash}-${index}`} />
            ))
          ) : (
            <p className="obs-muted">No landed work recorded yet.</p>
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
    <ObsSection title="Recent Outcomes" className={props.className}>
      <div className="obs-list">
        {(props.snapshot?.progress.recent_outcomes ?? []).length ? (
          props.snapshot?.progress.recent_outcomes.slice(0, 5).map((item, index) => (
            <ManifestRow item={item} key={`${text(item.run_id, "outcome")}-${index}`} />
          ))
        ) : (
          <p className="obs-muted">No recent applied, failed, or skipped role outputs yet.</p>
        )}
      </div>
    </ObsSection>
  );
}

function SignalNudgesSection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  return (
    <ObsSection title="Signal Nudges" className={props.className}>
      <div className="obs-list">
        {(props.snapshot?.signals.nudges ?? []).length ? (
          props.snapshot?.signals.nudges.map((item, index) => (
            <div className="obs-item-row" key={`${text(item.id, "signal")}-${index}`}>
              <div className="obs-item-title">
                <strong>{text(item.id, "signal")}</strong>
                <CompactBadge value={item.priority ?? "medium"} tone={text(item.priority, "info")} />
              </div>
              <p>{text(item.instructions, "No instructions recorded.")}</p>
              <small>{text(item.owner_role, "unknown")} · due {text(item.next_due_at, "unknown")}</small>
            </div>
          ))
        ) : (
          <p className="obs-muted">No active automation signals.</p>
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

function ProgressStorySection(props: {
  snapshot: ObservatorySnapshot | null;
  latest: ObservatoryCommit;
  className?: string;
}) {
  return (
    <ObsSection title="Progress Story" className={props.className}>
      <div className="obs-story">
        <h3>{text(props.snapshot?.progress.story, "No progress pulse yet.")}</h3>
        {Object.keys(props.latest).length > 0 && (
          <div className="obs-latest">
            <strong>Latest landed work</strong>
            <CommitCard commit={props.latest} compact />
          </div>
        )}
      </div>
    </ObsSection>
  );
}

function RuntimeMetricsSection(props: { snapshot: ObservatorySnapshot | null; className?: string }) {
  const metricEntries = useMemo(() => Object.entries(props.snapshot?.metrics ?? {}), [props.snapshot?.metrics]);
  return (
    <ObsSection title="Runtime Metrics" className={props.className}>
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
    <ObsSection title="Event Timeline" className="obs-tab-section">
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
          <p className="obs-muted">No conveyor history yet.</p>
        )}
        {limit < timeline.length && <p className="obs-muted">Rendering remaining timeline events...</p>}
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
      <ObsSection title="Queued / Deferred Patches" className="span-2">
        <div className="obs-list">
          {manifests.length ? (
            visibleManifests.map((item, index) => (
              <ManifestRow item={item} key={`${text(item.run_id, "patch")}-${index}`} />
            ))
          ) : (
            <p className="obs-muted">No queued or deferred patches yet.</p>
          )}
          {manifestLimit < manifests.length && <p className="obs-muted">Rendering remaining patches...</p>}
        </div>
      </ObsSection>
      <ObsSection title="Queue Totals">
        <div className="obs-compact-table">
          {queueEntries.map(([key, value]) => (
            <div key={key}><span>{key}</span><strong>{value}</strong></div>
          ))}
        </div>
      </ObsSection>
      <ObsSection title="Recent Outcomes" className="span-3">
        <div className="obs-list two">
          {visibleOutcomes.map((item, index) => (
            <ManifestRow item={item} key={`${text(item.run_id, "outcome")}-${index}`} />
          ))}
        </div>
        {outcomeLimit < outcomes.length && <p className="obs-muted">Rendering remaining outcomes...</p>}
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
    { label: "First review", record: safety.first_review },
  ];

  return (
    <ObsSection title="Validation / Safety" className={props.className}>
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
  const reviewDir = useMemo(() => (target ? targetSubdir(target, "native-observatory") : ""), [target]);
  const exportDir = useMemo(() => (target ? targetSubdir(target, "first-review") : ""), [target]);
  const [snapshot, setSnapshot] = useState<ObservatorySnapshot | null>(props.initialSnapshot ?? null);
  const [activeTab, setActiveTab] = useState<ObservatoryTab>("Summary");
  const [htmlPath, setHtmlPath] = useState("");
  const [markdownPath, setMarkdownPath] = useState("");
  const [busy, setBusy] = useState<"refresh" | "open" | "reveal" | "export" | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const model = useMemo(() => buildObservatoryViewModel(snapshot), [snapshot]);

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
        setError(payload.message ?? "Could not load the Observatory snapshot.");
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

  async function generateHtmlPath(): Promise<string> {
    if (htmlPath) return htmlPath;
    const payload: BackendEnvelope<ObservatoryHtmlData> = await runBackendCommand({
      command: "observatory.load_html",
      target,
      reviewDir,
    });
    if (!payload.ok || !payload.data) {
      throw new Error(payload.message ?? "Could not generate the Observatory HTML.");
    }
    setHtmlPath(payload.data.html_path);
    return payload.data.html_path;
  }

  async function openInBrowser() {
    if (!target) return;
    setBusy("open");
    setError("");
    try {
      const path = await generateHtmlPath();
      await openObservatoryFile(path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function revealGeneratedHtml() {
    if (!target) return;
    setBusy("reveal");
    setError("");
    try {
      const path = await generateHtmlPath();
      await revealReviewArtifact(path);
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
        setError(payload.message ?? "Could not export the review bundle.");
        return;
      }
      setHtmlPath(payload.data.html_path);
      setMarkdownPath(payload.data.markdown_path);
      props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function copyPath() {
    const path = htmlPath || markdownPath;
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setError("Could not copy the Observatory path from this environment.");
    }
  }

  useEffect(() => {
    if (!target) {
      setSnapshot(null);
      setHtmlPath("");
      setMarkdownPath("");
      return;
    }
    void loadSnapshot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, generatedMarker]);

  const selectedSnapshot = props.snapshot;
  if (!target || !selectedSnapshot) {
    return (
      <section className="observatory-page native">
        <div className="observatory-shell empty">
          <Telescope size={22} />
          <h1>Diffmogger Autonomous Build Log</h1>
          <p>Choose a project folder to load the native Observatory.</p>
          <button className="primary-action" onClick={props.onChoose}>Choose Project Folder</button>
        </div>
      </section>
    );
  }

  const disabled = props.loading || busy !== null;
  const activeRun = snapshot?.conveyor.active_run ?? {};
  const health = snapshot?.conveyor.health ?? {};
  const latest = snapshot?.progress.latest_landed_work ?? {};

  return (
    <section className="observatory-page native">
      <header className="obs-page-header">
        <div className="obs-page-title">
          <span className="obs-eyebrow">Native Observatory</span>
          <h1>{snapshot?.title ?? "Diffmogger Autonomous Build Log"}</h1>
          <p>{snapshot?.subtitle ?? "Diffmogger Observatory view: replay-style automation progress reconstructed from conveyor events, commits, and diff stats."}</p>
          <div className="obs-chips">
            {(snapshot?.mission.tags ?? []).map((item) => (
              <CompactBadge key={`${item.label}-${item.value}`} label={item.label} value={item.value} tone={item.tone} />
            ))}
          </div>
        </div>
        <aside className="obs-project-panel">
          <span>Project</span>
          <strong>{text(snapshot?.mission.project_name, selectedSnapshot.target.name ?? "target")}</strong>
          <small>Updated {text(snapshot?.generated_at, "not yet")}</small>
          <div className={`obs-status-callout ${tone(snapshot?.mission.automation_status)}`}>
            <b>{model.headline}</b>
            <em>{model.subheadline}</em>
          </div>
          <div className="observatory-actions">
            <button className="icon-text-button" disabled={disabled} onClick={() => loadSnapshot({ refreshProject: true })}>
              {busy === "refresh" ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              Refresh
            </button>
            <button className="icon-text-button" disabled={disabled} onClick={openInBrowser}>
              <ExternalLink size={14} />
              Open in Browser
            </button>
            <button className="icon-text-button" disabled={disabled} onClick={exportBundle}>
              {busy === "export" ? <Loader2 size={14} className="spin" /> : <FileDown size={14} />}
              Export Bundle
            </button>
            <button className="icon-text-button" disabled={disabled} onClick={revealGeneratedHtml}>
              <FolderOpen size={14} />
              Reveal
            </button>
            <button className="icon-text-button" disabled={!htmlPath && !markdownPath} onClick={copyPath}>
              <Clipboard size={14} />
              {copied ? "Copied" : "Copy path"}
            </button>
          </div>
        </aside>
      </header>

      <MissionStrip snapshot={snapshot} projectSnapshot={selectedSnapshot} activeRun={activeRun} />

      {error && <div className="observatory-error">{error}</div>}

      <div className="obs-tabs" role="tablist" aria-label="Observatory sections">
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
            <ProgressStorySection snapshot={snapshot} latest={latest} />
            <RecentOutcomesSection snapshot={snapshot} />
            <SignalNudgesSection snapshot={snapshot} />
          </div>
        </main>
      )}

      {activeTab === "Timeline" && <TimelineSection snapshot={snapshot} />}

      {activeTab === "Patches" && <PatchesSection snapshot={snapshot} />}

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
