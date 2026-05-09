import {
  CheckCircle2,
  Clipboard,
  ClipboardCheck,
  ExternalLink,
  FileDown,
  FolderOpen,
  Loader2,
  RefreshCw,
  Send,
} from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { BackendEnvelope, ObservatoryCommit, ProjectSnapshot, ReviewChangedFile, ReviewSnapshot } from "./api/backend";
import { openReviewArtifact, revealReviewArtifact, runBackendCommand } from "./api/backend";
import { useChunkedLimit, useDeferredStage } from "./performance";

type ReviewExportData = {
  html_path: string;
  markdown_path: string;
  review_dir: string;
  snapshot_generated_at?: string;
};

type MarkReviewedData = {
  marker_path: string;
  reviewed: ReviewSnapshot["reviewed"];
};

const followupIntents = [
  { value: "info", label: "General note" },
  { value: "done", label: "Done / completed" },
  { value: "approve", label: "Approved" },
  { value: "reject", label: "Rejected" },
  { value: "unknown", label: "Not sure" },
];

function text(value: unknown, fallback = "Not recorded"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function formatTimestamp(value?: string): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statusTone(value: unknown): string {
  const raw = text(value, "info").toLowerCase();
  if (["pass", "passed", "ready", "clear", "active", "reviewed", "ok"].includes(raw)) return "good";
  if (["fail", "failed", "blocked", "critical", "critical_stop", "error"].includes(raw)) return "bad";
  if (["warn", "warning", "pending", "not_recorded", "not recorded", "unknown", "skipped"].includes(raw)) return "warn";
  if (["quiet", "none"].includes(raw)) return "quiet";
  return "info";
}

function ReviewSection(props: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`review-section ${props.className ?? ""}`}>
      <h2>{props.title}</h2>
      {props.children}
    </section>
  );
}

function DeferredReviewSection(props: { title: string }) {
  return (
    <ReviewSection title={props.title}>
      <div className="review-deferred-panel">
        <div className="skeleton-line medium" />
        <div className="skeleton-line" />
      </div>
    </ReviewSection>
  );
}

function ReviewBadge(props: { value: unknown; tone?: string; label?: string }) {
  return (
    <span className={`review-badge ${statusTone(props.tone ?? props.value)}`}>
      {props.label ? `${props.label}: ` : ""}
      {text(props.value, "not recorded").replace(/_/g, " ")}
    </span>
  );
}

function countSummary(counts: Record<string, number> | undefined): string {
  return `${number(counts?.pass)} pass · ${number(counts?.fail)} fail · ${number(counts?.warn)} warn · ${number(counts?.pending)} pending`;
}

function buildTrustVerdict(snapshot: ReviewSnapshot | null, projectSnapshot: ProjectSnapshot): { label: string; tone: string; summary: string } {
  if (!snapshot) {
    return {
      label: "No review data",
      tone: "warn",
      summary: "Review evidence is loading.",
    };
  }

  const counts = snapshot.verification.counts ?? {};
  const fail = number(counts.fail);
  const warn = number(counts.warn);
  const pending = number(counts.pending);
  const limitations = snapshot.limitations.length;
  const human = number(projectSnapshot.home.pending_human_requests) + number(projectSnapshot.home.unhandled_inbox);
  const status = text(snapshot.latest_run.status, projectSnapshot.home.automation_status).toUpperCase();
  const safetyTone = statusTone(snapshot.safety.status);

  if (status.includes("CRITICAL") || status.includes("BLOCKED") || safetyTone === "bad") {
    return {
      label: "Blocked",
      tone: "bad",
      summary: "A blocker or failed safety state is recorded.",
    };
  }
  if (fail > 0 || human > 0) {
    return {
      label: "Needs review",
      tone: "warn",
      summary: "Failed verification or pending input is attached to this run.",
    };
  }
  if (warn > 0 || pending > 0 || limitations > 0 || !snapshot.reviewed.exists) {
    return {
      label: "Review needed",
      tone: "warn",
      summary: "Some checks are pending, skipped, or unreviewed.",
    };
  }
  return {
    label: "Clear",
    tone: "good",
    summary: "Safety and verification evidence are clear, and this run is reviewed.",
  };
}

