"use client";

import * as React from "react";
import { FlaskConical, Info, Play } from "lucide-react";

import { AnalyticalCard } from "@/components/analytics/analytical-card";
import { CategoryBarChart } from "@/components/analytics/charts";
import { KpiTile, ResultTable, Stat } from "@/components/analytics/primitives";
import { PageHeader } from "@/components/layout/page-header";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { money, percent } from "@/lib/format";
import { useAnalysis, useAsync } from "@/lib/hooks";
import type { Row } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Stress Testing.
 *
 * Runs the real Basic Management Scenario. Every scenario is labelled as a
 * management simulation, because presenting it as regulatory stress testing
 * would be an overclaim: it has no forward-looking macro paths and no lifetime
 * PD term structure, and the engine's own methodology text says so.
 */

const PRESETS = [
  {
    id: "base",
    label: "Base (no shock)",
    severity: "None",
    rationale: "The reported position, for comparison.",
    shocks: "No change",
  },
  {
    id: "mild",
    label: "Mild slowdown",
    severity: "Mild",
    rationale: "A shallow downturn: PD up a quarter, modest collateral erosion.",
    shocks: "PD ×1.25 · LGD +2pp · EAD +1% · 2% of Stage 1 migrated",
  },
  {
    id: "moderate",
    label: "Moderate downturn",
    severity: "Moderate",
    rationale:
      "The central management scenario: PD up three quarters, LGD up 5pp, undrawn commitments partly drawn.",
    shocks: "PD ×1.75 · LGD +5pp · EAD +3% · 5% of Stage 1 migrated",
  },
  {
    id: "severe",
    label: "Severe stress",
    severity: "Severe",
    rationale:
      "A sharp recession with property-price falls: PD two and a half times, LGD up 10pp.",
    shocks: "PD ×2.5 · LGD +10pp · EAD +6% · 10% of Stage 1 migrated",
  },
];

