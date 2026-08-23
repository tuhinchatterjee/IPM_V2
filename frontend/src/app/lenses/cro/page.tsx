"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, ArrowRight, GitBranch, Printer } from "lucide-react";

import { TraceButton } from "@/components/analytics/analytical-card";
import {
  CategoryBarChart,
  DivergingBarChart,
  TrendChart,
} from "@/components/analytics/charts";
import { KpiTile, ResultTable } from "@/components/analytics/primitives";
import { StageCompositionChart } from "@/components/analytics/result-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { AnalysisRunResponse, Row } from "@/lib/api";
import { byUnit, money, percent } from "@/lib/format";
import { useAnalysis } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * CRO Portfolio Lens.
 *
 * Structured as an executive paper, not a dashboard. It answers five questions
 * in the order a board asks them:
 *
 *   1  Where does the portfolio stand?
 *   2  What changed?
 *   3  Where is risk concentrated?
 *   4  What is deteriorating?
 *   5  Which obligors require attention?
 *
 * Each section opens with a headline sentence. Every headline is assembled from
 * figures the engine returned for that section — the wording changes with the
 * data, and where the engine returned nothing the section says so. Nothing here
 * is a conclusion IPM invented, and no figure on this page was calculated by the
 * front end.
 */

type Rows = Record<string, string | number | null>[];

function num(values: Record<string, unknown> | undefined, key: string): number | null {
  const v = values?.[key];
  return typeof v === "number" ? v : null;
}

/** "risen" / "fallen" / "held steady", from a movement the engine reported. */
function moved(value: number | null, up = "risen", down = "fallen", flat = "held steady"): string {
  if (value === null) return flat;
  if (value > 0) return up;
  if (value < 0) return down;
  return flat;
}