const TrustSummaryCard = memo(function TrustSummaryCard(props: {
  snapshot: ReviewSnapshot | null;
  projectSnapshot: ProjectSnapshot;
  verdict: { label: string; tone: string; summary: string };
}) {
  const counts = props.snapshot?.verification.counts ?? {};
  const human = number(props.projectSnapshot.home.pending_human_requests) + number(props.projectSnapshot.home.unhandled_inbox);
  const items = [
    { label: "Safety", value: text(props.snapshot?.safety.status, "not recorded"), tone: props.snapshot?.safety.status },
    { label: "Verification", value: countSummary(counts), tone: number(counts.fail) > 0 ? "bad" : number(counts.warn) > 0 || number(counts.pending) > 0 ? "warn" : "good" },
    { label: "Skipped / limited", value: `${props.snapshot?.limitations.length ?? 0} recorded`, tone: (props.snapshot?.limitations.length ?? 0) > 0 ? "warn" : "good" },
    { label: "Changed files", value: `${props.snapshot?.changed_files.length ?? 0} files`, tone: (props.snapshot?.changed_files.length ?? 0) > 0 ? "info" : "quiet" },
    { label: "Human input", value: human ? `${human} pending` : "none pending", tone: human ? "warn" : "good" },
  ];

  return (
    <ReviewSection title={props.verdict.label} className={`review-trust-summary ${props.verdict.tone}`}>
      <div className="review-verdict-line">
        <p>{props.verdict.summary}</p>
      </div>
      <div className="review-trust-grid">
        {items.map((item) => (
          <div className="review-trust-item" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <ReviewBadge value={text(item.tone, "info")} tone={text(item.tone, "info")} />
          </div>
        ))}
      </div>
    </ReviewSection>
  );
});

const LatestRunSummaryCard = memo(function LatestRunSummaryCard(props: {
  snapshot: ReviewSnapshot | null;
}) {
  const actionPlan = props.snapshot?.latest_run.action_plan ?? {};
  const recommendation = text(
    actionPlan["recommendation"] ?? actionPlan["next_action"] ?? actionPlan["summary"],
    "No next-run recommendation recorded yet.",
  );

  return (
    <ReviewSection title="Next action">
      <p className="review-muted">{recommendation}</p>
    </ReviewSection>
  );
});

const SafetyCheckCard = memo(function SafetyCheckCard(props: { snapshot: ReviewSnapshot | null }) {
  return (
    <ReviewSection title="Safety check">
      <div className={`review-status-card ${statusTone(props.snapshot?.safety.status)}`}>
        <div className="review-card-heading">
          <strong>Integration safety</strong>
          <ReviewBadge value={text(props.snapshot?.safety.status, "not recorded")} tone={text(props.snapshot?.safety.status, "warn")} />
        </div>
        <p>{text(props.snapshot?.safety.summary, "No integration-safety check result recorded yet.")}</p>
        <code>{text(props.snapshot?.safety.command, "python3 scripts/check_integration_safety.py")}</code>
      </div>
    </ReviewSection>
  );
});

const ChangedFilesList = memo(function ChangedFilesList(props: { files: ReviewChangedFile[]; source?: string }) {
  const limit = useChunkedLimit(props.files.length, 80, 160, props.files);
  const visibleFiles = useMemo(() => props.files.slice(0, limit), [limit, props.files]);
  return (
    <ReviewSection title="Changed files">
      {(props.files ?? []).length ? (
        <div className="review-file-list">
          {visibleFiles.map((file) => {
            const record = file as ReviewChangedFile & Record<string, unknown>;
            const additions = number(record.additions);
            const deletions = number(record.deletions);
            const stats = additions || deletions ? `+${additions} / -${deletions}` : text(file.summary, "No diff stats");
            return (
              <div className="review-file-row" key={`${file.kind}-${file.path}`}>
                <ReviewBadge value={file.status || "LANDED"} tone={file.status || "info"} />
                <code title={file.path}>{file.path}</code>
                <span className="review-diff-stat">{stats}</span>
              </div>
            );
          })}
          {limit < props.files.length && (
            <p className="review-muted">Rendering more files...</p>
          )}
        </div>
      ) : (
        <p className="review-muted">No changed files are visible from git or generated-file state yet.</p>
      )}
      <small>Source: {text(props.source, "unknown")}</small>
    </ReviewSection>
  );
});

