"use client";

import * as React from "react";

import type { DimensionCell } from "@/lib/api";
import { cn } from "@/lib/utils";

import { cellWord, scoreText } from "./present";

/**
 * The six Intelligence Dimensions, as screen furniture. Part F, §178-§189.
 *
 * Why a strip of six rather than a score
 * ---------------------------------------
 * §178 replaced a flat wall of ninety-odd checks, and the replacement is NOT
 * one number — a number averages away the dimension that failed, which is
 * always the dimension the reader needed. Six fixed cells in a fixed order
 * lets somebody scan forty Investigations and see which column is red.
 *
 * The fourth state is the important one
 * ---------------------------------------
 * PASSED, WARNING, FAILED and UNMEASURED. §183 is emphatic that a check
 * nothing ran is not a check that passed, so UNMEASURED renders as its own
 * visibly-absent state rather than as a neutral tick. A reader must be able
 * to tell "we checked and it was fine" from "we did not check".
 *
 * Colour is never the only signal: every cell carries its two-letter code,
 * and its title says the state in words.
 */

const CELL: Record<DimensionCell["state"], string> = {
  PASSED: "border-status-positive/40 bg-status-positive/10 text-text-primary",
  WARNING: "border-status-warning/50 bg-status-warning/10 text-text-primary",
  FAILED: "border-status-negative/50 bg-status-negative/10 text-text-primary",
  // Dashed and empty on purpose. It should look like a gap, because it is.
  UNMEASURED: "border-dashed border-border bg-transparent text-text-tertiary",
};

export function DimensionStrip({
  cells,
  className,
}: {
  cells: DimensionCell[];
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {cells.map((cell) => (
        <span
          key={cell.dimension}
          title={`${cell.dimension.replaceAll("_", " ").toLowerCase()} — ${cellWord(cell)}`}
          className={cn(
            "inline-flex h-5 min-w-[1.75rem] items-center justify-center rounded border px-1 text-[10px] font-medium tabular-nums",
            CELL[cell.state],
          )}
        >
          {cell.short}
        </span>
      ))}
    </div>
  );
}

/**
 * The one place the assurance figure is rendered.
 *
 * §184: "Do not display 'Accuracy 96%' for a live Investigation with no
 * independent reference." The label comes from the payload rather than from
 * a string here, so the backend's constant is the only definition of what
 * this number is called — and a null score renders the status in words
 * instead of a zero, because a zero reads as a very bad score rather than as
 * no score at all.
 */
export function AssuranceFigure({
  score,
  label,
  status,
  className,
}: {
  score: number | null;
  label: string;
  status: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "tabular-nums",
        score === null ? "text-text-secondary" : "text-text-primary",
        className,
      )}
    >
      {scoreText(score, label, status)}
    </span>
  );
}
