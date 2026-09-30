"use client";

/**
 * The one Plotly wrapper every CreditProbe analytical chart goes through.
 *
 * Why one wrapper: the product-wide visual contract (§27) is behaviour, not a
 * renderer. Hover with units and context, legend isolate that never alters a
 * total, zoom/pan/reset, box/lasso selection where a chart represents a
 * population, click-to-filter and click-to-drill, responsive resize and
 * PNG/SVG download are wired HERE once, so a chart cannot quietly opt out.
 *
 * Plotly is loaded dynamically, client-side only, so the bundle cost is paid
 * by the pages that draw charts and never by the server render.
 */

import * as React from "react";

export interface PlotPoint {
  x?: unknown;
  y?: unknown;
  label?: unknown;
  customdata?: unknown;
  curveNumber: number;
  pointNumber?: number;
  pointIndex?: number;
  pointNumbers?: number[];
  data?: { name?: string; customdata?: unknown[] };
}

export interface PlotlyChartProps {
  data: Record<string, unknown>[];
  layout?: Record<string, unknown>;
  height?: number;
  /** Box/lasso selection: only for charts whose marks are a population. */
  selectable?: boolean;
  onPointClick?: (point: PlotPoint) => void;
  onSelected?: (points: PlotPoint[]) => void;
  onDeselect?: () => void;
  ariaLabel: string;
  testId?: string;
  /** Filename stem for PNG/SVG downloads. */
  filename?: string;
  className?: string;
  /** "minimal" hides the mode bar (sparklines inside cards). */
  chrome?: "full" | "minimal";
}

type PlotlyModule = typeof import("plotly.js-dist-min").default;

let plotlyPromise: Promise<PlotlyModule> | null = null;

export function loadPlotly(): Promise<PlotlyModule> {
  if (!plotlyPromise) {
    plotlyPromise = import("plotly.js-dist-min").then((m) => (m.default ?? m) as PlotlyModule);
  }
  return plotlyPromise;
}

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

/** Theme-adaptive layout defaults read from the design tokens. */
export function themedLayout(layout: Record<string, unknown> = {}): Record<string, unknown> {
  const text = cssVar("--ipm-text-secondary", "#475569");
  const grid = cssVar("--ipm-border", "#E2E8F0");
  const base: Record<string, unknown> = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter, ui-sans-serif, system-ui, sans-serif", size: 12, color: text },
    margin: { l: 56, r: 16, t: 16, b: 44 },
    hoverlabel: { namelength: -1, font: { size: 12 } },
    legend: { orientation: "h", y: -0.18, x: 0 },
    xaxis: { gridcolor: grid, zerolinecolor: grid, automargin: true },
    yaxis: { gridcolor: grid, zerolinecolor: grid, automargin: true },
    transition: { duration: 250, easing: "cubic-in-out" },
    // A re-render with fresh figure objects must not undo what the reader
    // did: a series hidden from the legend, a zoom. Plotly keeps user-driven
    // UI state while `uirevision` is unchanged; a chart that WANTS a reset
    // on new data passes its own value.
    uirevision: "reader",
  };
  const merged: Record<string, unknown> = { ...base, ...layout };
  for (const axis of ["xaxis", "yaxis"]) {
    merged[axis] = { ...(base[axis] as object), ...((layout[axis] as object) ?? {}) };
  }
  return merged;
}

export interface PlotHandle {
  download: (format: "png" | "svg") => Promise<void>;
}

export const PlotlyChart = React.forwardRef<PlotHandle, PlotlyChartProps>(function PlotlyChart(
  {
    data,
    layout,
    height = 320,
    selectable = false,
    onPointClick,
    onSelected,
    onDeselect,
    ariaLabel,
    testId,
    filename = "creditprobe-chart",
    className,
    chrome = "full",
  },
  ref,
) {
  const host = React.useRef<HTMLDivElement | null>(null);
  const [error, setError] = React.useState<string>("");
  const handlers = React.useRef({ onPointClick, onSelected, onDeselect });
  handlers.current = { onPointClick, onSelected, onDeselect };

  React.useImperativeHandle(ref, () => ({
    download: async (format) => {
      const el = host.current;
      if (!el) return;
      const Plotly = await loadPlotly();
      await Plotly.downloadImage(el, { format, filename, width: 1200, height: Math.max(height, 400) });
    },
  }));

  React.useEffect(() => {
    let cancelled = false;
    const el = host.current;
    if (!el) return;
    loadPlotly()
      .then(async (Plotly) => {
        if (cancelled || !host.current) return;
        const config = {
          responsive: true,
          displaylogo: false,
          displayModeBar: chrome === "minimal" ? false : "hover",
          scrollZoom: false,
          toImageButtonOptions: { format: "png", filename, scale: 2 },
          modeBarButtonsToRemove: selectable ? [] : ["select2d", "lasso2d"],
        };
        await Plotly.react(
          el,
          data,
          themedLayout({ height, dragmode: selectable ? "select" : "zoom", ...(layout ?? {}) }),
          config,
        );
        const node = el as HTMLDivElement & {
          on?: (event: string, fn: (payload: { points?: PlotPoint[] }) => unknown) => void;
          removeAllListeners?: (event: string) => void;
        };
        for (const event of ["plotly_click", "plotly_selected", "plotly_deselect"]) {
          node.removeAllListeners?.(event);
        }
        node.on?.("plotly_click", (payload) => {
          const point = payload?.points?.[0];
          if (point) handlers.current.onPointClick?.(point);
        });
        node.on?.("plotly_selected", (payload) => {
          if (payload?.points?.length) handlers.current.onSelected?.(payload.points);
        });
        node.on?.("plotly_deselect", () => handlers.current.onDeselect?.());
        el.setAttribute("data-rendered", "true");
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [data, layout, height, selectable, filename, chrome]);

  React.useEffect(() => {
    const el = host.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      loadPlotly()
        .then((Plotly) => {
          // A chart hidden or detached mid-resize (a collapsed card, a route
          // change) is not resized: Plotly rejects it, and that rejection
          // would otherwise surface as an unhandled page error.
          if (!el.getAttribute("data-rendered") || !el.isConnected || el.offsetParent === null) return;
          void Promise.resolve(Plotly.Plots.resize(el)).catch(() => undefined);
        })
        .catch(() => undefined);
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      loadPlotly()
        .then((Plotly) => Plotly.purge(el))
        .catch(() => undefined);
    };
  }, []);

  if (error) {
    return (
      <div role="alert" className="rounded-md border border-border p-3 text-sm text-negative">
        The chart could not be drawn ({error}). Its data is in the table below.
      </div>
    );
  }
  return (
    <div
      ref={host}
      role="img"
      aria-label={ariaLabel}
      data-testid={testId}
      data-plotly="true"
      className={className}
      style={{ width: "100%", minHeight: height }}
    />
  );
});