export default function CroLensPage() {
  const summary = useAnalysis("portfolio_summary", {
    params: { period: "latest", compare_period: "previous" },
  });
  const stages = useAnalysis("stage_distribution", { params: { period: "latest" } });
  const trend = useAnalysis("portfolio_trend", {});
  const concentration = useAnalysis("sector_concentration", { params: { top_n: 10 } });
  const eclMovement = useAnalysis("ecl_movement", {
    params: { from_period: "previous", to_period: "latest", group_by: "sector" },
  });
  const migration = useAnalysis("stage_migration", {
    params: { from_period: "previous", to_period: "latest", basis: "ead" },
  });
  const deteriorating = useAnalysis("top_deteriorating_borrowers", {
    params: { from_period: "previous", to_period: "latest", top_n: 10 },
  });

  const values = summary.data?.result?.values;
  const movement = (values?.movement ?? {}) as Record<string, number>;
  const period = (values?.period as string) ?? "";
  const compare = (values?.compare_period as string) ?? "the prior period";

  return (
    <div className="space-y-10">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/lenses">
          <ArrowLeft aria-hidden />
          All lenses
        </Link>
      </Button>

      {/* ------------------------------------------------------------ masthead */}
      <header className="border-b border-border pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-text-muted">
              Executive review
            </p>
            <h1 className="mt-2 text-[30px] font-semibold leading-tight tracking-tight text-text-primary">
              CRO Portfolio Lens
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
              The wholesale book as at {period || "the latest reporting period"}, against{" "}
              {compare}. Every figure is a governed engine result and carries the Trace that
              produced it.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {period && <Badge variant="outline">{period}</Badge>}
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer aria-hidden />
              Print
            </Button>
          </div>
        </div>
      </header>

      {/* ------------------------------------------------- 1 · portfolio health */}
      <Chapter
        number="01"
        title="Portfolio health"
        run={summary.data}
        loading={summary.loading}
        error={summary.error}
        headline={
          values
            ? `The book stands at ${money(num(values, "total_ead"), 0)}mn of exposure, carried at ` +
              `${percent(num(values, "ecl_coverage_pct"))} coverage, with ` +
              `${percent(num(values, "npl_ratio_pct"))} non-performing.`
            : null
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiTile
            label="Total EAD"
            value={num(values, "total_ead")}
            unit="USD mn"
            change={movement.total_ead ?? null}
            changeUnit="USD mn"
            direction="neutral"
            hint={`vs ${compare}`}
            loading={summary.loading}
            emphasis
          />
          <KpiTile
            label="NPL ratio"
            value={num(values, "npl_ratio_pct")}
            unit="%"
            change={movement.npl_ratio_pct ?? null}
            changeUnit="pp"
            hint={`vs ${compare}`}
            loading={summary.loading}
            emphasis
          />
          <KpiTile
            label="Total ECL"
            value={num(values, "total_ecl")}
            unit="USD mn"
            change={movement.total_ecl ?? null}
            changeUnit="USD mn"
            hint={`vs ${compare}`}
            loading={summary.loading}
            emphasis
          />
          <KpiTile
            label="ECL coverage"
            value={num(values, "ecl_coverage_pct")}
            unit="%"
            change={movement.ecl_coverage_pct ?? null}
            changeUnit="pp"
            hint={`vs ${compare}`}
            loading={summary.loading}
            emphasis
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr]">
          <Panel
            title="IFRS 9 staging"
            hint="Exposure and coverage by stage"
            run={stages.data}
            loading={stages.loading}
          >
            {stages.data && <StageCompositionChart run={stages.data} />}
          </Panel>
          <Panel
            title="Portfolio quality"
            hint="Exposure-weighted, as the engine reported it"
            run={summary.data}
            loading={summary.loading}
          >
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
              {(
                [
                  ["weighted_pd_pct", "Weighted PD", "%"],
                  ["weighted_lgd_pct", "Weighted LGD", "%"],
                  ["weighted_utilisation_pct", "Utilisation", "%"],
                  ["stage2_pct", "Stage 2 share", "%"],
                  ["stage3_pct", "Stage 3 share", "%"],
                  ["watchlist_ead", "Watchlist EAD", "USD mn"],
                  ["total_collateral", "Collateral", "USD mn"],
                  ["macro_overlay", "Macro overlay", "USD mn"],
                ] as const
              ).map(([key, label, unit]) => (
                <div key={key} className="flex items-baseline justify-between gap-2 border-b border-border pb-1.5">
                  <dt className="text-xs text-text-muted">{label}</dt>
                  <dd className="text-sm font-medium text-text-primary tabular">
                    {byUnit(num(values, key), unit)}
                  </dd>
                </div>
              ))}
            </dl>
          </Panel>
        </div>
      </Chapter>

      {/* --------------------------------------------------------- 2 · what changed */}
      <Chapter
        number="02"
        title="What changed"
        run={trend.data}
        loading={trend.loading}
        error={trend.error}
        headline={(() => {
          const change = (trend.data?.result?.values.change ?? null) as Record<string, number> | null;
          if (!change) return null;
          const first = String(trend.data?.result?.values.first_period ?? "");
          const last = String(trend.data?.result?.values.last_period ?? "");
          return (
            `Across the ${trend.data?.result?.rows.length ?? 0} periods from ${first} to ${last}, ` +
            `ECL coverage has ${moved(change.ecl_coverage_pct)} by ` +
            `${Math.abs(change.ecl_coverage_pct).toFixed(2)}pp and the Stage 2 share has ` +
            `${moved(change.stage2_pct)} by ${Math.abs(change.stage2_pct).toFixed(2)}pp.`
          );
        })()}
      >
        <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <Panel
            title="Coverage and staging over time"
            hint="Every available reporting period"
            run={trend.data}
            loading={trend.loading}
          >
            {trend.data?.result && (
              <TrendChart
                data={trend.data.result.rows as Rows}
                xKey="period"
                series={[
                  { key: "ecl_coverage_pct", label: "ECL coverage", slot: 0 },
                  { key: "stage2_pct", label: "Stage 2 share", slot: 1 },
                  { key: "stage3_pct", label: "Stage 3 share", slot: 2 },
                ]}
                units={{ ecl_coverage_pct: "%", stage2_pct: "%", stage3_pct: "%" }}
                height={250}
              />
            )}
          </Panel>
          <Panel
            title="Stage migration"
            hint={`Exposure that moved between stages since ${compare}`}
            run={migration.data}
            loading={migration.loading}
          >
            {migration.data?.result && (
              <MigrationSplit run={migration.data} />
            )}
          </Panel>
        </div>
      </Chapter>

      {/* ------------------------------------------ 3 · where risk is concentrated */}
      <Chapter
        number="03"
        title="Where risk is concentrated"
        run={concentration.data}
        loading={concentration.loading}
        error={concentration.error}
        headline={(() => {
          const v = concentration.data?.result?.values;
          const rows = (concentration.data?.result?.rows ?? []) as Row[];
          if (!v || rows.length === 0) return null;
          return (
            `The five largest sectors hold ${percent(num(v, "top_5_pct"), 1)} of exposure, ` +
            `led by ${String(rows[0].sector)} at ${money(Number(rows[0].ead), 0)}mn ` +
            `(${percent(Number(rows[0].ead_pct), 1)} of the book).`
          );
        })()}
      >
        <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
          <Panel
            title="Exposure by sector"
            hint="Largest first"
            run={concentration.data}
            loading={concentration.loading}
          >
            {concentration.data?.result && (
              <CategoryBarChart
                data={concentration.data.result.rows as Rows}
                xKey="sector"
                series={[{ key: "ead", label: "EAD", slot: 0 }]}
                units={{ ead: "USD mn" }}
                horizontal
                height={300}
              />
            )}
          </Panel>
          <Panel
            title="Quality inside each concentration"
            hint="A large exposure and a poor one are different problems"
            run={concentration.data}
            loading={concentration.loading}
          >
            {concentration.data?.result && (
              <ResultTable
                rows={concentration.data.result.rows as Row[]}
                units={concentration.data.result.units}
                columns={["sector", "ead_pct", "coverage_pct", "npl_pct", "largest_obligor_pct"]}
                maxRows={10}
              />
            )}
          </Panel>
        </div>
      </Chapter>

      {/* --------------------------------------------- 4 · what is deteriorating */}
      <Chapter
        number="04"
        title="What is deteriorating"
        run={eclMovement.data}
        loading={eclMovement.loading}
        error={eclMovement.error}
        headline={(() => {
          const v = eclMovement.data?.result?.values;
          if (!v) return null;
          const breakdown = (v.breakdown ?? []) as { sector?: string; ecl_change?: number }[];
          const worst = breakdown[0];
          const net = num(v, "net_change");
          return (
            `Expected credit loss moved ${net !== null && net >= 0 ? "up" : "down"} by ` +
            `${money(Math.abs(net ?? 0), 1)}mn between ${String(v.from_period)} and ` +
            `${String(v.to_period)}` +
            (worst
              ? `, with ${worst.sector} contributing ${money(Math.abs(worst.ecl_change ?? 0), 1)}mn of it.`
              : ".")
          );
        })()}
      >
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
          <Panel
            title="ECL movement by sector"
            hint="Increases in loss are shown as adverse"
            run={eclMovement.data}
            loading={eclMovement.loading}
          >
            {eclMovement.data?.result && (
              <DivergingBarChart
                data={
                  ((eclMovement.data.result.values.breakdown ?? []) as Rows).slice(0, 10)
                }
                xKey="sector"
                valueKey="ecl_change"
                unit="USD mn"
                height={300}
              />
            )}
          </Panel>
          <Panel
            title="Impairment bridge"
            hint="Opening to closing, as the engine reconciled it"
            run={eclMovement.data}
            loading={eclMovement.loading}
          >
            {eclMovement.data?.result && (
              <ResultTable
                rows={eclMovement.data.result.rows as Row[]}
                units={{ value: "USD mn" }}
                columns={["component", "value"]}
              />
            )}
          </Panel>
        </div>
      </Chapter>

      {/* ----------------------------------- 5 · which obligors require attention */}
      <Chapter
        number="05"
        title="Which obligors require attention"
        run={deteriorating.data}
        loading={deteriorating.loading}
        error={deteriorating.error}
        headline={(() => {
          const v = deteriorating.data?.result?.values;
          if (!v) return null;
          return (
            `${String(v.deteriorated_count)} of ${String(v.borrowers_compared)} borrowers ` +
            `deteriorated against ${String(v.from_period)}, adding ` +
            `${money(num(v, "total_ecl_increase"), 1)}mn of expected credit loss.`
          );
        })()}
      >
        <Panel
          title="Deteriorating borrowers"
          hint="Ranked by the engine's composite severity score, with the recorded reasons"
          run={deteriorating.data}
          loading={deteriorating.loading}
        >
          {deteriorating.data?.result && (
            <ResultTable
              rows={deteriorating.data.result.rows as Row[]}
              units={deteriorating.data.result.units}
              columns={[
                "borrower_name",
                "sector",
                "ead",
                "ecl_change",
                "risk_rating_from",
                "risk_rating_to",
                "reasons",
              ]}
              renderCell={(column, value) =>
                column === "reasons" ? (
                  <span className="block max-w-[24rem] truncate text-xs text-text-muted">
                    {String(value)}
                  </span>
                ) : undefined
              }
            />
          )}
        </Panel>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href="/?focus=ask">
              Ask IPM about these names
              <ArrowRight aria-hidden />
            </Link>
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/stress">Run a downturn scenario</Link>
          </Button>
        </div>
      </Chapter>

      <p className="border-t border-border pt-4 text-xs leading-relaxed text-text-muted">
        Every headline on this page is assembled from figures the IPM Engine returned for the
        section beneath it. Where an analysis returned nothing, the section says so rather than
        offering a conclusion. Figures are synthetic demonstration data.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Chapter({
  number,
  title,
  headline,
  run,
  loading,
  error,
  children,
}: {
  number: string;
  title: string;
  headline: string | null;
  run?: AnalysisRunResponse | null;
  loading?: boolean;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-4 flex items-start justify-between gap-4 border-b border-border pb-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2.5 text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            <span className="tabular">{number}</span>
            <span className="h-px w-6 bg-border-strong" aria-hidden />
            {title}
          </p>
          {loading ? (
            <Skeleton className="mt-2.5 h-5 w-2/3" />
          ) : (
            <p className="mt-2 max-w-3xl text-[17px] font-medium leading-snug tracking-tight text-text-primary">
              {headline ??
                (error
                  ? "This section could not be produced from the published data."
                  : "No figures were returned for this section.")}
            </p>
          )}
        </div>
        <TraceButton runId={run?.analysis_run_id} />
      </div>
      {error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">{error}</Card>
      ) : (
        children
      )}
    </section>
  );
}

function Panel({
  title,
  hint,
  run,
  loading,
  children,
  className,
}: {
  title: string;
  hint?: string;
  run?: AnalysisRunResponse | null;
  loading?: boolean;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold tracking-tight text-text-primary">{title}</h3>
          {hint && <p className="mt-0.5 truncate text-xs text-text-muted">{hint}</p>}
        </div>
        {run?.analysis_run_id && (
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/trace/${run.analysis_run_id}`} title="How this was produced">
              <GitBranch aria-hidden />
              Trace
            </Link>
          </Button>
        )}
      </div>
      <div className="px-5 py-4">
        {loading ? <Skeleton className="h-56 w-full" /> : children}
      </div>
    </Card>
  );
}

/** The three-way split of a migration, drawn as proportions of one whole. */
function MigrationSplit({ run }: { run: AnalysisRunResponse }) {
  const move = (run.result?.values.movement ?? {}) as Record<string, number>;
  const bands = [
    { label: "Deteriorated", value: move.deteriorated, pct: move.deteriorated_pct, tone: "negative" },
    { label: "Stable", value: move.stable, pct: move.stable_pct, tone: "muted" },
    { label: "Improved", value: move.improved, pct: move.improved_pct, tone: "positive" },
  ] as const;

  return (
    <div className="space-y-3">
      {bands.map((band) => (
        <div key={band.label}>
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <span className="text-text-secondary">{band.label}</span>
            <span className="tabular text-text-primary">
              {money(band.value, 0)}mn · {percent(band.pct, 1)}
            </span>
          </div>
          <div
            className="mt-1 h-2 overflow-hidden rounded-full bg-surface-sunken"
            role="img"
            aria-label={`${band.label} ${percent(band.pct, 1)}`}
          >
            <div
              className={cn(
                "h-full rounded-full",
                band.tone === "negative" && "bg-negative",
                band.tone === "positive" && "bg-positive",
                band.tone === "muted" && "bg-border-strong",
              )}
              style={{ width: `${Math.min(100, Math.max(0, band.pct ?? 0))}%` }}
            />
          </div>
        </div>
      ))}
      <p className="border-t border-border pt-2.5 text-[11px] text-text-muted">
        {String((run.result?.values.coverage as Record<string, number>)?.matched ?? "—")}{" "}
        facilities present in both periods. Measured on opening exposure.
      </p>
    </div>
  );
}
