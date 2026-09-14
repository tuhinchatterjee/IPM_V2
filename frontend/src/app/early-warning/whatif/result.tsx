"use client";

/**
 * One scenario result, whole.
 *
 * The result of a What-If is not a number, it is an argument: this shock was
 * applied to these people, it hit this first, it moved through the model this
 * way, it left the allowance here, and it looks this size depending on how
 * wide a book you hold it against. A block that showed only the last figure
 * would be the easiest thing to read and the easiest thing to be wrong about.
 *
 * So the sections run in the order the argument does — what was run, what it
 * moved, how it moved it, who it hit, what it means, and where to go next —
 * and every one of them is either present with its figures or absent with its
 * reason. None is decorative and none is a placeholder.
 */

import * as React from "react";
import { Download, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import {
  BeforeAfterChart,
  ColourKey,
  ContributionChart,
  CutChart,
  LevelsChart,
  Panel,
  WaterfallChart,
  count,
  money,
  ratioPct,
} from "./charts";

type Loose = Record<string, unknown>;

function asRows(value: unknown): Loose[] {
  return Array.isArray(value) ? (value as Loose[]) : [];
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** A signed figure, coloured by which way it went. */
function Moved({ value, as = "money" }: { value: unknown; as?: "money" | "pct" }) {
  const n = Number(value);
  if (!Number.isFinite(n)) return <span className="text-text-muted">—</span>;
  return (
    <span className={cn("tabular-nums",
                        n > 0 ? "text-negative" : n < 0 ? "text-positive"
                                                        : "text-text-secondary")}>
      {n > 0 ? "+" : ""}
      {as === "money" ? money(n) : `${(n * 100).toFixed(2)}%`}
    </span>
  );
}

export function ResultBlock({ result, onFollowUp, onDownload, downloading }: {
  result: Loose;
  onFollowUp: (said: string) => void;
  onDownload: () => void;
  downloading?: boolean;
}) {
  const levels = asRows(result.levels);
  const cohort = levels.find((one) => one.level === "selection") ?? levels[0];
  const before = (cohort?.before ?? {}) as Loose;
  const after = (cohort?.after ?? {}) as Loose;
  const delta = (cohort?.delta ?? {}) as Loose;
  const method = (result.methodology ?? {}) as Loose;
  const steps = (result.waterfall ?? {}) as Loose;
  const challenger = result.challenger as Loose | undefined;
  const cuts = asRows((result.baseline as Loose | undefined)?.cuts);
  const engine = (cohort?.engine ?? {}) as Loose;

  return (
    <div className="space-y-3" data-testid="ews-whatif-result">
      {/* ---------------------------------------- 1-4. what ran, and the top */}
      <Card className="p-4" data-testid="whatif-result-summary">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold text-text-primary">
            {String(result.shocks_described ?? "Scenario")}
          </p>
          <Badge variant="outline">{String(method.name ?? "")}</Badge>
          {result.narrowing ? (
            <Badge variant="outline" data-testid="whatif-narrowing">
              {String(result.narrowing)}
            </Badge>
          ) : null}
        </div>
        <p className="mt-0.5 text-[11px] text-text-muted">
          {String(cohort?.label ?? "")} · {String(method.authority ?? "")}
        </p>

        <dl className="mt-3 grid gap-3 text-[12px] sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Customers", count(before.customers)],
            ["Accounts", count(before.accounts)],
            ["Exposure", money(before.exposure_sar)],
            ["ECL before", money(before.ecl_weighted_sar)],
            ["ECL after", money(after.ecl_weighted_sar)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {label}
              </dt>
              <dd className="tabular-nums text-text-primary">{value}</dd>
            </div>
          ))}
          <div>
            <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
              Change
            </dt>
            <dd className="font-medium">
              <Moved value={delta.ecl_weighted_sar} />{" "}
              <span className="text-[11px]">
                (<Moved value={num(delta.ecl_weighted_sar_pct) / 100} as="pct" />)
              </span>
            </dd>
          </div>
        </dl>
      </Card>

      {/* --------------------------------------------- 5-6. the mechanism */}
      {steps.available ? (
        <Panel title="How the number moved"
               note={String(steps.basis ?? "")}
               testId="whatif-waterfall">
          <WaterfallChart steps={asRows(steps.steps) as never}
                          baseline={num(steps.baseline_sar)}
                          final={num(steps.final_sar)} />
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-[11px]"
                   data-testid="whatif-waterfall-table">
              <thead>
                <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  {["Step", "From", "To", "Change", "Change %",
                    "Facilities moved"].map((one) => (
                    <th key={one} className="px-2 py-1 text-left">{one}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-border/60">
                  <td className="px-2 py-1 text-text-secondary">Baseline</td>
                  <td className="px-2 py-1" />
                  <td className="px-2 py-1 tabular-nums">
                    {money(steps.baseline_sar)}
                  </td>
                  <td className="px-2 py-1" />
                  <td className="px-2 py-1" />
                  <td className="px-2 py-1" />
                </tr>
                {asRows(steps.steps).map((one, index) => (
                  <tr key={`${String(one.key)}-${index}`}
                      className="border-t border-border/60">
                    <td className="px-2 py-1 font-medium text-text-primary">
                      {String(one.label)}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {money(one.from_sar)}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {money(one.to_sar)}
                    </td>
                    <td className="px-2 py-1"><Moved value={one.change_sar} /></td>
                    <td className="px-2 py-1">
                      <Moved value={one.change_pct} as="pct" />
                    </td>
                    <td className="px-2 py-1 tabular-nums text-text-secondary">
                      {one.facilities_moved === null
                       || one.facilities_moved === undefined
                        ? "every facility" : count(one.facilities_moved)}
                    </td>
                  </tr>
                ))}
                <tr className="border-t-2 border-border font-medium">
                  <td className="px-2 py-1 text-text-primary">After</td>
                  <td className="px-2 py-1" />
                  <td className="px-2 py-1 tabular-nums">
                    {money(steps.final_sar)}
                  </td>
                  <td className="px-2 py-1">
                    <Moved value={steps.total_change_sar} />
                  </td>
                  <td className="px-2 py-1">
                    <Moved value={steps.total_change_pct} as="pct" />
                  </td>
                  <td className="px-2 py-1" />
                </tr>
              </tbody>
            </table>
          </div>
        </Panel>
      ) : (
        <Panel title="How the number moved"
               empty={String(steps.because
                 ?? "This scenario applied no shock to decompose.")}
               testId="whatif-waterfall" />
      )}

      {/* ------------------------------------------------ before and after */}
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Before and after"
               note="The cohort's own position, on the measures a scenario moves."
               testId="whatif-before-after">
          <BeforeAfterChart rows={[
            { measure: "PIT 12m PD (%)",
              before: num(before.pd_pit_12m) * 100,
              after: num(after.pd_pit_12m) * 100 },
            { measure: "Lifetime PD (%)",
              before: num(before.pd_pit_lifetime) * 100,
              after: num(after.pd_pit_lifetime) * 100 },
            { measure: "LGD (%)",
              before: num(before.lgd) * 100, after: num(after.lgd) * 100 },
            { measure: "Coverage (%)",
              before: num(before.ecl_coverage_pct),
              after: num(after.ecl_coverage_pct) },
          ]} />
        </Panel>

        <Panel title="The same movement, at five widths"
               note="The riyal figure is identical everywhere — stressing a
                     cohort cannot change anything outside it. What changes is
                     how large it looks."
               testId="whatif-levels-panel">
          <LevelsChart rows={levels.map((one) => ({
            label: String(one.label),
            pct: num((one.delta as Loose)?.ecl_weighted_sar_pct) / 100,
          }))} />
        </Panel>
      </div>

      {/* ------------------------------------------- 8. impact by level */}
      <Panel title="Impact by level" testId="whatif-levels-table">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-[12px]"
                 data-testid="ews-whatif-levels">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {["Level", "Customers", "Accounts", "Exposure",
                  "ECL before", "ECL after", "Change", "Change %"].map((one) => (
                  <th key={one} className="px-2 py-1 text-left">{one}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {levels.map((one) => {
                const was = (one.before ?? {}) as Loose;
                const now = (one.after ?? {}) as Loose;
                const moved = (one.delta ?? {}) as Loose;
                return (
                  <tr key={String(one.level)} className="border-t border-border/60"
                      data-testid={`ews-whatif-level-${String(one.level)}`}>
                    <td className="px-2 py-1 font-medium text-text-primary">
                      {String(one.label)}
                    </td>
                    <td className="px-2 py-1 tabular-nums">{count(was.customers)}</td>
                    <td className="px-2 py-1 tabular-nums">{count(was.accounts)}</td>
                    <td className="px-2 py-1 tabular-nums">
                      {money(was.exposure_sar)}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {money(was.ecl_weighted_sar)}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {money(now.ecl_weighted_sar)}
                    </td>
                    <td className="px-2 py-1">
                      <Moved value={moved.ecl_weighted_sar} />
                    </td>
                    <td className="px-2 py-1">
                      <Moved value={num(moved.ecl_weighted_sar_pct) / 100}
                             as="pct" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ----------------------------------------- 10. top segments hit */}
      {asRows(engine.drivers).length ? (
        <Panel title="Where the movement landed"
               note="By product, worst first."
               testId="whatif-drivers">
          <ContributionChart rows={asRows(engine.drivers).map((one) => ({
            label: String(one.product_code ?? ""),
            change_sar: num(one.delta_sar),
          }))} />
        </Panel>
      ) : null}

      {/* ---------------------------------------- the cohort it ran on */}
      {cuts.length ? (
        <Panel title="What the cohort looked like"
               note="Each cut as it stood before the scenario ran."
               testId="whatif-cohort-charts">
          <div className="grid gap-4 lg:grid-cols-2">
            {cuts.filter((one) => one.available).slice(0, 4).map((one) => (
              <div key={String(one.key)}>
                <p className="mb-1 text-[10px] uppercase tracking-[0.08em]
                              text-text-muted">
                  {String(one.label)}
                </p>
                <CutChart cut={one as never} />
              </div>
            ))}
          </div>
          <div className="mt-3"><ColourKey /></div>
        </Panel>
      ) : null}

      {/* ------------------------------------------ 14. the challenger */}
      {challenger ? (
        <Card className="p-4" data-testid="ews-whatif-challenger">
          <div className="flex flex-wrap items-baseline gap-2">
            <p className="text-sm font-semibold text-text-primary">
              {String(challenger.name ?? "Challenger")}
            </p>
            {challenger.estimator ? (
              <span className="text-[11px] text-text-muted"
                    data-testid="ews-whatif-challenger-estimator">
                fitted with {String(challenger.estimator)}
                {challenger.fitted_on
                  ? ` on ${count(challenger.fitted_on)} rows` : ""}
              </span>
            ) : null}
          </div>
          {challenger.available ? (
            <>
              <dl className="mt-2 grid gap-3 text-[12px] sm:grid-cols-4">
                {[["Challenger before", money(challenger.estimated_ecl_before_sar)],
                  ["Challenger after", money(challenger.estimated_ecl_after_sar)],
                  ["Challenger change", money(challenger.estimated_delta_sar)],
                  ["Delta method change",
                   money(challenger.delta_method_delta_sar)]].map(([l, v]) => (
                  <div key={l}>
                    <dt className="text-[9px] uppercase tracking-[0.08em]
                                   text-text-muted">{l}</dt>
                    <dd className="tabular-nums text-text-primary">{v}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-[11px] text-text-secondary">
                {String(challenger.agreement ?? "")}{" "}
                {String(challenger.note ?? "")}
              </p>
            </>
          ) : (
            <p className="mt-2 text-[12px] italic text-text-muted">
              Not run: {String(challenger.because ?? "")}
            </p>
          )}
        </Card>
      ) : null}

      {/* --------------------------------------------- 9. interpretation */}
      {result.interpretation ? (
        <Card className="border-accent/30 bg-accent-muted/20 p-4"
              data-testid="ews-whatif-interpretation">
          <p className="text-sm font-semibold text-text-primary">
            AI Interpretation
          </p>
          <p className="mt-1 text-[13px] leading-relaxed text-text-secondary">
            {String(result.interpretation)}
          </p>
        </Card>
      ) : null}

      {/* ------------------------------ 12-13. take it away, or go on */}
      <Card className="p-4" data-testid="whatif-result-actions">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onDownload} disabled={downloading}
                  data-testid="whatif-download-workbook">
            {downloading
              ? <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />
              : <Download className="mr-1 size-3.5" aria-hidden />}
            Download detailed Excel
          </Button>
          <span className="text-[11px] text-text-muted">
            Thirteen sheets: the scenario, the waterfall, the cohort, every
            level, the affected customers and facilities before and after, the
            parameters, and the method.
          </span>
        </div>

        {asRows(result.follow_ups).length ? (
          <div className="mt-3">
            <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
              What to test next
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {(result.follow_ups as string[]).map((one) => (
                <button key={one} type="button"
                        onClick={() => onFollowUp(one)}
                        className="rounded-full border border-border px-2.5 py-1
                                   text-[11px] text-text-secondary
                                   transition-colors hover:bg-surface-muted"
                        data-testid="whatif-follow-up">
                  {one}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </Card>

      {/* ------------------------------------------------- what it assumed */}
      {(asRows(result.assumptions).length
        || asRows(result.limitations).length) ? (
        <details className="rounded-lg border border-border px-4 py-2"
                 data-testid="whatif-assumptions">
          <summary className="cursor-pointer text-[12px] text-text-secondary">
            What this assumed, and what it does not claim
          </summary>
          <ul className="mt-2 space-y-1 text-[11px] text-text-muted">
            {[...(result.assumptions as string[] ?? []),
              ...(result.limitations as string[] ?? [])].map((one, index) => (
              <li key={index}>· {String(one)}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export { money, count, ratioPct };