export default function StressPage() {
  const [tab, setTab] = React.useState("library");
  const [scenario, setScenario] = React.useState("moderate");
  const [sector, setSector] = React.useState("");
  const [pdMultiplier, setPdMultiplier] = React.useState(2);
  const [lgdUplift, setLgdUplift] = React.useState(6);
  const [eadUplift, setEadUplift] = React.useState(4);
  const [migration, setMigration] = React.useState(6);
  const [useCustom, setUseCustom] = React.useState(false);
  const canRun = useCanRunAnalysis();

  const dimensions = useAsync(() => api.dimensions(), []);
  const sectors =
    dimensions.data?.dimensions.find((d) => d.field === "sector")?.values ?? [];

  const params = React.useMemo(
    () =>
      useCustom
        ? {
            scenario: "custom",
            pd_multiplier: pdMultiplier,
            lgd_uplift_pp: lgdUplift,
            ead_uplift_pct: eadUplift,
            stage2_migration_pct: migration,
            ...(sector ? { sector } : {}),
          }
        : { scenario, ...(sector ? { sector } : {}) },
    [useCustom, scenario, sector, pdMultiplier, lgdUplift, eadUplift, migration],
  );

  const run = useAnalysis("stress_scenario_basic", { params }, canRun);

  // Comparison across all four presets, run for real.
  const mild = useAnalysis("stress_scenario_basic", { params: { scenario: "mild" } }, tab === "compare");
  const moderate = useAnalysis(
    "stress_scenario_basic",
    { params: { scenario: "moderate" } },
    tab === "compare",
  );
  const severe = useAnalysis(
    "stress_scenario_basic",
    { params: { scenario: "severe" } },
    tab === "compare",
  );

  const values = run.data?.result?.values;
  const bySector = (values?.by_sector ?? []) as Record<string, string | number | null>[];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Stress Testing"
        description="Named, parameterised shocks applied to the portfolio, with the incremental impairment attributed by sector."
        status="live"
        actions={<Badge variant="warning">Management Scenario Simulation</Badge>}
      />

      <Card className="flex items-start gap-2.5 border-info/30 bg-info-muted p-4 text-sm text-info">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          These are <strong>management scenarios</strong>, not regulatory stress testing. Each
          facility&apos;s reported ECL is scaled by the severity of the shock, which preserves its
          own lifetime or 12-month measurement basis. There are no forward-looking macro paths
          and no lifetime PD term structure.
        </span>
      </Card>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "library", label: "Scenario Library", count: PRESETS.length },
          { id: "builder", label: "Scenario Builder" },
          { id: "run", label: "Run Scenario" },
          { id: "compare", label: "Results Comparison" },
        ]}
      />

      {tab === "library" && (
        <div className="grid gap-4 md:grid-cols-2">
          {PRESETS.map((p) => (
            <Card key={p.id} className="flex flex-col p-5">
              <div className="mb-2 flex items-start justify-between gap-3">
                <FlaskConical className="size-5 text-text-muted" aria-hidden />
                <Badge
                  variant={
                    p.severity === "Severe"
                      ? "negative"
                      : p.severity === "Moderate"
                        ? "warning"
                        : p.severity === "Mild"
                          ? "info"
                          : "default"
                  }
                >
                  {p.severity}
                </Badge>
              </div>
              <h3 className="text-sm font-semibold text-text-primary">{p.label}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-text-muted">{p.rationale}</p>
              <p className="mt-3 rounded-md bg-surface-sunken px-3 py-2 font-mono text-[11px] text-text-secondary">
                {p.shocks}
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => {
                  setScenario(p.id);
                  setUseCustom(false);
                  setTab("run");
                }}
              >
                <Play aria-hidden />
                Run this scenario
              </Button>
            </Card>
          ))}
        </div>
      )}

      {tab === "builder" && (
        <Card className="p-6">
          <h3 className="mb-1 text-sm font-semibold text-text-primary">Scenario Builder</h3>
          <p className="mb-5 max-w-3xl text-sm text-text-secondary">
            Define your own shocks. A scenario is a set of parameters, not free text, so the
            result can be reproduced exactly and argued with in a committee.
          </p>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Field label="PD multiplier" hint="Every PD multiplied by this, capped at 100%.">
              <Input
                type="number"
                step="0.05"
                min={0.1}
                max={10}
                value={pdMultiplier}
                onChange={(e) => setPdMultiplier(Number(e.target.value))}
              />
            </Field>
            <Field label="LGD uplift (pp)" hint="Added to LGD, capped at 100%.">
              <Input
                type="number"
                step="0.5"
                min={0}
                max={60}
                value={lgdUplift}
                onChange={(e) => setLgdUplift(Number(e.target.value))}
              />
            </Field>
            <Field label="EAD uplift (%)" hint="Undrawn commitments being drawn.">
              <Input
                type="number"
                step="0.5"
                min={0}
                max={50}
                value={eadUplift}
                onChange={(e) => setEadUplift(Number(e.target.value))}
              />
            </Field>
            <Field label="Stage 1 → 2 migration (%)" hint="Moves to a lifetime measurement basis.">
              <Input
                type="number"
                step="1"
                min={0}
                max={100}
                value={migration}
                onChange={(e) => setMigration(Number(e.target.value))}
              />
            </Field>
            <Field label="Restrict to sector" className="md:col-span-2" hint="Leave unset for the whole book.">
              <Select value={sector} onChange={(e) => setSector(e.target.value)}>
                <option value="">Whole portfolio</option>
                {sectors.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Button
            className="mt-5"
            onClick={() => {
              setUseCustom(true);
              setTab("run");
            }}
          >
            <Play aria-hidden />
            Run custom scenario
          </Button>
        </Card>
      )}

      {tab === "run" && (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={useCustom ? "custom" : scenario}
              onChange={(e) => {
                if (e.target.value === "custom") setUseCustom(true);
                else {
                  setUseCustom(false);
                  setScenario(e.target.value);
                }
              }}
              className="w-56"
              aria-label="Scenario"
            >
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
              <option value="custom">Custom scenario</option>
            </Select>
            <Select
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="w-56"
              aria-label="Sector"
            >
              <option value="">Whole portfolio</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              label="Baseline ECL"
              value={typeof values?.base_ecl === "number" ? values.base_ecl : null}
              unit="USD mn"
              hint="as reported"
              loading={run.loading}
              emphasis
            />
            <KpiTile
              label="Stressed ECL"
              value={typeof values?.stressed_ecl === "number" ? values.stressed_ecl : null}
              unit="USD mn"
              hint="under the scenario"
              loading={run.loading}
              emphasis
            />
            <KpiTile
              label="Incremental ECL"
              value={typeof values?.ecl_increase === "number" ? values.ecl_increase : null}
              unit="USD mn"
              change={typeof values?.ecl_increase === "number" ? values.ecl_increase : null}
              changeUnit="USD mn"
              hint="additional impairment"
              loading={run.loading}
              emphasis
            />
            <KpiTile
              label="Stressed coverage"
              value={
                typeof values?.stressed_coverage_pct === "number"
                  ? values.stressed_coverage_pct
                  : null
              }
              unit="%"
              hint={
                typeof values?.base_coverage_pct === "number"
                  ? `from ${percent(values.base_coverage_pct)}`
                  : undefined
              }
              loading={run.loading}
              emphasis
            />
          </div>

          <AnalyticalCard
            title="Scenario result"
            description={
              values?.scenario_label ? String(values.scenario_label) : "Management scenario"
            }
            analysisId="stress_scenario_basic"
            run={run.data}
            loading={run.loading}
            error={run.error}
            onRetry={run.reload}
            minHeight={280}
          >
            {run.data?.result && (
              <div className="space-y-4">
                <div className="rounded-md border border-border bg-surface-sunken p-3">
                  <p className="mb-1 text-xs font-medium text-text-secondary">
                    Scenario assumptions
                  </p>
                  <p className="text-xs text-text-muted">{String(values?.rationale ?? "")}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {Object.entries((values?.shocks ?? {}) as Record<string, unknown>)
                      .filter(([k]) => k !== "label" && k !== "rationale")
                      .map(([k, v]) => (
                        <Badge key={k} variant="outline">
                          {k.replace(/_/g, " ")}: {String(v)}
                        </Badge>
                      ))}
                  </div>
                </div>
                <ResultTable
                  rows={run.data.result.rows as Row[]}
                  columns={["metric", "base", "stressed", "change", "change_pct"]}
                />
              </div>
            )}
          </AnalyticalCard>

          <AnalyticalCard
            title="Sector impact"
            description="Incremental ECL attributed by sector, and the largest contributors"
            run={run.data}
            loading={run.loading}
            error={run.error}
            actions={false}
            minHeight={300}
          >
            {bySector.length > 0 && (
              <div className="space-y-4">
                <CategoryBarChart
                  data={bySector.slice(0, 10)}
                  xKey="sector"
                  series={[{ key: "ecl_increase", label: "Incremental ECL", slot: 1 }]}
                  units={{ ecl_increase: "USD mn" }}
                  height={260}
                />
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead>Sector</TableHead>
                      <TableHead numeric>EAD</TableHead>
                      <TableHead numeric>Base ECL</TableHead>
                      <TableHead numeric>Stressed ECL</TableHead>
                      <TableHead numeric>Incremental</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {bySector.slice(0, 8).map((r) => (
                      <TableRow key={String(r.sector)}>
                        <TableCell className="font-medium text-text-primary">
                          {String(r.sector)}
                        </TableCell>
                        <TableCell numeric>{money(Number(r.ead), 0)}</TableCell>
                        <TableCell numeric>{money(Number(r.base_ecl), 1)}</TableCell>
                        <TableCell numeric>{money(Number(r.stressed_ecl), 1)}</TableCell>
                        <TableCell numeric className="font-medium text-negative">
                          +{money(Number(r.ecl_increase), 1)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </AnalyticalCard>
        </>
      )}

      {tab === "compare" && (
        <Card className="p-5">
          <h3 className="mb-1 text-sm font-semibold text-text-primary">Results comparison</h3>
          <p className="mb-4 text-sm text-text-secondary">
            All three severity presets, executed against the same reporting period.
          </p>
          {[mild, moderate, severe].some((r) => r.loading) ? (
            <p className="text-sm text-text-muted">Running scenarios…</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Scenario</TableHead>
                    <TableHead numeric>Baseline ECL</TableHead>
                    <TableHead numeric>Stressed ECL</TableHead>
                    <TableHead numeric>Incremental</TableHead>
                    <TableHead numeric>Increase</TableHead>
                    <TableHead numeric>Coverage</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[
                    ["Mild slowdown", mild],
                    ["Moderate downturn", moderate],
                    ["Severe stress", severe],
                  ].map(([label, state]) => {
                    const v = (state as typeof mild).data?.result?.values;
                    if (!v) return null;
                    return (
                      <TableRow key={String(label)}>
                        <TableCell className="font-medium text-text-primary">
                          {String(label)}
                        </TableCell>
                        <TableCell numeric>{money(Number(v.base_ecl), 1)}</TableCell>
                        <TableCell numeric>{money(Number(v.stressed_ecl), 1)}</TableCell>
                        <TableCell numeric className="font-medium text-negative">
                          +{money(Number(v.ecl_increase), 1)}
                        </TableCell>
                        <TableCell numeric className="text-negative">
                          {percent(Number(v.ecl_increase_pct), 1)}
                        </TableCell>
                        <TableCell numeric>{percent(Number(v.stressed_coverage_pct))}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>

              {moderate.data?.result && (
                <div className="mt-5 flex flex-wrap gap-8 border-t border-border pt-4">
                  <Stat
                    label="Base coverage"
                    value={percent(Number(moderate.data.result.values.base_coverage_pct))}
                  />
                  <Stat
                    label="Severe coverage"
                    value={percent(Number(severe.data?.result?.values.stressed_coverage_pct))}
                    tone="negative"
                  />
                  <Stat
                    label="Severe incremental ECL"
                    value={`+${money(Number(severe.data?.result?.values.ecl_increase), 1)}mn`}
                    tone="negative"
                  />
                </div>
              )}
            </>
          )}
        </Card>
      )}
    </div>
  );
}

export { cn };
