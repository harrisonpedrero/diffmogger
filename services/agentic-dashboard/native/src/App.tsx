import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  ClipboardCheck,
  Command,
  Database,
  ExternalLink,
  FileText,
  FolderOpen,
  GitBranch,
  Home,
  Inbox,
  type LucideIcon,
  LogOut,
  PlayCircle,
  RefreshCw,
  SlidersHorizontal,
  Telescope,
  TerminalSquare,
} from "lucide-react";
import { memo, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import {
  BackendEnvelope,
  EnvironmentDiagnosticsSnapshot,
  ProjectSnapshot,
  RecentTarget,
  getAdvancedSettings,
  listRecentProjects,
  loadProjectSnapshot,
  openManagedFile,
  openProjectInEditor,
  revealProject,
  runBackendCommand,
  runBackendCommandStreamed,
  selectContextFiles,
  selectProjectFolder,
} from "./api/backend";
import { AdvancedPage } from "./AdvancedPage";
import { BriefWizard } from "./BriefWizard";
import { CommandPalette } from "./CommandPalette";
import {
  PaletteCommand,
  PaletteCommandId,
  buildCommandPaletteModel,
} from "./commandPaletteModel";
import {
  HomeAction,
  HomeConveyorLane,
  HomeEventRow,
  HomeModel,
  HomeMetric,
  HomeQueueRow,
  HomeRoute,
  HomeSafetyRow,
  HomeTone,
  buildHomeModel,
} from "./homeModel";
import { InboxPage } from "./InboxPage";
import { ObservatoryPage } from "./ObservatoryPage";
import { ReviewPage } from "./ReviewPage";
import { RunPage } from "./RunPage";
import diffmoggerLogo from "./assets/diffmogger-logo-cropped.png";
import "./App.css";

export type ViewKey =
  | "Home"
  | "Brief"
  | "Run"
  | "Observatory"
  | "Inbox"
  | "Review"
  | "Advanced";

type LoadState = "idle" | "loading" | "loaded" | "error";
type CachedRouteVisits = Record<ViewKey, boolean>;
type DirtyRouteState = Partial<Record<ViewKey, string>>;
type BusyRouteState = Partial<Record<ViewKey, boolean>>;

type ViewDefinition = {
  key: ViewKey;
  label: string;
  legacyLabel: string;
  icon: LucideIcon;
};

const views: ViewDefinition[] = [
  { key: "Home", label: "Home", legacyLabel: "Control Room", icon: Home },
  { key: "Brief", label: "Setup", legacyLabel: "Brief", icon: FileText },
  { key: "Run", label: "Run", legacyLabel: "Run", icon: PlayCircle },
  { key: "Observatory", label: "Activity", legacyLabel: "Observatory", icon: Telescope },
  { key: "Inbox", label: "Inbox", legacyLabel: "Handoffs", icon: Inbox },
  { key: "Review", label: "Review", legacyLabel: "Review", icon: ClipboardCheck },
  { key: "Advanced", label: "Sidecar", legacyLabel: "Advanced", icon: SlidersHorizontal },
];

const transparentBackground: [number, number, number, number] = [0, 0, 0, 0];
export const AUTO_REFRESH_ACTIVE_INTERVAL_MS = 30_000;
export const AUTO_REFRESH_IDLE_INTERVAL_MS = 60_000;
export const AUTO_REFRESH_FOCUS_STALE_MS = 60_000;
export const AUTO_REFRESH_MIN_OVERDUE_MS = 90_000;
const ACTIVE_AUTOMATION_STATES = new Set(["running", "starting", "stopping"]);

export type AutoRefreshBlocker =
  | "no_target"
  | "not_loaded"
  | "refreshing"
  | "dirty_route"
  | "busy_command";

export type AutoRefreshChipState = {
  label: string;
  title: string;
  tone: "quiet" | "info" | "warn" | "critical";
  overdue: boolean;
  paused: boolean;
};

function createCachedRouteVisits(
  overrides: Partial<CachedRouteVisits> = {},
): CachedRouteVisits {
  return {
    Home: false,
    Brief: false,
    Run: false,
    Observatory: false,
    Inbox: false,
    Review: false,
    Advanced: false,
    ...overrides,
  };
}

type TargetRequiredView = Exclude<ViewKey, "Home" | "Brief">;

const targetRequiredCopy: Record<
  TargetRequiredView,
  { title: string; body: string; detail: string }
> = {
  Run: {
    title: "Select a project to run jobs",
    body: "Run controls, automation state, worker strategy, and logs are target-local.",
    detail: "Choose a project folder or complete setup for a new target.",
  },
  Observatory: {
    title: "Select a project to view activity",
    body: "Activity is built from the selected target's commits, role events, checks, and patch queues.",
    detail: "Choose a project folder to load current target activity.",
  },
  Inbox: {
    title: "Select a project to open Inbox",
    body: "Requests, replies, and next-run notes live in target-local Markdown files.",
    detail: "Choose a target to see pending requests or complete setup for file-based messaging.",
  },
  Review: {
    title: "Select a project to review a run",
    body: "Review evidence is generated from the selected target's latest run, changed files, validation, and safety results.",
    detail: "After a project is loaded, you can export review files or send a next-run note.",
  },
  Advanced: {
    title: "Select a project to inspect Sidecar",
    body: "Diagnostics, managed files, settings, and debug exports are scoped to a selected target.",
    detail: "Choose a project folder to inspect allowed files and run readiness checks.",
  },
};

function viewLabel(view: ViewKey): string {
  return views.find((item) => item.key === view)?.label ?? view;
}

export function viewRequiresTarget(view: ViewKey): view is TargetRequiredView {
  return view !== "Home" && view !== "Brief";
}

function formatTimestamp(value: number): string {
  if (!value) return "";
  return new Date(value * 1000).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function targetSubdir(target: string, leaf: string): string {
  return `${target.replace(/[\\/]+$/, "")}/target/${leaf}`;
}

function textValue(value: unknown, fallback = ""): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function numberValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function boolValue(value: unknown): boolean {
  return value === true;
}

function recordValue(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

export function hasDirtyRouteState(routes: DirtyRouteState): boolean {
  return Object.values(routes).some((message) => Boolean(message));
}

export function hasBusyRouteState(routes: BusyRouteState): boolean {
  return Object.values(routes).some((busy) => busy === true);
}

export function snapshotHasActiveRefreshSignals(snapshot: ProjectSnapshot | null): boolean {
  if (!snapshot) return false;
  const automation = recordValue(snapshot.run.automation);
  const controls = recordValue(snapshot.run.controls);
  const conveyor = recordValue(snapshot.run.conveyor);
  const activeRoleRun = recordValue(conveyor.active_role_run);
  const activeRun = recordValue(conveyor.active_run);
  const human = recordValue(snapshot.run.human);
  const automationState = textValue(automation.state).toLowerCase();
  const pendingHuman =
    numberValue(snapshot.home.pending_human_requests) +
    numberValue(snapshot.home.unhandled_inbox) +
    numberValue(human.pending_requests) +
    numberValue(human.unhandled_inbox);

  return (
    ACTIVE_AUTOMATION_STATES.has(automationState) ||
    boolValue(controls.is_running) ||
    Object.keys(activeRoleRun).length > 0 ||
    Object.keys(activeRun).length > 0 ||
    pendingHuman > 0
  );
}

export function autoRefreshIntervalMs(snapshot: ProjectSnapshot | null): number {
  return snapshotHasActiveRefreshSignals(snapshot)
    ? AUTO_REFRESH_ACTIVE_INTERVAL_MS
    : AUTO_REFRESH_IDLE_INTERVAL_MS;
}

export function autoRefreshOverdueMs(snapshot: ProjectSnapshot | null): number {
  return Math.max(AUTO_REFRESH_MIN_OVERDUE_MS, autoRefreshIntervalMs(snapshot) * 2);
}

export function autoRefreshBlocker(options: {
  hasSelectedTarget: boolean;
  loadState: LoadState;
  refreshInFlight: boolean;
  hasDirtyRoutes: boolean;
  hasBusyCommands: boolean;
}): AutoRefreshBlocker | null {
  if (!options.hasSelectedTarget) return "no_target";
  if (options.loadState !== "loaded") return "not_loaded";
  if (options.refreshInFlight) return "refreshing";
  if (options.hasDirtyRoutes) return "dirty_route";
  if (options.hasBusyCommands) return "busy_command";
  return null;
}

export function canAutoRefreshProject(options: {
  hasSelectedTarget: boolean;
  loadState: LoadState;
  refreshInFlight: boolean;
  hasDirtyRoutes: boolean;
  hasBusyCommands: boolean;
}): boolean {
  return autoRefreshBlocker(options) === null;
}

export function shouldRefreshOnFocus(lastUpdatedAt: number | null, now = Date.now()): boolean {
  return Boolean(lastUpdatedAt && now - lastUpdatedAt >= AUTO_REFRESH_FOCUS_STALE_MS);
}

export function buildAutoRefreshChipState(options: {
  lastUpdatedAt: number | null;
  now: number;
  refreshing: boolean;
  pauseReason: AutoRefreshBlocker | null;
  pauseDetail?: string | null;
  failureMessage?: string | null;
  overdueMs: number;
}): AutoRefreshChipState {
  if (options.refreshing || options.pauseReason === "refreshing") {
    return {
      label: "Refreshing...",
      title: "Refreshing the selected project.",
      tone: "info",
      overdue: false,
      paused: false,
    };
  }

  if (!options.lastUpdatedAt) {
    return {
      label: "Not loaded yet",
      title: "Not loaded yet",
      tone: "quiet",
      overdue: false,
      paused: false,
    };
  }

  if (options.pauseReason && options.pauseReason !== "no_target") {
    const title =
      options.pauseReason === "dirty_route"
        ? `Auto-refresh paused: ${options.pauseDetail || "local dashboard edits are still unsaved."}`
        : options.pauseReason === "busy_command"
          ? "Auto-refresh paused while a dashboard command is running."
          : "Auto-refresh paused until the selected project is loaded.";
    return {
      label: "Auto-refresh paused",
      title,
      tone: options.pauseReason === "not_loaded" ? "quiet" : "warn",
      overdue: false,
      paused: true,
    };
  }

  if (options.failureMessage) {
    return {
      label: "Refresh failed",
      title: `Auto-refresh failed: ${options.failureMessage}`,
      tone: "warn",
      overdue: false,
      paused: false,
    };
  }

  const overdue = options.now - options.lastUpdatedAt > options.overdueMs;
  if (overdue) {
    return {
      label: "Refresh delayed",
      title: `Last successful refresh ${new Date(options.lastUpdatedAt).toLocaleString()}; waiting for the next automatic refresh.`,
      tone: "warn",
      overdue: true,
      paused: false,
    };
  }

  return {
    label: formatLastUpdated(options.lastUpdatedAt),
    title: `Updated ${new Date(options.lastUpdatedAt).toLocaleString()}`,
    tone: "quiet",
    overdue: false,
    paused: false,
  };
}

function formatLastUpdated(value: number | null): string {
  if (!value) return "Not loaded yet";
  return `Updated ${new Date(value).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

function formatDirtyLabel(count: number, hasSnapshot: boolean): string {
  if (!hasSnapshot) return "No git state";
  if (count === 0) return "Worktree clean";
  return `${count} uncommitted ${count === 1 ? "file" : "files"}`;
}

function formatTopbarStatusLabel(status: string): string {
  return status.toLowerCase() === "stale" ? "State needs refresh" : status;
}

function sidecarState(snapshot: ProjectSnapshot | null): { label: string; tone: "good" | "warn" | "quiet" } {
  if (!snapshot) return { label: "No target", tone: "quiet" };
  if (snapshot.target.is_diffmogger_project && snapshot.target.automation_task_exists) {
    return { label: "Sidecar ready", tone: "good" };
  }
  if (snapshot.target.project_intake_exists || snapshot.target.dashboard_state_exists) {
    return { label: "Sidecar partial", tone: "warn" };
  }
  return { label: "No sidecar", tone: "warn" };
}

type SidebarBadge = {
  label: string;
  tone: "running" | "needs-input" | "blocked" | "review";
};

function buildSidebarBadges(snapshot: ProjectSnapshot | null): Partial<Record<ViewKey, SidebarBadge>> {
  if (!snapshot) return {};
  const task = recordValue(snapshot.run.task);
  const controls = recordValue(snapshot.run.controls);
  const automation = recordValue(snapshot.run.automation);
  const status = textValue(task.status, snapshot.home.automation_status).toUpperCase();
  const running =
    boolValue(controls.is_running) ||
    status.includes("RUNNING") ||
    textValue(automation.state).toLowerCase() === "running";
  const needsInput =
    status.includes("PENDING_USER_INPUT") ||
    status.includes("BLOCKED_ON_USER") ||
    numberValue(snapshot.home.pending_human_requests) > 0 ||
    numberValue(snapshot.home.unhandled_inbox) > 0;
  const blocked =
    status.includes("BLOCKED") ||
    status.includes("CRITICAL_STOP") ||
    (snapshot.run.environment_blockers ?? []).length > 0;
  const firstReview = textValue(snapshot.run.first_review?.status, "").toLowerCase();
  const reviewNeeded =
    snapshot.target.automation_task_exists &&
    Boolean(firstReview) &&
    !["ready", "reviewed", "complete", "completed", "not_required", "none"].includes(firstReview);
  const badges: Partial<Record<ViewKey, SidebarBadge>> = {};
  if (blocked) badges.Home = { label: "Blocked", tone: "blocked" };
  if (running) badges.Run = { label: "Run", tone: "running" };
  if (needsInput) {
    const count = numberValue(snapshot.home.pending_human_requests) + numberValue(snapshot.home.unhandled_inbox);
    badges.Inbox = { label: count ? String(count) : "Input", tone: "needs-input" };
  }
  if (reviewNeeded) badges.Review = { label: "Review", tone: "review" };
  return badges;
}

function WindowControls(props: { onWindowStateChange?: () => void }) {
  async function windowAction(action: "minimize" | "fullscreen" | "close") {
    try {
      const nativeWindow = getCurrentWindow();
      if (action === "minimize") await nativeWindow.minimize();
      if (action === "fullscreen") {
        const isFullscreen = await nativeWindow.isFullscreen();
        try {
          await nativeWindow.setFullscreen(!isFullscreen);
        } catch {
          await nativeWindow.setSimpleFullscreen(!isFullscreen);
        }
      }
      if (action === "close") await nativeWindow.close();
      props.onWindowStateChange?.();
    } catch {
      // Browser preview has no native window handle.
    }
  }

  return (
    <div className="window-controls" aria-label="Window controls">
      <button className="traffic-close" aria-label="Close" title="Close" onClick={() => windowAction("close")}>
        <span />
      </button>
      <button className="traffic-minimize" aria-label="Minimize" title="Minimize" onClick={() => windowAction("minimize")}>
        <span />
      </button>
      <button className="traffic-maximize" aria-label="Fullscreen" title="Fullscreen" onClick={() => windowAction("fullscreen")}>
        <span />
      </button>
    </div>
  );
}

async function startTitlebarDrag(event: PointerEvent<HTMLElement>) {
  if (event.button !== 0) return;
  const target = event.target as HTMLElement;
  if (target.closest("button, input, select, textarea, a, [data-no-drag]")) return;
  try {
    await getCurrentWindow().startDragging();
  } catch {
    // Browser preview has no native window handle.
  }
}

async function applyTransparentNativeBackground() {
  try {
    await getCurrentWindow().setBackgroundColor(transparentBackground);
  } catch {
    // Browser preview and some platforms may not support native background control.
  }
  try {
    await getCurrentWebviewWindow().setBackgroundColor(transparentBackground);
  } catch {
    // macOS currently handles this through the transparent window API.
  }
  try {
    await getCurrentWebview().setBackgroundColor(transparentBackground);
  } catch {
    // macOS webview background color is not implemented; CSS remains transparent.
  }
}

function TonePill(props: { tone: HomeTone | string; children: ReactNode }) {
  return <span className={`home-tone-pill ${props.tone}`}>{props.children}</span>;
}

function HomeActionButton(props: {
  action: HomeAction;
  primary?: boolean;
  disabled: boolean;
  onAction: (action: HomeAction) => void;
}) {
  return (
    <button
      className={props.primary ? "primary-action" : "secondary-action"}
      disabled={props.disabled || props.action.kind === "disabled"}
      onClick={() => props.onAction(props.action)}
    >
      {props.action.label}
      {props.primary && <ArrowRight size={16} />}
    </button>
  );
}

function MiniConveyor(props: { lanes: HomeConveyorLane[] }) {
  return (
    <div className="mini-conveyor" aria-label="Mini conveyor">
      {props.lanes.map((lane, index) => (
        <div className="mini-conveyor-step" key={lane.role}>
          <span className={`mini-conveyor-node ${lane.tone}`} aria-hidden="true" />
          <span>{lane.label}</span>
          {index < props.lanes.length - 1 && <i aria-hidden="true" />}
        </div>
      ))}
    </div>
  );
}

function OperationalStatusHero(props: {
  model: HomeModel;
  loading: boolean;
  noTarget: boolean;
  onAction: (action: HomeAction) => void;
}) {
  const showHeadline =
    props.noTarget || props.model.headline.toLowerCase() !== props.model.statusLabel.toLowerCase();
  return (
    <section
      aria-label="Home operational status"
      className={`operational-hero ${props.model.statusTone}`}
      data-testid="operational-status-hero"
    >
      <div className={`operational-hero-state ${showHeadline ? "" : "badge-only"}`}>
        {!props.noTarget && <TonePill tone={props.model.statusTone}>{props.model.statusLabel}</TonePill>}
        {showHeadline && <h1>{props.model.headline}</h1>}
        <p>{props.model.subheadline}</p>
      </div>
      <MiniConveyor lanes={props.model.conveyor.lanes} />
      <aside className="operational-next-action" aria-label="Next action">
        <span>Next</span>
        <strong>{props.model.recommendation.title}</strong>
        <p>{props.model.recommendation.reason}</p>
        <div className="operational-actions">
          <HomeActionButton
            action={props.model.primaryAction}
            disabled={props.loading || (props.model.primaryAction.kind === "refresh" && props.noTarget)}
            onAction={props.onAction}
            primary
          />
          {props.model.secondaryActions.map((action) => (
            <HomeActionButton
              action={action}
              disabled={props.loading || (action.kind === "refresh" && props.noTarget)}
              key={`${action.kind}-${action.label}`}
              onAction={props.onAction}
            />
          ))}
        </div>
      </aside>
    </section>
  );
}

function MetricSignalStrip(props: { metrics: HomeMetric[] }) {
  return (
    <section className="metric-signal-strip" aria-label="Metric signals" data-testid="metric-signal-strip">
      {props.metrics.map((metric) => (
        <div className={`metric-signal ${metric.tone}`} key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
        </div>
      ))}
    </section>
  );
}

function SafetyMatrix(props: { rows: HomeSafetyRow[]; onAction: (action: HomeAction) => void }) {
  return (
    <section className="control-panel safety-matrix-panel" aria-label="Safety" data-testid="safety-matrix">
      <div className="control-panel-heading compact">
        <h2>Safety</h2>
      </div>
      <div className="safety-matrix">
        {props.rows.map((row) => (
          <div className={`safety-matrix-row ${row.tone}`} key={row.label}>
            <div>
              <strong>{row.label}</strong>
              <span>{row.source}</span>
            </div>
            <TonePill tone={row.tone}>{row.status}</TonePill>
            <p title={row.summary}>{row.summary}</p>
            <button
              className="ledger-action"
              disabled={row.action.kind === "disabled"}
              onClick={() => props.onAction(row.action)}
            >
              {row.action.label}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function QueueLedger(props: {
  rows: HomeQueueRow[];
  emptyMessage: string;
  onAction: (action: HomeAction) => void;
}) {
  return (
    <section className="control-panel queue-ledger-panel" aria-label="Queue ledger" data-testid="queue-ledger">
      <div className="control-panel-heading compact">
        <h2>Queue Ledger</h2>
        <button className="ledger-action" onClick={() => props.onAction({ label: "Run", kind: "navigate", route: "Run" })}>
          Run
        </button>
      </div>
      <div className="queue-ledger">
        <div className="ledger-header" aria-hidden="true">
          <span>Ticket</span>
          <span>Status</span>
          <span>Lane</span>
          <span>Last change</span>
          <span>Blocker</span>
        </div>
        {props.rows.length ? (
          props.rows.map((row) => (
            <div className={`queue-ledger-row ${row.tone}`} key={row.id}>
              <div>
                <strong title={row.id}>{row.id}</strong>
                <span title={row.title}>{row.title}</span>
              </div>
              <TonePill tone={row.tone}>{row.status}</TonePill>
              <span className="queue-ledger-lane" title={row.lane}>{row.lane}</span>
              <span className="queue-ledger-time" title={row.lastChange}>{row.lastChange}</span>
              <span className="queue-ledger-source" title={row.blocker || row.source}>{row.blocker || row.source}</span>
            </div>
          ))
        ) : (
          <div className="ledger-empty">{props.emptyMessage}</div>
        )}
      </div>
    </section>
  );
}

function EventLedger(props: { rows: HomeEventRow[]; emptyMessage: string }) {
  return (
    <section className="control-panel event-ledger-panel" aria-label="Event ledger" data-testid="event-ledger">
      <div className="control-panel-heading compact">
        <h2>Event Ledger</h2>
      </div>
      <div className="event-ledger">
        {props.rows.length ? (
          props.rows.map((row) => (
            <div className={`event-ledger-row ${row.tone}`} key={row.id}>
              <time className="event-ledger-time" title={row.time}>{row.time}</time>
              <TonePill tone={row.tone}>{row.type}</TonePill>
              <span className="event-ledger-lane" title={row.lane}>{row.lane}</span>
              <strong className="event-ledger-message" title={row.message}>{row.message}</strong>
              <code className="event-ledger-artifact" title={row.artifact}>{row.artifact}</code>
              <span className="event-ledger-status" title={row.status}>{row.status}</span>
            </div>
          ))
        ) : (
          <div className="ledger-empty">{props.emptyMessage}</div>
        )}
      </div>
    </section>
  );
}

function HumanBridgeMini(props: {
  model: HomeModel["humanBridge"];
  onAction: (action: HomeAction) => void;
}) {
  const total = props.model.pending + props.model.unhandled;
  return (
    <section className={`control-panel human-bridge-mini ${total ? "warn" : "good"}`} aria-label="Inbox summary" data-testid="human-bridge-mini">
      <div className="control-panel-heading compact">
        <h2>Inbox</h2>
        <TonePill tone={total ? "warn" : "good"}>{props.model.latestStatus}</TonePill>
      </div>
      <div className="bridge-mini-grid">
        <div>
          <span>Requests</span>
          <strong>{props.model.pending}</strong>
        </div>
        <div>
          <span>Notes</span>
          <strong>{props.model.unhandled}</strong>
        </div>
        <div>
          <span>Outbound</span>
          <strong>{props.model.outbound}</strong>
        </div>
      </div>
      <button
        className="secondary-action"
        disabled={props.model.action.kind === "disabled"}
        onClick={() => props.onAction(props.model.action)}
      >
        {props.model.action.label}
      </button>
    </section>
  );
}

function ShellSkeleton() {
  return (
    <section className="skeleton-page" aria-label="Loading project" role="status" aria-live="polite">
      <div className="skeleton-banner">
        <div className="skeleton-line wide" />
        <div className="skeleton-line" />
        <div className="skeleton-action-row">
          <div className="skeleton-pill" />
          <div className="skeleton-pill short" />
        </div>
      </div>
      <div className="skeleton-metrics">
        {Array.from({ length: 6 }, (_, index) => (
          <div className="skeleton-card compact" key={index}>
            <div className="skeleton-line tiny" />
            <div className="skeleton-line medium" />
          </div>
        ))}
      </div>
      <div className="skeleton-grid">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="skeleton-card" key={index}>
            <div className="skeleton-line medium" />
            <div className="skeleton-line" />
            <div className="skeleton-line narrow" />
          </div>
        ))}
      </div>
    </section>
  );
}

function HomePage(props: {
  snapshot: ProjectSnapshot | null;
  recents: RecentTarget[];
  loading: boolean;
  environmentDiagnostics?: EnvironmentDiagnosticsSnapshot | null;
  environmentDiagnosticsLoading?: boolean;
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: HomeRoute) => void;
  onRefresh: () => void;
  onRunEnvironmentDiagnostics?: () => void;
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug";
}) {
  const model = buildHomeModel(props.snapshot);

  function runAction(action: HomeAction) {
    if (action.kind === "choose-project") props.onChoose();
    if (action.kind === "refresh") props.onRefresh();
    if (action.kind === "navigate" && action.route) props.onNavigate(action.route);
  }

  const noTarget = !props.snapshot;
  const hasRecentTargets = noTarget && props.recents.length > 0;

  async function copyCommand(command: string) {
    try {
      await navigator.clipboard.writeText(command);
    } catch {
      // Clipboard can be unavailable in static tests or browser previews.
    }
  }

  return (
    <section
      aria-label="Home"
      className={`home-page control-room-page ${noTarget ? "no-target" : "with-target"} ${hasRecentTargets ? "has-recents" : "no-recents"}`}
      data-testid="control-room-home"
    >
      <OperationalStatusHero
        loading={props.loading}
        model={model}
        noTarget={noTarget}
        onAction={runAction}
      />

      <MetricSignalStrip metrics={model.metrics} />

      {noTarget && props.recents.length > 0 && (
        <div className="home-recent-targets control-panel">
          <h2>Recent Projects</h2>
          <div className="recent-list">
            {props.recents.map((recent) => (
              <button
                className="recent-item"
                key={recent.path}
                onClick={() => props.onOpenRecent(recent)}
              >
                <span>{recent.name}</span>
                <small>{formatTimestamp(recent.lastOpenedAt)}</small>
              </button>
            ))}
          </div>
        </div>
      )}

      {noTarget && (
        <div className="control-panel home-setup-doctor span-3">
          <div className="panel-heading-row">
            <div>
              <h2>Backend checks</h2>
              <p>Check the backend runtime used by the packaged app.</p>
            </div>
            <button
              className="secondary-action"
              disabled={props.environmentDiagnosticsLoading}
              onClick={props.onRunEnvironmentDiagnostics}
            >
              <TerminalSquare size={15} />
              {props.environmentDiagnosticsLoading ? "Checking..." : "Run setup checks"}
            </button>
          </div>
          {props.environmentDiagnostics ? (
            <>
              <div className="home-setup-grid">
                {(props.environmentDiagnostics.runtime_environment.tools ?? []).map((tool) => (
                  <div className={`home-setup-tool ${tool.ok ? "good" : tool.required ? "warn" : "quiet"}`} key={tool.name}>
                    <span>{tool.name}</span>
                    <strong>{tool.ok ? "OK" : tool.required ? "Required" : "Optional"}</strong>
                    <p>{tool.detail}</p>
                  </div>
                ))}
              </div>
              <div className="home-setup-fixes">
                {props.environmentDiagnostics.fix_suggestions.map((item) => (
                  <div className="home-setup-fix" key={item.id}>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.detail}</p>
                      <code>{item.command}</code>
                    </div>
                    <button className="secondary-action" onClick={() => void copyCommand(item.command)}>
                      <Clipboard size={14} />
                      Copy
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-copy">
              Run checks to verify the backend PATH and required tools.
            </div>
          )}
        </div>
      )}

      {!noTarget && (
        <div className="control-room-grid">
          <QueueLedger
            emptyMessage={model.queueLedger.emptyMessage}
            onAction={runAction}
            rows={model.queueLedger.rows}
          />
          <HumanBridgeMini model={model.humanBridge} onAction={runAction} />
          <SafetyMatrix onAction={runAction} rows={model.safety.rows} />
          <EventLedger
            emptyMessage={model.eventLedger.emptyMessage}
            rows={model.eventLedger.rows}
          />
        </div>
      )}
    </section>
  );
}

function TargetRequiredPlaceholder(props: {
  view: TargetRequiredView;
  recents: RecentTarget[];
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: HomeRoute) => void;
}) {
  const copy = targetRequiredCopy[props.view];
  const Icon = views.find((view) => view.key === props.view)?.icon ?? Home;

  return (
    <section className="target-placeholder">
      <div className="empty-mark">
        <Icon className="surface-icon-image" size={42} />
      </div>
      <span className="target-placeholder-eyebrow">{viewLabel(props.view)}</span>
      <h1>{copy.title}</h1>
      <p>{copy.body}</p>
      <small>{copy.detail}</small>
      <div className="target-placeholder-actions">
        <button className="primary-action" onClick={props.onChoose}>
          <FolderOpen size={18} />
          Choose project
        </button>
        <button className="secondary-action" onClick={() => props.onNavigate("Brief")}>
          Open setup
        </button>
      </div>
      {props.recents.length > 0 && (
        <div className="target-placeholder-recents">
          <strong>Recent projects</strong>
          <div className="recent-list">
            {props.recents.slice(0, 4).map((recent) => (
              <button className="recent-item" key={recent.path} onClick={() => props.onOpenRecent(recent)}>
                <span>{recent.name}</span>
                <small>{formatTimestamp(recent.lastOpenedAt)}</small>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function LoadedView(props: {
  activeView: ViewKey;
  snapshot: ProjectSnapshot;
  recents: RecentTarget[];
  loading: boolean;
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: HomeRoute) => void;
  onRefresh: () => void;
  onDirtyChange?: (view: ViewKey, message: string | null) => void;
  onBusyChange?: (view: ViewKey, busy: boolean) => void;
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug";
}) {
  const { snapshot } = props;
  if (props.activeView === "Home") {
    return (
      <HomePage
        snapshot={snapshot}
        recents={props.recents}
        loading={props.loading}
        onChoose={props.onChoose}
        onOpenRecent={props.onOpenRecent}
        onNavigate={props.onNavigate}
        onRefresh={props.onRefresh}
      />
    );
  }

  if (props.activeView === "Brief") {
    return (
      <BriefWizard
        snapshot={snapshot}
        recents={props.recents}
        loading={props.loading}
        onChoose={props.onChoose}
        onOpenRecent={props.onOpenRecent}
        onNavigate={props.onNavigate}
        onRefresh={props.onRefresh}
        onDirtyChange={(message) => props.onDirtyChange?.("Brief", message)}
        onBusyChange={(busy) => props.onBusyChange?.("Brief", busy)}
      />
    );
  }

  if (props.activeView === "Run") {
    return (
      <RunPage
        snapshot={snapshot}
        loading={props.loading}
        onChoose={props.onChoose}
        onNavigate={props.onNavigate}
        onRefresh={props.onRefresh}
        onDirtyChange={(message) => props.onDirtyChange?.("Run", message)}
        onBusyChange={(busy) => props.onBusyChange?.("Run", busy)}
      />
    );
  }

  if (props.activeView === "Observatory") {
    return (
      <ObservatoryPage
        snapshot={snapshot}
        loading={props.loading}
        onChoose={props.onChoose}
        onRefresh={props.onRefresh}
      />
    );
  }

  if (props.activeView === "Inbox") {
    return (
      <InboxPage
        snapshot={snapshot}
        loading={props.loading}
        onRefresh={props.onRefresh}
      />
    );
  }

  if (props.activeView === "Review") {
    return (
      <ReviewPage
        snapshot={snapshot}
        loading={props.loading}
        onNavigate={props.onNavigate}
        onRefresh={props.onRefresh}
      />
    );
  }

  if (props.activeView === "Advanced") {
    return (
      <AdvancedPage
        snapshot={snapshot}
        loading={props.loading}
        onRefresh={props.onRefresh}
        initialTab={props.advancedInitialTab}
      />
    );
  }

  return null;
}

type CachedRouteSurfaceProps = {
  view: ViewKey;
  isActive: boolean;
  snapshot: ProjectSnapshot;
  recents: RecentTarget[];
  loading: boolean;
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: HomeRoute) => void;
  onRefresh: () => void;
  onDirtyChange?: (view: ViewKey, message: string | null) => void;
  onBusyChange?: (view: ViewKey, busy: boolean) => void;
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug";
};

const CachedRouteSurface = memo(function CachedRouteSurface(props: CachedRouteSurfaceProps) {
  return (
    <div
      aria-hidden={!props.isActive}
      className="cached-route-surface"
      hidden={!props.isActive}
    >
      <LoadedView
        activeView={props.view}
        snapshot={props.snapshot}
        recents={props.recents}
        loading={props.loading}
        onChoose={props.onChoose}
        onOpenRecent={props.onOpenRecent}
        onNavigate={props.onNavigate}
        onRefresh={props.onRefresh}
        onDirtyChange={props.onDirtyChange}
        onBusyChange={props.onBusyChange}
        advancedInitialTab={props.advancedInitialTab}
      />
    </div>
  );
}, (previous, next) => (
  previous.view === next.view &&
  previous.isActive === next.isActive &&
  previous.snapshot === next.snapshot &&
  previous.recents === next.recents &&
  previous.loading === next.loading &&
  previous.advancedInitialTab === next.advancedInitialTab
));

function CachedLoadedView(props: {
  activeView: ViewKey;
  snapshot: ProjectSnapshot;
  recents: RecentTarget[];
  loading: boolean;
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onNavigate: (view: HomeRoute) => void;
  onRefresh: () => void;
  cachedRoutes: CachedRouteVisits;
  onDirtyChange?: (view: ViewKey, message: string | null) => void;
  onBusyChange?: (view: ViewKey, busy: boolean) => void;
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug";
}) {
  return (
    <>
      {views
        .filter((view) => props.activeView === view.key || props.cachedRoutes[view.key])
        .map((view) => (
          <CachedRouteSurface
            advancedInitialTab={props.advancedInitialTab}
            isActive={props.activeView === view.key}
            key={`${view.key}-${props.snapshot.target.path}`}
            loading={props.loading}
            onChoose={props.onChoose}
            onOpenRecent={props.onOpenRecent}
            onNavigate={props.onNavigate}
            onRefresh={props.onRefresh}
            onDirtyChange={props.onDirtyChange}
            onBusyChange={props.onBusyChange}
            recents={props.recents}
            snapshot={props.snapshot}
            view={view.key}
          />
        ))}
    </>
  );
}

function App(props: { initialView?: ViewKey; initialProjectMenuOpen?: boolean } = {}) {
  const [activeView, setActiveView] = useState<ViewKey>(props.initialView ?? "Home");
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null);
  const [selectedTarget, setSelectedTarget] = useState<RecentTarget | null>(null);
  const [recents, setRecents] = useState<RecentTarget[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshFailure, setRefreshFailure] = useState<{ message: string; at: number } | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteBusyId, setPaletteBusyId] = useState<PaletteCommandId | "">("");
  const [paletteError, setPaletteError] = useState("");
  const [paletteMessage, setPaletteMessage] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [environmentDiagnostics, setEnvironmentDiagnostics] = useState<EnvironmentDiagnosticsSnapshot | null>(null);
  const [environmentDiagnosticsLoading, setEnvironmentDiagnosticsLoading] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(props.initialProjectMenuOpen ?? false);
  const [windowState, setWindowState] = useState<"windowed" | "maximized" | "fullscreen">("windowed");
  const [nowTick, setNowTick] = useState(Date.now());
  const [cachedRoutes, setCachedRoutes] = useState<CachedRouteVisits>(() => createCachedRouteVisits());
  const [cachedRoutesTargetPath, setCachedRoutesTargetPath] = useState("");
  const [dirtyRoutes, setDirtyRoutes] = useState<DirtyRouteState>({});
  const [busyRoutes, setBusyRoutes] = useState<BusyRouteState>({});
  const [advancedInitialTab, setAdvancedInitialTab] = useState<
    "Files" | "Diagnostics" | "Settings" | "Debug" | undefined
  >();
  const projectMenuRef = useRef<HTMLDivElement>(null);
  const projectChipRef = useRef<HTMLButtonElement>(null);
  const projectMenuFirstButtonRef = useRef<HTMLButtonElement>(null);
  const paletteTriggerRef = useRef<HTMLButtonElement>(null);
  const lastFocusedBeforePaletteRef = useRef<HTMLElement | null>(null);
  const sidebarNavRef = useRef<HTMLElement>(null);
  const refreshInFlightRef = useRef(false);
  const selectedTargetPathRef = useRef<string | null>(null);

  const topbarModel = useMemo(() => buildHomeModel(snapshot), [snapshot]);
  const status = topbarModel.statusLabel;
  const topbarStatusLabel = formatTopbarStatusLabel(status);
  const tone = topbarModel.statusTone;
  const showStatusPill = tone !== "good" || !["active", "ready"].includes(status.toLowerCase());
  const sidebarBadges = useMemo(() => buildSidebarBadges(snapshot), [snapshot]);
  const sidecar = useMemo(() => sidecarState(snapshot), [snapshot]);
  const branchLabel = textValue(snapshot?.run.git?.branch, snapshot ? "Unknown branch" : "No branch");
  const dirtyCount = numberValue(snapshot?.run.git?.dirty_count);
  const dirtyLabel = formatDirtyLabel(dirtyCount, Boolean(snapshot));
  const routeBusy = hasBusyRouteState(busyRoutes);
  const shellBusy = Boolean(paletteBusyId) || routeBusy;
  const dirtyRouteMessage = Object.values(dirtyRoutes).find((message): message is string => Boolean(message)) ?? null;
  const refreshPauseReason = autoRefreshBlocker({
    hasSelectedTarget: Boolean(selectedTarget),
    loadState,
    refreshInFlight: refreshInFlightRef.current,
    hasDirtyRoutes: hasDirtyRouteState(dirtyRoutes),
    hasBusyCommands: shellBusy,
  });
  const updatedChip = buildAutoRefreshChipState({
    lastUpdatedAt,
    now: nowTick,
    refreshing,
    pauseReason: refreshPauseReason,
    pauseDetail: dirtyRouteMessage,
    failureMessage: refreshFailure?.message ?? null,
    overdueMs: autoRefreshOverdueMs(snapshot),
  });
  const updatedLabel = updatedChip.label;
  const updatedTitle = updatedChip.title;
  const paletteCommands = useMemo(
    () => buildCommandPaletteModel({
      snapshot,
      loading: loadState === "loading" || refreshing,
      busy: Boolean(paletteBusyId),
    }),
    [loadState, paletteBusyId, refreshing, snapshot],
  );

  const projectChip = useMemo(() => {
    if (!snapshot) return "Choose project";
    return topbarModel.projectName;
  }, [snapshot, topbarModel.projectName]);

  function announce(message: string) {
    setAnnouncement(message);
  }

  function openPalette() {
    lastFocusedBeforePaletteRef.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : paletteTriggerRef.current;
    setPaletteOpen(true);
  }

  function closePalette() {
    setPaletteOpen(false);
    window.setTimeout(() => {
      lastFocusedBeforePaletteRef.current?.focus();
    }, 0);
  }

  function handleSidebarKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    const buttons = Array.from(
      sidebarNavRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? [],
    );
    if (!buttons.length) return;
    const currentIndex = Math.max(0, buttons.indexOf(document.activeElement as HTMLButtonElement));
    const nextIndex =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? buttons.length - 1
          : event.key === "ArrowDown" || event.key === "ArrowRight"
            ? (currentIndex + 1) % buttons.length
            : (currentIndex - 1 + buttons.length) % buttons.length;
    event.preventDefault();
    buttons[nextIndex]?.focus();
  }

  async function syncNativeWindowState() {
    try {
      const nativeWindow = getCurrentWindow();
      const isFullscreen = await nativeWindow.isFullscreen();
      const isMaximized = await nativeWindow.isMaximized();
      setWindowState(isFullscreen ? "fullscreen" : isMaximized ? "maximized" : "windowed");
    } catch {
      setWindowState("windowed");
    }
  }

  async function refreshRecents() {
    try {
      setRecents(await listRecentProjects());
    } catch {
      setRecents([]);
    }
  }

  function applyEnvelope(
    envelope: BackendEnvelope<ProjectSnapshot>,
    target?: RecentTarget,
    options: { announceLoaded?: boolean } = {},
  ) {
    if (!envelope.ok || !envelope.data) {
      setLoadState("error");
      setError(envelope.message ?? "The backend command failed.");
      announce(envelope.message ?? "The backend command failed.");
      return;
    }
    setSnapshot(envelope.data);
    setSelectedTarget(
      target ?? {
        path: envelope.data.target.path,
        name: envelope.data.target.name,
        lastOpenedAt: Math.floor(Date.now() / 1000),
      },
    );
    setError(null);
    setRefreshFailure(null);
    setLastUpdatedAt(Date.now());
    setLoadState("loaded");
    if (options.announceLoaded !== false) {
      announce(`Loaded ${envelope.data.target.name}.`);
    }
  }

  function setRouteDirtyState(view: ViewKey, message: string | null) {
    setDirtyRoutes((current) => {
      if (!message) {
        if (!current[view]) return current;
        const next = { ...current };
        delete next[view];
        return next;
      }
      if (current[view] === message) return current;
      return { ...current, [view]: message };
    });
  }

  function setRouteBusyState(view: ViewKey, busy: boolean) {
    setBusyRoutes((current) => {
      if (!busy) {
        if (!current[view]) return current;
        const next = { ...current };
        delete next[view];
        return next;
      }
      if (current[view] === true) return current;
      return { ...current, [view]: true };
    });
  }

  function blockDirtyRouteExit(action: string): boolean {
    const message = dirtyRoutes[activeView];
    if (!message) return false;
    const detail = `${message} ${action}`;
    setError(detail);
    announce(detail);
    return true;
  }

  async function chooseProject() {
    if (blockDirtyRouteExit(`Save or clear changes before switching projects from ${viewLabel(activeView)}.`)) return;
    setProjectMenuOpen(false);
    setLoadState("loading");
    setRefreshing(false);
    setError(null);
    announce("Opening project chooser.");
    try {
      const result = await selectProjectFolder();
      if (!result) {
        setLoadState(snapshot ? "loaded" : "idle");
        announce("Project selection cancelled.");
        return;
      }
      applyEnvelope(result.snapshot, result.target);
      await refreshRecents();
    } catch (err) {
      setLoadState("error");
      const message = err instanceof Error ? err.message : "Could not open the selected project.";
      setError(message);
      announce(message);
    }
  }

  async function openRecent(target: RecentTarget) {
    if (blockDirtyRouteExit(`Save or clear changes before opening another project from ${viewLabel(activeView)}.`)) return;
    setProjectMenuOpen(false);
    setLoadState("loading");
    setRefreshing(false);
    setError(null);
    announce(`Loading ${target.name}.`);
    try {
      const envelope = await loadProjectSnapshot(target.path);
      applyEnvelope(envelope, target);
      await refreshRecents();
    } catch (err) {
      setLoadState("error");
      const message = err instanceof Error ? err.message : "Could not load the recent project.";
      setError(message);
      announce(message);
    }
  }

  async function refreshProject(options: {
    silent?: boolean;
    respectDirtyRoutes?: boolean;
    updateRecents?: boolean;
  } = {}) {
    if (!selectedTarget) return;
    const refreshTarget = selectedTarget;
    const silent = options.silent === true;
    const shouldRespectRouteState = options.respectDirtyRoutes === true;
    const updateRecents = options.updateRecents !== false;
    if (
      shouldRespectRouteState &&
      !canAutoRefreshProject({
        hasSelectedTarget: true,
        loadState,
        refreshInFlight: refreshInFlightRef.current,
        hasDirtyRoutes: hasDirtyRouteState(dirtyRoutes),
        hasBusyCommands: shellBusy,
      })
    ) {
      return;
    }
    if (refreshInFlightRef.current || loadState === "loading") return;
    refreshInFlightRef.current = true;
    if (!silent) {
      setRefreshing(true);
      setError(null);
      setRefreshFailure(null);
      announce("Refreshing target.");
    }
    try {
      const envelope = updateRecents
        ? await loadProjectSnapshot(refreshTarget.path)
        : await runBackendCommand<ProjectSnapshot>({
            command: "project.load_snapshot",
            target: refreshTarget.path,
          });
      if (selectedTargetPathRef.current !== refreshTarget.path) return;
      if (!envelope.ok || !envelope.data) {
        const message = envelope.message ?? "Could not refresh the selected project.";
        setRefreshFailure({ message, at: Date.now() });
        if (!silent) {
          setError(message);
          announce(message);
        }
        return;
      }
      applyEnvelope(envelope, refreshTarget, { announceLoaded: false });
      if (updateRecents) await refreshRecents();
      if (!silent) announce("Target refreshed.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not refresh the selected project.";
      setRefreshFailure({ message, at: Date.now() });
      if (!silent) {
        setError(message);
        announce(message);
      }
    } finally {
      refreshInFlightRef.current = false;
      if (!silent) setRefreshing(false);
    }
  }

  async function runEnvironmentDiagnostics() {
    setEnvironmentDiagnosticsLoading(true);
    setError(null);
    announce("Running backend environment checks.");
    try {
      const payload = await runBackendCommand<EnvironmentDiagnosticsSnapshot>({
        command: "diagnostics.environment",
      });
      if (!payload.ok || !payload.data) {
        const message = payload.message ?? "Could not run backend environment checks.";
        setError(message);
        announce(message);
        return;
      }
      setEnvironmentDiagnostics(payload.data);
      announce("Backend environment checks completed.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not run backend environment checks.";
      setError(message);
      announce(message);
    } finally {
      setEnvironmentDiagnosticsLoading(false);
    }
  }

  function navigate(view: HomeRoute) {
    if (view !== activeView && loadState !== "loaded" && blockDirtyRouteExit(`Save or clear changes before leaving ${viewLabel(activeView)}.`)) return;
    if (view !== "Advanced") {
      setAdvancedInitialTab(undefined);
    }
    setProjectMenuOpen(false);
    setActiveView(view);
  }

  function closeProject() {
    if (blockDirtyRouteExit(`Save or clear changes before closing ${viewLabel(activeView)}.`)) return;
    setProjectMenuOpen(false);
    setSnapshot(null);
    setSelectedTarget(null);
    setError(null);
    setLastUpdatedAt(null);
    setRefreshFailure(null);
    setRefreshing(false);
    setLoadState("idle");
    setAdvancedInitialTab(undefined);
    setDirtyRoutes({});
    setBusyRoutes({});
    setCachedRoutes(createCachedRouteVisits());
    setCachedRoutesTargetPath("");
    refreshInFlightRef.current = false;
    selectedTargetPathRef.current = null;
    setActiveView("Home");
    announce("Project closed.");
  }

  async function revealSelectedProject() {
    if (!selectedTarget) return;
    setProjectMenuOpen(false);
    try {
      await revealProject(selectedTarget.path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function openSelectedProjectInEditor() {
    if (!selectedTarget) return;
    setProjectMenuOpen(false);
    try {
      await openProjectInEditor(selectedTarget.path);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function runPaletteStreamed(command: PaletteCommand, backendCommand: string) {
    if (!snapshot) return;
    setPaletteBusyId(command.id);
    setPaletteError("");
    setPaletteMessage(`${command.title} started.`);
    announce(`${command.title} started.`);
    try {
      const payload = await runBackendCommandStreamed({
        runId: `palette-${command.id}-${Date.now()}`,
        command: backendCommand,
        target: snapshot.target.path,
      });
      if (!payload.ok) {
        const message = payload.message ?? `${command.title} failed.`;
        setPaletteError(message);
        announce(message);
        return;
      }
      setPaletteMessage(`${command.title} completed.`);
      announce(`${command.title} completed.`);
      await refreshProject();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setPaletteError(message);
      announce(message);
    } finally {
      setPaletteBusyId("");
    }
  }

  async function executePaletteCommand(command: PaletteCommand) {
    if (command.disabledReason) {
      setPaletteError(command.disabledReason);
      announce(command.disabledReason);
      return;
    }
    setPaletteError("");
    setPaletteMessage("");
    const target = snapshot?.target.path ?? "";

    if (command.id === "open-project") {
      closePalette();
      await chooseProject();
      return;
    }
    if (command.id === "close-project") {
      closeProject();
      closePalette();
      return;
    }
    if (command.id === "create-new-project") {
      navigate("Brief");
      closePalette();
      return;
    }
    if (command.id === "open-control-room") {
      navigate("Home");
      closePalette();
      return;
    }
    if (command.id === "continue-brief" || command.id === "scaffold-bootstrap") {
      navigate("Brief");
      closePalette();
      return;
    }
    if (command.id === "open-run-control") {
      navigate("Run");
      closePalette();
      return;
    }
    if (command.id === "open-observatory") {
      navigate("Observatory");
      closePalette();
      return;
    }
    if (command.id === "open-human-bridge") {
      navigate("Inbox");
      closePalette();
      return;
    }
    if (command.id === "open-review") {
      navigate("Review");
      closePalette();
      return;
    }
    if (command.id === "open-sidecar") {
      navigate("Advanced");
      closePalette();
      return;
    }
    if (command.id === "send-note-next-run") {
      navigate("Inbox");
      closePalette();
      return;
    }
    if (command.id === "open-diagnostics") {
      setAdvancedInitialTab("Diagnostics");
      setActiveView("Advanced");
      closePalette();
      return;
    }
    if (command.id === "reveal-project") {
      setPaletteBusyId(command.id);
      try {
        await revealProject(target);
        setPaletteMessage("Project revealed.");
        announce("Project revealed.");
        closePalette();
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setPaletteError(message);
        announce(message);
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "open-project-editor") {
      setPaletteBusyId(command.id);
      try {
        await openProjectInEditor(target);
        setPaletteMessage("Project opened in editor.");
        announce("Project opened in editor.");
        closePalette();
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setPaletteError(message);
        announce(message);
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "import-context-files") {
      setPaletteBusyId(command.id);
      try {
        const picked = await selectContextFiles();
        if (!picked.length) {
          setPaletteMessage("No context files selected.");
          announce("No context files selected.");
          return;
        }
        const payload = await runBackendCommand({
          command: "context.import",
          target,
          filesJson: JSON.stringify(picked.map((file) => file.path)),
          projectName: snapshot?.brief.project_name || snapshot?.target.name || "New Project",
        });
        if (!payload.ok) {
          const message = payload.message ?? "Context import failed.";
          setPaletteError(message);
          announce(message);
          return;
        }
        setPaletteMessage("Context files imported.");
        announce("Context files imported.");
        await refreshProject();
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setPaletteError(message);
        announce(message);
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "start-automation") {
      await runPaletteStreamed(command, "automation.start");
      return;
    }
    if (command.id === "stop-automation") {
      await runPaletteStreamed(command, "automation.stop");
      return;
    }
    if (command.id === "run-safety-check") {
      await runPaletteStreamed(command, "safety.run_check");
      return;
    }
    if (command.id === "export-review-bundle") {
      setPaletteBusyId(command.id);
      try {
        const payload = await runBackendCommand({
          command: "review.export_bundle",
          target,
          reviewDir: targetSubdir(target, "first-review"),
        });
        if (!payload.ok) {
          const message = payload.message ?? "Could not export the review files.";
          setPaletteError(message);
          announce(message);
          return;
        }
        setPaletteMessage("Review export written.");
        announce("Review export written.");
        await refreshProject();
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setPaletteError(message);
        announce(message);
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "open-raw-automation-tasks") {
      setPaletteBusyId(command.id);
      try {
        await openManagedFile(target, "monitor.automation_tasks");
        announce("Task state opened.");
        closePalette();
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setPaletteError(message);
        announce(message);
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "export-debug-bundle") {
      setPaletteBusyId(command.id);
      try {
        const settings = await getAdvancedSettings();
        const outputDir = settings.reviewExportDir || targetSubdir(target, "debug-bundles");
        const payload = await runBackendCommand({
          command: "advanced.export_debug_bundle",
          target,
          outputDir,
        });
        if (!payload.ok) {
          const message = payload.message ?? "Could not export the debug files.";
          setPaletteError(message);
          announce(message);
          return;
        }
        setPaletteMessage("Debug export written.");
        announce("Debug export written.");
      } catch (caught) {
        const message = caught instanceof Error ? caught.message : String(caught);
        setPaletteError(message);
        announce(message);
      } finally {
        setPaletteBusyId("");
      }
    }
  }

  useEffect(() => {
    refreshRecents();
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    selectedTargetPathRef.current = selectedTarget?.path ?? null;
  }, [selectedTarget?.path]);

  useEffect(() => {
    if (!selectedTarget || loadState !== "loaded") return;
    const id = window.setInterval(() => {
      void refreshProject({
        silent: true,
        respectDirtyRoutes: true,
        updateRecents: false,
      });
    }, autoRefreshIntervalMs(snapshot));
    return () => window.clearInterval(id);
  }, [selectedTarget?.path, loadState, snapshot, dirtyRoutes, shellBusy]);

  useEffect(() => {
    if (!selectedTarget) return;
    function refreshOnReturn() {
      if (document.visibilityState === "hidden") return;
      if (!shouldRefreshOnFocus(lastUpdatedAt)) return;
      void refreshProject({
        silent: true,
        respectDirtyRoutes: true,
        updateRecents: false,
      });
    }
    window.addEventListener("focus", refreshOnReturn);
    document.addEventListener("visibilitychange", refreshOnReturn);
    return () => {
      window.removeEventListener("focus", refreshOnReturn);
      document.removeEventListener("visibilitychange", refreshOnReturn);
    };
  }, [selectedTarget?.path, lastUpdatedAt, loadState, dirtyRoutes, shellBusy]);

  useEffect(() => {
    setCachedRoutes(createCachedRouteVisits());
    setCachedRoutesTargetPath(snapshot?.target.path ?? "");
    setDirtyRoutes({});
    setBusyRoutes({});
  }, [snapshot?.target.path]);

  useEffect(() => {
    if (!snapshot?.target.path) return;
    setCachedRoutesTargetPath(snapshot?.target.path ?? "");
    setCachedRoutes((current) => {
      if (current[activeView]) return current;
      return { ...current, [activeView]: true };
    });
  }, [activeView, snapshot?.target.path]);

  useEffect(() => {
    void applyTransparentNativeBackground();
    void syncNativeWindowState();
    let disposed = false;
    let unlistenResize: (() => void) | undefined;
    let unlistenMove: (() => void) | undefined;
    try {
      const nativeWindow = getCurrentWindow();
      nativeWindow.onResized(() => void syncNativeWindowState()).then((unlisten) => {
        if (disposed) unlisten();
        else unlistenResize = unlisten;
      });
      nativeWindow.onMoved(() => void syncNativeWindowState()).then((unlisten) => {
        if (disposed) unlisten();
        else unlistenMove = unlisten;
      });
    } catch {
      // Browser preview has no native window handle.
    }
    return () => {
      disposed = true;
      unlistenResize?.();
      unlistenMove?.();
    };
  }, []);

  useEffect(() => {
    if (!projectMenuOpen) return;
    window.setTimeout(() => projectMenuFirstButtonRef.current?.focus(), 0);
    function onPointerDown(event: globalThis.PointerEvent) {
      const menu = projectMenuRef.current;
      if (menu && !menu.contains(event.target as Node)) {
        setProjectMenuOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setProjectMenuOpen(false);
        projectChipRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [projectMenuOpen]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (paletteOpen) closePalette();
        else openPalette();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [paletteOpen]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const target = event.target as HTMLElement | null;
      const button = target?.closest("button");
      const tablist = button?.closest('[role="tablist"]');
      if (!button || !tablist) return;
      const buttons = Array.from(tablist.querySelectorAll<HTMLButtonElement>("button:not(:disabled)"));
      if (!buttons.length) return;
      const currentIndex = Math.max(0, buttons.indexOf(button));
      const nextIndex =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? buttons.length - 1
            : event.key === "ArrowRight"
              ? (currentIndex + 1) % buttons.length
              : (currentIndex - 1 + buttons.length) % buttons.length;
      event.preventDefault();
      buttons[nextIndex]?.focus();
      buttons[nextIndex]?.click();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    document.title = `${viewLabel(activeView)} - Diffmogger`;
  }, [activeView]);

  return (
    <div className="app-shell" data-window-state={windowState}>
      <header className="titlebar">
        <WindowControls onWindowStateChange={() => void syncNativeWindowState()} />
        <div className="titlebar-drag-region" data-tauri-drag-region onPointerDown={startTitlebarDrag}>
          <div className="brand" data-tauri-drag-region>
            <img className="brand-logo" src={diffmoggerLogo} alt="Diffmogger" />
          </div>
          <div className="titlebar-spacer" data-tauri-drag-region />
        </div>
      </header>

      <aside className="sidebar">
        <nav
          aria-label="Primary surfaces"
          data-testid="primary-icon-rail"
          onKeyDown={handleSidebarKeyDown}
          ref={sidebarNavRef}
        >
          {views.map((view) => {
            const Icon = view.icon;
            const badge = sidebarBadges[view.key];
            const badgeLabel = badge?.label ?? "";
            const visibleBadgeLabel = /^\d+$/.test(badgeLabel) ? badgeLabel : "";
            const ariaLabel = badgeLabel ? `${view.label}, ${badgeLabel}` : view.label;
            return (
              <button
                aria-current={activeView === view.key ? "page" : undefined}
                aria-label={ariaLabel}
                className={activeView === view.key ? "active" : ""}
                data-aliases={`${view.label} ${view.legacyLabel}`}
                data-legacy-label={view.legacyLabel}
                data-sidebar-view={view.key}
                data-testid={`sidebar-nav-${view.key}`}
                data-tooltip={view.label}
                key={view.key}
                onClick={() => navigate(view.key)}
                title={view.label}
              >
                <Icon className="surface-icon-image" size={28} />
                <span className="sidebar-label">{view.label}</span>
                {badge && (
                  <em
                    aria-label={badgeLabel}
                    className={`sidebar-badge ${badge.tone} ${visibleBadgeLabel ? "has-label" : ""}`}
                    title={badgeLabel}
                  >
                    {visibleBadgeLabel}
                  </em>
                )}
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="workspace">
        <section className="topbar target-context-strip" aria-label="Target context strip" data-testid="target-context-strip">
          <div className="project-menu-wrap" ref={projectMenuRef}>
            <button
              aria-label={snapshot ? `Switch project, current target ${projectChip}` : "Choose project"}
              aria-expanded={projectMenuOpen}
              aria-haspopup="menu"
              className={`project-chip ${projectMenuOpen ? "open" : ""}`}
              ref={projectChipRef}
              title={selectedTarget?.path ?? "Choose a project folder"}
              onClick={() => setProjectMenuOpen((open) => !open)}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setProjectMenuOpen(true);
                }
              }}
            >
              <span>{projectChip}</span>
              <ChevronDown size={14} />
            </button>
            {projectMenuOpen && (
              <div className="project-menu" role="menu" data-no-drag>
                <div className="project-menu-group">
                  <button ref={projectMenuFirstButtonRef} role="menuitem" onClick={chooseProject}>
                    <FolderOpen size={15} />
                    Switch project...
                  </button>
                  <button role="menuitem" onClick={() => navigate("Brief")}>
                    <FileText size={15} />
                    New project
                  </button>
                </div>
                {recents.length > 0 && (
                  <div className="project-menu-group">
                    <strong>Recent</strong>
                    {recents.slice(0, 5).map((recent) => (
                      <button key={recent.path} role="menuitem" onClick={() => openRecent(recent)} title={recent.path}>
                        <span>{recent.name}</span>
                        <small>{formatTimestamp(recent.lastOpenedAt)}</small>
                      </button>
                    ))}
                  </div>
                )}
                <div className="project-menu-group">
                  <button disabled={!selectedTarget} role="menuitem" onClick={revealSelectedProject}>
                    <FolderOpen size={15} />
                    Reveal in Finder
                  </button>
                  <button disabled={!selectedTarget} role="menuitem" onClick={openSelectedProjectInEditor}>
                    <ExternalLink size={15} />
                    Open in Editor
                  </button>
                  <button disabled={!selectedTarget} role="menuitem" onClick={closeProject}>
                    <LogOut size={15} />
                    Close Project
                  </button>
                </div>
              </div>
            )}
          </div>
          <div className="target-context-meta" aria-label="Target metadata">
            <span className={`context-chip ${snapshot ? "info" : "quiet"}`} data-testid="target-context-branch" title={branchLabel}>
              <GitBranch size={14} />
              <span>{branchLabel}</span>
            </span>
            <span className={`context-chip ${sidecar.tone}`} data-testid="target-context-sidecar" title={sidecar.label}>
              <Database size={14} />
              <span>{sidecar.label}</span>
            </span>
            <span className={`context-chip ${dirtyCount ? "warn" : snapshot ? "good" : "quiet"}`} data-testid="target-context-dirty" title={dirtyLabel}>
              {dirtyCount ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
              <span>{dirtyLabel}</span>
            </span>
            {showStatusPill && (
              <span className={`status-pill context-chip ${tone}`} data-testid="target-context-status" title={topbarStatusLabel}>
                {tone === "critical" || tone === "warn" ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
                <span>{topbarStatusLabel}</span>
              </span>
            )}
            <span
              className={`context-chip ${updatedChip.tone} updated-chip`}
              data-testid="target-context-updated"
              title={updatedTitle}
            >
              <span>{updatedLabel}</span>
            </span>
          </div>
          <div className="topbar-actions">
            <button
              aria-label="Refresh target"
              className={`icon-button ${refreshing ? "refreshing" : ""}`}
              data-tooltip="Refresh target"
              disabled={!selectedTarget || loadState === "loading" || refreshing}
              title="Refresh target"
              onClick={() => void refreshProject()}
            >
              <RefreshCw className={refreshing ? "spin" : ""} size={17} />
            </button>
            <button
              aria-label="Open command palette"
              className="command-button"
              data-testid="command-palette-trigger"
              ref={paletteTriggerRef}
              title="Command Palette (Cmd/Ctrl+K)"
              onClick={() => {
                if (paletteOpen) closePalette();
                else openPalette();
              }}
            >
              <Command size={17} />
              <span>Command</span>
            </button>
          </div>
        </section>

        <section className="stage">
          {loadState === "loading" && (
            <ShellSkeleton />
          )}

          {loadState === "idle" &&
            (activeView === "Brief" ? (
              <BriefWizard
                snapshot={null}
                recents={recents}
                loading={false}
                onChoose={chooseProject}
                onOpenRecent={openRecent}
                onNavigate={navigate}
                onRefresh={refreshProject}
                onDirtyChange={(message) => setRouteDirtyState("Brief", message)}
              />
            ) : activeView === "Home" ? (
              <HomePage
                snapshot={null}
                recents={recents}
                loading={false}
                environmentDiagnostics={environmentDiagnostics}
                environmentDiagnosticsLoading={environmentDiagnosticsLoading}
                onChoose={chooseProject}
                onOpenRecent={openRecent}
                onNavigate={navigate}
                onRefresh={refreshProject}
                onRunEnvironmentDiagnostics={runEnvironmentDiagnostics}
              />
            ) : viewRequiresTarget(activeView) ? (
              <TargetRequiredPlaceholder
                view={activeView}
                recents={recents}
                onChoose={chooseProject}
                onOpenRecent={openRecent}
                onNavigate={navigate}
              />
            ) : null)}

          {loadState === "error" && (
            <section className="error-state" role="alert">
              <h1>Backend Error</h1>
              <p>{error}</p>
              <div className="error-actions">
                <button className="primary-action" onClick={chooseProject}>
                  <FolderOpen size={18} />
                  Choose project
                </button>
                {selectedTarget && (
                  <button className="secondary-action" onClick={() => void refreshProject()}>
                    <RefreshCw size={17} />
                    Retry
                  </button>
                )}
              </div>
            </section>
          )}

          {loadState === "loaded" && snapshot && (
            <CachedLoadedView
              activeView={activeView}
              snapshot={snapshot}
              recents={recents}
              loading={false}
              onChoose={chooseProject}
              onOpenRecent={openRecent}
              onNavigate={navigate}
              onRefresh={refreshProject}
              cachedRoutes={
                cachedRoutesTargetPath === snapshot.target.path
                  ? cachedRoutes
                  : createCachedRouteVisits()
              }
              onDirtyChange={setRouteDirtyState}
              onBusyChange={setRouteBusyState}
              advancedInitialTab={advancedInitialTab}
            />
          )}
        </section>
      </main>

      {paletteOpen && (
        <CommandPalette
          commands={paletteCommands}
          busyCommandId={paletteBusyId}
          error={paletteError}
          message={paletteMessage}
          onClose={closePalette}
          onExecute={(command) => void executePaletteCommand(command)}
        />
      )}

      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-testid="shell-live-region">
        {announcement}
      </div>

      {error && loadState !== "error" && (
        <div className="shell-toast error" role="status">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}
    </div>
  );
}

export default App;
