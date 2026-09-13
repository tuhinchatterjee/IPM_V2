"use client";

/**
 * A sparkline small enough to put three of them on a customer row.
 *
 * Inline SVG rather than a charting library. Fifty customer cards carrying
 * three Recharts surfaces each is a hundred and fifty ResponsiveContainers on
 * one screen, and the list stops scrolling. This draws one path and, where a
 * threshold matters, one line across it.
 *
 * A point with no value is a GAP, not a zero: a customer with no behavioural
 * score in their first month on book has not scored zero, and drawing it that
 * way would invent a fall.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SparkPoint {
  month: string;
  value: number | null;
}

export function Spark({
  points, label, unit = "", tone = "accent", bands, height = 34,
  width = 120, testId, empty = "no history",
}: {
  points: SparkPoint[];
  label: string;
  unit?: string;
  tone?: "accent" | "negative" | "warning" | "positive";
  /** Horizontal reference lines, in the series' own units. */
  bands?: { value: number; label: string }[];
  height?: number;
  width?: number;
  testId?: string;
  empty?: string;
}) {
  const usable = points.filter((p) => p.value !== null && Number.isFinite(p.value));
  const last = usable.length ? usable[usable.length - 1].value : null;
  const first = usable.length ? usable[0].value : null;
  const moved = last !== null && first !== null ? last - first : null;

  const stroke = {
    accent: "var(--ipm-accent)",
    negative: "var(--ipm-negative)",
    warning: "var(--ipm-warning)",
    positive: "var(--ipm-positive)",
  }[tone];

  const values = usable.map((p) => p.value as number);
  const bandValues = (bands ?? []).map((b) => b.value);
  const low = Math.min(...values, ...bandValues);
  const high = Math.max(...values, ...bandValues);
  const span = high - low || 1;
  const pad = 3;
  const plotH = height - pad * 2;

  const x = (index: number) =>
    points.length <= 1 ? width / 2 : (index / (points.length - 1)) * width;
  const y = (value: number) =>
    pad + plotH - ((value - low) / span) * plotH;

  // One path per unbroken run, so a missing month leaves a gap rather than a
  // line drawn through a value nobody measured.
  const runs: string[] = [];
  let current: string[] = [];
  points.forEach((point, index) => {
    if (point.value === null || !Number.isFinite(point.value)) {
      if (current.length > 1) runs.push(current.join(" "));
      current = [];
      return;
    }
    current.push(`${current.length ? "L" : "M"}${x(index).toFixed(1)},`
                 + `${y(point.value).toFixed(1)}`);
  });
  if (current.length > 1) runs.push(current.join(" "));

  const lastIndex = points.reduce(
    (best, point, index) =>
      point.value !== null && Number.isFinite(point.value) ? index : best, -1);

  return (
    <div className="min-w-0" data-testid={testId}>
      {/* The label sits on its own line rather than beside the figure. Three
          of these across a customer card leaves about eight characters on the
          same row as the number, and "Behavioural" was rendering as
          "BEHAVIO…" on every card in the list. */}
      <p className="truncate text-[9px] font-medium uppercase tracking-[0.06em] text-text-muted">
        {label}
      </p>
      <div className="flex items-baseline justify-between gap-1.5">
        <span className="shrink-0 text-[11px] font-medium tabular-nums text-text-primary">
          {last === null ? "—" : `${last.toLocaleString(undefined, {
            maximumFractionDigits: unit === "%" ? 1 : 0 })}${unit}`}
          {moved !== null && Math.abs(moved) >= 0.05 ? (
            <span className={cn(
              "ml-1 text-[9px]",
              moved > 0 ? "text-negative" : "text-positive",
            )}>
              {moved > 0 ? "+" : ""}{moved.toFixed(unit === "%" ? 1 : 0)}
            </span>
          ) : null}
        </span>
      </div>
      {usable.length ? (
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
             className="mt-0.5 w-full" role="img"
             aria-label={`${label}: ${usable.length} months, latest ${last}`}>
          {(bands ?? []).map((band) => (
            <g key={band.label}>
              <line x1={0} x2={width} y1={y(band.value)} y2={y(band.value)}
                    stroke="var(--ipm-border-strong)" strokeWidth={0.75}
                    strokeDasharray="2 2" />
            </g>
          ))}
          {runs.map((path, index) => (
            <path key={index} d={path} fill="none" stroke={stroke}
                  strokeWidth={1.5} strokeLinecap="round"
                  strokeLinejoin="round" />
          ))}
          {lastIndex >= 0 ? (
            <circle cx={x(lastIndex)}
                    cy={y(points[lastIndex].value as number)} r={2}
                    fill={stroke} />
          ) : null}
        </svg>
      ) : (
        <p className="mt-1 text-[10px] italic text-text-muted">{empty}</p>
      )}
    </div>
  );
}
