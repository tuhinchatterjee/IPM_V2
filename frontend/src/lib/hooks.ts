"use client";

import * as React from "react";

import { ApiError, api, type AnalysisRunResponse, type ExecuteOptions } from "@/lib/api";

/**
 * Data-fetching hooks.
 *
 * One small pattern used everywhere, rather than each screen inventing its own:
 * an async call becomes {data, error, loading, reload}. Every screen therefore
 * has the same three states and the same error text, which is what stops
 * "loading" and "broken" from looking alike.
 */

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  /**
   * True when the backend REFUSED this panel rather than failing at it — the
   * caller's role may not read what the panel shows.
   *
   * This exists because flattening every failure into one string lost the
   * difference. A route crawl found six screens where a Viewer, correctly
   * refused, saw an empty panel or a red error: the product had told them
   * something was broken when nothing was. A refusal is the permission model
   * working, and it reads differently — see `<Unavailable>`.
   */
  refused: boolean;
  /** The HTTP status behind `error`, or 0 when the backend was unreachable. */
  status: number;
}

type Phase<T> =
  | { status: "idle" }
  /**
   * `data` is what the last successful call returned, carried through the
   * next one when the caller asked for `keepPrevious`. It is not a cache: it
   * is the answer to "what should the screen show while this reloads", and
   * the honest answer is usually the reading it is replacing rather than a
   * skeleton where a working screen used to be.
   */
  | { status: "loading"; data?: T }
  | { status: "ready"; data: T }
  | { status: "error"; message: string; code: number };

export function useAsync<T>(
  fn: () => Promise<T>,
  deps: React.DependencyList = [],
  options: { enabled?: boolean; keepPrevious?: boolean } = {},
): AsyncState<T> {
  const enabled = options.enabled ?? true;
  /**
   * Keep the last result on screen while the next one loads.
   *
   * Off by default: a first load has nothing to keep, and most screens
   * reload only when the thing they are showing has been replaced. It is for
   * screens that reload *underneath* an interaction — a lens re-rendering
   * because a metric was added to it from inside the page. Blanking the body
   * there unmounts whatever the person was in the middle of along with it.
   */
  const keepPrevious = options.keepPrevious ?? false;
  const [phase, setPhase] = React.useState<Phase<T>>(enabled ? { status: "loading" } : { status: "idle" });
  const [nonce, setNonce] = React.useState(0);

  // Callers pass an inline arrow, so `fn` is a new function on every render and
  // cannot go in the dependency array — the effect keys off the caller's own
  // deps instead. The ref holds the latest closure, and it is updated in an
  // effect declared BEFORE the fetching one: effects run in declaration order,
  // so the ref is current by the time the fetch reads it, and nothing touches a
  // ref during render.
  const fnRef = React.useRef(fn);
  React.useEffect(() => {
    fnRef.current = fn;
  });

  React.useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      // Not called synchronously in the effect body — this is the async
      // subscription-style callback the rule permits.
      setPhase((prev) =>
        keepPrevious && prev.status === "ready"
          ? { status: "loading", data: prev.data }
          : { status: "loading" });
      try {
        const result = await fnRef.current();
        if (!cancelled) setPhase({ status: "ready", data: result });
      } catch (e) {
        if (cancelled) return;
        setPhase({
          status: "error",
          message: e instanceof ApiError ? e.message : "Something went wrong.",
          code: e instanceof ApiError ? e.status : -1,
        });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled, keepPrevious]);

  const reload = React.useCallback(() => setNonce((n) => n + 1), []);

  return {
    data:
      phase.status === "ready"
        ? phase.data
        : phase.status === "loading"
          ? phase.data ?? null
          : null,
    error: phase.status === "error" ? phase.message : null,
    loading: phase.status === "loading",
    reload,
    refused: phase.status === "error" && phase.code === 403,
    status: phase.status === "error" && phase.code > 0 ? phase.code : 0,
  };
}

/**
 * Run one registered analysis.
 *
 * Every analytical figure on screen comes through here, so nothing in the UI
 * can display a number the engine did not produce.
 */
export function useAnalysis(
  analysisId: string,
  options: ExecuteOptions = {},
  enabled = true,
): AsyncState<AnalysisRunResponse> {
  const key = JSON.stringify(options);
  return useAsync<AnalysisRunResponse>(
    () => api.execute(analysisId, options),
    [analysisId, key],
    { enabled },
  );
}

/** The reporting periods available, with `latest` resolved. */
export function usePeriods() {
  return useAsync(() => api.periods(), []);
}

/** Debounce a value — used by search boxes so every keystroke is not a filter pass. */
export function useDebounced<T>(value: T, delayMs = 200): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
