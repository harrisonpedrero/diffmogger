import type { ObservatorySnapshot } from "./api/backend";

export type ObservatoryTone = "good" | "warn" | "critical" | "info" | "quiet";

// Runtime state remains on Summary rather than a separate tab.
export type ObservatoryTab = "Summary" | "Events" | "Queue" | "Metrics";

export type ObservatoryViewModel = {
  empty: boolean;
  status: string;
  tone: ObservatoryTone;
  headline: string;
  subheadline: string;
  activeRole: string;
  hasQueuedPatch: boolean;
  needsHuman: boolean;
  criticalStop: boolean;
  tabs: ObservatoryTab[];
};

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function number(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && Number.isFinite(Number(value))) return Number(value);
  return 0;
}

function toneFromStatus(status: string): ObservatoryTone {
  if (status.includes("CRITICAL")) return "critical";
  if (status.includes("BLOCKED")) return "warn";
  if (status.includes("PENDING")) return "warn";
  if (status === "ACTIVE" || status === "ACTIVE_WITH_PENDING_USER_INPUT") return "good";
  return status === "UNKNOWN" ? "quiet" : "info";
}

export function buildObservatoryViewModel(snapshot: ObservatorySnapshot | null): ObservatoryViewModel {
  const tabs: ObservatoryTab[] = ["Summary", "Events", "Queue", "Metrics"];
  if (!snapshot) {
    return {
      empty: true,
      status: "NO_TARGET",
      tone: "quiet",
      headline: "Activity",
      subheadline: "Choose a project folder to load activity.",
      activeRole: "",
      hasQueuedPatch: false,
      needsHuman: false,
      criticalStop: false,
      tabs,
    };
  }

  const status = text(snapshot.mission.automation_status, "UNKNOWN").toUpperCase();
  const activeRole = text(snapshot.conveyor.active_run?.role, "");
  const queued = number(snapshot.patches.queue_totals?.queued);
  const needsHuman =
    status.includes("BLOCKED_ON_USER") ||
    number(snapshot.metrics.pending_human) > 0 ||
    snapshot.mission.tags.some((tag) => tag.label === "Human" && number(tag.value) > 0);
  const criticalStop = status.includes("CRITICAL_STOP");
  const headline = criticalStop
    ? "Critical stop is active"
    : needsHuman
      ? "Input needed"
      : activeRole
        ? `${activeRole} is running`
        : "Activity";

  return {
    empty: false,
    status,
    tone: criticalStop ? "critical" : toneFromStatus(status),
    headline,
    subheadline: text(snapshot.mission.best_next_milestone, snapshot.subtitle),
    activeRole,
    hasQueuedPatch: queued > 0,
    needsHuman,
    criticalStop,
    tabs,
  };
}
