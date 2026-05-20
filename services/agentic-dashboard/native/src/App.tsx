import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  AlertTriangle,
  ChevronDown,
  Command,
  FileText,
  FolderOpen,
  GitBranch,
  PlayCircle,
  RefreshCw,
  TerminalSquare,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  BackendEnvelope,
  EnvironmentDiagnosticsSnapshot,
  ProjectSnapshot,
  RecentTarget,
} from "./api/backend";
import {
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
import { AutomationPage } from "./AutomationPage";
import { BriefWizard } from "./BriefWizard";
import { CommandPalette } from "./CommandPalette";
import type { PaletteCommand, PaletteCommandId } from "./commandPaletteModel";
import { buildCommandPaletteModel } from "./commandPaletteModel";
import diffmoggerLogo from "./assets/diffmogger-logo-cropped.png";
import "./App.css";

export type ViewKey = "Setup" | "Automation";

type LoadState = "idle" | "loading" | "loaded" | "error";
type DirtyRouteState = Partial<Record<ViewKey, string>>;
type BusyRouteState = Partial<Record<ViewKey, boolean>>;

const views: Array<{ key: ViewKey; label: string; icon: typeof FileText }> = [
  { key: "Setup", label: "Setup", icon: FileText },
  { key: "Automation", label: "Automation", icon: PlayCircle },
];

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

export function viewRequiresTarget(view: ViewKey): view is "Automation" {
  return view === "Automation";
}

function WindowControls() {
  async function windowAction(action: "close" | "minimize" | "fullscreen") {
    try {
      const nativeWindow = getCurrentWindow();
      if (action === "close") await nativeWindow.close();
      if (action === "minimize") await nativeWindow.minimize();
      if (action === "fullscreen") {
        const isFullscreen = await nativeWindow.isFullscreen();
        try {
          await nativeWindow.setFullscreen(!isFullscreen);
        } catch {
          await nativeWindow.setSimpleFullscreen(!isFullscreen);
        }
      }
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
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function isActiveSnapshot(snapshot: ProjectSnapshot | null): boolean {
  if (!snapshot) return false;
  const automation = record(snapshot.controls.automation);
  const automationState = text(automation.state, "").toLowerCase();
  const status = text(snapshot.setup.status || record(snapshot.setup.task).status, "").toUpperCase();
  const human = record(snapshot.human_input);
  const pendingHuman =
    number(human.pending_requests) +
    number(human.unhandled_records) +
    number(human.unhandled_inbox);
  const dag = record(snapshot.dag.execution_dag);
  const dagSummary = record(snapshot.dag.summary);
  const activeDagNodes = list(dag.nodes).map(record).some((node) => {
    const nodeStatus = text(node.status, "").toLowerCase();
    return ["ready", "running", "active", "failed", "blocked"].includes(nodeStatus);
  });
  const activeDagSummary = number(dagSummary.ready) + number(dagSummary.running) + number(dagSummary.blocked) + number(dagSummary.failed) > 0;
  return (
    ACTIVE_AUTOMATION_STATES.has(automationState) ||
    snapshot.controls.is_running === true ||
    status.includes("RUNNING") ||
    status === "ACTIVE_WITH_PENDING_USER_INPUT" ||
    pendingHuman > 0 ||
    activeDagNodes ||
    activeDagSummary
  );
}

export function autoRefreshIntervalMs(snapshot: ProjectSnapshot | null): number {
  return isActiveSnapshot(snapshot) ? AUTO_REFRESH_ACTIVE_INTERVAL_MS : AUTO_REFRESH_IDLE_INTERVAL_MS;
}

export function autoRefreshOverdueMs(snapshot: ProjectSnapshot | null): number {
  return isActiveSnapshot(snapshot) ? AUTO_REFRESH_MIN_OVERDUE_MS : AUTO_REFRESH_IDLE_INTERVAL_MS * 2;
}

export function autoRefreshBlocker(state: {
  hasSelectedTarget: boolean;
  loadState: LoadState;
  refreshInFlight: boolean;
  hasDirtyRoutes: boolean;
  hasBusyCommands: boolean;
}): AutoRefreshBlocker | null {
  if (!state.hasSelectedTarget) return "no_target";
  if (state.loadState !== "loaded") return "not_loaded";
  if (state.refreshInFlight) return "refreshing";
  if (state.hasDirtyRoutes) return "dirty_route";
  if (state.hasBusyCommands) return "busy_command";
  return null;
}

export function canAutoRefreshProject(state: Parameters<typeof autoRefreshBlocker>[0]): boolean {
  return autoRefreshBlocker(state) === null;
}

function ageLabel(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1_000));
  if (seconds < 90) return `${Math.max(1, seconds)}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}

export function buildAutoRefreshChipState(input: {
  lastUpdatedAt: number | null;
  now: number;
  refreshing: boolean;
  pauseReason: AutoRefreshBlocker | null;
  pauseDetail?: string;
  failureMessage?: string;
  overdueMs: number;
}): AutoRefreshChipState {
  if (input.failureMessage) {
    return {
      label: "Refresh failed",
      title: input.failureMessage,
      tone: "critical",
      overdue: false,
      paused: false,
    };
  }
  if (input.pauseReason) {
    const detail = input.pauseDetail || input.pauseReason.replace(/_/g, " ");
    return {
      label: "Auto-refresh paused",
      title: `Auto-refresh paused: ${detail}`,
      tone: input.pauseReason === "dirty_route" || input.pauseReason === "busy_command" ? "warn" : "quiet",
      overdue: false,
      paused: true,
    };
  }
  if (input.refreshing) {
    return {
      label: "Refreshing",
      title: "Refreshing selected project state.",
      tone: "info",
      overdue: false,
      paused: false,
    };
  }
  if (!input.lastUpdatedAt) {
    return {
      label: "Not refreshed",
      title: "No project snapshot has loaded yet.",
      tone: "quiet",
      overdue: false,
      paused: false,
    };
  }
  const age = input.now - input.lastUpdatedAt;
  const overdue = age > input.overdueMs;
  return {
    label: overdue ? "Refresh delayed" : `Updated ${ageLabel(age)}`,
    title: overdue ? "The selected project snapshot is older than the refresh cadence." : "Selected project state is current.",
    tone: overdue ? "warn" : "quiet",
    overdue,
    paused: false,
  };
}

export function shouldRefreshOnFocus(lastUpdatedAt: number | null, now: number): boolean {
  return lastUpdatedAt !== null && now - lastUpdatedAt >= AUTO_REFRESH_FOCUS_STALE_MS;
}

export function hasDirtyRouteState(state: DirtyRouteState): boolean {
  return Object.values(state).some(Boolean);
}

export function hasBusyRouteState(state: BusyRouteState): boolean {
  return Object.values(state).some(Boolean);
}

function targetName(snapshot: ProjectSnapshot | null, selected: RecentTarget | null): string {
  return snapshot?.target.name || selected?.name || "No project";
}

function targetPath(snapshot: ProjectSnapshot | null, selected: RecentTarget | null): string {
  return snapshot?.target.path || selected?.path || "";
}

function installStatus(snapshot: ProjectSnapshot | null): { label: string; tone: "good" | "warn" | "quiet"; detail: string } {
  if (!snapshot) return { label: "Not selected", tone: "quiet", detail: "Choose a project folder." };
  if (snapshot.target.automation_task_exists && snapshot.target.project_intake_exists) {
    return { label: "Configured", tone: "good", detail: "Diffmogger sidecar files are present." };
  }
  if (snapshot.target.is_diffmogger_project) {
    return { label: "Partial", tone: "warn", detail: "Finish setup to generate required sidecar files." };
  }
  return { label: "Setup needed", tone: "warn", detail: "Scaffold Diffmogger into the selected project." };
}

function humanInputCount(snapshot: ProjectSnapshot | null): number {
  if (!snapshot) return 0;
  const human = record(snapshot.human_input);
  return (
    number(human.pending_requests) +
    number(human.unhandled_records) +
    number(human.unhandled_inbox)
  );
}

function schedulerLabel(snapshot: ProjectSnapshot | null): string {
  if (!snapshot) return "Choose project";
  const selected = record(snapshot.scheduler.selected_action);
  const nextAction = (list(snapshot.scheduler.next_actions).map(record)[0] ?? {}) as Record<string, unknown>;
  const decision = (list(snapshot.scheduler.decision_queue).map(record)[0] ?? {}) as Record<string, unknown>;
  return text(
    selected.action_kind || selected.action_type || nextAction.kind || decision.action_kind || decision.reason,
    snapshot.target.automation_task_exists ? "Ready to choose next work" : "Finish setup",
  );
}

function refreshPauseDetail(blocker: AutoRefreshBlocker | null, dirty: DirtyRouteState, busy: BusyRouteState): string | undefined {
  if (blocker === "dirty_route") return Object.values(dirty).find(Boolean);
  if (blocker === "busy_command") {
    const route = Object.entries(busy).find(([, value]) => value)?.[0];
    return route ? `${route} command is still running.` : undefined;
  }
  return undefined;
}

function ProjectMenu(props: {
  open: boolean;
  snapshot: ProjectSnapshot | null;
  selectedTarget: RecentTarget | null;
  recents: RecentTarget[];
  onChoose: () => void;
  onOpenRecent: (target: RecentTarget) => void;
  onCloseProject: () => void;
  onReveal: () => void;
  onOpenEditor: () => void;
  onNewProject: () => void;
}) {
  if (!props.open) return null;
  const currentPath = targetPath(props.snapshot, props.selectedTarget);
  return (
    <div className="project-menu" role="menu" aria-label="Project menu">
      <button role="menuitem" onClick={props.onChoose}>Switch project...</button>
      <button role="menuitem" onClick={props.onNewProject}>New project</button>
      <button role="menuitem" disabled={!currentPath} onClick={props.onReveal}>Reveal project</button>
      <button role="menuitem" disabled={!currentPath} onClick={props.onOpenEditor}>Open in editor</button>
      {props.recents.length > 0 && (
        <div className="project-menu-recents" aria-label="Recent projects">
          <span>Recent</span>
          {props.recents.slice(0, 5).map((target) => (
            <button role="menuitem" key={target.path} onClick={() => props.onOpenRecent(target)}>
              {target.name}
              <small>{target.path}</small>
            </button>
          ))}
        </div>
      )}
      <button role="menuitem" disabled={!currentPath} onClick={props.onCloseProject}>Close Project</button>
    </div>
  );
}

function SetupStatusCard(props: {
  snapshot: ProjectSnapshot | null;
  selectedTarget: RecentTarget | null;
  diagnostics: EnvironmentDiagnosticsSnapshot | null;
  diagnosticsLoading: boolean;
  onRunChecks: () => void;
}) {
  const status = installStatus(props.snapshot);
  const human = humanInputCount(props.snapshot);
  const path = targetPath(props.snapshot, props.selectedTarget);
  return (
    <aside className="setup-status-strip" aria-label="Project setup status">
      <div className="setup-status-card">
        <span>Project</span>
        <strong>{targetName(props.snapshot, props.selectedTarget)}</strong>
        <small title={path}>{path || "No target folder selected"}</small>
      </div>
      <div className={`setup-status-card ${status.tone}`}>
        <span>Diffmogger</span>
        <strong>{status.label}</strong>
        <small>{status.detail}</small>
      </div>
      <div className={`setup-status-card ${human ? "warn" : "good"}`}>
        <span>Human Input</span>
        <strong>{human ? `${human} pending` : "Clear"}</strong>
        <small>Recorded as input; scheduler work continues independently.</small>
      </div>
      <div className={`setup-status-card ${props.diagnostics?.status === "pass" ? "good" : props.diagnostics?.status ? "warn" : "quiet"}`}>
        <span>Backend checks</span>
        <strong>{props.diagnosticsLoading ? "Checking" : props.diagnostics?.status || "Not run"}</strong>
        <button className="secondary-action compact-action" disabled={!path || props.diagnosticsLoading} onClick={props.onRunChecks}>
          <TerminalSquare size={15} />
          Run setup checks
        </button>
      </div>
    </aside>
  );
}

function NoTargetAutomation(props: { onChoose: () => void; onSetup: () => void }) {
  return (
    <section className="automation-page no-target" aria-label="Automation">
      <div className="automation-empty">
        <FolderOpen size={22} />
        <h1>Choose Project</h1>
        <p>Choose a project before viewing scheduler state, queued work, input records, or run commands.</p>
        <div className="automation-command-row">
          <button className="primary-action" onClick={props.onChoose}>
            <FolderOpen size={17} />
            Choose project
          </button>
          <button className="secondary-action" onClick={props.onSetup}>
            <FileText size={17} />
            Open setup
          </button>
        </div>
      </div>
    </section>
  );
}

function App(props: { initialView?: ViewKey; initialProjectMenuOpen?: boolean } = {}) {
  const [activeView, setActiveView] = useState<ViewKey>(props.initialView ?? "Setup");
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
  const [nowTick, setNowTick] = useState(Date.now());
  const [dirtyRoutes, setDirtyRoutes] = useState<DirtyRouteState>({});
  const [busyRoutes, setBusyRoutes] = useState<BusyRouteState>({});
  const refreshInFlightRef = useRef(false);
  const selectedTargetPathRef = useRef<string | null>(null);

  const selectedPath = targetPath(snapshot, selectedTarget);
  const hasDirtyRoutes = hasDirtyRouteState(dirtyRoutes);
  const hasBusyCommands = hasBusyRouteState(busyRoutes) || Boolean(paletteBusyId);
  const autoBlocker = autoRefreshBlocker({
    hasSelectedTarget: Boolean(selectedPath),
    loadState,
    refreshInFlight: refreshInFlightRef.current,
    hasDirtyRoutes,
    hasBusyCommands,
  });
  const refreshChip = buildAutoRefreshChipState({
    lastUpdatedAt,
    now: nowTick,
    refreshing,
    pauseReason: autoBlocker,
    pauseDetail: refreshPauseDetail(autoBlocker, dirtyRoutes, busyRoutes),
    failureMessage: refreshFailure?.message,
    overdueMs: autoRefreshOverdueMs(snapshot),
  });
  const commands = useMemo(
    () => buildCommandPaletteModel({ snapshot, loading: loadState === "loading" || refreshing, busy: hasBusyCommands }),
    [snapshot, loadState, refreshing, hasBusyCommands],
  );
  const status = installStatus(snapshot);
  const human = humanInputCount(snapshot);

  function announce(message: string) {
    setAnnouncement(message);
  }

  async function refreshRecents() {
    try {
      setRecents(await listRecentProjects());
    } catch {
      setRecents([]);
    }
  }

  async function loadTarget(target: RecentTarget, options: { navigateTo?: ViewKey; quiet?: boolean } = {}) {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;
    setRefreshing(true);
    setLoadState("loading");
    setError(null);
    if (!options.quiet) announce(`Loading ${target.name}.`);
    try {
      const envelope: BackendEnvelope<ProjectSnapshot> = await loadProjectSnapshot(target.path);
      if (!envelope.ok || !envelope.data) {
        const message = envelope.message ?? "Could not load project snapshot.";
        setError(message);
        setRefreshFailure({ message, at: Date.now() });
        setLoadState("error");
        return;
      }
      setSelectedTarget(target);
      setSnapshot(envelope.data);
      setLastUpdatedAt(Date.now());
      setRefreshFailure(null);
      setLoadState("loaded");
      if (options.navigateTo) setActiveView(options.navigateTo);
      await refreshRecents();
      if (!options.quiet) announce(`${target.name} loaded.`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(message);
      setRefreshFailure({ message, at: Date.now() });
      setLoadState("error");
    } finally {
      refreshInFlightRef.current = false;
      setRefreshing(false);
    }
  }

  async function refreshProject() {
    const path = selectedPath;
    if (!path) return;
    await loadTarget({ path, name: targetName(snapshot, selectedTarget), lastOpenedAt: Date.now() }, { quiet: true });
  }

  async function chooseProject() {
    setProjectMenuOpen(false);
    try {
      const result = await selectProjectFolder();
      if (!result) return;
      if (result.snapshot.ok && result.snapshot.data) {
        setSelectedTarget(result.target);
        setSnapshot(result.snapshot.data);
        setLastUpdatedAt(Date.now());
        setRefreshFailure(null);
        setLoadState("loaded");
        setActiveView("Setup");
        await refreshRecents();
        announce(`${result.target.name} loaded.`);
        return;
      }
      await loadTarget(result.target, { navigateTo: "Setup" });
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      setError(message);
      announce(message);
    }
  }

  function navigate(view: ViewKey) {
    setActiveView(view);
    setProjectMenuOpen(false);
  }

  function closeProject() {
    setProjectMenuOpen(false);
    setSnapshot(null);
    setSelectedTarget(null);
    setError(null);
    setLastUpdatedAt(null);
    setRefreshFailure(null);
    setRefreshing(false);
    setLoadState("idle");
    setDirtyRoutes({});
    setBusyRoutes({});
    setActiveView("Setup");
    refreshInFlightRef.current = false;
    announce("Project closed.");
  }

  async function revealSelectedProject() {
    if (!selectedPath) return;
    setProjectMenuOpen(false);
    try {
      await revealProject(selectedPath);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function openSelectedProjectInEditor() {
    if (!selectedPath) return;
    setProjectMenuOpen(false);
    try {
      await openProjectInEditor(selectedPath);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function runSetupChecks() {
    if (!selectedPath) return;
    setEnvironmentDiagnosticsLoading(true);
    setError(null);
    try {
      const payload = await runBackendCommand<EnvironmentDiagnosticsSnapshot>({
        command: "diagnostics.environment",
        target: selectedPath,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Environment diagnostics failed.");
        return;
      }
      setEnvironmentDiagnostics(payload.data);
      announce("Backend checks completed.");
      await refreshProject();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setEnvironmentDiagnosticsLoading(false);
    }
  }

  async function runPaletteStreamed(command: PaletteCommand, backendCommand: string) {
    if (!selectedPath) return;
    setPaletteBusyId(command.id);
    setPaletteError("");
    setPaletteMessage(`${command.title} started.`);
    announce(`${command.title} started.`);
    try {
      const payload = await runBackendCommandStreamed({
        runId: `palette-${command.id}-${Date.now()}`,
        command: backendCommand,
        target: selectedPath,
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

    if (command.id === "open-project") {
      setPaletteOpen(false);
      await chooseProject();
      return;
    }
    if (command.id === "create-new-project" || command.id === "open-setup" || command.id === "scaffold-project") {
      navigate("Setup");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "open-automation") {
      navigate("Automation");
      setPaletteOpen(false);
      return;
    }
    if (command.id === "close-project") {
      closeProject();
      setPaletteOpen(false);
      return;
    }
    if (command.id === "reveal-project") {
      setPaletteBusyId(command.id);
      try {
        await revealProject(selectedPath);
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
        await openProjectInEditor(selectedPath);
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
          target: selectedPath,
          filesJson: JSON.stringify(picked.map((file) => file.path)),
          projectName: snapshot?.setup.project_name || snapshot?.target.name || "New Project",
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
    if (command.id === "open-raw-automation-tasks") {
      setPaletteBusyId(command.id);
      try {
        await openManagedFile(selectedPath, "monitor.automation_tasks");
        setPaletteMessage("Task projection opened.");
        setPaletteOpen(false);
      } catch (caught) {
        setPaletteError(caught instanceof Error ? caught.message : String(caught));
      } finally {
        setPaletteBusyId("");
      }
    }
  }

  useEffect(() => {
    void refreshRecents();
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    selectedTargetPathRef.current = selectedPath || null;
  }, [selectedPath]);

  useEffect(() => {
    const id = window.setInterval(() => {
      const path = selectedTargetPathRef.current;
      if (!path) return;
      const blocker = autoRefreshBlocker({
        hasSelectedTarget: true,
        loadState,
        refreshInFlight: refreshInFlightRef.current,
        hasDirtyRoutes: hasDirtyRouteState(dirtyRoutes),
        hasBusyCommands: hasBusyRouteState(busyRoutes) || Boolean(paletteBusyId),
      });
      if (!blocker) void refreshProject();
    }, autoRefreshIntervalMs(snapshot));
    return () => window.clearInterval(id);
  }, [snapshot, loadState, dirtyRoutes, busyRoutes, paletteBusyId]);

  useEffect(() => {
    function onFocus() {
      if (shouldRefreshOnFocus(lastUpdatedAt, Date.now()) && canAutoRefreshProject({
        hasSelectedTarget: Boolean(selectedTargetPathRef.current),
        loadState,
        refreshInFlight: refreshInFlightRef.current,
        hasDirtyRoutes: hasDirtyRouteState(dirtyRoutes),
        hasBusyCommands: hasBusyRouteState(busyRoutes) || Boolean(paletteBusyId),
      })) {
        void refreshProject();
      }
    }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [lastUpdatedAt, loadState, dirtyRoutes, busyRoutes, paletteBusyId]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="app-shell simplified-dashboard">
      <div className="titlebar">
        <WindowControls />
        <div className="titlebar-drag-region">
          <div className="brand" aria-label="Diffmogger">
            <img className="brand-logo" alt="Diffmogger" src={diffmoggerLogo} />
          </div>
          <div className="titlebar-spacer" />
        </div>
      </div>

      <aside className="sidebar" aria-label="Primary navigation">
        <nav className="primary-icon-rail" data-testid="primary-icon-rail" aria-label="Dashboard pages">
          {views.map((view) => {
            const Icon = view.icon;
            const active = activeView === view.key;
            const badge =
              view.key === "Automation" && human
                ? String(human)
                : view.key === "Setup" && status.tone === "warn"
                  ? "!"
                  : "";
            return (
              <button
                aria-label={view.label}
                aria-current={active ? "page" : undefined}
                className={active ? "active" : ""}
                data-sidebar-view={view.key}
                data-testid={`sidebar-nav-${view.key}`}
                data-tooltip={view.label}
                key={view.key}
                onClick={() => navigate(view.key)}
                title={view.label}
              >
                <Icon size={24} />
                <span className="sidebar-label">{view.label}</span>
                {badge && <em className={`sidebar-badge ${badge.length > 1 ? "has-label" : ""}`}>{badge}</em>}
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="dashboard-main workspace">
        <header className="topbar">
          <div className="project-chip-wrap project-menu-wrap">
            <button
              className={`project-chip ${projectMenuOpen ? "open" : ""}`}
              aria-expanded={projectMenuOpen}
              aria-haspopup="menu"
              onClick={() => setProjectMenuOpen((current) => !current)}
            >
              <FolderOpen size={16} />
              <span>{targetName(snapshot, selectedTarget)}</span>
              <ChevronDown size={15} />
            </button>
            <ProjectMenu
              open={projectMenuOpen}
              snapshot={snapshot}
              selectedTarget={selectedTarget}
              recents={recents}
              onChoose={() => void chooseProject()}
              onOpenRecent={(target) => void loadTarget(target, { navigateTo: "Setup" })}
              onCloseProject={closeProject}
              onReveal={() => void revealSelectedProject()}
              onOpenEditor={() => void openSelectedProjectInEditor()}
              onNewProject={() => navigate("Setup")}
            />
          </div>
          <div className="topbar-facts target-context-meta">
            <span className="context-chip quiet" title={targetPath(snapshot, selectedTarget)}>
              <GitBranch size={14} />
              {text(snapshot?.setup.git?.branch, "No branch")}
            </span>
            <span className={`status-pill ${status.tone}`}>{status.label}</span>
            <span className={`context-chip updated-chip ${refreshChip.tone}`} title={refreshChip.title}>{refreshChip.label}</span>
          </div>
          <div className="topbar-actions">
            <button className={`icon-button ${refreshing ? "refreshing" : ""}`} aria-label="Refresh target" title="Refresh target" disabled={!selectedPath || refreshing} onClick={() => void refreshProject()}>
              <RefreshCw size={16} />
            </button>
            <button className="command-button" aria-label="Open command palette" title="Open command palette" onClick={() => setPaletteOpen(true)}>
              <Command size={16} />
              <span>Command</span>
            </button>
            <button className="icon-button shell-close-button" aria-label="Close" title="Close" onClick={() => void getCurrentWindow().close()}>
              <X size={16} />
            </button>
          </div>
        </header>

        <section className="dashboard-summary-strip" aria-label="Dashboard summary">
          <div>
            <span>Project</span>
            <strong>{targetName(snapshot, selectedTarget)}</strong>
          </div>
          <div>
            <span>Configured</span>
            <strong>{status.label}</strong>
          </div>
          <div>
            <span>Scheduler next</span>
            <strong>{schedulerLabel(snapshot)}</strong>
          </div>
          <div>
            <span>Human input</span>
            <strong>{human ? `${human} pending` : "Clear"}</strong>
          </div>
        </section>

        {error && (
          <div className="shell-error" role="alert">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}

        <div className="dashboard-stage" data-active-view={activeView}>
          {activeView === "Setup" ? (
            <>
              <SetupStatusCard
                snapshot={snapshot}
                selectedTarget={selectedTarget}
                diagnostics={environmentDiagnostics}
                diagnosticsLoading={environmentDiagnosticsLoading}
                onRunChecks={() => void runSetupChecks()}
              />
              <BriefWizard
                snapshot={snapshot}
                recents={recents}
                loading={loadState === "loading" || refreshing}
                onChoose={() => void chooseProject()}
                onOpenRecent={(target) => void loadTarget(target, { navigateTo: "Setup" })}
                onNavigate={navigate}
                onRefresh={() => void refreshProject()}
                onDirtyChange={(message) => setDirtyRoutes((current) => ({ ...current, Setup: message || undefined }))}
                onBusyChange={(busy) => setBusyRoutes((current) => ({ ...current, Setup: busy }))}
              />
            </>
          ) : snapshot ? (
            <AutomationPage
              snapshot={snapshot}
              loading={loadState === "loading" || refreshing}
              onChoose={() => void chooseProject()}
              onNavigate={navigate}
              onRefresh={() => void refreshProject()}
              onBusyChange={(busy) => setBusyRoutes((current) => ({ ...current, Automation: busy }))}
            />
          ) : (
            <NoTargetAutomation onChoose={() => void chooseProject()} onSetup={() => navigate("Setup")} />
          )}
        </div>
      </main>

      <div className="shell-live-region" aria-live="polite" data-testid="shell-live-region">
        {announcement || paletteMessage || paletteError}
      </div>

      {paletteOpen && (
        <CommandPalette
          commands={commands}
          busyCommandId={paletteBusyId}
          message={paletteMessage}
          error={paletteError}
          onClose={() => setPaletteOpen(false)}
          onExecute={(command) => void executePaletteCommand(command)}
        />
      )}
    </div>
  );
}

export default App;
