import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileArchive,
  FolderOpen,
  RefreshCw,
  Save,
  TerminalSquare,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  AdvancedDebugBundleResult,
  AdvancedFilesSnapshot,
  AdvancedLoadedFile,
  AdvancedSettings,
  AdvancedValidationResult,
  BackendEnvelope,
  DiagnosticsSnapshot,
  FixSuggestion,
  ProjectSnapshot,
  RegisteredFile,
  RuntimeEnvironmentSnapshot,
  StateSnapshotResult,
} from "./api/backend";
import {
  getAdvancedSettings,
  openManagedFile,
  revealManagedFile,
  runBackendCommand,
  selectSettingsDirectory,
  updateAdvancedSettings,
} from "./api/backend";
import { buildAdvancedEditorModel } from "./advancedModel";
import { scheduleAfterPaint } from "./performance";

export type AdvancedTab = "Files" | "State" | "Diagnostics" | "Settings" | "Debug";

const tabs: AdvancedTab[] = ["Files", "State", "Diagnostics", "Settings", "Debug"];
const tabLabels: Record<AdvancedTab, string> = {
  Files: "Files",
  State: "Canonical state",
  Diagnostics: "Diagnostics",
  Settings: "Settings",
  Debug: "Debug bundle",
};
const fileCategories = [
  "Core state",
  "Inbox",
  "Review",
  "Context",
  "Roles / conveyor",
];

const defaultSettings: AdvancedSettings = {
  reviewExportDir: "",
  preferredEditorCommand: "",
  humanBridgeMode: "file_only",
  appearance: "system",
  density: "comfortable",
};

function text(value: unknown, fallback = "Not recorded"): string {
  if (value === null || value === undefined) return fallback;
  const result = String(value).trim();
  return result || fallback;
}

function statusTone(status: unknown): string {
  const value = text(status, "").toLowerCase();
  if (["pass", "ok", "ready", "running"].includes(value)) return "good";
  if (["fail", "blocked", "missing", "critical"].some((marker) => value.includes(marker))) return "critical";
  if (["warn", "not_run", "unknown", "unavailable"].some((marker) => value.includes(marker))) return "warn";
  return "quiet";
}

function humanSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "Missing";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 102.4) / 10} KB`;
  return `${Math.round(bytes / 1024 / 102.4) / 10} MB`;
}

function rowValue(row: Record<string, unknown>, key: string, fallback = "Not recorded"): string {
  return text(row[key], fallback);
}

function DetailRow(props: { label: string; value: unknown }) {
  return (
    <div className="data-row">
      <span>{props.label}</span>
      <strong>{text(props.value)}</strong>
    </div>
  );
}

function CheckRow(props: { row: Record<string, unknown>; labelKey?: string }) {
  const ok = props.row.ok === true || props.row.status === "pass";
  const tone = ok ? "good" : statusTone(props.row.status ?? props.row.ok);
  const category = text(
    props.row.category,
    props.row.required === true ? "required" : props.row.required === false ? "advisory" : "",
  );
  return (
    <div className={`advanced-check-row ${tone}`}>
      <span>
        {rowValue(props.row, props.labelKey ?? "name", "Check")}
        {category ? <em>{category}</em> : null}
      </span>
      <strong>{ok ? "OK" : text(props.row.status ?? props.row.ok, "Review")}</strong>
      <p>{rowValue(props.row, "detail", rowValue(props.row, "reason", ""))}</p>
    </div>
  );
}

function RuntimeToolRow(props: { row: Record<string, unknown> }) {
  return (
    <div className={`advanced-check-row ${props.row.ok === true ? "good" : props.row.required === true ? "critical" : "warn"}`}>
      <span>{rowValue(props.row, "name", "Tool")}</span>
      <strong>{props.row.ok === true ? "OK" : props.row.required === true ? "Required" : "Optional"}</strong>
      <p>{rowValue(props.row, "detail", "")}</p>
      {props.row.path ? <code>{text(props.row.path)}</code> : null}
    </div>
  );
}

function RuntimeEnvironmentCard(props: {
  environment?: RuntimeEnvironmentSnapshot;
  suggestions?: FixSuggestion[];
  onCopy: (value: string, message: string) => void;
}) {
  const environment = props.environment;
  const tools = environment?.tools ?? [];
  const suggestions = props.suggestions ?? [];
  return (
    <article className="panel span-2">
      <h2>Backend environment</h2>
      <p className="advanced-muted">
        These checks use the backend PATH passed to Python commands.
      </p>
      <div className="advanced-runtime-grid">
        <DetailRow label="Backend Python" value={environment?.backend_python ?? "Not loaded"} />
        <DetailRow label="Python version" value={environment?.backend_python_version ?? "unknown"} />
        <DetailRow label="Kit root" value={environment?.kit_root ?? "unknown"} />
        <DetailRow label=".env loaded" value={environment?.dotenv_loaded ? "Yes" : "No"} />
      </div>
      <div className="advanced-path-row">
        <code>{environment?.effective_path ?? "Run diagnostics to inspect the backend PATH."}</code>
        <button
          className="secondary-action"
          disabled={!environment?.effective_path}
          onClick={() => props.onCopy(environment?.effective_path ?? "", "Runtime PATH copied.")}
        >
          <Clipboard size={15} />
          Copy PATH
        </button>
      </div>
      <div className="advanced-check-list compact">
        {tools.map((row) => (
          <RuntimeToolRow key={row.name} row={row as unknown as Record<string, unknown>} />
        ))}
      </div>
      {suggestions.length > 0 && (
        <div className="advanced-fix-list">
          <h3>Fixes</h3>
          {suggestions.map((item) => (
            <div className="advanced-fix-row" key={item.id}>
              <div>
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
                <code>{item.command}</code>
              </div>
              <button className="secondary-action" onClick={() => props.onCopy(item.command, "Command copied.")}>
                <Clipboard size={15} />
                Copy
              </button>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}

function categoryOf(file: RegisteredFile): string {
  if (file.category === "Human bridge") return "Inbox";
  if (file.category === "Multi-role / conveyor") return "Roles / conveyor";
  return file.category || "Core state";
}

export function syncedSelectedFileKey(files: RegisteredFile[], currentKey: string): string {
  if (currentKey && files.some((file) => file.key === currentKey)) return currentKey;
  return files[0]?.key ?? "";
}

export function AdvancedPage(props: {
  snapshot: ProjectSnapshot;
  loading?: boolean;
  onRefresh?: () => void;
  initialTab?: AdvancedTab;
}) {
  const target = props.snapshot.target.path;
  const snapshotFiles = props.snapshot.files ?? [];
  const snapshotFilesSignature = snapshotFiles
    .map(
      (file) =>
        `${file.key}:${file.label}:${file.rel_path}:${file.path ?? ""}:${file.exists ? 1 : 0}:${file.size_bytes ?? ""}:${file.modified_at ?? ""}`,
    )
    .join("|");
  const [activeTab, setActiveTab] = useState<AdvancedTab>("Files");
  const [files, setFiles] = useState<RegisteredFile[]>(snapshotFiles);
  const [selectedKey, setSelectedKey] = useState(snapshotFiles[0]?.key ?? "");
  const [loadedFile, setLoadedFile] = useState<AdvancedLoadedFile | null>(null);
  const [editorContent, setEditorContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [validation, setValidation] = useState<AdvancedValidationResult | null>(null);
  const [stateSnapshot, setStateSnapshot] = useState<StateSnapshotResult | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsSnapshot | null>(null);
  const [settings, setSettings] = useState<AdvancedSettings>(defaultSettings);
  const [debugOutputDir, setDebugOutputDir] = useState("");
  const [debugBundle, setDebugBundle] = useState<AdvancedDebugBundleResult | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedFile = useMemo(
    () => files.find((file) => file.key === selectedKey) ?? files[0],
    [files, selectedKey],
  );
  const editorModel = useMemo(
    () =>
      buildAdvancedEditorModel({
        selectedFile,
        editorContent,
        savedContent,
        busy,
        loading: props.loading,
      }),
    [busy, editorContent, props.loading, savedContent, selectedFile],
  );
  const dirty = editorModel.dirty;
  const groupedFiles = useMemo(() => {
    const groups = new Map<string, RegisteredFile[]>();
    for (const category of fileCategories) groups.set(category, []);
    for (const file of files) {
      const category = categoryOf(file);
      const group = groups.get(category);
      if (group) {
        group.push(file);
      } else {
        groups.set(category, [file]);
      }
    }
    return groups;
  }, [files]);

  async function loadFiles(nextSelectedKey = selectedKey, options: { loadSelected?: boolean } = {}) {
    setBusy("files");
    setError("");
    try {
      const payload: BackendEnvelope<AdvancedFilesSnapshot> = await runBackendCommand({
        command: "advanced.list_files",
        target,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not list managed files.");
        return;
      }
      setFiles(payload.data.files);
      const nextKey =
        payload.data.files.find((file) => file.key === nextSelectedKey)?.key ??
        payload.data.files[0]?.key ??
        "";
      setSelectedKey(nextKey);
      if (nextKey && options.loadSelected) {
        await loadFile(nextKey);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function loadFile(fileKey: string) {
    setBusy("load-file");
    setError("");
    setNotice("");
    try {
      const payload: BackendEnvelope<AdvancedLoadedFile> = await runBackendCommand({
        command: "advanced.load_file",
        target,
        fileKey,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not load the selected file.");
        return;
      }
      setLoadedFile(payload.data);
      setEditorContent(payload.data.content);
      setSavedContent(payload.data.content);
      setValidation(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function saveFile() {
    if (!selectedFile || !dirty) return;
    setBusy("save-file");
    setError("");
    setNotice("");
    try {
      const payload: BackendEnvelope<{ file: RegisteredFile }> = await runBackendCommand({
        command: "advanced.save_file",
        target,
        fileKey: selectedFile.key,
        body: editorContent,
      });
      if (!payload.ok) {
        setError(payload.message ?? "Could not save the managed file.");
        return;
      }
      setSavedContent(editorContent);
      setNotice("File saved through the backend allowlist.");
      await loadFiles(selectedFile.key, { loadSelected: true });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function validateFile() {
    if (!selectedFile) return;
    setBusy("validate-file");
    setError("");
    setNotice("");
    try {
      const payload: BackendEnvelope<AdvancedValidationResult> = await runBackendCommand({
        command: "advanced.validate_file",
        target,
        fileKey: selectedFile.key,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not validate the managed file.");
        return;
      }
      setValidation(payload.data);
      setNotice(`Validation ${payload.data.status}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function runDiagnostics() {
    setBusy("diagnostics");
    setError("");
    try {
      const payload: BackendEnvelope<DiagnosticsSnapshot> = await runBackendCommand({
        command: "diagnostics.run_checks",
        target,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not run diagnostics.");
        return;
      }
      setDiagnostics(payload.data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function loadCanonicalState() {
    setBusy("state");
    setError("");
    try {
      const payload: BackendEnvelope<StateSnapshotResult> = await runBackendCommand({
        command: "state.snapshot",
        target,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not load canonical state.");
        return;
      }
      setStateSnapshot(payload.data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function loadSettings() {
    try {
      const loaded = await getAdvancedSettings();
      setSettings(loaded);
      setDebugOutputDir(loaded.reviewExportDir || `${target}/.diffmogger/runtime/debug-bundles`);
    } catch {
      setSettings(defaultSettings);
      setDebugOutputDir(`${target}/.diffmogger/runtime/debug-bundles`);
    }
  }

  async function saveSettings() {
    setBusy("settings");
    setError("");
    setNotice("");
    try {
      const saved = await updateAdvancedSettings(settings);
      setSettings(saved);
      setDebugOutputDir(saved.reviewExportDir || `${target}/.diffmogger/runtime/debug-bundles`);
      setNotice("Settings saved to the app-local config.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function chooseSettingsDir() {
    const picked = await selectSettingsDirectory();
    if (picked) {
      setSettings((current) => ({ ...current, reviewExportDir: picked }));
      setDebugOutputDir(picked);
    }
  }

  async function exportDebugBundle() {
    setBusy("debug-bundle");
    setError("");
    setNotice("");
    setDebugBundle(null);
    try {
      const payload: BackendEnvelope<AdvancedDebugBundleResult> = await runBackendCommand({
        command: "advanced.export_debug_bundle",
        target,
        outputDir: debugOutputDir || `${target}/.diffmogger/runtime/debug-bundles`,
      });
      if (!payload.ok || !payload.data) {
        setError(payload.message ?? "Could not export debug files.");
        return;
      }
      setDebugBundle(payload.data);
      setNotice("Debug export written without .env files or secret-like values.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy("");
    }
  }

  async function openFile() {
    if (!selectedFile) return;
    try {
      await openManagedFile(target, selectedFile.key);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function revealFile() {
    if (!selectedFile) return;
    try {
      await revealManagedFile(target, selectedFile.key);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function copyPath(path: string) {
    await copyText(path, "Path copied.");
  }

  async function copyText(value: string, message: string) {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(message);
    } catch {
      setError("Could not copy from this environment.");
    }
  }

  useEffect(() => {
    setFiles(snapshotFiles);
    const initialKey = snapshotFiles[0]?.key ?? "";
    setSelectedKey(initialKey);
    setLoadedFile(null);
    setEditorContent("");
    setSavedContent("");
    setValidation(null);
    setStateSnapshot(null);
    setDiagnostics(null);
    const cancel = scheduleAfterPaint(() => {
      void loadFiles(initialKey);
      void loadSettings();
    });
    return cancel;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  useEffect(() => {
    setFiles(snapshotFiles);
    setSelectedKey((currentKey) => syncedSelectedFileKey(snapshotFiles, currentKey));
    setLoadedFile((current) => {
      if (!current) return current;
      const updatedFile = snapshotFiles.find((file) => file.key === current.file.key);
      return updatedFile ? { ...current, file: updatedFile } : null;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotFilesSignature]);

  useEffect(() => {
    if (activeTab !== "Files" || !selectedKey) return undefined;
    if (loadedFile?.file.key === selectedKey) return undefined;
    return scheduleAfterPaint(() => {
      void loadFile(selectedKey);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selectedKey, target]);

  useEffect(() => {
    if (activeTab !== "State" || stateSnapshot) return undefined;
    return scheduleAfterPaint(() => {
      void loadCanonicalState();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, stateSnapshot, target]);

  useEffect(() => {
    if (activeTab !== "Diagnostics" || diagnostics) return undefined;
    return scheduleAfterPaint(() => {
      void runDiagnostics();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, diagnostics, target]);

  useEffect(() => {
    if (props.initialTab) {
      setActiveTab(props.initialTab);
    }
  }, [props.initialTab]);

  const prereqRows = (diagnostics?.prerequisites.items ?? []) as Array<Record<string, unknown>>;
  const toolRows = (diagnostics?.tools ?? []) as Array<Record<string, unknown>>;
  const validationItems = validation?.items ?? [];
  const debugDir = debugOutputDir || `${target}/.diffmogger/runtime/debug-bundles`;
  const selectedPath = text(loadedFile?.file.path ?? selectedFile?.path ?? selectedFile?.rel_path, "");
  const editableFileCount = files.filter((file) => file.editable).length;
  const missingFileCount = files.filter((file) => !file.exists).length;
  const diagnosticsStatus = text(
    diagnostics?.required_files.status ?? diagnostics?.integration_safety.status ?? diagnostics?.prerequisites.status,
    "not run",
  );
  const canonicalState = stateSnapshot?.state ?? (props.snapshot.run.state as StateSnapshotResult["state"] | undefined);
  const stateStatus = text(canonicalState?.status, "not loaded");
  const stateCounts = canonicalState?.counts ?? {};
  const recentStateEvents = canonicalState?.recent_events ?? [];
  const nextActions = canonicalState?.next_actions ?? [];

  return (
    <section className="advanced-page">
      <div className="advanced-header">
        <div>
          <h1>Sidecar</h1>
          <p>Managed files, diagnostics, settings, and debug exports.</p>
        </div>
        <div className="advanced-header-actions">
          <button className="secondary-action" disabled={props.loading || !!busy} onClick={() => void loadFiles(selectedKey, { loadSelected: activeTab === "Files" })}>
            <RefreshCw size={16} />
            Refresh files
          </button>
          <button className="secondary-action" disabled={props.loading || !!busy} onClick={props.onRefresh}>
            <RefreshCw size={16} />
            Refresh snapshot
          </button>
        </div>
      </div>

      <section className="sidecar-state-strip" aria-label="Sidecar state">
        <div>
          <span>Managed files</span>
          <strong>{files.length}</strong>
          <p>{editableFileCount} editable · {missingFileCount} missing</p>
        </div>
        <div className={dirty ? "warn" : "good"}>
          <span>Editor</span>
          <strong>{editorModel.statusLabel}</strong>
          <p>{selectedFile?.label ?? "No managed file selected"}</p>
        </div>
        <div className={statusTone(diagnosticsStatus)}>
          <span>Diagnostics</span>
          <strong>{diagnosticsStatus}</strong>
          <p>{diagnostics ? "Latest diagnostic snapshot loaded." : "Run checks to load backend evidence."}</p>
        </div>
        <div>
          <span>Debug bundle</span>
          <strong>{debugBundle ? "Exported" : "Ready"}</strong>
          <p>Secrets and arbitrary source files are excluded.</p>
        </div>
        <div className={statusTone(stateStatus)}>
          <span>Canonical state</span>
          <strong>{stateStatus}</strong>
          <p>{text(stateCounts.events, "0")} events · {text(stateCounts.checkpoints, "0")} checkpoints</p>
        </div>
      </section>

      <div className="advanced-tabs" role="tablist" aria-label="Sidecar sections">
        {tabs.map((tab) => (
          <button
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "active" : ""}
            key={tab}
            onClick={() => setActiveTab(tab)}
            role="tab"
          >
            {tabLabels[tab]}
          </button>
        ))}
      </div>

      {error && (
        <div className="brief-error" role="alert">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}
      {notice && (
        <div className="success-callout quiet" role="status" aria-live="polite">
          <CheckCircle2 size={16} />
          <div>
            <strong>{notice}</strong>
          </div>
        </div>
      )}

      {activeTab === "Files" && (
        <div className="advanced-files-layout">
          <aside className="panel advanced-file-list">
            <div className="panel-heading-row">
              <div>
                <h2>Files</h2>
                <p>Allowed managed files grouped by category.</p>
              </div>
            </div>
            {fileCategories.map((category) => {
              const categoryFiles = groupedFiles.get(category) ?? [];
              if (!categoryFiles.length) return null;
              return (
                <div className="advanced-file-category" key={category}>
                  <h3>{category}</h3>
                  {categoryFiles.map((file) => (
                    <button
                      className={selectedFile?.key === file.key ? "active" : ""}
                      key={file.key}
                      onClick={() => {
                        setSelectedKey(file.key);
                        void loadFile(file.key);
                      }}
                    >
                      <span>{file.label}</span>
                      <small>{file.exists ? humanSize(file.size_bytes) : "Missing"}</small>
                    </button>
                  ))}
                </div>
              );
            })}
          </aside>

          <article className="panel advanced-editor-panel">
            <div className="advanced-editor-toolbar">
              <div>
                <h2>{selectedFile?.label ?? "Managed File"}</h2>
                <p>{selectedFile?.key ?? "No file selected"}</p>
              </div>
              <div className={`advanced-dirty-pill ${dirty ? "dirty" : "clean"}`}>
                {editorModel.statusLabel}
              </div>
            </div>

            <div className="advanced-path-row">
              <code>{selectedPath || "No path"}</code>
              <button className="secondary-action" disabled={!selectedPath} onClick={() => void copyPath(selectedPath)}>
                <Clipboard size={15} />
                Copy
              </button>
            </div>

            <div className="advanced-file-actions">
              <button
                className="primary-action"
                disabled={!editorModel.canSave}
                title={!selectedFile?.editable ? "This managed file is read-only here." : undefined}
                onClick={() => void saveFile()}
              >
                <Save size={15} />
                Save
              </button>
              <button className="secondary-action" disabled={!editorModel.canDiscard} onClick={() => setEditorContent(savedContent)}>
                Discard
              </button>
              <button className="secondary-action" disabled={!editorModel.canValidate} onClick={() => void validateFile()}>
                <CheckCircle2 size={15} />
                Validate
              </button>
              <button className="secondary-action" disabled={!editorModel.canOpen} onClick={() => void openFile()}>
                <ExternalLink size={15} />
                Open externally
              </button>
              <button className="secondary-action" disabled={!editorModel.canReveal} onClick={() => void revealFile()}>
                <FolderOpen size={15} />
                Reveal in Finder
              </button>
            </div>

            <textarea
              className="advanced-editor"
              disabled={!selectedFile?.editable}
              spellCheck={false}
              value={editorContent}
              onChange={(event) => setEditorContent(event.target.value)}
            />

            {validation && (
              <div className={`advanced-validation ${statusTone(validation.status)}`}>
                <strong>Validation: {validation.status}</strong>
                {validationItems.map((item, index) => (
                  <p key={`${item.detail}-${index}`}>{item.detail}</p>
                ))}
              </div>
            )}
          </article>
        </div>
      )}

      {activeTab === "State" && (
        <div className="advanced-diagnostics-grid">
          <article className="panel span-2">
            <div className="panel-heading-row">
              <div>
                <h2>SQLite control plane</h2>
                <p>Authoritative orchestration state, event ledger, checkpoints, and generated projections.</p>
              </div>
              <button className="secondary-action" disabled={busy === "state"} onClick={() => void loadCanonicalState()}>
                <RefreshCw size={15} />
                Refresh state
              </button>
            </div>
            <div className="advanced-runtime-grid">
              <DetailRow label="Authority" value={canonicalState?.authority ?? "sqlite"} />
              <DetailRow label="Status" value={stateStatus} />
              <DetailRow label="Events" value={stateCounts.events ?? 0} />
              <DetailRow label="Checkpoints" value={stateCounts.checkpoints ?? 0} />
              <DetailRow label="Next actions" value={stateCounts.next_actions ?? 0} />
              <DetailRow label="Validations" value={stateCounts.validations ?? 0} />
            </div>
            <div className="advanced-path-row">
              <code>{text(canonicalState?.database?.path, "Canonical database will be initialized after scaffold or first run.")}</code>
              <button
                className="secondary-action"
                disabled={!canonicalState?.database?.path}
                onClick={() => void copyText(text(canonicalState?.database?.path, ""), "State database path copied.")}
              >
                <Clipboard size={15} />
                Copy
              </button>
            </div>
          </article>

          <article className="panel">
            <h2>Database health</h2>
            <DetailRow label="SQLite" value={canonicalState?.database?.sqlite_version ?? "unknown"} />
            <DetailRow label="Journal" value={canonicalState?.database?.journal_mode ?? "unknown"} />
            <DetailRow label="Integrity" value={canonicalState?.database?.integrity_check ?? "unknown"} />
            <DetailRow label="Projection" value={canonicalState?.projection?.name ?? "conveyor.state"} />
          </article>

          <article className="panel">
            <h2>Last event</h2>
            <DetailRow label="Type" value={canonicalState?.last_event?.event_type ?? "none"} />
            <DetailRow label="Role" value={canonicalState?.last_event?.actor_role ?? "none"} />
            <DetailRow label="Phase" value={canonicalState?.last_event?.phase ?? "none"} />
            <DetailRow label="Hash" value={canonicalState?.last_event?.event_hash ?? "none"} />
          </article>

          <article className="panel span-2">
            <h2>Next actions</h2>
            <div className="advanced-check-list compact">
              {nextActions.length ? nextActions.map((row) => (
                <div className="advanced-check-row" key={rowValue(row, "action_id")}>
                  <span>{rowValue(row, "owner_role", "idle")}</span>
                  <strong>{rowValue(row, "status", "planned")}</strong>
                  <p>{rowValue(row, "reason", "")}</p>
                </div>
              )) : <div className="empty-copy">No materialized next actions yet.</div>}
            </div>
          </article>

          <article className="panel span-2">
            <h2>Recent event ledger</h2>
            <div className="advanced-check-list compact">
              {recentStateEvents.length ? recentStateEvents.slice(0, 8).map((row) => (
                <div className="advanced-check-row" key={rowValue(row, "event_id")}>
                  <span>{rowValue(row, "event_type", "event")}</span>
                  <strong>#{rowValue(row, "sequence", "0")}</strong>
                  <p>{rowValue(row, "occurred_at", "")} · {rowValue(row, "actor_role", "runtime")} · {rowValue(row, "phase", "")}</p>
                  <code>{rowValue(row, "event_hash", "")}</code>
                </div>
              )) : <div className="empty-copy">No events recorded yet.</div>}
            </div>
          </article>
        </div>
      )}

      {activeTab === "Diagnostics" && (
        <div className="advanced-diagnostics-grid">
          <RuntimeEnvironmentCard
            environment={diagnostics?.runtime_environment}
            suggestions={diagnostics?.fix_suggestions}
            onCopy={(value, message) => void copyText(value, message)}
          />

          <article className="panel span-2">
            <div className="panel-heading-row">
              <div>
                <h2>Diagnostics</h2>
                <p>Backend prerequisite and target checks.</p>
              </div>
              <button className="secondary-action" disabled={busy === "diagnostics"} onClick={() => void runDiagnostics()}>
                <TerminalSquare size={15} />
                Run checks
              </button>
            </div>
            <div className="advanced-check-list">
              {prereqRows.length ? prereqRows.map((row) => <CheckRow key={rowValue(row, "name")} row={row} />) : <div className="empty-copy">Run diagnostics to inspect prerequisites.</div>}
            </div>
          </article>

          <article className="panel">
            <h2>Tools</h2>
            <p className="advanced-muted">Codex CLI, Python, bash, and git status.</p>
            <div className="advanced-check-list compact">
              {toolRows.map((row) => (
                <CheckRow key={rowValue(row, "name")} row={row} />
              ))}
            </div>
          </article>

          <article className="panel">
            <h2>Target write access</h2>
            <DetailRow label="Target" value={diagnostics?.target_writability.target === true ? "Writable" : "Review"} />
            <DetailRow label="Docs" value={diagnostics?.target_writability.docs === true ? "Writable" : "Review"} />
            <DetailRow label="Status" value={diagnostics?.target_writability.status ?? "unknown"} />
          </article>

          <article className="panel">
            <h2>Automation</h2>
            <DetailRow label="State" value={diagnostics?.automation.state ?? "unknown"} />
            <DetailRow label="PID" value={diagnostics?.automation.pid ?? "not running"} />
            <DetailRow label="Message" value={diagnostics?.automation.message ?? "No automation status loaded."} />
          </article>

          <article className="panel">
            <h2>Notifier</h2>
            <DetailRow label="Inbox mode" value={diagnostics?.notifier_health.bridge_mode ?? "file_only"} />
            <DetailRow label="Status" value={diagnostics?.notifier_health.status ?? "not_configured"} />
            <p className="empty-copy">{text(diagnostics?.notifier_health.detail, "No notifier health detail recorded.")}</p>
          </article>

          <article className="panel">
            <h2>Backend versions</h2>
            <DetailRow label="Schema" value={diagnostics?.backend.schema_version ?? 1} />
            <DetailRow label="Required files" value={diagnostics?.required_files.status ?? "not_run"} />
            <DetailRow label="Safety" value={diagnostics?.integration_safety.status ?? "unknown"} />
            <p className="empty-copy">{text(diagnostics?.macos_permissions.detail, "macOS permissions note unavailable.")}</p>
          </article>
        </div>
      )}

      {activeTab === "Settings" && (
        <div className="advanced-settings-grid">
          <article className="panel span-2">
            <h2>Settings</h2>
            <div className="brief-form-grid two">
              <label className="brief-field">
                <span>Review export directory</span>
                <input
                  value={settings.reviewExportDir}
                  onChange={(event) => setSettings((current) => ({ ...current, reviewExportDir: event.target.value }))}
                />
              </label>
              <label className="brief-field">
                <span>Preferred editor command</span>
                <input
                  value={settings.preferredEditorCommand}
                  onChange={(event) => setSettings((current) => ({ ...current, preferredEditorCommand: event.target.value }))}
                  placeholder="Stored only; OS default is used for Open"
                />
              </label>
              <label className="brief-field">
                <span>Inbox mode</span>
                <select
                  value={settings.humanBridgeMode}
                  onChange={(event) => setSettings((current) => ({ ...current, humanBridgeMode: event.target.value }))}
                >
                  <option value="file_only">File-only</option>
                  <option value="local_notifier">Local notifier</option>
                  <option value="discord_notifier">Discord notifier</option>
                  <option value="disabled">Disabled</option>
                </select>
              </label>
              <label className="brief-field">
                <span>Appearance</span>
                <select
                  value={settings.appearance}
                  onChange={(event) => setSettings((current) => ({ ...current, appearance: event.target.value }))}
                >
                  <option value="system">System</option>
                  <option value="light">Light</option>
                  <option value="dark">Dark</option>
                </select>
              </label>
              <label className="brief-field">
                <span>Density</span>
                <select
                  value={settings.density}
                  onChange={(event) => setSettings((current) => ({ ...current, density: event.target.value }))}
                >
                  <option value="comfortable">Comfortable</option>
                  <option value="compact">Compact</option>
                </select>
              </label>
            </div>
            <div className="advanced-file-actions">
              <button className="secondary-action" onClick={() => void chooseSettingsDir()}>
                <FolderOpen size={15} />
                Choose export directory
              </button>
              <button className="primary-action" disabled={busy === "settings"} onClick={() => void saveSettings()}>
                <Save size={15} />
                Save settings
              </button>
            </div>
          </article>

          <article className="panel">
            <h2>Storage</h2>
            <p className="empty-copy">
              Preferences are stored in the app config. Project state remains target-local in .diffmogger/agentic/dashboard_state.json.
            </p>
          </article>
        </div>
      )}

      {activeTab === "Debug" && (
        <div className="advanced-debug-grid">
          <article className="panel span-2">
            <div className="panel-heading-row">
              <div>
                <h2>Debug bundle</h2>
                <p>Exports app notes, backend command metadata, dashboard state, safety checks, and diagnostics without secrets.</p>
              </div>
              <button className="primary-action" disabled={busy === "debug-bundle"} onClick={() => void exportDebugBundle()}>
                <FileArchive size={15} />
                Export debug
              </button>
            </div>
            <label className="brief-field">
              <span>Output directory</span>
              <input value={debugDir} onChange={(event) => setDebugOutputDir(event.target.value)} />
            </label>
            <div className="advanced-omit-list">
              <div>
                <XCircle size={15} />
                <span>.env and .env.* contents are omitted.</span>
              </div>
              <div>
                <XCircle size={15} />
                <span>Secret-like keys and values are redacted.</span>
              </div>
              <div>
                <XCircle size={15} />
                <span>Arbitrary project source files are not exported.</span>
              </div>
            </div>
          </article>

          <article className="panel">
            <h2>Latest export</h2>
            {debugBundle ? (
              <div className="advanced-bundle-result">
                <code>{debugBundle.bundle_path}</code>
                <button className="secondary-action" onClick={() => void copyPath(debugBundle.bundle_path)}>
                  <Clipboard size={15} />
                  Copy path
                </button>
                <h3>Included</h3>
                {debugBundle.included.map((item) => (
                  <span key={item}>{item}</span>
                ))}
                <h3>Excluded / redacted</h3>
                {debugBundle.omitted.map((item) => (
                  <span key={item}>{item}</span>
                ))}
              </div>
            ) : (
              <div className="empty-copy">No debug export in this session.</div>
            )}
          </article>
        </div>
      )}
    </section>
  );
}
