import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clipboard,
  ClipboardCheck,
  Command,
  ExternalLink,
  FileText,
  FolderOpen,
  Home,
  Inbox,
  LogOut,
  PlayCircle,
  RefreshCw,
  SlidersHorizontal,
  Telescope,
  TerminalSquare,
} from "lucide-react";
import { memo, type PointerEvent, useEffect, useMemo, useRef, useState } from "react";
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
  openObservatoryFile,
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
import { HomeAction, HomeRoute, buildHomeModel } from "./homeModel";
import { InboxPage } from "./InboxPage";
import { ObservatoryPage } from "./ObservatoryPage";
import { ReviewPage } from "./ReviewPage";
import { RunPage } from "./RunPage";
import diffmoggerIcon from "./assets/diffmogger-icon.png";
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

const views: Array<{ key: ViewKey; icon: typeof Home }> = [
  { key: "Home", icon: Home },
  { key: "Brief", icon: FileText },
  { key: "Run", icon: PlayCircle },
  { key: "Observatory", icon: Telescope },
  { key: "Inbox", icon: Inbox },
  { key: "Review", icon: ClipboardCheck },
  { key: "Advanced", icon: SlidersHorizontal },
];

const transparentBackground: [number, number, number, number] = [0, 0, 0, 0];

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
    title: "Open a project before running automation",
    body: "Run controls, schedule state, worker strategy, and logs are target-local.",
    detail: "Choose a project folder to load readiness and automation controls, or continue the Brief to create a new target.",
  },
  Observatory: {
    title: "Open a project to view the Observatory",
    body: "The Observatory reconstructs automation progress from the selected target's commits, conveyor events, and patch queues.",
    detail: "Once a project is selected, this page shows the native build log and keeps the old HTML export available.",
  },
  Inbox: {
    title: "Open a project to use the human bridge",
    body: "Requests, replies, and notes to the next run live in target-local Markdown bridge files.",
    detail: "Choose a target to see pending requests or start a new Brief to configure file-only messaging.",
  },
  Review: {
    title: "Open a project before reviewing automation",
    body: "Review evidence is generated from the selected target's latest run, changed files, validation, and safety results.",
    detail: "After a project is loaded, you can export the review bundle or send follow-up notes to the next run.",
  },
  Advanced: {
    title: "Open a project to access managed files",
    body: "Diagnostics, raw Markdown editing, settings, and debug bundles are scoped to a selected target.",
    detail: "Choose a project folder to inspect allowed files and run readiness checks.",
  },
};

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

