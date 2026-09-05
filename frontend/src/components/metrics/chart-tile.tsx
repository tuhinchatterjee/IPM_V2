"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";

import { MetricInfo } from "@/components/metrics/metric-panel";
import { formatMetric } from "@/components/metrics/present";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import type { ChartComparison, ChartPoint, RenderedPanel } from "@/lib/api";

/**
 * One metric across one dimension, drawn.
 *
 * The same three states as a metric tile — succeeded, unavailable, failed —
 * because a reader should not have to learn a second vocabulary for a chart.
 *
 * Bars rather than a charting library, deliberately. Every value on screen is
 * a governed calculation the backend already did; the only thing left to do
 * here is give each one a width, and a dependency that draws its own axes has
 * a way of quietly rescaling, clipping or interpolating them. What is drawn
 * below is exactly what came back, and the numbers are printed beside the bars
 * so nobody has to read a length to know a value.
 */
export function ChartTile({ panel }: { panel: RenderedPanel }) {
  const metric = panel.metric;
  const title =
    panel.title ||
    `${panel.series_label ?? metric?.name ?? panel.metric_id} by ${
      panel.dimension_label ?? panel.dimension ?? ""
    }`;

  if (panel.status === "failed") {
    return (
      <Card className="border-negative/40 p-4">
        <p className="text-xs font-medium text-text-secondary">{title}</p>
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-negative">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{panel.error || "This chart could not be produced."}</span>
        </p>
      </Card>
    );
  }

  const points = panel.points ?? [];

  return (
    <Card className="p-4" data-testid="chart-tile">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-text-secondary">{title}</p>
          <p className="mt-0.5 text-[10px] text-text-muted">
            {panel.period_used || panel.period}
            {panel.comparison ? ` vs ${panel.comparison.period}` : ""}
          </p>
        </div>
        {metric && (
          <InfoPopover label={`How ${metric.name} is calculated`}>
            <MetricInfo metric={metric} />
            <ChartLineage panel={panel} />
          </InfoPopover>
        )}
      </header>

      {panel.status === "unavailable" ? (
        <p className="mt-3 text-xs leading-relaxed text-text-muted">
          {panel.unavailable ||
            "There is nothing to draw for this period. That is a gap in the " +
              "book rather than a fault in the platform."}
        </p>
      ) : (
        <Bars
          points={points}
          comparison={panel.comparison ?? null}
          unit={panel.unit ?? "number"}
          decimals={panel.decimals ?? 2}
        />
      )}

      {(panel.chart_notes ?? []).length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-border/60 pt-2">
          {(panel.chart_notes ?? []).map((note) => (
            <li key={note} className="text-[10px] leading-relaxed text-text-muted">
              {note}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * The bars themselves.
 *
 * Widths are shares of the largest absolute value in the series, so a chart
 * containing a negative number does not draw it off the end. Where a
 * comparison is present its bar sits under the primary one, in a lighter
 * weight, and the change is printed rather than implied by the gap.
 */
export function Bars({
  points,
  comparison,
  unit,
  decimals,
}: {
  points: ChartPoint[];
  comparison: ChartComparison | null;
  unit: string;
  decimals: number;
}) {
  const values = points
    .map((point) => point.value)
    .filter((value): value is number => value !== null);
  const others = (comparison?.points ?? [])
    .map((point) => point.value)
    .filter((value): value is number => value !== null);
  const largest = Math.max(1e-12, ...[...values, ...others].map(Math.abs));
  const before = new Map(
    (comparison?.points ?? []).map((point) => [point.label, point]),
  );

  return (
    <ul className="mt-3 space-y-2.5">
      {points.map((point) => {
        const previous = before.get(point.label);
        return (
          <li key={point.label}>
            <div className="flex items-baseline justify-between gap-3">
              <span className="truncate text-xs text-text-secondary">
                {point.label}
              </span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-text-primary">
                {point.value === null
                  ? "—"
                  : formatMetric(point.value, unit, decimals)}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-muted">
              <div
                className="h-full rounded-full bg-accent"
                style={{
                  width:
                    point.value === null
                      ? "0%"
                      : `${(Math.abs(point.value) / largest) * 100}%`,
                }}
              />
            </div>
            {previous && (
              <div className="mt-1 flex items-baseline justify-between gap-3">
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-muted">
                  <div
                    className="h-full rounded-full bg-text-muted/40"
                    style={{
                      width:
                        previous.value === null
                          ? "0%"
                          : `${(Math.abs(previous.value) / largest) * 100}%`,
                    }}
                  />
                </div>
                <span className="shrink-0 font-mono text-[10px] tabular-nums text-text-muted">
                  {previous.change === null
                    ? "no comparison"
                    : `${previous.change >= 0 ? "+" : ""}${formatMetric(
                        previous.change,
                        unit,
                        decimals,
                      )}`}
                </span>
              </div>
            )}
            {point.unavailable && (
              <p className="mt-0.5 text-[10px] text-text-muted">
                {point.unavailable}
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Where the bars came from: the dataset, the filters, the query, the run. */
function ChartLineage({ panel }: { panel: RenderedPanel }) {
  const lineage = panel.lineage;
  if (!lineage) return null;
  const filters = Object.entries(lineage.filters ?? {});
  return (
    <div className="mt-4 border-t border-border/60 pt-3">
      <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
        This chart
      </p>
      <dl className="mt-2 space-y-1 text-[11px]">
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-text-muted">Grouped by</dt>
          <dd className="text-text-secondary">
            {panel.dimension_label || panel.dimension}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-text-muted">Read from</dt>
          <dd className="font-mono text-text-secondary">{lineage.dataset}</dd>
        </div>
        {filters.length > 0 && (
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-text-muted">Filtered to</dt>
            <dd className="text-text-secondary">
              {filters.map(([key, value]) => `${key} = ${String(value)}`).join("; ")}
            </dd>
          </div>
        )}
        {typeof panel.groups_found === "number" && (
          <div className="flex gap-2">
            <dt className="w-24 shrink-0 text-text-muted">Groups</dt>
            <dd className="text-text-secondary">
              {(panel.points ?? []).length} drawn of {panel.groups_found} found
            </dd>
          </div>
        )}
        <div className="flex gap-2">
          <dt className="w-24 shrink-0 text-text-muted">Run</dt>
          <dd className="font-mono text-text-secondary">{lineage.run_id}</dd>
        </div>
      </dl>
      {lineage.sql && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10px] text-text-muted">
            The query that produced these numbers
          </summary>
          <pre className="mt-1.5 max-h-56 overflow-auto rounded bg-surface-muted p-2 font-mono text-[10px] leading-relaxed text-text-secondary">
            {lineage.sql}
          </pre>
        </details>
      )}
    </div>
  );
}