const VerificationEvidenceList = memo(function VerificationEvidenceList(props: { snapshot: ReviewSnapshot | null }) {
  const counts = props.snapshot?.verification.counts ?? {};
  const items = props.snapshot?.verification.items ?? [];
  const limit = useChunkedLimit(items.length, 12, 60, items);
  const visibleItems = useMemo(() => items.slice(0, limit), [items, limit]);
  return (
    <ReviewSection title="Verification">
      <div className="review-evidence-summary">
        <strong>{countSummary(counts)}</strong>
        <p>{text(props.snapshot?.verification.summary, "No validation results recorded yet.")}</p>
      </div>
      <div className="review-check-list">
        {items.length ? (
          visibleItems.map((item, index) => {
            const title = text(item.title ?? item.name ?? item.text, "No check detail recorded.");
            const details = text(item.detail ?? item.summary ?? item.output ?? item.message, "");
            const command = text(item.command, "");
            return (
              <div className={`review-check ${statusTone(item.status)}`} key={`${title}-${index}`}>
                <ReviewBadge value={text(item.status, "info")} tone={text(item.status, "info")} />
                <div>
                  <strong>{title}</strong>
                  {details && details !== title && <p>{details}</p>}
                  {command && <code>{command}</code>}
                </div>
              </div>
            );
          })
        ) : (
          <p className="review-muted">No individual verification checks are recorded yet.</p>
        )}
        {limit < items.length && (
          <p className="review-muted">Rendering more checks...</p>
        )}
      </div>
    </ReviewSection>
  );
});

const LandedWorkRail = memo(function LandedWorkRail(props: { commits: ObservatoryCommit[] }) {
  const limit = useChunkedLimit(props.commits.length, 8, 16, props.commits);
  const visibleCommits = useMemo(() => props.commits.slice(0, limit), [limit, props.commits]);
  return (
    <ReviewSection title="Commits">
      {(props.commits ?? []).length ? (
        <div className="review-commit-rail" aria-label="Commits">
          {visibleCommits.map((commit) => (
            <article className="review-commit-card" key={commit.hash}>
              <strong>{text(commit.subject, "Commit")}</strong>
              <p>{text(commit.summary, "No commit summary recorded.")}</p>
              <footer>
                <code>{text(commit.hash, "no-hash")}</code>
                <span>{number(commit.file_count)} files</span>
                <span className="review-diff-stat">+{number(commit.additions)} / -{number(commit.deletions)}</span>
                <span>{formatTimestamp(commit.time)}</span>
              </footer>
            </article>
          ))}
          {limit < props.commits.length && (
            <div className="review-commit-card">
              <strong>Rendering more commits...</strong>
            </div>
          )}
        </div>
      ) : (
        <p className="review-muted">No commits are visible yet. Run or refresh activity.</p>
      )}
    </ReviewSection>
  );
});

const SkippedChecksCard = memo(function SkippedChecksCard(props: { limitations: Array<Record<string, unknown>> }) {
  const limit = useChunkedLimit(props.limitations.length, 30, 80, props.limitations);
  const visibleLimitations = useMemo(() => props.limitations.slice(0, limit), [limit, props.limitations]);
  return (
    <ReviewSection title="Skipped checks">
      {(props.limitations ?? []).length ? (
        <div className="review-limitations">
          {visibleLimitations.map((item, index) => (
            <div className={`review-limitation ${statusTone(item.status)}`} key={`${text(item.text, "limitation")}-${index}`}>
              <ReviewBadge value={text(item.source, "environment")} tone={text(item.status, "warn")} />
              <span>{text(item.text, "No limitation detail recorded.")}</span>
            </div>
          ))}
          {limit < props.limitations.length && (
            <p className="review-muted">Rendering more skipped checks...</p>
          )}
        </div>
      ) : (
        <p className="review-muted">No skipped checks recorded.</p>
      )}
    </ReviewSection>
  );
});

const ArtifactCard = memo(function ArtifactCard(props: {
  label: string;
  path: string;
  copied: boolean;
  disabled: boolean;
  onCopy: () => void;
  onReveal: () => void;
}) {
  return (
    <div className="review-artifact-card">
      <span>{props.label}</span>
      <code title={props.path}>{props.path || "Not exported yet"}</code>
      <div className="review-bundle-actions">
        <button className="icon-text-button" disabled={props.disabled || !props.path} onClick={props.onCopy}>
          <Clipboard size={13} />
          {props.copied ? "Copied" : "Copy"}
        </button>
        <button className="icon-text-button" disabled={props.disabled} onClick={props.onReveal}>
          <FolderOpen size={13} />
          Reveal
        </button>
      </div>
    </div>
  );
});

