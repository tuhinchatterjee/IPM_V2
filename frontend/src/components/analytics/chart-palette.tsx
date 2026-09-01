"use client";

import * as React from "react";
import { Palette } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * How a chart is coloured, chosen per chart rather than per product.
 *
 * Why this is not a theme setting
 * ------------------------------
 * A theme decides what the application looks like. A palette decides what a
 * *series* means, and the right answer changes with the chart and the room. The
 * same person wants full categorical colour at their desk, one flat colour in a
 * board pack that will be photocopied, and maximum separation when they are
 * projecting onto a wall from four metres away. Making that a global preference
 * forces one of those three onto the other two.
 *
 * So the control sits under the chart, changes only analytical colour, and is
 * remembered — the choice is about how somebody works, and asking again on
 * every chart would be its own kind of noise.
 *
 * How it works
 * ------------
 * By overriding `--ipm-chart-1..8` on a wrapper element. Every chart already
 * reads those at render time so a theme switch repaints them; a palette is the
 * same mechanism applied one level down. Not one line of chart code knows this
 * exists.
 *
 * Everything is derived from the theme's own tokens with `color-mix`, never
 * from literals — so a palette works on all eight themes, including ones added
 * later, and cannot drift away from the surface it is drawn on.
 */

/**
 * How many categorical slots a palette defines.
 *
 * Declared here rather than imported from `charts`, which imports this file —
 * the cycle would be legal and would make the module order matter, which is a
 * thing nobody should have to think about to add a palette.
 */
export const CHART_SLOTS = 8;

export type PaletteId = "institutional" | "signal" | "monochrome" | "contrast";

export interface PaletteDefinition {
  id: PaletteId;
  name: string;
  /** One line, shown on hover. Says when to reach for it. */
  hint: string;
  /** The eight slot colours, as CSS values. */
  slots: (index: number) => string;
}

/** The theme's own validated categorical ramp. */
const institutional = (index: number) => `var(--ipm-chart-${index + 1})`;

/**
 * Status colours, for a chart whose series ARE conditions.
 *
 * Only meaningful when the series mean good/watch/bad — a stage distribution, a
 * rating bucket. Used on a chart of sectors it would say something false, which
 * is why it is a choice and not a default.
 */
const SIGNAL = [
  "var(--ipm-positive)",
  "var(--ipm-info)",
  "var(--ipm-warning)",
  "var(--ipm-negative)",
  "color-mix(in oklab, var(--ipm-positive) 60%, var(--ipm-surface))",
  "color-mix(in oklab, var(--ipm-info) 60%, var(--ipm-surface))",
  "color-mix(in oklab, var(--ipm-warning) 60%, var(--ipm-surface))",
  "color-mix(in oklab, var(--ipm-negative) 60%, var(--ipm-surface))",
];

/**
 * One hue, eight steps.
 *
 * For anything that will be printed, photocopied or read by somebody who cannot
 * separate the categorical ramp. Ordered light to dark so the sequence survives
 * as greyscale.
 */
const monochrome = (index: number) => {
  const share = 92 - index * 11;
  return `color-mix(in oklab, var(--ipm-accent) ${100 - share}%, var(--ipm-text-primary))`;
};

/**
 * Maximum separation between neighbours, for a projector.
 *
 * The institutional ramp is tuned for a monitor at arm's length. Across a room,
 * through a projector's washed-out gamut, adjacent slots stop being adjacent —
 * this alternates far-apart slots so neighbouring series never sit next to each
 * other in hue.
 */
const CONTRAST_ORDER = [0, 4, 1, 5, 2, 6, 3, 7];
const contrast = (index: number) =>
  `var(--ipm-chart-${CONTRAST_ORDER[index % CHART_SLOTS] + 1})`;

export const PALETTES: PaletteDefinition[] = [
  {
    id: "institutional",
    name: "Institutional",
    hint: "The theme's categorical ramp. Tuned for a monitor.",
    slots: institutional,
  },
  {
    id: "signal",
    name: "Signal",
    hint: "Good, watch, bad. Only when the series actually mean that.",
    slots: (index) => SIGNAL[index % SIGNAL.length],
  },
  {
    id: "monochrome",
    name: "Monochrome",
    hint: "One hue in eight steps. Survives a photocopier.",
    slots: monochrome,
  },
  {
    id: "contrast",
    name: "Contrast",
    hint: "Maximum separation between neighbours. For a projector.",
    slots: contrast,
  },
];

