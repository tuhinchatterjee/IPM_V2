"use client";

import * as React from "react";
import { FlaskConical, Info, Play, Settings2 } from "lucide-react";

import { KpiTile } from "@/components/analytics/primitives";
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
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import type { WhatIfConfiguration, WhatIfRun } from "@/lib/api";
import { money } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * What-If Analysis.
 *
 * The screen's job is to make the ASSUMPTIONS visible, not to hide them behind
 * a Run button. A stressed provision that a credit officer cannot take apart is
 * a number they will not defend in a committee, so the rating masterscale, the
 * macro sensitivity matrix and the IFRS 9 staging policy are all on the page —
 * and every one of them carries an owner and a version.
 *
 * The results are TABLE FIRST. A scenario answer is a summary and a list of
 * names; a chart of stressed exposure by sector is offered on the sector tab,
 * where the comparison is genuinely the point, and nowhere else.
 */

const SHOCK_KINDS = [
  { value: "rating", label: "Rating downgrade", unit: "notches", hint: "notches" },
  { value: "pd", label: "12-month PD", unit: "relative_pct", hint: "%" },
  { value: "lgd", label: "Loss given default", unit: "absolute_pp", hint: "pp" },
  { value: "ead", label: "Exposure at default", unit: "relative_pct", hint: "%" },
  { value: "collateral", label: "Collateral values", unit: "relative_pct", hint: "%" },
  { value: "financial", label: "EBITDA", unit: "relative_pct", hint: "%" },
] as const;

const SEVERITY_TONE: Record<string, string> = {
  base: "border-border text-text-muted",
  mild: "border-border text-text-secondary",
  moderate: "border-caution/50 text-caution",
  severe: "border-negative/50 text-negative",
  custom: "border-accent/50 text-accent",
};

function Money({ value }: { value: number }) {
  return <>{money(value, 1)}</>;
}

/** A number a reader can compare, with its direction shown rather than told. */
function Movement({ from, to, unit }: { from: number; to: number; unit?: string }) {
  const worse = to > from;
  return (
    <span className="tabular-nums">
      {money(from, 1)}
      <span aria-hidden className="mx-1 text-text-muted">
        →
      </span>
      <span className={cn(worse ? "text-negative" : "text-text-primary")}>
        {money(to, 1)}
      </span>
      {unit ? <span className="ml-1 text-text-muted">{unit}</span> : null}
    </span>
  );
}