export function ReviewPage(props: {
  snapshot: ProjectSnapshot;
  loading: boolean;
  onNavigate: (view: "Run" | "Observatory" | "Inbox") => void;
  onRefresh: () => void;
}) {
  const target = props.snapshot.target.path;
  const [snapshot, setSnapshot] = useState<ReviewSnapshot | null>(null);
  const [busy, setBusy] = useState<"load" | "export" | "open" | "reveal" | "mark" | "followup" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [markdownPath, setMarkdownPath] = useState("");
  const [copiedPath, setCopiedPath] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [followup, setFollowup] = useState("");
  const [followupIntent, setFollowupIntent] = useState("info");

  const reviewDir = useMemo(
    () => snapshot?.bundle.review_dir ?? `${target.replace(/[\\/]+$/, "")}/target/first-review`,
    [snapshot, target],
  );
  const deferredStage = useDeferredStage(
    snapshot?.generated_at ?? props.snapshot.run.snapshot_generated_at ?? target,
    2,
  );
  const changedFiles = useMemo(() => snapshot?.changed_files ?? [], [snapshot?.changed_files]);
  const latestCommits = useMemo(() => snapshot?.latest_commits ?? [], [snapshot?.latest_commits]);
  const limitations = useMemo(() => snapshot?.limitations ?? [], [snapshot?.limitations]);
  const verdict = useMemo(
    () => buildTrustVerdict(snapshot, props.snapshot),
    [props.snapshot, snapshot],
  );

  async function loadReview(options: { refreshProject?: boolean } = {}) {
    setBusy("load");
    setError("");
    try {
      const payload: BackendEnvelope<ReviewSnapshot> = await runBackendCommand({
        command: "review.load",
        target,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not load review state.");
        return;
      }
      setSnapshot(payload.data);
      setMarkdownPath(payload.data.bundle.markdown_path);
      if (options.refreshProject) props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function exportBundle(): Promise<ReviewExportData | null> {
    setBusy("export");
    setError("");
    try {
      const payload: BackendEnvelope<ReviewExportData> = await runBackendCommand({
        command: "review.export_bundle",
        target,
        reviewDir,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not export review files.");
        return null;
      }
      setMarkdownPath(payload.data.markdown_path);
      setNotice("Review export written.");
      props.onRefresh();
      await loadReview();
      return payload.data;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function ensureBundle(): Promise<ReviewExportData | null> {
    return exportBundle();
  }

  async function openArtifact() {
    setBusy("open");
    setError("");
    try {
      const bundle = await ensureBundle();
      if (!bundle) return;
      await openReviewArtifact(bundle.markdown_path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function revealArtifact() {
    setBusy("reveal");
    setError("");
    try {
      const bundle = await ensureBundle();
      if (!bundle) return;
      await revealReviewArtifact(bundle.markdown_path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function copyArtifactPath(path: string, label: string) {
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(label);
      window.setTimeout(() => setCopiedPath(""), 1400);
    } catch {
      setError("Could not copy the review artifact path from this environment.");
    }
  }

  async function markReviewed() {
    setBusy("mark");
    setError("");
    try {
      const payload: BackendEnvelope<MarkReviewedData> = await runBackendCommand({
        command: "review.mark_reviewed",
        target,
        body: reviewNote,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not mark this target reviewed.");
        return;
      }
      setNotice("Review marker recorded.");
      setReviewNote("");
      await loadReview({ refreshProject: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function sendFollowup() {
    if (!followup.trim()) return;
    setBusy("followup");
    setError("");
    try {
      const payload: BackendEnvelope<{ inbox_id: string }> = await runBackendCommand({
        command: "inbox.send_note",
        target,
        body: followup,
        intent: followupIntent,
        related: "review-follow-up",
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not send the follow-up note.");
        return;
      }
      setNotice(`Follow-up queued as ${payload.data.inbox_id}.`);
      setFollowup("");
      props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    void loadReview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, props.snapshot.run.snapshot_generated_at]);

  if (!props.snapshot.target.automation_task_exists) {
    return (
      <section className="review-page">
        <div className="review-empty">
          <ClipboardCheck size={26} />
          <h1>Review unavailable</h1>
          <p>Complete setup and run once before reviewing output.</p>
          <div>
            <button className="primary-action" onClick={() => props.onNavigate("Run")}>Run</button>
            <button className="secondary-action" onClick={() => props.onNavigate("Observatory")}>Activity</button>
          </div>
        </div>
      </section>
    );
  }

  const disabled = props.loading || busy !== null;
  const selfReviewPath = markdownPath || snapshot?.bundle.markdown_path || "";

  async function copySelfReviewMarkdown() {
    const markdown = snapshot?.self_review.markdown_preview ?? "";
    if (!markdown) return;
    try {
      await navigator.clipboard.writeText(markdown);
      setCopiedPath("markdown-preview");
      window.setTimeout(() => setCopiedPath(""), 1400);
    } catch {
      setError("Could not copy the self-review Markdown from this environment.");
    }
  }

  return (
    <section className="review-page">
      <header className={`review-hero ${verdict.tone}`}>
        <div className="review-hero-main">
          <h1>Review</h1>
          <p>{snapshot?.latest_run.summary ?? "Loading review evidence from the backend snapshot."}</p>
        </div>
        <div className="review-hero-side">
          <div className="review-actions">
            <button className="icon-text-button" disabled={disabled} onClick={() => loadReview({ refreshProject: true })}>
              {busy === "load" ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              Refresh
            </button>
            <button className="icon-text-button" disabled={disabled} onClick={() => openArtifact()}>
              <ExternalLink size={14} />
              Open Markdown
            </button>
            <button className="icon-text-button" disabled={disabled} onClick={exportBundle}>
              {busy === "export" ? <Loader2 size={14} className="spin" /> : <FileDown size={14} />}
              Export review
            </button>
          </div>
        </div>
      </header>

      {error && <div className="review-alert error">{error}</div>}
      {notice && <div className="review-alert notice">{notice}</div>}

      <div className="review-layout">
        <main className="review-main-column">
          <TrustSummaryCard snapshot={snapshot} projectSnapshot={props.snapshot} verdict={verdict} />
          <LatestRunSummaryCard snapshot={snapshot} />
          <SafetyCheckCard snapshot={snapshot} />
          {snapshot && deferredStage >= 1 ? (
            <>
              <ChangedFilesList files={changedFiles} source={snapshot.changed_files_source} />
              <VerificationEvidenceList snapshot={snapshot} />
            </>
          ) : (
            <>
              <DeferredReviewSection title="Changed files" />
              <DeferredReviewSection title="Verification" />
            </>
          )}
          {snapshot && deferredStage >= 2 ? (
            <>
              <LandedWorkRail commits={latestCommits} />
              <SkippedChecksCard limitations={limitations} />
            </>
          ) : (
            <>
              <DeferredReviewSection title="Commits" />
              <DeferredReviewSection title="Skipped checks" />
            </>
          )}
          <ReviewSection title="Markdown preview" className="review-markdown-section">
            <details>
              <summary>
                <span>Preview</span>
              </summary>
              <div className="review-markdown-tools">
                <button className="icon-text-button" type="button" disabled={!snapshot?.self_review.markdown_preview} onClick={copySelfReviewMarkdown}>
                  <Clipboard size={13} />
                  {copiedPath === "markdown-preview" ? "Copied" : "Copy markdown"}
                </button>
              </div>
              {snapshot && deferredStage >= 2 ? (
                <pre className="review-markdown-preview">{snapshot.self_review.markdown_preview ?? "Loading self-review preview..."}</pre>
              ) : (
                <div className="review-deferred-panel">
                  <div className="skeleton-line medium" />
                  <div className="skeleton-line" />
                </div>
              )}
              {snapshot?.self_review.truncated && <small>Preview truncated. Open the full self-review after export.</small>}
            </details>
          </ReviewSection>
        </main>

        <aside className="review-side-rail">
          <ReviewSection title="Review marker" className="review-rail-card">
            <div className="review-mark-card">
              <CheckCircle2 size={18} />
              <div>
                <strong>{snapshot?.reviewed.exists ? "Reviewed" : "Not reviewed yet"}</strong>
                <span>{formatTimestamp(snapshot?.reviewed.reviewed_at)}</span>
              </div>
              <ReviewBadge value={snapshot?.reviewed.exists ? "reviewed" : "pending"} tone={snapshot?.reviewed.exists ? "good" : "warn"} />
            </div>
            <label className="review-note-label">
              Optional note
              <textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} />
            </label>
            <button className="primary-action" disabled={disabled} onClick={markReviewed}>
              Mark reviewed
            </button>
          </ReviewSection>

          <ReviewSection title="Review export" className="review-rail-card">
            <div className="review-bundle-paths">
              <ArtifactCard
                label="Self-review"
                path={selfReviewPath}
                copied={copiedPath === "self-review"}
                disabled={disabled}
                onCopy={() => copyArtifactPath(selfReviewPath, "self-review")}
                onReveal={() => revealArtifact()}
              />
            </div>
            <button className="primary-action" disabled={disabled} onClick={exportBundle}>
              <FileDown size={16} />
              Export review
            </button>
          </ReviewSection>

          <ReviewSection title="Next-run note" className="review-rail-card">
            <div className="review-followup">
              <select value={followupIntent} onChange={(event) => setFollowupIntent(event.target.value)}>
                {followupIntents.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <textarea
                value={followup}
                onChange={(event) => setFollowup(event.target.value)}
                placeholder="Tell the next run what to check or avoid."
              />
              <button className="primary-action" disabled={disabled || !followup.trim()} onClick={sendFollowup}>
                {busy === "followup" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
                Send follow-up
              </button>
            </div>
          </ReviewSection>
        </aside>
      </div>
    </section>
  );
}