function formatLastUpdated(value: number | null): string {
  if (!value) return "Not loaded yet";
  return `Updated ${new Date(value).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

type SidebarBadge = {
  label: string;
  tone: "running" | "needs-input" | "blocked" | "review";
};

function buildSidebarBadges(snapshot: ProjectSnapshot | null): Partial<Record<ViewKey, SidebarBadge>> {
  if (!snapshot) return {};
  const task = recordValue(snapshot.run.task);
  const controls = recordValue(snapshot.run.controls);
  const schedule = recordValue(snapshot.run.schedule);
  const status = textValue(task.status, snapshot.home.automation_status).toUpperCase();
  const running =
    boolValue(controls.is_running) ||
    status.includes("RUNNING") ||
    textValue(schedule.state).toLowerCase() === "running";
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
      <button className="traffic-close" aria-label="Close" onClick={() => windowAction("close")}>
        <span />
      </button>
      <button className="traffic-minimize" aria-label="Minimize" onClick={() => windowAction("minimize")}>
        <span />
      </button>
      <button className="traffic-maximize" aria-label="Fullscreen" onClick={() => windowAction("fullscreen")}>
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

function StatTile(props: { label: string; value: string | number; tone?: string }) {
  return (
    <div className={`stat-tile ${props.tone ?? ""}`}>
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function DataRow(props: { label: string; value: string | number }) {
  return (
    <div className="data-row">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function ShellSkeleton() {
  return (
    <section className="skeleton-page" aria-label="Loading project">
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
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug bundle";
}) {
  const model = buildHomeModel(props.snapshot);

  function runAction(action: HomeAction) {
    if (action.kind === "choose-project") props.onChoose();
    if (action.kind === "refresh") props.onRefresh();
    if (action.kind === "navigate" && action.route) props.onNavigate(action.route);
  }

  const noTarget = !props.snapshot;
  const hasRecentTargets = noTarget && props.recents.length > 0;
  const showFirstRunEmpty = props.snapshot && model.hasNoRuns && !model.isUnconfigured;

  async function copyCommand(command: string) {
    try {
      await navigator.clipboard.writeText(command);
    } catch {
      // Clipboard can be unavailable in static tests or browser previews.
    }
  }

  return (
    <section className={`home-page ${noTarget ? "no-target" : "with-target"} ${hasRecentTargets ? "has-recents" : "no-recents"}`}>
      <div className={`home-banner ${model.statusTone}`}>
        <div>
          <div className="home-eyebrow">{model.projectName}</div>
          <h1>{model.headline}</h1>
          <p>{model.subheadline}</p>
          <div className="home-actions">
            <button
              className="primary-action"
              disabled={props.loading || model.primaryAction.kind === "disabled"}
              onClick={() => runAction(model.primaryAction)}
            >
              {model.primaryAction.label}
              <ArrowRight size={17} />
            </button>
            {model.secondaryActions.map((action) => (
              <button
                className="secondary-action"
                disabled={props.loading || action.kind === "disabled" || (action.kind === "refresh" && noTarget)}
                key={`${action.kind}-${action.label}`}
                onClick={() => runAction(action)}
              >
                {action.label}
              </button>
            ))}
          </div>
        </div>
        <div className={`state-badge ${model.statusTone}`}>
          {model.statusTone === "critical" || model.statusTone === "warn" ? (
            <AlertTriangle size={17} />
          ) : (
            <CheckCircle2 size={17} />
          )}
          {model.statusLabel}
        </div>
      </div>

      <div className="home-metrics">
        {model.metrics.map((metric) => (
          <StatTile
            key={metric.label}
            label={metric.label}
            value={metric.value}
            tone={metric.tone}
          />
        ))}
      </div>

      {noTarget && props.recents.length > 0 && (
        <div className="home-recent-targets panel">
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
        <div className="panel home-setup-doctor span-3">
          <div className="panel-heading-row">
            <div>
              <h2>Native Setup Doctor</h2>
              <p>Check the backend runtime the packaged app will use after cloning and building Diffmogger.</p>
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
              The native app uses a Homebrew-friendly backend PATH so GUI launches see the same tools as scheduled automation.
            </div>
          )}
        </div>
      )}

      {showFirstRunEmpty && (
        <div className="home-education panel span-3">
          <h2>No Automation Runs Yet</h2>
          <p>
            Diffmogger has scaffolded state for this project. The first run will create the initial
            evidence trail: validation notes, role outcomes, queue pressure, and review context.
          </p>
          <button className="secondary-action" onClick={() => props.onNavigate("Run")}>
            Run Once Now
          </button>
        </div>
      )}

      <div className="home-grid">
        <article className="panel home-card next-action-card">
          <h2>Recommended Next Action</h2>
          <strong>{model.recommendation.title}</strong>
          <p>{model.recommendation.reason}</p>
          <button
            className="secondary-action"
            disabled={model.recommendation.action.kind === "disabled"}
            onClick={() => runAction(model.recommendation.action)}
          >
            {model.recommendation.action.label}
          </button>
        </article>

        <article className="panel home-card safety-card">
          <h2>{model.safety.headline}</h2>
          {model.safety.items.length ? (
            <div className="safety-list">
              {model.safety.items.map((item) => (
                <div className={`safety-item ${item.tone}`} key={item.label}>
                  <div>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </div>
                  <p>{item.detail}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-copy">Select a target to load safety and readiness state.</div>
          )}
        </article>

        <article className="panel home-card progress-card">
          <h2>{model.progress.headline}</h2>
          {model.progress.empty ? (
            <div className="empty-copy">
              No landed automation work is recorded yet. Recent commits, role outcomes, and conveyor
              events will appear here after the first run.
            </div>
          ) : (
            <div className="progress-list">
              {model.progress.items.map((item) => (
                <div className={`progress-item ${item.tone}`} key={`${item.title}-${item.meta}`}>
                  <strong>{item.title}</strong>
                  <p>{item.detail}</p>
                  <span>{item.meta}</span>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="panel home-card human-card">
          <h2>Human Bridge</h2>
          <div className="human-counts">
            <StatTile label="Pending requests" value={model.humanBridge.pending} tone={model.humanBridge.pending ? "warn" : "good"} />
            <StatTile label="Unhandled notes" value={model.humanBridge.unhandled} tone={model.humanBridge.unhandled ? "warn" : "good"} />
          </div>
          <DataRow label="Latest note status" value={model.humanBridge.latestStatus} />
          <DataRow label="Outbound records" value={model.humanBridge.outbound} />
          <button
            className="secondary-action"
            disabled={model.humanBridge.action.kind === "disabled"}
            onClick={() => runAction(model.humanBridge.action)}
          >
            {model.humanBridge.action.label}
          </button>
        </article>
      </div>
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
  const Icon = views.find((view) => view.key === props.view)?.icon ?? FolderOpen;

  return (
    <section className="target-placeholder">
      <div className="empty-mark">
        <Icon size={26} />
      </div>
      <span className="target-placeholder-eyebrow">{props.view}</span>
      <h1>{copy.title}</h1>
      <p>{copy.body}</p>
      <small>{copy.detail}</small>
      <div className="target-placeholder-actions">
        <button className="primary-action" onClick={props.onChoose}>
          <FolderOpen size={18} />
          Choose Project Folder
        </button>
        <button className="secondary-action" onClick={() => props.onNavigate("Brief")}>
          Continue Brief
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
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug bundle";
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
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug bundle";
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
  advancedInitialTab?: "Files" | "Diagnostics" | "Settings" | "Debug bundle";
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
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteBusyId, setPaletteBusyId] = useState<PaletteCommandId | "">("");
  const [paletteError, setPaletteError] = useState("");
  const [paletteMessage, setPaletteMessage] = useState("");
  const [environmentDiagnostics, setEnvironmentDiagnostics] = useState<EnvironmentDiagnosticsSnapshot | null>(null);
  const [environmentDiagnosticsLoading, setEnvironmentDiagnosticsLoading] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(props.initialProjectMenuOpen ?? false);
  const [windowState, setWindowState] = useState<"windowed" | "maximized" | "fullscreen">("windowed");
  const [cachedRoutes, setCachedRoutes] = useState<CachedRouteVisits>(() => createCachedRouteVisits());
  const [cachedRoutesTargetPath, setCachedRoutesTargetPath] = useState("");
  const [advancedInitialTab, setAdvancedInitialTab] = useState<
    "Files" | "Diagnostics" | "Settings" | "Debug bundle" | undefined
  >();
  const projectMenuRef = useRef<HTMLDivElement>(null);

  const topbarModel = useMemo(() => buildHomeModel(snapshot), [snapshot]);
  const status = topbarModel.statusLabel;
  const tone = topbarModel.statusTone;
  const sidebarBadges = useMemo(() => buildSidebarBadges(snapshot), [snapshot]);
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
  ) {
    if (!envelope.ok || !envelope.data) {
      setLoadState("error");
      setError(envelope.message ?? "The backend command failed.");
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
    setLastUpdatedAt(Date.now());
    setLoadState("loaded");
  }

  async function chooseProject() {
    setProjectMenuOpen(false);
    setLoadState("loading");
    setRefreshing(false);
    setError(null);
    try {
      const result = await selectProjectFolder();
      if (!result) {
        setLoadState(snapshot ? "loaded" : "idle");
        return;
      }
      applyEnvelope(result.snapshot, result.target);
      await refreshRecents();
    } catch (err) {
      setLoadState("error");
      setError(err instanceof Error ? err.message : "Could not open the selected project.");
    }
  }

  async function openRecent(target: RecentTarget) {
    setProjectMenuOpen(false);
    setLoadState("loading");
    setRefreshing(false);
    setError(null);
    try {
      const envelope = await loadProjectSnapshot(target.path);
      applyEnvelope(envelope, target);
      await refreshRecents();
    } catch (err) {
      setLoadState("error");
      setError(err instanceof Error ? err.message : "Could not load the recent project.");
    }
  }

  async function refreshProject() {
    if (!selectedTarget) return;
    setRefreshing(true);
    setError(null);
    try {
      const envelope = await loadProjectSnapshot(selectedTarget.path);
      if (!envelope.ok || !envelope.data) {
        setError(envelope.message ?? "Could not refresh the selected project.");
        return;
      }
      applyEnvelope(envelope, selectedTarget);
      await refreshRecents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh the selected project.");
    } finally {
      setRefreshing(false);
    }
  }

  async function runEnvironmentDiagnostics() {
    setEnvironmentDiagnosticsLoading(true);
    setError(null);
    try {
      const payload = await runBackendCommand<EnvironmentDiagnosticsSnapshot>({
        command: "diagnostics.environment",
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not run native environment diagnostics.");
        return;
      }
      setEnvironmentDiagnostics(payload.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run native environment diagnostics.");
    } finally {
      setEnvironmentDiagnosticsLoading(false);
    }
  }

  function navigate(view: HomeRoute) {
    if (view !== "Advanced") {
      setAdvancedInitialTab(undefined);
    }
    setProjectMenuOpen(false);
    setActiveView(view);
  }

  function closeProject() {
    setProjectMenuOpen(false);
    setSnapshot(null);
    setSelectedTarget(null);
    setError(null);
    setLastUpdatedAt(null);
    setRefreshing(false);
    setLoadState("idle");
    setAdvancedInitialTab(undefined);
    setCachedRoutes(createCachedRouteVisits());
    setCachedRoutesTargetPath("");
    setActiveView("Home");
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

  async function runPaletteStreamed(command: PaletteCommand, backendCommand: string, confirmMessage?: string) {
    if (!snapshot) return;
    if (confirmMessage && !confirm(confirmMessage)) return;
    setPaletteBusyId(command.id);
    setPaletteError("");
    setPaletteMessage(`${command.title} started.`);
    try {
      const payload = await runBackendCommandStreamed({
        runId: `palette-${command.id}-${Date.now()}`,
        command: backendCommand,
        target: snapshot.target.path,
      });
      if (!payload.ok) {
        setPaletteError(payload.message ?? `${command.title} failed.`);
        return;
      }
      setPaletteMessage(`${command.title} completed.`);
      await refreshProject();
    } catch (caught) {
      setPaletteError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setPaletteBusyId("");
    }
  }

  async function executePaletteCommand(command: PaletteCommand) {
    if (command.disabledReason) {
      setPaletteError(command.disabledReason);
      return;
    }
    setPaletteError("");
    setPaletteMessage("");
    const target = snapshot?.target.path ?? "";

    if (command.id === "open-project") {
      setPaletteOpen(false);
      await chooseProject();
      return;
    }
    if (command.id === "close-project") {
      closeProject();
      setPaletteOpen(false);
      return;
    }
    if (command.id === "create-new-project") {
      navigate("Brief");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "continue-brief" || command.id === "scaffold-bootstrap") {
      navigate("Brief");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "open-observatory") {
      navigate("Observatory");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "send-note-next-run") {
      navigate("Inbox");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "open-diagnostics") {
      setAdvancedInitialTab("Diagnostics");
      setActiveView("Advanced");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "reveal-project") {
      setPaletteBusyId(command.id);
      try {
        await revealProject(target);
        setPaletteMessage("Project revealed.");
        setPaletteOpen(false);
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
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
        setPaletteOpen(false);
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
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
          return;
        }
        const payload = await runBackendCommand({
          command: "context.import",
          target,
          filesJson: JSON.stringify(picked.map((file) => file.path)),
          projectName: snapshot?.brief.project_name || snapshot?.target.name || "New Project",
        });
        if (!payload.ok) {
          setPaletteError(payload.message ?? "Context import failed.");
          return;
        }
        setPaletteMessage("Context files imported.");
        await refreshProject();
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "run-once") {
      await runPaletteStreamed(command, "run.once", "Run automation once now?");
      return;
    }
    if (command.id === "start-schedule") {
      await runPaletteStreamed(command, "schedule.start", "Start scheduled automation for this project?");
      return;
    }
    if (command.id === "pause-schedule") {
      await runPaletteStreamed(command, "schedule.pause", "Pause scheduled automation for this project?");
      return;
    }
    if (command.id === "remove-schedule") {
      setPaletteBusyId(command.id);
      setPaletteError("");
      setPaletteMessage("Remove schedule started.");
      try {
        const payload = await runBackendCommand<Record<string, unknown>>({
          command: "schedule.remove",
          target,
        });
        if (!payload.ok) {
          setPaletteError(payload.message ?? "Remove schedule failed.");
          return;
        }
        const removedCount = typeof payload.data?.removed_count === "number" ? payload.data.removed_count : 0;
        setPaletteMessage(
          removedCount === 1
            ? "Removed 1 LaunchAgent plist."
            : removedCount > 1
              ? `Removed ${removedCount} LaunchAgent plists.`
              : "No LaunchAgent plist was found for this target.",
        );
        await refreshProject();
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "run-safety-check") {
      await runPaletteStreamed(command, "safety.run_check");
      return;
    }
    if (command.id === "open-observatory-browser") {
      setPaletteBusyId(command.id);
      try {
        const payload = await runBackendCommand<{ html_path: string }>({
          command: "observatory.load_html",
          target,
          reviewDir: targetSubdir(target, "native-observatory"),
        });
        if (!payload.ok || !payload.data) {
          setPaletteError(payload.message ?? "Could not generate Observatory HTML.");
          return;
        }
        await openObservatoryFile(payload.data.html_path);
        setPaletteMessage("Observatory opened in browser.");
        setPaletteOpen(false);
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setPaletteBusyId("");
      }
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
          setPaletteError(payload.message ?? "Could not export the review bundle.");
          return;
        }
        setPaletteMessage("Review bundle exported.");
        await refreshProject();
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setPaletteBusyId("");
      }
      return;
    }
    if (command.id === "open-raw-automation-tasks") {
      setPaletteBusyId(command.id);
      try {
        await openManagedFile(target, "monitor.automation_tasks");
        setPaletteOpen(false);
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
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
          setPaletteError(payload.message ?? "Could not export the debug bundle.");
          return;
        }
        setPaletteMessage("Debug bundle exported.");
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setPaletteBusyId("");
      }
    }
  }

  useEffect(() => {
    refreshRecents();
  }, []);

  useEffect(() => {
    setCachedRoutes(createCachedRouteVisits());
    setCachedRoutesTargetPath(snapshot?.target.path ?? "");
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
    function onPointerDown(event: globalThis.PointerEvent) {
      const menu = projectMenuRef.current;
      if (menu && !menu.contains(event.target as Node)) {
        setProjectMenuOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setProjectMenuOpen(false);
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
        setPaletteOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

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
        <nav>
          {views.map((view) => {
            const Icon = view.icon;
            return (
              <button
                className={activeView === view.key ? "active" : ""}
                key={view.key}
                onClick={() => navigate(view.key)}
              >
                <Icon size={18} />
                <span>{view.key}</span>
                {sidebarBadges[view.key] && (
                  <em className={`sidebar-badge ${sidebarBadges[view.key]?.tone}`}>
                    {sidebarBadges[view.key]?.label}
                  </em>
                )}
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="workspace">
        <section className="topbar">
          <div className="project-menu-wrap" ref={projectMenuRef}>
            <button
              aria-expanded={projectMenuOpen}
              className={`project-chip ${projectMenuOpen ? "open" : ""}`}
              title={selectedTarget?.path ?? "Choose a project folder"}
              onClick={() => setProjectMenuOpen((open) => !open)}
            >
              <img src={diffmoggerIcon} alt="" aria-hidden="true" />
              <span>{projectChip}</span>
              <ChevronDown size={14} />
            </button>
            {projectMenuOpen && (
              <div className="project-menu" role="menu" data-no-drag>
                <div className="project-menu-group">
                  <button onClick={chooseProject}>
                    <FolderOpen size={15} />
                    Switch Project...
                  </button>
                  <button onClick={() => navigate("Brief")}>
                    <FileText size={15} />
                    Create New Project
                  </button>
                </div>
                {recents.length > 0 && (
                  <div className="project-menu-group">
                    <strong>Recent</strong>
                    {recents.slice(0, 5).map((recent) => (
                      <button key={recent.path} onClick={() => openRecent(recent)} title={recent.path}>
                        <span>{recent.name}</span>
                        <small>{formatTimestamp(recent.lastOpenedAt)}</small>
                      </button>
                    ))}
                  </div>
                )}
                <div className="project-menu-group">
                  <button disabled={!selectedTarget} onClick={revealSelectedProject}>
                    <FolderOpen size={15} />
                    Reveal in Finder
                  </button>
                  <button disabled={!selectedTarget} onClick={openSelectedProjectInEditor}>
                    <ExternalLink size={15} />
                    Open in Editor
                  </button>
                  <button className="danger" disabled={!selectedTarget} onClick={closeProject}>
                    <LogOut size={15} />
                    Close Project
                  </button>
                </div>
              </div>
            )}
          </div>
          <div className={`status-pill ${tone}`}>
            {tone === "critical" || tone === "warn" ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}
            {status}
          </div>
          <div className="topbar-meta">{refreshing ? "Refreshing..." : formatLastUpdated(lastUpdatedAt)}</div>
          <button
            className={`icon-button ${refreshing ? "refreshing" : ""}`}
            disabled={!selectedTarget || loadState === "loading" || refreshing}
            title="Refresh"
            onClick={refreshProject}
          >
            <RefreshCw className={refreshing ? "spin" : ""} size={17} />
          </button>
          <button
            className="command-button"
            title="Command Palette (Cmd/Ctrl+K)"
            onClick={() => setPaletteOpen((open) => !open)}
          >
            <Command size={17} />
            Command
          </button>
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
            <section className="error-state">
              <h1>Backend Error</h1>
              <p>{error}</p>
              <div className="error-actions">
                <button className="primary-action" onClick={chooseProject}>
                  <FolderOpen size={18} />
                  Choose Project Folder
                </button>
                {selectedTarget && (
                  <button className="secondary-action" onClick={refreshProject}>
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
          onClose={() => setPaletteOpen(false)}
          onExecute={(command) => void executePaletteCommand(command)}
        />
      )}

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
