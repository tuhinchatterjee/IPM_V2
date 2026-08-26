"use client";

import * as React from "react";
import { Maximize2, RotateCcw } from "lucide-react";

import { STATUS, statusOf, worst } from "@/components/trace/status";
import { LAYER_LABELS, LAYER_LANE } from "@/components/trace/graph";
import { MetadataLabel } from "@/components/typography";
import type { TraceGraph, TraceNode } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The computational landscape: an analysis rising from data to conclusion.
 *
 * The idea
 * --------
 * Stack the governance stages as planes in depth. Governed data is the ground;
 * relationships sit above it; then transformations, the mathematical query,
 * execution, validation, the result, and CreditProbe's interpretation at the
 * top. A reader sees at a glance how far an answer travelled from the rows it
 * came from, and — because a troubled plane is lifted toward them — where it
 * ran into difficulty.
 *
 * Why this is CSS and not WebGL
 * -----------------------------
 * The brief asked for a dimensional view and said to assess a 3D library
 * rather than adding one blindly. Assessed, and not added. Three.js with React
 * Three Fiber is roughly 600KB before anything is drawn, needs its own
 * lazy-loading path so it cannot block an ordinary analysis, brings a WebGL
 * context that some managed desktop estates disable outright, and would have
 * to reimplement text rendering, hit-testing and focus handling that the
 * browser already does correctly.
 *
 * What it would buy is a freely orbitable camera. What this view actually needs
 * is a *fixed, restrained* perspective — the brief says so itself — with planes
 * that can be tilted and separated. `transform-style: preserve-3d` does that
 * natively, in about a hundred lines, with real DOM nodes that are selectable,
 * focusable, readable by a screen reader and printable.
 *
 * So the depth is real and the dependency is not. If a future visualisation
 * genuinely needs a free camera over thousands of points — the Risk Landscape
 * scatter, say — that is the case to reopen it for, and it can be lazy-loaded
 * there without this view paying for it.
 */

/** How far the stack tilts. Restrained on purpose: this is not a flythrough. */
const TILT_MIN = 0;
const TILT_MAX = 62;
const TILT_DEFAULT = 38;

/** Vertical separation between planes, in px. */
const SPREAD_MIN = 28;
const SPREAD_MAX = 110;
const SPREAD_DEFAULT = 52;

export function TraceLandscape({
  graph,
  selected,
  onSelect,
  className,
}: {
  graph: TraceGraph;
  selected?: string | null;
  onSelect?: (nodeId: string) => void;
  className?: string;
}) {
  const [tilt, setTilt] = React.useState(TILT_DEFAULT);
  const [spread, setSpread] = React.useState(SPREAD_DEFAULT);
  const [rotate, setRotate] = React.useState(0);

  const planes = React.useMemo(() => stack(graph), [graph]);

  const reset = () => {
    setTilt(TILT_DEFAULT);
    setSpread(SPREAD_DEFAULT);
    setRotate(0);
  };

  return (
    <div className={cn("relative min-w-0", className)}>
      {/* Sized to the stack rather than to a guess. Eight planes at a wide
          separation are taller than any fixed height worth choosing, and a
          clipped stack hides the two planes a reader most wants — the result
          and what CreditProbe made of it. */}
      <div
        className="relative overflow-y-auto overflow-x-hidden rounded-lg bg-surface-sunken"
        style={{
          perspective: "1400px",
          perspectiveOrigin: "50% 40%",
          maxHeight: 640,
        }}
      >
        <div
          className="mx-auto flex flex-col items-center justify-center gap-1 py-8"
          style={{
            transformStyle: "preserve-3d",
            transform: `rotateX(${tilt}deg) rotateZ(${rotate}deg)`,
            transition: "transform var(--duration-settled) var(--ease-out-quiet)",
            minHeight: planes.length * 62 + spread * 1.1 + 80,
          }}
        >
          {planes.map((plane, index) => {
            const presentation = STATUS[plane.status];
            // A plane in difficulty rises toward the reader. Depth carries the
            // same information the colour and the mark carry, so nobody is
            // relying on any one of the three.
            const lift = presentation.attention ? 26 : 0;
            // `planes` runs interpretation-first, so the depth runs the other
            // way: the data the answer came from sits furthest back, and each
            // stage the analysis passed through steps toward the reader. What
            // that draws is the answer climbing out of the rows.
            const depth = (planes.length - 1 - index) * spread + lift;
            return (
              <div
                key={plane.lane}
                className="relative"
                style={{
                  transform: `translateZ(${depth}px)`,
                  transition: "transform var(--duration-settled) var(--ease-out-quiet)",
                }}
              >
                <Plane
                  plane={plane}
                  selected={selected}
                  onSelect={onSelect}
                  emphasised={presentation.attention}
                />
              </div>
            );
          })}
        </div>
      </div>

      <Controls
        tilt={tilt}
        spread={spread}
        rotate={rotate}
        setTilt={setTilt}
        setSpread={setSpread}
        setRotate={setRotate}
        reset={reset}
      />

      <p className="mt-2 px-1 text-[0.6875rem] text-text-muted">
        Data at the base, CreditProbe&rsquo;s interpretation at the top. A stage
        that needs attention is lifted toward you.{" "}
        <span className="text-text-secondary">
          Audit mode carries the same lineage as a list.
        </span>
      </p>
    </div>
  );
}

