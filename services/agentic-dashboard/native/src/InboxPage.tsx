import { Archive, Inbox, Loader2, RefreshCw, Search, Send } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { BackendEnvelope, InboxMessage, InboxSnapshot, ProjectSnapshot } from "./api/backend";
import { runBackendCommand } from "./api/backend";

type InboxTab = "Requests" | "Notes to next run" | "Archive";

type SendResult = {
  inbox_id: string;
  status: string;
  snapshot: InboxSnapshot;
};

const tabs: InboxTab[] = ["Requests", "Notes to next run", "Archive"];
const intentOptions = [
  { value: "info", label: "General note" },
  { value: "done", label: "Done / completed" },
  { value: "skip", label: "Skip this request" },
  { value: "approve", label: "Approved" },
  { value: "reject", label: "Rejected" },
  { value: "unknown", label: "Not sure" },
];

function text(value: unknown, fallback = "Not recorded"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function formatStatus(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatTimestamp(value?: string): string {
  if (!value) return "No timestamp";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function relatedChips(message: InboxMessage): string[] {
  const related = message.related ?? {};
  return [
    related.request ? `Request ${related.request}` : "",
    related.ticket ? `Ticket ${related.ticket}` : "",
    related.run ? `Run ${related.run}` : "",
    related.file ? `File ${related.file}` : "",
    message.intent ? `Intent ${message.intent}` : "",
    message.channel ? `Via ${message.channel}` : "",
  ].filter(Boolean);
}

function MessageCard(props: {
  message: InboxMessage;
  selected?: boolean;
  onSelect?: (message: InboxMessage) => void;
}) {
  return (
    <button
      className={`message-card ${props.message.ui_state} ${props.selected ? "selected" : ""}`}
      onClick={() => props.onSelect?.(props.message)}
      type="button"
    >
      <div className="message-card-head">
        <div>
          <strong>{props.message.title || props.message.id}</strong>
          <span>{props.message.id}</span>
        </div>
        <em>{formatStatus(props.message.ui_state || props.message.status)}</em>
      </div>
      <div className="message-meta-row">
        <span>{formatTimestamp(props.message.timestamp)}</span>
        <span>{formatStatus(props.message.status || "unknown")}</span>
      </div>
      {relatedChips(props.message).length > 0 && (
        <div className="message-chips">
          {relatedChips(props.message).map((chip) => <span key={chip}>{chip}</span>)}
        </div>
      )}
      <p>{props.message.body || props.message.summary}</p>
    </button>
  );
}

function ChatBubble(props: { message: InboxMessage }) {
  return (
    <article className={`chat-bubble ${props.message.ui_state}`}>
      <div>
        <strong>{props.message.body || props.message.summary}</strong>
        <span>{formatTimestamp(props.message.timestamp)}</span>
      </div>
      <footer>
        <span>{props.message.id}</span>
        <em>{formatStatus(props.message.ui_state)}</em>
      </footer>
    </article>
  );
}

export function InboxPage(props: {
  snapshot: ProjectSnapshot;
  loading: boolean;
  onRefresh: () => void;
  initialSnapshot?: InboxSnapshot | null;
  initialTab?: InboxTab;
}) {
  const target = props.snapshot.target.path;
  const [activeTab, setActiveTab] = useState<InboxTab>(props.initialTab ?? "Requests");
  const [snapshot, setSnapshot] = useState<InboxSnapshot | null>(props.initialSnapshot ?? null);
  const [selectedRequestId, setSelectedRequestId] = useState("");
  const [replyBody, setReplyBody] = useState("");
  const [replyIntent, setReplyIntent] = useState("info");
  const [noteBody, setNoteBody] = useState("");
  const [noteIntent, setNoteIntent] = useState("info");
  const [noteRelated, setNoteRelated] = useState("");
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<"load" | "reply" | "note" | null>(null);
  const [error, setError] = useState("");
  const [sentNotice, setSentNotice] = useState("");

  const selectedRequest = useMemo(
    () => snapshot?.requests.find((request) => request.id === selectedRequestId) ?? snapshot?.active_requests[0],
    [selectedRequestId, snapshot],
  );

  async function loadInbox(options: { refreshProject?: boolean } = {}) {
    setBusy("load");
    setError("");
    try {
      const payload: BackendEnvelope<InboxSnapshot> = await runBackendCommand({
        command: "inbox.load",
        target,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not load the inbox.");
        return;
      }
      setSnapshot(payload.data);
      if (!selectedRequestId && payload.data.active_requests[0]) {
        setSelectedRequestId(payload.data.active_requests[0].id);
      }
      if (options.refreshProject) props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function sendReply() {
    if (!selectedRequest || !replyBody.trim()) return;
    setBusy("reply");
    setError("");
    try {
      const payload: BackendEnvelope<SendResult> = await runBackendCommand({
        command: "inbox.reply_request",
        target,
        requestId: selectedRequest.id,
        body: replyBody,
        intent: replyIntent,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not queue the reply.");
        return;
      }
      setReplyBody("");
      setSentNotice(`Queued reply ${payload.data.inbox_id} for the next run.`);
      setSnapshot(payload.data.snapshot);
      props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  async function sendNote() {
    if (!noteBody.trim()) return;
    setBusy("note");
    setError("");
    try {
      const payload: BackendEnvelope<SendResult> = await runBackendCommand({
        command: "inbox.send_note",
        target,
        body: noteBody,
        intent: noteIntent,
        related: noteRelated,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not queue the note.");
        return;
      }
      setNoteBody("");
      setNoteRelated("");
      setSentNotice(`Queued note ${payload.data.inbox_id} for the next run.`);
      setSnapshot(payload.data.snapshot);
      props.onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    void loadInbox();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, props.snapshot.run.snapshot_generated_at]);

  const archiveItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    const items = snapshot?.archive ?? [];
    if (!query) return items;
    return items.filter((item) =>
      [item.id, item.title, item.status, item.body, item.summary, item.request_id, item.source_inbox_id]
        .map((value) => text(value, "").toLowerCase())
        .some((value) => value.includes(query)),
    );
  }, [search, snapshot]);
  const noteTimeline = useMemo(() => {
    const notes = snapshot?.notes ?? [];
    const noteIds = new Set(notes.map((note) => note.id));
    const archivedNotes = (snapshot?.archive ?? [])
      .filter((item) => item.source_inbox_id && !noteIds.has(item.source_inbox_id))
      .map((item) => ({
        ...item,
        id: item.source_inbox_id || item.id,
        body: item.body || item.summary,
        ui_state: "archived",
        kind: "note",
      }));
    return [...notes, ...archivedNotes];
  }, [snapshot]);

  const disabled = props.loading || busy !== null;

  return (
    <section className="inbox-page">
      <div className="inbox-hero">
        <div>
          <h1>Inbox</h1>
          <p>
            Review requests, queue replies, and leave instructions for the next run.
          </p>
        </div>
        <div className="inbox-hero-actions">
          <div className="bridge-mode-pill">{formatStatus(snapshot?.bridge_mode ?? "file_only")}</div>
          <button className="icon-text-button" disabled={disabled} onClick={() => loadInbox({ refreshProject: true })}>
            {busy === "load" ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
            Refresh
          </button>
        </div>
      </div>

      <div className="inbox-metrics">
        <div><span>Pending requests</span><strong>{snapshot?.counts.pending_requests ?? props.snapshot.home.pending_human_requests}</strong></div>
        <div><span>Queued notes</span><strong>{snapshot?.counts.queued_notes ?? props.snapshot.home.unhandled_inbox}</strong></div>
        <div><span>Archive</span><strong>{snapshot?.counts.archived_items ?? 0}</strong></div>
        <div><span>Outbox</span><strong>{snapshot?.counts.outbound_records ?? 0}</strong></div>
      </div>

      {error && <div className="inbox-error">{error}</div>}
      {sentNotice && <div className="inbox-notice">{sentNotice}</div>}

      <div className="inbox-tabs" role="tablist" aria-label="Inbox sections">
        {tabs.map((tab) => (
          <button
            className={activeTab === tab ? "active" : ""}
            key={tab}
            onClick={() => setActiveTab(tab)}
            type="button"
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "Requests" && (
        <div className="inbox-layout">
          <section className="inbox-list-panel">
            <h2>Requests</h2>
            {(snapshot?.active_requests ?? []).length ? (
              <div className="message-list">
                {(snapshot?.active_requests ?? []).map((request) => (
                  <MessageCard
                    key={request.id}
                    message={request}
                    selected={selectedRequest?.id === request.id}
                    onSelect={(message) => setSelectedRequestId(message.id)}
                  />
                ))}
              </div>
            ) : (
              <div className="inbox-empty">
                <Inbox size={22} />
                <strong>No pending requests</strong>
                <p>Manual decisions appear here.</p>
              </div>
            )}
          </section>

          <section className="reply-panel">
            <h2>Reply</h2>
            {selectedRequest ? (
              <>
                <div className="selected-request-summary">
                  <strong>{selectedRequest.id}</strong>
                  <p>{selectedRequest.body || selectedRequest.summary}</p>
                </div>
                <label>
                  Intent
                  <select value={replyIntent} onChange={(event) => setReplyIntent(event.target.value)}>
                    {intentOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                  </select>
                </label>
                <label>
                  Reply body
                  <textarea
                    value={replyBody}
                    onChange={(event) => setReplyBody(event.target.value)}
                    placeholder="Example: Done. The key was added locally and the app can continue with the dry-run path."
                  />
                </label>
                <button className="primary-action" disabled={disabled || !replyBody.trim()} onClick={sendReply}>
                  {busy === "reply" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
                  Send reply
                </button>
              </>
            ) : (
              <div className="inbox-empty">
                <strong>No request selected</strong>
                <p>Replies are enabled when a request is active.</p>
              </div>
            )}
          </section>
        </div>
      )}

      {activeTab === "Notes to next run" && (
        <div className="notes-layout">
          <section className="reply-panel">
            <h2>New note</h2>
            <label>
              Intent
              <select value={noteIntent} onChange={(event) => setNoteIntent(event.target.value)}>
                {intentOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label>
              Related request, ticket, file, or run
              <input
                value={noteRelated}
                onChange={(event) => setNoteRelated(event.target.value)}
                placeholder="Optional, for example HR-2026-05-03-001 or ticket T-7"
              />
            </label>
            <label>
              Message body
              <textarea
                value={noteBody}
                onChange={(event) => setNoteBody(event.target.value)}
                placeholder="Tell the next run what to check or avoid."
              />
            </label>
            <button className="primary-action" disabled={disabled || !noteBody.trim()} onClick={sendNote}>
              {busy === "note" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              Send to next run
            </button>
          </section>

          <section className="chat-panel">
            <h2>Queued and recent notes</h2>
            {noteTimeline.length ? (
              <div className="chat-list">
                {noteTimeline.map((note) => <ChatBubble key={`${note.ui_state}-${note.id}`} message={note} />)}
              </div>
            ) : (
              <div className="inbox-empty">
                <strong>No notes queued</strong>
                <p>Use notes to adjust the next run without changing setup.</p>
              </div>
            )}
          </section>
        </div>
      )}

      {activeTab === "Archive" && (
        <section className="archive-panel">
          <div className="archive-toolbar">
            <div>
              <Archive size={18} />
              <h2>Archive</h2>
            </div>
            <label className="archive-search">
              <Search size={15} />
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search archive" />
            </label>
          </div>
          {archiveItems.length ? (
            <div className="message-list archive-list">
              {archiveItems.map((item) => <MessageCard key={`${item.kind}-${item.id}`} message={item} />)}
            </div>
          ) : (
            <div className="inbox-empty">
              <Archive size={22} />
              <strong>No archived messages yet</strong>
              <p>Handled requests and consumed replies appear here after archiving.</p>
            </div>
          )}
        </section>
      )}
    </section>
  );
}
