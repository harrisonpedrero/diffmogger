import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  ExternalLink,
  FileDown,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Trash2,
  Users,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { BackendEnvelope, BackendLogEvent, ProjectSnapshot } from "./api/backend";
import {
  listenBackendLogs,
  runBackendCommand,
  runBackendCommandStreamed,
} from "./api/backend";
import { buildRunModel, type RunAction, type RunRoute } from "./runModel";

type RunLogEvent = BackendLogEvent & { capturedAt: string };

function routeFromRun(route: RunRoute): "Brief" | "Run" | "Review" | "Advanced" {
  return route;
}

function formatTime(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function value(value: string, fallback = "Not recorded"): string {
  return value.trim() ? value : fallback;
}

function scheduleRemovalMessage(data?: Record<string, unknown>): string {
  const rawRemovedCount = data?.removed_count;
  const removedCount = typeof rawRemovedCount === "number" ? rawRemovedCount : 0;
  if (removedCount === 1) return "Removed 1 LaunchAgent plist.";
  if (removedCount > 1) return `Removed ${removedCount} LaunchAgent plists.`;
  return "No LaunchAgent plist was found for this target.";
}

function ActionButton(props: {
  action: RunAction;
  onRun: (action: RunAction) => void;
  icon?: ReactNode;
  primary?: boolean;
  disabled?: boolean;
}) {
  const disabled = props.disabled ?? !props.action.enabled;
  return (
    <button
      className={props.primary ? "primary-action" : "secondary-action"}
      disabled={disabled}
      title={disabled ? props.action.reason : undefined}
      onClick={() => props.onRun(props.action)}
    >
      {props.icon}
      {props.action.label}
    </button>
  );
}

function DetailRow(props: { label: string; value: string | number }) {
  return (
    <div className="data-row">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

export function RunPage(props: {
  snapshot: ProjectSnapshot | null;
  loading: boolean;
  onChoose: () => void;
  onNavigate: (route: "Brief" | "Run" | "Review" | "Advanced") => void;
  onRefresh: () => void;
}) {
  const model = useMemo(() => buildRunModel(props.snapshot), [props.snapshot]);
  const [busyCommand, setBusyCommand] = useState<string | null>(null);
  const [logs, setLogs] = useState<RunLogEvent[]>([]);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandMessage, setCommandMessage] = useState<string | null>(null);
  const [logOverride, setLogOverride] = useState<Record<string, unknown> | null>(null);
  const [writeOwnership, setWriteOwnership] = useState("");
  const isBusy = props.loading || busyCommand !== null;

  const target = props.snapshot?.target.path;
  const displayedLog = logOverride
    ? {
        exists: logOverride.exists === true,
        path: String(logOverride.rel_path || logOverride.path || ""),
        modifiedAt: String(logOverride.modified_at || ""),
        content: String(logOverride.content || ""),
        lines: Array.isArray(logOverride.lines)
          ? logOverride.lines
              .map((line) => (typeof line === "object" && line ? (line as Record<string, unknown>) : {}))
              .map((line) => ({
                timestamp: String(line.timestamp || logOverride.modified_at || ""),
                text: String(line.text || ""),
              }))
              .filter((line) => line.text)
          : [],
      }
    : model.runLog;
  const terminalLines =
    logs.length > 0
      ? logs.map((line) => ({
          timestamp: line.capturedAt,
          text: `[${line.stage}] ${line.message}`,
          level: line.level,
        }))
      : displayedLog.lines.map((line) => ({ ...line, level: "info" }));

  async function runAction(action: RunAction) {
    setCommandError(null);
    setCommandMessage(null);
    if (action.kind === "choose-project") {
      props.onChoose();
      return;
    }
    if (action.kind === "navigate" && action.route) {
      if (action.route === "Run") props.onRefresh();
      else props.onNavigate(routeFromRun(action.route));
      return;
    }
    if (!action.command || !target || !action.enabled) return;
    const command = action.command;
    if (command === "schedule.remove") {
      setBusyCommand(command);
      setLogs([]);
      try {
        const payload = await runBackendCommand<Record<string, unknown>>({
          command,
          target,
        });
        if (!payload.ok) {
          setCommandError(payload.message ?? "Backend command failed.");
          return;
        }
        setCommandMessage(scheduleRemovalMessage(payload.data));
        props.onRefresh();
      } catch (error) {
        setCommandError(error instanceof Error ? error.message : String(error));
      } finally {
        setBusyCommand(null);
      }
      return;
    }
    if (command === "worker.run_write" && !writeOwnership.trim()) {
      setCommandError("Enter a disjoint ownership scope before launching a write worker.");
      return;
    }
    const runId = `${command}-${Date.now()}`;
    setBusyCommand(command);
    setLogs([]);
    let unlisten: (() => void) | null = null;
    try {
      unlisten = await listenBackendLogs(runId, (event) => {
        setLogs((current) => [...current, { ...event, capturedAt: new Date().toISOString() }]);
      });
      const payload: BackendEnvelope<Record<string, unknown>> = await runBackendCommandStreamed({
        runId,
        command,
        target,
        ownership: command === "worker.run_write" ? writeOwnership.trim() : undefined,
      });
      if (!payload.ok) {
        setCommandError(payload.message ?? "Backend command failed.");
      }
      props.onRefresh();
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : String(error));
    } finally {
      unlisten?.();
      setBusyCommand(null);
    }
  }

  async function openLogFile() {
    if (!target) return;
    setCommandError(null);
    try {
      const payload = await runBackendCommand<{ run_log?: Record<string, unknown> }>({
        command: "run.load_log",
        target,
      });
      if (!payload.ok) {
        setCommandError(payload.message ?? "Could not load the latest run log.");
        return;
      }
      setLogOverride(payload.data?.run_log ?? null);
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : String(error));
    }
  }

  async function copyLog() {
    const content =
      terminalLines.map((line) => `${formatTime(line.timestamp)} ${line.text}`).join("\n") ||
      displayedLog.content;
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
    } catch {
      setCommandError("Could not copy the run log from this environment.");
    }
  }

  if (!model.isScaffolded) {
    return (
      <section className="run-page">
        <div className={`run-banner ${model.banner.tone}`}>
          <div>
            <span className="state-badge">{model.banner.badge}</span>
            <h1>{model.banner.headline}</h1>
            <p>{model.banner.subheadline}</p>
          </div>
          <ActionButton action={model.banner.primaryAction} onRun={runAction} primary icon={<Play size={16} />} />
        </div>
      </section>
    );
  }

  const writeDisabled =
    !model.worker.actions.write.enabled || isBusy || !writeOwnership.trim();

  return (
    <section className="run-page">
      <div className={`run-banner ${model.banner.tone}`}>
        <div>
          <span className="state-badge">{model.banner.badge}</span>
          <h1>{model.banner.headline}</h1>
          <p>{model.banner.subheadline}</p>
        </div>
        <ActionButton
          action={model.banner.primaryAction}
          onRun={runAction}
          primary
          disabled={isBusy || !model.banner.primaryAction.enabled}
          icon={<Play size={16} />}
        />
      </div>

      {commandError && (
        <div className="brief-error">
          <AlertTriangle size={16} />
          {commandError}
        </div>
      )}

      {commandMessage && (
        <div className="success-callout quiet">
          <CheckCircle2 size={16} />
          <div>
            <strong>{commandMessage}</strong>
          </div>
        </div>
      )}

      <div className="run-layout">
        <article className="panel run-readiness">
          <h2>Run Readiness</h2>
          <DetailRow label="Current status" value={model.latestRun.status} />
          <DetailRow label="Horizon" value={model.latestRun.horizon} />
          <DetailRow label="Last updated" value={model.latestRun.lastUpdated} />
          <p className="empty-copy">{model.latestRun.summary}</p>
        </article>

        <article className="panel run-controls-panel">
          <h2>Run Controls</h2>
          <div className="run-control-grid">
            <ActionButton
              action={model.controls.runOnce}
              onRun={runAction}
              disabled={isBusy || !model.controls.runOnce.enabled}
              icon={<Play size={16} />}
            />
            <ActionButton
              action={model.controls.startSchedule}
              onRun={runAction}
              disabled={isBusy || !model.controls.startSchedule.enabled}
              icon={<RefreshCw size={16} />}
            />
            <ActionButton
              action={model.controls.pauseSchedule}
              onRun={runAction}
              disabled={isBusy || !model.controls.pauseSchedule.enabled}
              icon={<Pause size={16} />}
            />
            <ActionButton
              action={model.controls.removeSchedule}
              onRun={runAction}
              disabled={isBusy || !model.controls.removeSchedule.enabled}
              icon={<Trash2 size={16} />}
            />
            <ActionButton
              action={model.controls.safetyCheck}
              onRun={runAction}
              disabled={isBusy || !model.controls.safetyCheck.enabled}
              icon={<ShieldCheck size={16} />}
            />
          </div>
          <button className="link-action" onClick={() => props.onNavigate("Review")}>
            <FileDown size={14} />
            Export Review Bundle
          </button>
        </article>

        <article className="panel">
          <h2>Schedule Status</h2>
          <DetailRow label="State" value={model.schedule.state} />
          <DetailRow label="Strategy" value={model.schedule.strategyLabel} />
          <DetailRow label="Cadence" value={model.schedule.cadence} />
          <p className="empty-copy">{model.schedule.message}</p>
          {model.schedule.labels.length > 0 && (
            <details>
              <summary>LaunchAgent labels</summary>
              <div className="raw-details">
                {model.schedule.labels.map((label) => (
                  <code key={label}>{label}</code>
                ))}
              </div>
            </details>
          )}
        </article>

        <article className="panel">
          <h2>Current / Latest Run</h2>
          <DetailRow label="Status" value={model.latestRun.status} />
          <DetailRow label="Horizon" value={model.latestRun.horizon} />
          <DetailRow label="Updated" value={model.latestRun.lastUpdated} />
        </article>

        <article className="panel span-2">
          <div className="panel-heading-row">
            <h2>Run Log</h2>
            <div className="inline-actions">
              <button className="icon-text-button" disabled={terminalLines.length === 0 && !displayedLog.content} onClick={copyLog}>
                <Clipboard size={14} />
                Copy
              </button>
              <button className="icon-text-button" disabled={!displayedLog.exists} onClick={openLogFile}>
                <ExternalLink size={14} />
                Open Log File
              </button>
            </div>
          </div>
          <div className="terminal-log">
            {terminalLines.length > 0 ? (
              terminalLines.map((line, index) => (
                <div className={`terminal-line ${line.level}`} key={`${line.timestamp}-${index}`}>
                  <span>{formatTime(line.timestamp)}</span>
                  <code>{line.text}</code>
                </div>
              ))
            ) : (
              <div className="terminal-empty">
                <Terminal size={16} />
                No automation log has been recorded yet.
              </div>
            )}
          </div>
          {displayedLog.path && <p className="log-path">{displayedLog.path}</p>}
        </article>

        <article className="panel worker-card">
          <h2>Worker Strategy</h2>
          <div className="worker-headline">
            <Users size={18} />
            <strong>{model.worker.headline}</strong>
          </div>
          <p className="empty-copy">{model.worker.summary}</p>
          <DetailRow label="Latest result" value={model.worker.latest} />
          <details>
            <summary>Raw strategy details</summary>
            <pre className="raw-json">{JSON.stringify(model.worker.raw, null, 2)}</pre>
          </details>
          <div className="worker-actions">
            <ActionButton
              action={model.worker.actions.readOnly}
              onRun={runAction}
              disabled={isBusy || !model.worker.actions.readOnly.enabled}
            />
            <div className="write-worker-row">
              <input
                value={writeOwnership}
                onChange={(event) => setWriteOwnership(event.target.value)}
                placeholder="Ownership scope, e.g. docs/** only"
                disabled={!model.worker.actions.write.enabled || isBusy}
              />
              <ActionButton
                action={model.worker.actions.write}
                onRun={runAction}
                disabled={writeDisabled}
              />
            </div>
            <ActionButton
              action={model.worker.actions.integrator}
              onRun={runAction}
              disabled={isBusy || !model.worker.actions.integrator.enabled}
            />
          </div>
        </article>

        <article className="panel blockers-card">
          <h2>Environment Blockers</h2>
          {model.blockers.length > 0 ? (
            <div className="blocker-list">
              {model.blockers.map((blocker) => (
                <div className="blocker-row" key={blocker.name}>
                  <strong>{blocker.name}</strong>
                  <span>{value(blocker.detail, "No detail recorded.")}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty-copy">No required environment blockers are recorded for the current target.</p>
          )}
        </article>
      </div>
    </section>
  );
}
