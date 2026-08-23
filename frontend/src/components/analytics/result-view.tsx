"use client";

import * as React from "react";

import {
  CategoryBarChart,
  DivergingBarChart,
  MatrixHeatmap,
  StackedBarChart,
  TrendChart,
} from "@/components/analytics/charts";
import { ResultTable, Stat } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import type { AnalysisRunResponse, Row } from "@/lib/api";
import { byUnit, money, percent } from "@/lib/format";

/**
 * Renders the result of any registered analysis.
 *
 * One component rather than a bespoke layout per screen, so an analysis looks
 * the same in the Cockpit, in a Lens, inside an Investigation and on its own
 * page. The form is chosen by what the data's job is — a matrix for
 * transitions, a signed bar for an attribution, a line for a trend — following
 * the contract's declared visualizations rather than guessing from the shape.
 */

type Rows = Record<string, string | number | null>[];

function asRows(rows: Row[]): Rows {
  return rows as Rows;
}

function num(values: Record<string, unknown>, key: string): number | null {
  const v = values[key];
  return typeof v === "number" ? v : null;
}

export function ResultView({
  run,
  compact = false,
}: {
  run: AnalysisRunResponse;
  compact?: boolean;
}) {
  const result = run.result;
  if (!result) return null;
  const { rows, values, units } = result;

  switch (run.analysis_id) {
    // ------------------------------------------------------------- summary
    case "portfolio_summary": {
      const movement = (values.movement ?? {}) as Record<string, number>;
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Stat label="Total EAD" value={`${money(num(values, "total_ead"), 0)}mn`} />
            <Stat label="Total ECL" value={`${money(num(values, "total_ecl"), 1)}mn`} />
            <Stat label="Coverage" value={percent(num(values, "ecl_coverage_pct"))} />
            <Stat label="NPL ratio" value={percent(num(values, "npl_ratio_pct"))} />
            <Stat label="Stage 2" value={percent(num(values, "stage2_pct"))} />
            <Stat label="Stage 3" value={percent(num(values, "stage3_pct"))} />
            <Stat label="Weighted PD" value={percent(num(values, "weighted_pd_pct"))} />
            <Stat label="Weighted LGD" value={percent(num(values, "weighted_lgd_pct"))} />
          </div>
          {!compact && Object.keys(movement).length > 0 && (
            <div className="rounded-md border border-border bg-surface-sunken p-3">
              <p className="mb-2 text-xs font-medium text-text-secondary">
                Movement against {String(values.compare_period ?? "the prior period")}
              </p>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {(
                  [
                    ["total_ead", "EAD", "USD mn"],
                    ["total_ecl", "ECL", "USD mn"],
                    ["ecl_coverage_pct", "Coverage", "pp"],
                    ["stage2_pct", "Stage 2", "pp"],
                  ] as const
                ).map(([key, label, unit]) => {
                  const value = movement[key];
                  if (value === undefined) return null;
                  const bad = value > 0 && key !== "total_ead";
                  return (
                    <div key={key}>
                      <p className="text-[11px] uppercase tracking-wider text-text-muted">
                        {label}
                      </p>
                      <p
                        className={`text-sm font-semibold tabular ${
                          key === "total_ead"
                            ? "text-text-primary"
                            : bad
                              ? "text-negative"
                              : "text-positive"
                        }`}
                      >
                        {value > 0 ? "+" : ""}
                        {byUnit(value, unit)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      );
    }

    // -------------------------------------------------------- distribution
    case "stage_distribution": {
      const data = asRows(rows).map((r) => ({
        ...r,
        stage: `Stage ${r.ifrs9_stage}`,
      }));
      return (
        <div className="space-y-4">
          <CategoryBarChart
            data={data}
            xKey="stage"
            series={[{ key: "ead", label: "EAD", slot: 0 }]}
            units={{ ead: "USD mn" }}
            height={compact ? 150 : 190}
          />
          {!compact && (
            <ResultTable
              rows={rows}
              units={units}
              columns={[
                "ifrs9_stage",
                "ead",
                "ead_pct",
                "total_ecl",
                "coverage_pct",
                "facility_count",
              ]}
            />
          )}
        </div>
      );
    }

    // ------------------------------------------------------------- trend
    case "portfolio_trend":
      return (
        <div className="space-y-4">
          <TrendChart
            data={asRows(rows)}
            xKey="period"
            series={[
              { key: "total_ead", label: "Total EAD", slot: 0 },
              { key: "total_ecl", label: "Total ECL", slot: 1 },
            ]}
            units={{ total_ead: "USD mn", total_ecl: "USD mn" }}
            height={compact ? 180 : 220}
          />
          <TrendChart
            data={asRows(rows)}
            xKey="period"
            series={[
              { key: "ecl_coverage_pct", label: "ECL coverage", slot: 2 },
              { key: "stage2_pct", label: "Stage 2 share", slot: 3 },
              { key: "stage3_pct", label: "Stage 3 share", slot: 4 },
              { key: "npl_ratio_pct", label: "NPL ratio", slot: 5 },
            ]}
            units={{
              ecl_coverage_pct: "%",
              stage2_pct: "%",
              stage3_pct: "%",
              npl_ratio_pct: "%",
            }}
            height={compact ? 180 : 220}
          />
        </div>
      );

    // ----------------------------------------------------- concentration
    case "sector_concentration": {
      const dimension = String(values.dimension ?? "sector");
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-6">
            <Stat label="Herfindahl index" value={money(num(values, "hhi"), 0)} />
            <Stat label="Top 5 share" value={percent(num(values, "top_5_pct"))} />
            <Stat label="Groups" value={String(values.group_count ?? "—")} />
          </div>
          <CategoryBarChart
            data={asRows(rows)}
            xKey={dimension}
            series={[{ key: "ead", label: "EAD", slot: 0 }]}
            units={{ ead: "USD mn" }}
            height={compact ? 200 : 300}
          />
          {!compact && (
            <ResultTable
              rows={rows}
              units={units}
              columns={[
                dimension,
                "ead",
                "ead_pct",
                "coverage_pct",
                "npl_pct",
                "largest_obligor_pct",
                "borrower_count",
              ]}
            />
          )}
        </div>
      );
    }

    // -------------------------------------------------------- migrations
    case "stage_migration":
    case "dpd_migration":
    case "rating_transition_matrix": {
      const categories =
        run.analysis_id === "rating_transition_matrix"
          ? ((values.grades as string[]) ?? [])
          : run.analysis_id === "dpd_migration"
            ? ((values.buckets as string[]) ?? [])
            : ["1", "2", "3"];
      const cells: Record<string, number> = {};
      for (const r of rows) {
        cells[`${r.from}|${r.to}`] = Number(r.row_pct ?? 0);
      }
      const movement = (values.movement ?? {}) as Record<string, number>;
      const isRating = run.analysis_id === "rating_transition_matrix";

      return (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-6">
            <Stat
              label={isRating ? "Upgraded" : "Improved"}
              value={percent(movement.improved_pct ?? movement.upgraded_pct)}
              tone="positive"
            />
            <Stat label="Stable" value={percent(movement.stable_pct)} tone="muted" />
            <Stat
              label={isRating ? "Downgraded" : "Deteriorated"}
              value={percent(movement.deteriorated_pct ?? movement.downgraded_pct)}
              tone="negative"
            />
            {movement.cure_rate_pct !== undefined && (
              <Stat label="Cure rate" value={percent(movement.cure_rate_pct)} tone="positive" />
            )}
          </div>
          <div>
            <p className="mb-2 text-xs text-text-muted">
              Row percentages — of the exposure that started in each row, where it ended up.
              {isRating && " Not annualised."}
            </p>
            <MatrixHeatmap categories={categories} cells={cells} />
          </div>
          {!compact && (
            <p className="text-xs text-text-muted">
              {String((values.coverage as Record<string, number>)?.matched ?? "—")} facilities
              matched across both periods ·{" "}
              {String((values.coverage as Record<string, number>)?.entries ?? "—")} entered ·{" "}
              {String((values.coverage as Record<string, number>)?.exits ?? "—")} exited
            </p>
          )}
        </div>
      );
    }

    // ------------------------------------------------------- ECL movement
    case "ecl_movement": {
      const components = asRows(rows).filter((r) => r.kind === "movement");
      const breakdown = (values.breakdown ?? []) as Rows;
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-6">
            <Stat label="Opening ECL" value={`${money(num(values, "opening_ecl"), 1)}mn`} />
            <Stat label="Closing ECL" value={`${money(num(values, "closing_ecl"), 1)}mn`} />
            <Stat
              label="Net change"
              value={`${(num(values, "net_change") ?? 0) > 0 ? "+" : ""}${money(
                num(values, "net_change"),
                1,
              )}mn`}
              tone={(num(values, "net_change") ?? 0) > 0 ? "negative" : "positive"}
            />
          </div>
          <DivergingBarChart
            data={components}
            xKey="component"
            valueKey="value"
            unit="USD mn"
            height={compact ? 190 : 240}
          />
          {!compact && breakdown.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-text-secondary">
                By {String(values.group_by)}
              </p>
              <ResultTable rows={breakdown as Row[]} units={{ ecl_change: "USD mn" }} maxRows={8} />
            </div>
          )}
          <p className="text-xs text-text-muted">
            Bridge reconciles to {byUnit(values.reconciliation_difference, "USD mn")} — opening
            plus every component equals closing.
          </p>
        </div>
      );
    }

    // ------------------------------------------------------- deterioration
    case "top_deteriorating_borrowers":
      return (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-6">
            <Stat label="Deteriorated" value={String(values.deteriorated_count ?? "—")} tone="negative" />
            <Stat label="Compared" value={String(values.borrowers_compared ?? "—")} />
            <Stat
              label="ECL increase"
              value={`${money(num(values, "total_ecl_increase"), 1)}mn`}
              tone="negative"
            />
          </div>
          <ResultTable
            rows={rows}
            units={units}
            columns={[
              "borrower_name",
              "sector",
              "ead",
              "ecl_change",
              "stage_change",
              "notch_change",
              "reasons",
            ]}
            maxRows={compact ? 6 : undefined}
            renderCell={(column, value) =>
              column === "reasons" ? (
                <span className="block max-w-[26rem] text-xs text-text-muted">
                  {String(value)}
                </span>
              ) : undefined
            }
          />
        </div>
      );

    // -------------------------------------------------------------- stress
    case "stress_scenario_basic": {
      const bySector = (values.by_sector ?? []) as Rows;
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="warning">Management Scenario Simulation</Badge>
            <span className="text-xs text-text-muted">
              Not a regulatory or IFRS 9 lifetime calculation
            </span>
          </div>
          <div className="flex flex-wrap gap-6">
            <Stat label="Baseline ECL" value={`${money(num(values, "base_ecl"), 1)}mn`} />
            <Stat
              label="Stressed ECL"
              value={`${money(num(values, "stressed_ecl"), 1)}mn`}
              tone="negative"
            />
            <Stat
              label="Incremental ECL"
              value={`+${money(num(values, "ecl_increase"), 1)}mn`}
              tone="negative"
            />
            <Stat label="Increase" value={percent(num(values, "ecl_increase_pct"), 1)} tone="negative" />
            <Stat
              label="Coverage"
              value={`${percent(num(values, "base_coverage_pct"))} → ${percent(
                num(values, "stressed_coverage_pct"),
              )}`}
            />
          </div>
          <ResultTable rows={rows} columns={["metric", "base", "stressed", "change", "change_pct"]} />
          {!compact && bySector.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-text-secondary">
                Incremental ECL by sector
              </p>
              <CategoryBarChart
                data={bySector.slice(0, 10)}
                xKey="sector"
                series={[{ key: "ecl_increase", label: "Incremental ECL", slot: 1 }]}
                units={{ ecl_increase: "USD mn" }}
                height={240}
              />
            </div>
          )}
        </div>
      );
    }

    // ------------------------------------------------------------ fallback
    default:
      return (
        <div className="space-y-3">
          {Object.keys(values).length > 0 && (
            <div className="flex flex-wrap gap-6">
              {Object.entries(values)
                .filter(([, v]) => typeof v === "number" || typeof v === "string")
                .slice(0, 6)
                .map(([k, v]) => (
                  <Stat key={k} label={k.replace(/_/g, " ")} value={byUnit(v, units[k])} />
                ))}
            </div>
          )}
          <ResultTable rows={rows} units={units} maxRows={compact ? 6 : 25} />
        </div>
      );
  }
}

/** Stacked composition of the stage split — used by the CRO Lens. */
export function StageCompositionChart({ run }: { run: AnalysisRunResponse }) {
  const rows = run.result?.rows ?? [];
  const point: Record<string, string | number | null> = { label: "Exposure" };
  for (const r of rows) point[`stage_${r.ifrs9_stage}`] = Number(r.ead ?? 0);
  return (
    <StackedBarChart
      data={[point]}
      xKey="label"
      horizontal
      series={[
        { key: "stage_1", label: "Stage 1", slot: 0 },
        { key: "stage_2", label: "Stage 2", slot: 4 },
        { key: "stage_3", label: "Stage 3", slot: 1 },
      ]}
      units={{ stage_1: "USD mn", stage_2: "USD mn", stage_3: "USD mn" }}
      height={130}
    />
  );
}