const STORAGE_KEY = "creditprobe.chart.palette";
const CHANGED = "creditprobe:chart-palette";

export function useChartPalette(): [PaletteId, (id: PaletteId) => void] {
  const stored = React.useSyncExternalStore(
    subscribe,
    read,
    () => "institutional" as PaletteId,
  );
  const [override, setOverride] = React.useState<PaletteId | null>(null);

  const choose = React.useCallback((next: PaletteId) => {
    setOverride(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
      window.dispatchEvent(new Event(CHANGED));
    } catch {
      // Site data blocked. The palette still applies for this page.
    }
  }, []);

  return [override ?? stored, choose];
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function read(): PaletteId {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (PALETTES.some((p) => p.id === value)) return value as PaletteId;
  } catch {
    // Fall through.
  }
  return "institutional";
}

/** The slot overrides for one palette, as inline custom properties. */
export function paletteStyle(id: PaletteId): React.CSSProperties {
  const palette = PALETTES.find((p) => p.id === id) ?? PALETTES[0];
  if (palette.id === "institutional") return {};
  const style: Record<string, string> = {};
  for (let index = 0; index < CHART_SLOTS; index += 1) {
    style[`--ipm-chart-${index + 1}`] = palette.slots(index);
  }
  return style as React.CSSProperties;
}

/**
 * A chart, with its palette applied and its control underneath.
 *
 * The control is deliberately small and low-contrast. It is a preference, not a
 * finding, and it must never compete with the figures above it.
 */
export function ChartFrame({
  children,
  className,
  /**
   * Whether to offer the control. Left undefined it is decided by looking:
   * the frame shows it only if something inside actually drew a chart.
   *
   * A result can be a table, a set of KPI tiles, a chart, or all three
   * depending on the analysis, and threading that fact down from eight
   * different render branches would be eight places to forget. Asking the DOM
   * is one place, and it cannot fall out of step with what was rendered.
   */
  showControl,
}: {
  children: React.ReactNode;
  className?: string;
  showControl?: boolean;
}) {
  const [palette] = useChartPalette();
  const container = React.useRef<HTMLDivElement>(null);
  const [hasChart, setHasChart] = React.useState(false);

  // Re-checked when the rendered result changes, which is the only time the
  // answer can differ. Running it on every render would work — the update is
  // guarded — but it would also be a lint warning that is right in general.
  React.useEffect(() => {
    if (showControl !== undefined) return;
    const found = Boolean(container.current?.querySelector("svg.recharts-surface"));
    setHasChart((current) => (current === found ? current : found));
  }, [children, showControl]);

  const offer = showControl ?? hasChart;

  return (
    <div
      ref={container}
      className={cn("min-w-0", className)}
      style={paletteStyle(palette)}
    >
      {children}
      {offer && <PaletteControl />}
    </div>
  );
}

/**
 * The control itself. Tiny, low-contrast, and never competing with the figures
 * above it — it is a preference, not a finding.
 */
export function PaletteControl({ className }: { className?: string }) {
  const [palette, choose] = useChartPalette();
  return (
    <div className={cn("mt-1.5 flex items-center gap-1 px-1", className)}>
      <Palette className="size-3 shrink-0 text-text-muted/60" aria-hidden />
      <div role="group" aria-label="Chart colour" className="flex items-center gap-0.5">
        {PALETTES.map((option) => {
          const active = option.id === palette;
          return (
            <button
              key={option.id}
              type="button"
              title={option.hint}
              aria-pressed={active}
              onClick={() => choose(option.id)}
              className={cn(
                "rounded px-1.5 py-0.5 text-[0.625rem] transition-colors",
                active
                  ? "bg-surface-selected text-text-secondary"
                  : "text-text-muted/70 hover:text-text-secondary",
              )}
            >
              {option.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}