interface PlaneModel {
  lane: number;
  label: string;
  nodes: TraceNode[];
  status: ReturnType<typeof worst>;
}

function Plane({
  plane,
  selected,
  onSelect,
  emphasised,
}: {
  plane: PlaneModel;
  selected?: string | null;
  onSelect?: (nodeId: string) => void;
  emphasised: boolean;
}) {
  const presentation = STATUS[plane.status];
  return (
    <div
      className={cn(
        "flex w-[min(46rem,80vw)] items-center gap-3 rounded-lg border px-3 py-2",
        "backdrop-blur-[1px]",
        emphasised
          ? cn(presentation.border, presentation.surface)
          : "border-border bg-surface/85",
      )}
      style={{ boxShadow: "var(--shadow-raised)" }}
    >
      <div className="flex w-40 shrink-0 items-center gap-1.5">
        <span
          aria-hidden
          className={cn(
            "grid size-4 place-items-center rounded-sm text-[0.625rem] font-bold",
            presentation.surface,
            presentation.text,
          )}
        >
          {presentation.mark}
        </span>
        <span className="truncate text-[0.6875rem] font-semibold text-text-secondary">
          {plane.label}
        </span>
      </div>

      <div className="flex min-w-0 flex-wrap gap-1.5">
        {plane.nodes.length === 0 ? (
          <MetadataLabel className="opacity-50">nothing in this stage</MetadataLabel>
        ) : (
          plane.nodes.map((node) => {
            const nodeStatus = STATUS[statusOf(node)];
            const isSelected = selected === node.id;
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => onSelect?.(node.id)}
                title={`${node.label} — ${nodeStatus.label}`}
                className={cn(
                  "max-w-[13rem] truncate rounded border px-2 py-1 text-left text-[0.6875rem]",
                  "transition-colors duration-[--duration-instant]",
                  isSelected
                    ? "border-accent bg-surface-selected text-text-primary"
                    : cn(
                        nodeStatus.attention ? nodeStatus.border : "border-border",
                        "bg-surface text-text-secondary hover:bg-surface-hover",
                      ),
                )}
              >
                {nodeStatus.attention && (
                  <span aria-hidden className={cn("mr-1 font-bold", nodeStatus.text)}>
                    {nodeStatus.mark}
                  </span>
                )}
                {node.label}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}

function Controls({
  tilt,
  spread,
  rotate,
  setTilt,
  setSpread,
  setRotate,
  reset,
}: {
  tilt: number;
  spread: number;
  rotate: number;
  setTilt: (v: number) => void;
  setSpread: (v: number) => void;
  setRotate: (v: number) => void;
  reset: () => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-4 px-1">
      <Slider label="Tilt" value={tilt} min={TILT_MIN} max={TILT_MAX} onChange={setTilt} />
      <Slider
        label="Separation"
        value={spread}
        min={SPREAD_MIN}
        max={SPREAD_MAX}
        onChange={setSpread}
      />
      <Slider label="Rotate" value={rotate} min={-24} max={24} onChange={setRotate} />
      <button
        type="button"
        onClick={reset}
        className={cn(
          "flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.6875rem]",
          "text-text-muted transition-colors hover:bg-surface-hover hover:text-text-secondary",
        )}
      >
        <RotateCcw className="size-3" aria-hidden />
        Reset view
      </button>
      <button
        type="button"
        onClick={() => {
          setTilt(0);
          setRotate(0);
        }}
        title="Look at the stack straight on"
        className={cn(
          "flex items-center gap-1.5 rounded-md px-2 py-1 text-[0.6875rem]",
          "text-text-muted transition-colors hover:bg-surface-hover hover:text-text-secondary",
        )}
      >
        <Maximize2 className="size-3" aria-hidden />
        Flatten to 2D
      </button>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  const id = React.useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-[0.6875rem] text-text-muted">
        {label}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 w-24 cursor-pointer accent-accent"
      />
    </div>
  );
}

/** The planes, base first, in governance order. */
function stack(graph: TraceGraph): PlaneModel[] {
  const byLane = new Map<number, TraceNode[]>();
  for (const node of graph.nodes) {
    const lane = LAYER_LANE[node.type] ?? LAYER_LABELS.length - 1;
    const list = byLane.get(lane) ?? [];
    list.push(node);
    byLane.set(lane, list);
  }
  return LAYER_LABELS.map((label, lane) => {
    const nodes = byLane.get(lane) ?? [];
    return { lane, label, nodes, status: worst(nodes.map(statusOf)) };
  })
    // Reversed so the DOM order is top-to-bottom while `flex-col-reverse`
    // renders the data plane at the base — which keeps the tab order running
    // from the data upward, the same direction the reader reads.
    // Interpretation first, so it is first in the DOM and first in the tab
    // order — the conclusion is what a reader wants, and the data it came from
    // is what they check afterwards.
    .reverse();
}