export default function StressTestingPage() {
  const canRun = useCanRunAnalysis();
  const configuration = useAsync<WhatIfConfiguration>(
    () => api.whatIfConfiguration(),
    [],
  );

  const [scenarioKey, setScenarioKey] = React.useState("downgrade_bbb_two");
  const [customKind, setCustomKind] = React.useState<string>("rating");
  const [customSize, setCustomSize] = React.useState("2");
  const [sector, setSector] = React.useState("");
  const [ratingBand, setRatingBand] = React.useState("");
  const [assumeSicr, setAssumeSicr] = React.useState(false);
  const [run, setRun] = React.useState<WhatIfRun | null>(null);
  const [comparison, setComparison] = React.useState<{
    columns: string[];
    rows: (string | number)[][];
  } | null>(null);
  const [resultTab, setResultTab] = React.useState("borrowers");
  const [configTab, setConfigTab] = React.useState("masterscale");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const scenarios = configuration.data?.scenarios ?? [];
  const selected = scenarios.find((s) => s.key === scenarioKey);

  async function runPreset() {
    setBusy(true);
    setError("");
    try {
      setRun(
        await api.runWhatIf({
          scenario: scenarioKey,
          limit: 100,
          assumptions: { rating_deterioration_sicr: assumeSicr },
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "The scenario could not run.");
    } finally {
      setBusy(false);
    }
  }

  async function runCustom() {
    setBusy(true);
    setError("");
    const shock = SHOCK_KINDS.find((k) => k.value === customKind);
    try {
      setRun(
        await api.runWhatIf({
          name: "Custom scenario",
          shocks: [
            {
              kind: customKind,
              magnitude: Number(customSize) || 0,
              unit: shock?.unit ?? "relative_pct",
              target: customKind === "financial" ? "ebitda" : "",
            },
          ],
          population: {
            sectors: sector ? [sector] : [],
            rating_bands: ratingBand ? [ratingBand] : [],
          },
          assumptions: { rating_deterioration_sicr: assumeSicr },
          limit: 100,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "The scenario could not run.");
    } finally {
      setBusy(false);
    }
  }

  async function compare() {
    setBusy(true);
    setError("");
    try {
      setComparison(
        await api.compareWhatIf([
          "base",
          "downgrade_one_notch",
          "pd_up_25",
          "rates_200bp",
          "severe_combined",
        ]),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "The comparison could not run.");
    } finally {
      setBusy(false);
    }
  }

  const summary = run?.summary;

  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="Intelligence"
        title="What-If Analysis"
        description="Ask what would happen before it happens. Every scenario is computed borrower by borrower against the same governed staging and measurement rules that produced the reported book, so the base column ties to the accounts and the stressed column can be argued with line by line."
      />

      {/*
        A refused Viewer used to land here on a page with an empty scenario
        dropdown and no configuration section — `configuration.data?` swallowed
        the 403 into a `??` default and said nothing. Stated first, above the
        controls, because the controls below are the thing that is missing.
      */}
      <Unavailable state={configuration} what="the scenario configuration" />

      {/* ----------------------------------------------------- configure */}
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <FlaskConical className="size-4 text-accent" aria-hidden />
            <h2 className="text-[15px] font-semibold">Configured scenario</h2>
          </div>
          <Field label="Scenario">
            <Select
              value={scenarioKey}
              onChange={(e) => setScenarioKey(e.target.value)}
            >
              {scenarios.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name}
                </option>
              ))}
            </Select>
          </Field>
          {selected && (
            <div className="space-y-2">
              <Badge
                className={cn("border", SEVERITY_TONE[selected.severity] ?? "")}
              >
                {selected.severity}
              </Badge>
              <p className="text-[13px] leading-[1.55] text-text-secondary">
                {selected.rationale}
              </p>
              <p className="text-[12px] text-text-muted">
                Shocks: {selected.description}. Population:{" "}
                {selected.population.description}.
              </p>
            </div>
          )}
          <Button onClick={runPreset} disabled={!canRun || busy}>
            <Play className="size-3.5" aria-hidden /> Run scenario
          </Button>
        </Card>

        <Card className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <Settings2 className="size-4 text-accent" aria-hidden />
            <h2 className="text-[15px] font-semibold">Your own scenario</h2>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Shock">
              <Select
                value={customKind}
                onChange={(e) => setCustomKind(e.target.value)}
              >
                {SHOCK_KINDS.map((k) => (
                  <option key={k.value} value={k.value}>
                    {k.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label={`Size (${SHOCK_KINDS.find((k) => k.value === customKind)?.hint ?? ""})`}
            >
              <Input
                value={customSize}
                onChange={(e) => setCustomSize(e.target.value)}
                inputMode="decimal"
              />
            </Field>
            <Field label="Sector">
              <Select value={sector} onChange={(e) => setSector(e.target.value)}>
                <option value="">Whole book</option>
                {(configuration.data?.sensitivity.sectors ?? []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Rating band">
              <Select
                value={ratingBand}
                onChange={(e) => setRatingBand(e.target.value)}
              >
                <option value="">Every grade</option>
                {Object.keys(configuration.data?.masterscale.bands ?? {}).map(
                  (band) => (
                    <option key={band} value={band}>
                      {band}
                    </option>
                  ),
                )}
              </Select>
            </Field>
          </div>
          <label className="flex items-start gap-2 text-[12px] text-text-secondary">
            <input
              type="checkbox"
              checked={assumeSicr}
              onChange={(e) => setAssumeSicr(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Treat a rating deterioration as a significant increase in credit
              risk. Off by default: a notch is not a SICR trigger in this policy,
              and turning it on is a judgement somebody has to make.
            </span>
          </label>
          <Button onClick={runCustom} disabled={!canRun || busy} variant="outline">
            <Play className="size-3.5" aria-hidden /> Run
          </Button>
        </Card>
      </div>

      {error && (
        <Card className="border-negative/40 p-4 text-[13px] text-negative">
          {error}
        </Card>
      )}

      {/* -------------------------------------------------------- result */}
      {summary && run && (
        <div className="space-y-5">
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              label="Incremental ECL"
              value={money(summary.incremental_ecl, 1)}
              unit={summary.currency}
              change={summary.incremental_ecl_pct}
              changeUnit="%"
              direction="up-is-bad"
              hint={`${summary.borrowers.toLocaleString()} borrowers, ${summary.period}`}
            />
            <KpiTile
              label="Stressed ECL"
              value={money(summary.stressed_ecl, 1)}
              unit={summary.currency}
              hint={`Baseline ${money(summary.baseline_ecl, 1)}`}
            />
            <KpiTile
              label="Stage 1 → 2 migrations"
              value={summary.stage_2_migrations.toLocaleString()}
              hint={`Stage 2 population ${summary.stage_2_baseline} → ${summary.stage_2_stressed}`}
            />
            <KpiTile
              label="ECL coverage"
              value={`${summary.stressed_coverage_pct.toFixed(2)}%`}
              hint={`Baseline ${summary.baseline_coverage_pct.toFixed(2)}%`}
            />
          </div>

          <Tabs
            active={resultTab}
            onChange={setResultTab}
            tabs={[
              { id: "borrowers", label: `Borrowers (${summary.borrowers.toLocaleString()})` },
              { id: "sectors", label: "By sector" },
              { id: "how", label: "How this was calculated" },
              { id: "sensitivity", label: "Sensitivity" },
            ]}
          />

          {resultTab === "borrowers" && (
            <Card className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    {run.borrowers.columns.map((c) => (
                      <TableHead key={c}>{c}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {run.borrowers.rows.map((row, i) => (
                    <TableRow key={i}>
                      {row.map((cell, j) => (
                        <TableCell key={j} className="tabular-nums">
                          {typeof cell === "number" ? money(cell, 2) : String(cell)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}

          {resultTab === "sectors" && (
            <Card className="overflow-x-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Sector</TableHead>
                    <TableHead>Borrowers</TableHead>
                    <TableHead>Baseline ECL</TableHead>
                    <TableHead>Stressed ECL</TableHead>
                    <TableHead>Increase</TableHead>
                    <TableHead>Increase (%)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {run.detail.by_sector.map((row, i) => (
                    <TableRow key={i}>
                      <TableCell>{String(row.sector ?? "")}</TableCell>
                      <TableCell className="tabular-nums">
                        {Number(row.borrowers ?? 0)}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        <Money value={Number(row.baseline_ecl ?? 0)} />
                      </TableCell>
                      <TableCell className="tabular-nums">
                        <Money value={Number(row.stressed_ecl ?? 0)} />
                      </TableCell>
                      <TableCell className="tabular-nums text-negative">
                        <Money value={Number(row.ecl_increase ?? 0)} />
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {Number(row.ecl_increase_pct ?? 0).toFixed(1)}%
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}

          {resultTab === "how" && (
            <Card className="space-y-3 p-5">
              <ol className="space-y-3">
                {run.steps.map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-surface-sunken font-mono text-[10px] text-text-muted">
                      {i + 1}
                    </span>
                    <div>
                      <p className="text-[13px] font-medium text-text-primary">
                        {step.step}
                      </p>
                      <p className="text-[12px] leading-[1.55] text-text-secondary">
                        {step.detail}
                      </p>
                      {step.affected > 0 && (
                        <p className="mt-0.5 font-mono text-[11px] text-text-muted">
                          {step.affected.toLocaleString()} borrowers affected
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          )}

          {resultTab === "sensitivity" &&
            (run.sensitivity.length ? (
              <Card className="overflow-x-auto p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Variable</TableHead>
                      <TableHead>Shock</TableHead>
                      <TableHead>Sector</TableHead>
                      <TableHead>Sector sensitivity</TableHead>
                      <TableHead>PD effect</TableHead>
                      <TableHead>LGD effect</TableHead>
                      <TableHead>Borrowers</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {run.sensitivity.map((row, i) => (
                      <TableRow key={i}>
                        <TableCell>{row.variable}</TableCell>
                        <TableCell>{row.shock}</TableCell>
                        <TableCell>{row.scope}</TableCell>
                        <TableCell className="tabular-nums">
                          {row.sector_sensitivity.toFixed(2)}×
                        </TableCell>
                        <TableCell className="tabular-nums">
                          +{row.pd_effect_pct.toFixed(1)}%
                        </TableCell>
                        <TableCell className="tabular-nums">
                          +{row.lgd_effect_pp.toFixed(1)}pp
                        </TableCell>
                        <TableCell className="tabular-nums">{row.borrowers}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Card>
            ) : (
              <Card className="p-5 text-[13px] text-text-secondary">
                This scenario carries no macro shock, so the sensitivity matrix
                was not consulted.
              </Card>
            ))}
        </div>
      )}

      {/* ---------------------------------------------------- comparison */}
      <Card className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold">Scenario comparison</h2>
            <p className="text-[12px] text-text-muted">
              Five scenarios on the same book, so the severities can be read
              against each other rather than one at a time.
            </p>
          </div>
          <Button onClick={compare} disabled={!canRun || busy} variant="outline">
            Compare
          </Button>
        </div>
        {comparison && (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {comparison.columns.map((c) => (
                    <TableHead key={c}>{c}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparison.rows.map((row, i) => (
                  <TableRow key={i}>
                    {row.map((cell, j) => (
                      <TableCell key={j} className="tabular-nums">
                        {typeof cell === "number" ? money(cell, 1) : String(cell)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {/* ------------------------------------------------- configuration */}
      {configuration.data && (
        <>
          <Tabs
            active={configTab}
            onChange={setConfigTab}
            tabs={[
              { id: "masterscale", label: "Rating masterscale" },
              { id: "matrix", label: "Macro sensitivity matrix" },
              { id: "policy", label: "IFRS 9 staging policy" },
            ]}
          />

          {configTab === "masterscale" && (
            <Card className="space-y-3 p-5">
              <p className="text-[12px] text-text-muted">
                Owned by {configuration.data.masterscale.owner}, version{" "}
                {configuration.data.masterscale.version}. A downgrade moves a
                borrower onto the PD its new grade carries; each
                borrower&rsquo;s own position inside the band is preserved.
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Grade</TableHead>
                      <TableHead>PD floor</TableHead>
                      <TableHead>PD ceiling</TableHead>
                      <TableHead>Masterscale PD</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {configuration.data.masterscale.grades.map((g) => (
                      <TableRow key={g.grade}>
                        <TableCell className="font-medium">{g.grade}</TableCell>
                        <TableCell className="tabular-nums">{g.pd_floor_pct}%</TableCell>
                        <TableCell className="tabular-nums">{g.pd_ceiling_pct}%</TableCell>
                        <TableCell className="tabular-nums">
                          {g.masterscale_pd_pct}%
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}

          {configTab === "matrix" && (
            <Card className="space-y-3 p-5">
              <p className="flex items-start gap-2 text-[12px] text-text-secondary">
                <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span>{configuration.data.sensitivity.statement}</span>
              </p>
              <p className="font-mono text-[11px] text-text-muted">
                {configuration.data.sensitivity.owner} · version{" "}
                {configuration.data.sensitivity.version} · effective{" "}
                {configuration.data.sensitivity.effective_date}
              </p>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Variable</TableHead>
                      <TableHead>Shock unit</TableHead>
                      <TableHead>PD effect</TableHead>
                      <TableHead>LGD effect</TableHead>
                      <TableHead>Most exposed sectors</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {configuration.data.sensitivity.variables.map((v) => (
                      <TableRow key={v.key}>
                        <TableCell className="font-medium">{v.variable}</TableCell>
                        <TableCell>{v.shock_unit}</TableCell>
                        <TableCell className="tabular-nums">
                          +{v.pd_effect_pct_per_step}%
                        </TableCell>
                        <TableCell className="tabular-nums">
                          {v.lgd_effect_pp_per_step
                            ? `+${v.lgd_effect_pp_per_step}pp`
                            : "—"}
                        </TableCell>
                        <TableCell className="text-[12px] text-text-secondary">
                          {Object.entries(v.sector_sensitivity)
                            .filter(([, m]) => m > 1)
                            .sort((a, b) => b[1] - a[1])
                            .slice(0, 3)
                            .map(([sc, m]) => `${sc} ${m}×`)
                            .join(", ") || "no sector differentiation"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}

          {configTab === "policy" && (
            <Card className="space-y-3 p-5">
              <p className="font-mono text-[11px] text-text-muted">
                {configuration.data.ifrs9_policy.owner} · version{" "}
                {configuration.data.ifrs9_policy.version}
              </p>
              <div>
                <h3 className="text-[13px] font-semibold">
                  What moves a borrower into Stage 2
                </h3>
                <ul className="mt-1.5 space-y-1.5">
                  {configuration.data.ifrs9_policy.sicr_triggers.map((t) => (
                    <li key={t.trigger} className="text-[13px]">
                      <span className="font-medium">{t.trigger}.</span>{" "}
                      <span className="text-text-secondary">{t.rule}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="text-[13px] font-semibold">
                  How each Stage is measured
                </h3>
                <ul className="mt-1.5 space-y-1">
                  {Object.entries(configuration.data.ifrs9_policy.measurement).map(
                    ([stage, basis]) => (
                      <li key={stage} className="text-[13px] text-text-secondary">
                        <span className="font-medium text-text-primary">
                          {stage}:
                        </span>{" "}
                        {basis}
                      </li>
                    ),
                  )}
                </ul>
              </div>
              <p className="text-[12px] text-text-muted">
                Default is presumed at{" "}
                {configuration.data.ifrs9_policy.default_presumption}. A scenario
                never creates one.
              </p>
            </Card>
          )}
        </>
      )}

      {run && summary && (
        <p className="text-[12px] text-text-muted">
          <Movement
            from={summary.baseline_ead}
            to={summary.stressed_ead}
            unit={`${summary.currency} exposure at default`}
          />
        </p>
      )}
    </div>
  );
}
