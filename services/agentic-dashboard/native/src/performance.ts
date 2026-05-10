import { useEffect, useState } from "react";

type IdleHandle = number;

type IdleWindow = Window & {
  requestIdleCallback?: (callback: () => void, options?: { timeout?: number }) => IdleHandle;
  cancelIdleCallback?: (handle: IdleHandle) => void;
};

export function scheduleAfterPaint(callback: () => void, timeout = 160): () => void {
  if (typeof window === "undefined") return () => undefined;
  const idleWindow = window as IdleWindow;
  let idleHandle: IdleHandle | null = null;
  let timeoutHandle: number | null = null;
  let frameHandle: number | null = null;
  let cancelled = false;

  const run = () => {
    if (cancelled) return;
    callback();
  };

  const scheduleIdle = () => {
    if (cancelled) return;
    if (typeof idleWindow.requestIdleCallback === "function") {
      idleHandle = idleWindow.requestIdleCallback(run, { timeout });
      return;
    }
    timeoutHandle = window.setTimeout(run, 0);
  };

  if (typeof window.requestAnimationFrame === "function") {
    frameHandle = window.requestAnimationFrame(scheduleIdle);
  } else {
    scheduleIdle();
  }

  return () => {
    cancelled = true;
    if (frameHandle !== null && typeof window.cancelAnimationFrame === "function") {
      window.cancelAnimationFrame(frameHandle);
    }
    if (idleHandle !== null && typeof idleWindow.cancelIdleCallback === "function") {
      idleWindow.cancelIdleCallback(idleHandle);
    }
    if (timeoutHandle !== null) window.clearTimeout(timeoutHandle);
  };
}

export function useDeferredStage(resetKey: unknown, maxStage: number): number {
  const [state, setState] = useState<{ key: unknown; stage: number }>(() => ({ key: resetKey, stage: 0 }));
  const stage = Object.is(state.key, resetKey) ? state.stage : 0;

  useEffect(() => {
    let cancelled = false;
    let cancelScheduled: () => void = () => undefined;

    setState({ key: resetKey, stage: 0 });

    function scheduleStage(nextStage: number) {
      cancelScheduled = scheduleAfterPaint(() => {
        if (cancelled) return;
        setState({ key: resetKey, stage: nextStage });
        if (nextStage < maxStage) scheduleStage(nextStage + 1);
      });
    }

    scheduleStage(1);

    return () => {
      cancelled = true;
      cancelScheduled();
    };
  }, [maxStage, resetKey]);

  return stage;
}

export function useChunkedLimit(total: number, initial: number, step: number, resetKey: unknown): number {
  const [state, setState] = useState<{ key: unknown; total: number; limit: number }>(() => ({
    key: resetKey,
    total,
    limit: Math.min(total, initial),
  }));
  const limit = Object.is(state.key, resetKey) && state.total === total ? state.limit : Math.min(total, initial);

  useEffect(() => {
    let cancelled = false;
    let cancelScheduled: () => void = () => undefined;

    setState({ key: resetKey, total, limit: Math.min(total, initial) });

    function scheduleNext(currentLimit: number) {
      if (currentLimit >= total) return;
      cancelScheduled = scheduleAfterPaint(() => {
        if (cancelled) return;
        const nextLimit = Math.min(total, currentLimit + step);
        setState({ key: resetKey, total, limit: nextLimit });
        scheduleNext(nextLimit);
      });
    }

    scheduleNext(Math.min(total, initial));

    return () => {
      cancelled = true;
      cancelScheduled();
    };
  }, [initial, resetKey, step, total]);

  return limit;
}
