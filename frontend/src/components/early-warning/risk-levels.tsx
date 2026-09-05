"use client";

import * as React from "react";

import { Card } from "@/components/ui/card";
import type { EarlyWarningDashboard } from "@/lib/api";
import * as ew from "@/lib/early-warning-format";
import { cn } from "@/lib/utils";

/**
 * The book split by overall Early Warning risk. Sections 11B and 11G.
 *
 * Three cards, and each one says what the level MEANS rather than only how
 * many names are in it. A card reading "898 High" is a number; a card reading
 * "898 High — something serious is established and the rest of the credit
 * picture agrees" is an answer, and the reader can disagree with it.
 *
 * The rule is printed underneath, because the first question anybody asks a
 * risk level is how it was decided, and a level nobody can account for is a
 * level nobody acts on.
 */

export const LEVEL_TONE: Record<string, string> = {
  HIGH: "border-negative/40 bg-negative-muted",
  MEDIUM: "border-warning/40 bg-warning-muted",
  LOW: "border-border",
};

export const LEVEL_INK: Record<string, string> = {
  HIGH: "text-negative",
  MEDIUM: "text-warning",
  LOW: "text-text-secondary",
};

export function RiskLevelBadge({ level }: { level: string }) {
  if (!level) return null;
  return (
    <span
      className={cn(
        "rounded border px-1.5 py-0.5 text-[11px] font-medium",
        LEVEL_TONE[level] ?? LEVEL_TONE.LOW,
        LEVEL_INK[level] ?? LEVEL_INK.LOW,
      )}
    >
      {level.charAt(0) + level.slice(1).toLowerCase()} risk
    </span>
  );
}

export function RiskLevels({
  levels,
  currency = "SAR",
}: {
  levels: EarlyWarningDashboard["risk_levels"] | undefined;
  currency?: string;
}) {
  if (!levels?.levels?.length) return null;
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Where the book sits</h2>
        <p className="text-[11px] text-text-muted">
          Owned by {levels.owner} · version {levels.version}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {levels.levels.map((entry) => (
          <Card
            key={entry.level}
            className={cn("p-4", LEVEL_TONE[entry.level] ?? LEVEL_TONE.LOW)}
          >
            <p
              className={cn(
                "text-xs font-medium uppercase tracking-wide",
                LEVEL_INK[entry.level] ?? LEVEL_INK.LOW,
              )}
            >
              {entry.level}
            </p>
            <p className="mt-2 text-2xl font-medium tabular-nums">
              {entry.borrowers.toLocaleString()}
              <span className="ml-2 text-sm font-normal text-text-muted">
                {entry.share.toFixed(1)}%
              </span>
            </p>
            <p className="mt-1 text-xs text-text-secondary tabular-nums">
              {ew.showValue(entry.exposure, "money", currency)} of exposure
            </p>
            <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
              {entry.means}
            </p>
          </Card>
        ))}
      </div>

      <Card className="p-4">
        <p className="text-xs font-medium">How the level is decided</p>
        <dl className="mt-2 grid gap-2 sm:grid-cols-2">
          {["gravity", "corroboration", "medium", "low"].map((key) =>
            levels.rule?.[key] ? (
              <div key={key}>
                <dt className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
                  {key}
                </dt>
                <dd className="mt-0.5 text-xs leading-relaxed text-text-secondary">
                  {levels.rule[key]}
                </dd>
              </div>
            ) : null,
          )}
        </dl>
        <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
          {levels.statement}
        </p>
      </Card>
    </section>
  );
}
