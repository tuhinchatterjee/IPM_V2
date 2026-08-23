"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Printer } from "lucide-react";

import { AnalyticalCard, TraceButton } from "@/components/analytics/analytical-card";
import { CategoryBarChart, MatrixHeatmap, TrendChart } from "@/components/analytics/charts";
import { KpiTile, ResultTable, Stat } from "@/components/analytics/primitives";
import { StageCompositionChart } from "@/components/analytics/result-view";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { money, percent } from "@/lib/format";
import { useAnalysis } from "@/lib/hooks";
import type { Row } from "@/lib/api";

/**
 * CRO Portfolio Lens.
 *
 * The monthly executive view, composed entirely from registered analyses. Every
 * tile runs its own analysis, carries its own Trace button, and can be opened
 * on its own page or turned into an investigation — so a figure that prompts a
 * question is one click from the work that answers it.
 */

type Rows = Record<string, string | number | null>[];

function num(values: Record<string, unknown> | undefined, key: string): number | null {
  const v = values?.[key];
  return typeof v === "number" ? v : null;
}

export default function CroLensPage() {
  const summary = useAnalysis("portfolio_summary", { params: { period: "latest" } });
  const stages = useAnalysis("stage_distribution", { params: { period: "latest" } });
  const trend = useAnalysis("portfolio_trend", {});
  const concentration = useAnalysis("sector_concentration", { params: { top_n: 10 } });
  const eclMovement = useAnalysis("ecl_movement", {
    params: { from_period: "previous", to_period: "latest", group_by: "sector" },
  });
  const ratings = useAnalysis("rating_transition_matrix", {
    params: { from_period: "earliest", to_period: "latest" },
  });
  const deteriorating = useAnalysis("top_deteriorating_borrowers", {
    params: { from_period: "previous", to_period: "latest", top_n: 10 },
  });

  const values = summary.data?.result?.values;
  const movement = (values?.movement ?? {}) as Record<string, number>;
  const period = (values?.period as string) ?? "";

  return (
    <div className="space-y-7">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/lenses">
          <ArrowLeft aria-hidden />
          All lenses
        </Link>
      </Button>

      <PageHeader
        title="CRO Portfolio Lens"
        description="The monthly executive view of the wholesale book. Every tile is a governed engine result; every figure is traceable to the data, filters and function version that produced it."
        status="live"
        actions={
          <div className="flex items-center gap-2">
            {period && <Badge variant="outline">{period}</Badge>}
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer aria-hidden />
              Print
            </Button>
          </div>
        }
      />

      {/* --------------------------------------------------------- headline */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-tight text-text-primary">
            Position and movement
          </h2>
          <TraceButton runId={summary.data?.analysis_run_id} />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiTile
            label="Total EAD"
            value={num(values, "total_ead")}
            unit="USD mn"
            change={movement.total_ead ?? null}
            changeUnit="USD mn"
            direction="neutral"
            hint="vs prior period"
            loading={summary.loading}
            emphasis
          />
          <KpiTile
            label="NPL ratio"
            value={num(values, "npl_ratio_pct")}
            unit="%"
            change={movement.npl_ratio_pct ?? null}
            changeUnit="pp"
            hint="vs prior period"
            loading={summary.loading}
            emphasis
          />
          <KpiTile
            label="Total ECL"
            value={num(values, "total_ecl")}
            unit="USD mn"
            change={movement.total_ecl ?? null}
            changeUnit="USD mn"
            hint="vs prior period"
            loading={summary.loading}
            emphasis
          />
          <KpiTile
            label="ECL coverage"
            value={num(values, "ecl_coverage_pct")}
            unit="%"
            change={movement.ecl_coverage_pct ?? null}
            changeUnit="pp"
            hint="vs prior period"
            loading={summary.loading}
            emphasis
          />
        </div>
      </section>

      {/* ------------------------------------------------------- stage split */}
      <AnalyticalCard
        title="IFRS 9 stage distribution"
        description="Exposure and coverage by stage"
        analysisId="stage_distribution"
        run={stages.data}
        loading={stages.loading}
        error={stages.error}
        onRetry={stages.reload}
        minHeight={230}
      >
        {stages.data && (
          <div className="space-y-4">
            <StageCompositionChart run={stages.data} />
            <div className="grid gap-4 sm:grid-cols-3">
              {(stages.data.result?.rows ?? []).map((row) => (
                <div
                  key={String(row.ifrs9_stage)}
                  className="rounded-md border border-border bg-surface-sunken p-3"
                >
                  <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
                    Stage {row.ifrs9_stage}
                  </p>
                  <p className="mt-1 text-lg font-semibold text-text-primary tabular">
                    {money(Number(row.ead), 0)}mn
                  </p>
                  <div className="mt-1.5 flex gap-4 text-xs text-text-muted">
                    <span>{percent(Number(row.ead_pct))} of book</span>
                    <span>{percent(Number(row.coverage_pct))} covered</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </AnalyticalCard>

      {/* ------------------------------------------------------------ trends */}
      <div className="grid gap-4 xl:grid-cols-2">
        <AnalyticalCard
          title="Portfolio trend"
          description="Exposure and impairment across every period"
          analysisId="portfolio_trend"
          run={trend.data}
          loading={trend.loading}
          error={trend.error}
          onRetry={trend.reload}
          minHeight={260}
        >
          {trend.data?.result && (
            <TrendChart
              data={trend.data.result.rows as Rows}
              xKey="period"
              series={[
                { key: "total_ead", label: "Total EAD", slot: 0 },
                { key: "total_ecl", label: "Total ECL", slot: 1 },
              ]}
              units={{ total_ead: "USD mn", total_ecl: "USD mn" }}
              height={220}
            />
          )}
        </AnalyticalCard>

        <AnalyticalCard
          title="Stage 2 trend"
          description="Share of exposure under significant increase in credit risk"
          analysisId="portfolio_trend"
          run={trend.data}
          loading={trend.loading}
          error={trend.error}
          onRetry={trend.reload}
          minHeight={260}
        >
          {trend.data?.result && (
            <>
              <TrendChart
                data={trend.data.result.rows as Rows}
                xKey="period"
                area
                series={[{ key: "stage2_pct", label: "Stage 2 share", slot: 4 }]}
                units={{ stage2_pct: "%" }}
                height={190}
              />
              <div className="mt-3 flex gap-6 border-t border-border pt-3">
                <Stat
                  label="Opening"
                  value={percent(Number(trend.data.result.rows[0]?.stage2_pct))}
                />
                <Stat
                  label="Closing"
                  value={percent(
                    Number(trend.data.result.rows[trend.data.result.rows.length - 1]?.stage2_pct),
                  )}
                  tone="negative"
                />
                <Stat
                  label="Change"
                  value={`${
                    (
                      (trend.data.result.values.change as Record<string, number>)?.stage2_pct ?? 0
                    ) > 0
                      ? "+"
                      : ""
                  }${percent(
                    (trend.data.result.values.change as Record<string, number>)?.stage2_pct,
                  )}`}
                  tone="negative"
                />
              </div>
            </>
          )}
        </AnalyticalCard>
      </div>

      {/* --------------------------------------------- concentration + drivers */}
      <div className="grid gap-4 xl:grid-cols-2">
        <AnalyticalCard
          title="Sector concentration"
          description="Exposure by sector, with single-name risk inside each"
          analysisId="sector_concentration"
          run={concentration.data}
          loading={concentration.loading}
          error={concentration.error}
          onRetry={concentration.reload}
          minHeight={330}
        >
          {concentration.data?.result && (
            <div className="space-y-3">
              <div className="flex gap-6">
                <Stat
                  label="Herfindahl index"
                  value={money(num(concentration.data.result.values, "hhi"), 0)}
                />
                <Stat
                  label="Top 5 share"
                  value={percent(num(concentration.data.result.values, "top_5_pct"))}
                />
              </div>
              <CategoryBarChart
                data={concentration.data.result.rows as Rows}
                xKey="sector"
                series={[{ key: "ead", label: "EAD", slot: 0 }]}
                units={{ ead: "USD mn" }}
                height={260}
              />
            </div>
          )}
        </AnalyticalCard>

        <AnalyticalCard
          title="Sector deterioration"
          description="Contribution to the change in ECL, by sector"
          analysisId="ecl_movement"
          run={eclMovement.data}
          loading={eclMovement.loading}
          error={eclMovement.error}
          onRetry={eclMovement.reload}
          minHeight={330}
        >
          {eclMovement.data?.result && (
            <div className="space-y-3">
              <div className="flex gap-6">
                <Stat
                  label="Opening ECL"
                  value={`${money(num(eclMovement.data.result.values, "opening_ecl"), 1)}mn`}
                />
                <Stat
                  label="Closing ECL"
                  value={`${money(num(eclMovement.data.result.values, "closing_ecl"), 1)}mn`}
                  tone="negative"
                />
              </div>
              <ResultTable
                rows={(eclMovement.data.result.values.breakdown ?? []) as Row[]}
                units={{ ecl_change: "USD mn" }}
                maxRows={8}
                emptyMessage="No sector attribution available for this period."
              />
            </div>
          )}
        </AnalyticalCard>
      </div>

      {/* ------------------------------------------------ rating transitions */}
      <AnalyticalCard
        title="Rating transition summary"
        description="Empirical migration across the full history, measured facility by facility"
        analysisId="rating_transition_matrix"
        run={ratings.data}
        loading={ratings.loading}
        error={ratings.error}
        onRetry={ratings.reload}
        minHeight={300}
      >
        {ratings.data?.result && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-6">
              <Stat
                label="Upgraded"
                value={percent(
                  (ratings.data.result.values.movement as Record<string, number>)?.upgraded_pct,
                )}
                tone="positive"
              />
              <Stat
                label="Stable"
                value={percent(
                  (ratings.data.result.values.movement as Record<string, number>)?.stable_pct,
                )}
                tone="muted"
              />
              <Stat
                label="Downgraded"
                value={percent(
                  (ratings.data.result.values.movement as Record<string, number>)?.downgraded_pct,
                )}
                tone="negative"
              />
              <Stat
                label="Interval"
                value={
                  <span className="text-sm font-normal text-text-secondary">
                    {String(ratings.data.result.values.interval ?? "—")}
                  </span>
                }
              />
            </div>
            <MatrixHeatmap
              categories={(ratings.data.result.values.grades as string[]) ?? []}
              cells={Object.fromEntries(
                (ratings.data.result.rows ?? []).map((r) => [
                  `${r.from}|${r.to}`,
                  Number(r.row_pct ?? 0),
                ]),
              )}
            />
          </div>
        )}
      </AnalyticalCard>

      {/* --------------------------------------------- deteriorating borrowers */}
      <AnalyticalCard
        title="Top deteriorating borrowers"
        description="Ranked by a composite of ECL increase, stage migration, downgrade and delinquency"
        analysisId="top_deteriorating_borrowers"
        run={deteriorating.data}
        loading={deteriorating.loading}
        error={deteriorating.error}
        onRetry={deteriorating.reload}
        minHeight={320}
      >
        {deteriorating.data?.result && (
          <ResultTable
            rows={deteriorating.data.result.rows as Row[]}
            units={{ ead: "USD mn", ecl_change: "USD mn" }}
            columns={[
              "borrower_name",
              "sector",
              "ead",
              "ecl_change",
              "stage_change",
              "notch_change",
              "reasons",
            ]}
            renderCell={(column, value) =>
              column === "reasons" ? (
                <span className="block max-w-[24rem] text-xs text-text-muted">
                  {String(value)}
                </span>
              ) : undefined
            }
          />
        )}
      </AnalyticalCard>

      <p className="border-t border-border pt-4 text-xs text-text-muted">
        Seven analyses, all IPM Certified, executed against the governed analytical layer.
        Portfolio figures are synthetic demonstration data and are labelled as such in the
        data catalogue.
      </p>
    </div>
  );
}
