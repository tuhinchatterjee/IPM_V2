"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type EarlyWarningV2BorrowerRow,
  type EarlyWarningV2Overview,
  type EarlyWarningV2Segments,
} from "@/lib/api";
import { money } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { borrower360Href } from "@/lib/borrower-link";
import Link from "next/link";

/**
 * Early Warning V2 — the consolidated portfolio view.
 *
 * This is the ONE canonical Early Warning experience (spec Section D): the
 * classifier/trigger/accelerator/network engine in backend/early_warning/
 * scored against the actual workbook mathematics, not the legacy fitted
 * Forward Risk Signal or the separate rule-based taxonomy shown further
 * down this page while that migration completes.
 */

const BAND_VARIANT: Record<string, "negative" | "warning" | "info" | "positive" | "default"> = {
  VERY_HIGH: "negative",
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "default",
  VERY_LOW: "positive",
};

const BAND_LABEL: Record<string, string> = {
  VERY_HIGH: "Very High",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  VERY_LOW: "Very Low",
};

function BandBadge({ band }: { band: string }) {
  return (
    <Badge variant={BAND_VARIANT[band] ?? "default"}>{BAND_LABEL[band] ?? band}</Badge>
  );
}

export function EarlyWarningV2Portfolio() {
  const overview = useAsync<EarlyWarningV2Overview>(
    () => api.earlyWarningV2Overview(),
    [],
  );
  const segments = useAsync<EarlyWarningV2Segments>(
    () => api.earlyWarningV2Segments(),
    [],
  );
  const [filterBand, setFilterBand] = React.useState<string | null>(null);

  if (overview.loading) {
    return <Skeleton className="h-96 w-full" />;
  }
  if (overview.error || !overview.data) {
    return (
      <EmptyState
        title="Early Warning V2 data is not built yet"
        description="Run scripts/build_corporate_universe.py then scripts/build_early_warning_v2.py to generate the governed monthly domain."
      />
    );
  }

  const { summary, top_high_risk } = overview.data;
  const filteredRows = filterBand
    ? top_high_risk.filter((r: EarlyWarningV2BorrowerRow) => r.ews_band === filterBand)
    : top_high_risk;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>Portfolio EWS, exposure-weighted</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {summary.portfolio_ews.toFixed(1)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>Borrowers at High or above</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {summary.high_plus_count}
            <span className="ml-1 text-sm font-normal text-text-secondary">
              of {summary.borrower_count}
            </span>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>Exposure at High or above</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {money(summary.high_plus_exposure)}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1">
            <CardTitle>Total exposure</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">
            {money(summary.total_exposure)}
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-wrap gap-2">
        {summary.severity_distribution.map((band) => (
          <button
            key={band.band}
            type="button"
            onClick={() =>
              setFilterBand((current) => (current === band.band ? null : band.band))
            }
            className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
              filterBand === band.band
                ? "border-accent bg-accent-muted"
                : "border-border bg-surface hover:border-border-strong"
            }`}
          >
            <div className="flex items-center gap-2 font-medium">
              <BandBadge band={band.band} />
              <span>{band.borrower_count} ({band.borrower_pct.toFixed(1)}%)</span>
            </div>
            <div className="text-text-secondary">
              {money(band.exposure)} · {band.exposure_pct.toFixed(1)}% of exposure
            </div>
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            {filterBand ? `${BAND_LABEL[filterBand]} risk borrowers` : "Top high-risk borrowers"}
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="py-1.5 pr-3">Customer</th>
                <th className="py-1.5 pr-3">Segment</th>
                <th className="py-1.5 pr-3">Exposure</th>
                <th className="py-1.5 pr-3">DPD</th>
                <th className="py-1.5 pr-3">EWS</th>
                <th className="py-1.5 pr-3">T&amp;A</th>
                <th className="py-1.5 pr-3">Classifier</th>
                <th className="py-1.5 pr-3">Dominant driver</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row: EarlyWarningV2BorrowerRow) => (
                <tr key={row.customer_id} className="border-b border-border/60">
                  <td className="py-1.5 pr-3">
                    <Link
                      href={borrower360Href(row.customer_id)}
                      className="font-medium text-accent hover:underline"
                    >
                      {row.customer_name}
                    </Link>
                  </td>
                  <td className="py-1.5 pr-3 text-text-secondary">{row.segment}</td>
                  <td className="py-1.5 pr-3">{money(row.exposure)}</td>
                  <td className="py-1.5 pr-3">{row.dpd}</td>
                  <td className="py-1.5 pr-3">
                    <div className="flex items-center gap-1.5">
                      <BandBadge band={row.ews_band} />
                      <span className="text-text-secondary">{row.ews_score.toFixed(1)}</span>
                    </div>
                  </td>
                  <td className="py-1.5 pr-3 text-text-secondary">
                    {row.ta_band} ({row.ta_score.toFixed(1)})
                  </td>
                  <td className="py-1.5 pr-3 text-text-secondary">
                    {row.classifier_band} ({row.classifier_score.toFixed(1)})
                  </td>
                  <td className="py-1.5 pr-3 text-text-secondary">
                    {row.dominant_driver ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredRows.length === 0 && (
            <p className="py-4 text-center text-sm text-text-secondary">
              No borrowers in this band.
            </p>
          )}
        </CardContent>
      </Card>

      {segments.data && (
        <Card>
          <CardHeader>
            <CardTitle>By segment</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="py-1.5 pr-3">Segment</th>
                  <th className="py-1.5 pr-3">Borrowers</th>
                  <th className="py-1.5 pr-3">Exposure</th>
                  <th className="py-1.5 pr-3">Portfolio EWS</th>
                  <th className="py-1.5 pr-3">High+</th>
                </tr>
              </thead>
              <tbody>
                {segments.data.segments.map((seg) => (
                  <tr key={seg.segment} className="border-b border-border/60">
                    <td className="py-1.5 pr-3 font-medium">{seg.segment}</td>
                    <td className="py-1.5 pr-3">{seg.borrower_count}</td>
                    <td className="py-1.5 pr-3">{money(seg.exposure)}</td>
                    <td className="py-1.5 pr-3">{seg.portfolio_ews.toFixed(1)}</td>
                    <td className="py-1.5 pr-3">{seg.high_plus_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
