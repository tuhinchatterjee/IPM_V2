"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";

import { MetricInfo } from "@/components/metrics/metric-panel";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import type { RenderedPanel } from "@/lib/api";
import { formatMetric } from "@/components/metrics/present";

/**
 * One number on a lens, and everything it needs to defend itself.
 *
 * Three states, and the difference between the second and third is the point:
 *
 *   succeeded    the figure, with its info control
 *   unavailable  a gap in the BOOK — no data for this period, and the tile
 *                says which periods there are
 *   failed       a gap in the PLATFORM
 *
 * A reader told the wrong one of those two wastes an afternoon chasing the
 * wrong people, so they are drawn differently and worded differently.
 *
 * A tile that is not governed or verified carries that label beside it rather
 * than looking exactly like one that is.
 */
export function MetricTile({ panel }: { panel: RenderedPanel }) {
  const metric = panel.metric;
  const title = panel.title || metric?.name || panel.metric_id;

  if (panel.status === "failed") {
    return (
      <Card className="border-negative/40 p-4">
        <p className="text-xs font-medium text-text-secondary">{title}</p>
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-negative">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{panel.error || "This tile could not be produced."}</span>
        </p>
      </Card>
    );
  }

  if (panel.status === "unavailable") {
    return (
      <Card className="border-border p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-medium text-text-secondary">{title}</p>
          {metric && (
            <InfoPopover
              title={metric.name}
              label={`How ${metric.name} is calculated`}
            >
              <MetricInfo metric={metric} calculation={panel.calculation} />
            </InfoPopover>
          )}
        </div>
        <p className="mt-2 text-[22px] font-semibold leading-none text-text-muted">
          —
        </p>
        <p className="mt-2 text-xs leading-relaxed text-text-muted">
          {panel.unavailable ||
            "There is no data for this period. That is a fact about the book, not a failure."}
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 text-xs font-medium text-text-secondary">
          {title}
        </p>
        {metric && (
          <InfoPopover
              title={metric.name}
              label={`How ${metric.name} is calculated`}
            >
            <MetricInfo metric={metric} calculation={panel.calculation} />
          </InfoPopover>
        )}
      </div>

      <p className="mt-2 text-[22px] font-semibold leading-none tabular tracking-tight text-text-primary">
        {formatMetric(panel.value, panel.unit, panel.decimals)}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {panel.period_used && (
          <span className="text-[11px] text-text-muted">
            {panel.period_used}
          </span>
        )}
        {metric && !metric.trustworthy && (
          // A metric nobody has checked must not look like a governed one.
          <Badge variant="warning">{metric.status_label}</Badge>
        )}
        {metric && metric.origin !== "CREDITPROBE_GOVERNED" && (
          <Badge variant="info">{metric.origin_label}</Badge>
        )}
      </div>

      {panel.note && (
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          {panel.note}
        </p>
      )}
    </Card>
  );
}
