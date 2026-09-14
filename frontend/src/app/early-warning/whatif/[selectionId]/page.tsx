"use client";

/**
 * The What-If thread a cohort arrives in, having been exported from Early
 * Warning.
 *
 * The point of the handoff is that the customers a reader was looking at are
 * the customers that get stressed. So the first thing this screen does is say
 * exactly what arrived — how many customers, how many accounts, how much
 * exposure, from which card, at which month, under which model version — and
 * offer the way back to where it came from.
 *
 * Then the baseline, before any scenario: the cohort's IFRS 9 position and
 * how it distributes across days past due, score band, stage, sub-product and
 * the Early Warning cuts. A scenario result means nothing without the
 * position it moved from.
 *
 * Then a methodology, chosen rather than assumed, and a result reported at
 * every level above the selection — because a shock that halves a cohort's
 * expected loss and moves total Retail by four basis points is two facts and a
 * reader needs both.
 */

import Link from "next/link";
import * as React from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, FlaskConical, Loader2, Sparkles, Users,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api, type EwsCohortResult, type EwsSelectionView,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { money } from "../../parts";

/** The scenarios the chat box understands, mapped to governed shocks. */
const SHOCKS: { match: RegExp; build: (m: RegExpMatchArray) =>
  Record<string, number>; }[] = [
  { match: /pd.*?([-+]?\d+(?:\.\d+)?)\s*%/i,
    build: (m) => ({ pd_relative: Number(m[1]) / 100 }) },
  { match: /lgd.*?([-+]?\d+(?:\.\d+)?)\s*(?:percentage points|pp|%)/i,
    build: (m) => ({ lgd_relative: Number(m[1]) / 100 }) },
  { match: /collateral.*?([-+]?\d+(?:\.\d+)?)\s*%/i,
    build: (m) => ({ collateral_value_pct: -Math.abs(Number(m[1])) / 100 }) },
  { match: /utilisation.*?([-+]?\d+(?:\.\d+)?)\s*(?:percentage points|pp|%)/i,
    build: (m) => ({ utilisation_pp: Number(m[1]) }) },
  { match: /ccf.*?([-+]?\d+(?:\.\d+)?)/i,
    build: (m) => ({ ccf_absolute: Number(m[1]) / 100 }) },
  { match: /income.*?([-+]?\d+(?:\.\d+)?)\s*%/i,
    build: (m) => ({ income_pct: -Math.abs(Number(m[1])) / 100 }) },
];

function readScenario(said: string): Record<string, number> | null {
  for (const one of SHOCKS) {
    const found = said.match(one.match);
    if (found) return one.build(found);
  }
  return null;
}

function pct(value: unknown, places = 2): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(places)}%` : "—";
}

function num(value: unknown, places = 4): string {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(places) : "—";
}

export default function ImportedWhatIfPage() {
  const params = useParams<{ selectionId: string }>();
  const selectionId = String(params?.selectionId ?? "");
  const load = React.useCallback(
    () => api.ewsSelection(selectionId), [selectionId]);
  const { data, loading, error } = useAsync<EwsSelectionView>(load, [load]);

  const [method, setMethod] = React.useState("delta");
  const [typed, setTyped] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState<EwsCohortResult | null>(null);
  const [problem, setProblem] = React.useState("");
  const [showCustomers, setShowCustomers] = React.useState(false);
  const [customers, setCustomers] =
    React.useState<Record<string, unknown>[]>([]);

  const runScenario = React.useCallback(async (said: string) => {
    const shocks = readScenario(said);
    if (!shocks) {
      setProblem(
        `This thread could not read a governed shock out of "${said}". `
        + "Try a scenario naming a parameter and a size, such as "
        + "'Increase PIT 12-month PD by 20%'.");
      return;
    }
    setBusy(true);
    setProblem("");
    try {
      setResult(await api.ewsSelectionRun({
        selection_id: selectionId, shocks, name: said, method }));
    } catch (failed) {
      setProblem(String(failed));
    } finally {
      setBusy(false);
    }
  }, [method, selectionId]);

  const openCustomers = React.useCallback(async () => {
    setShowCustomers((was) => !was);
    if (customers.length) return;
    try {
      const got = await api.ewsSelectionCustomers(selectionId, 200);
      setCustomers(got.customers);
    } catch (failed) {
      setProblem(String(failed));
    }
  }, [customers.length, selectionId]);

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) {
    return <EmptyState title="This selection could not be read"
                       description={String(error)} />;
  }
  if (!data) return null;

  const selection = data.selection;
  const baseline = data.baseline;
  const backTo = selection.source_route || "/early-warning";

  return (
    <div className="space-y-6" data-testid="ews-whatif-thread">
      <PageHeader
        eyebrow="What-If Analysis"
        title="Imported from Early Warning Score"
        description={selection.source_label}
        status="live"
        phase="Governed model on synthetic demonstration data"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href={backTo} data-testid="ews-whatif-back-to-source">
                <ArrowLeft aria-hidden /> Back to the source card
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/what-if" data-testid="ews-whatif-open-module">
                <FlaskConical aria-hidden /> What-If Analysis
              </Link>
            </Button>
          </div>
        }
      />

      {/* ------------------------------------------------ what arrived */}
      <Card className="p-4" data-testid="ews-whatif-source">
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className="size-4 text-accent" aria-hidden />
          <p className="text-sm font-semibold text-text-primary">
            Source: Early Warning Score
          </p>
          <Badge variant="outline">{selection.selection_id}</Badge>
          <span className="text-[11px] text-text-muted">
            model {selection.source_model_version} · rulebook{" "}
            {selection.source_rulebook_version} · exported{" "}
            {selection.created_at}
          </span>
        </div>
        <dl className="mt-3 grid gap-3 text-[12px] sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Month", selection.source_month],
            ["Portfolio", selection.source_product || "Total Retail"],
            ["Classification", selection.source_classification || "—"],
            ["Sub-product", selection.source_sub_product || "—"],
            ["Selection",
             `${selection.selected_customer_count.toLocaleString()} customers `
             + `/ ${selection.selected_account_count.toLocaleString()} accounts`],
            ["Exposure", money(selection.selected_exposure_sar)],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {label}
              </dt>
              <dd className="text-text-primary">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-[12px] text-text-secondary"
           data-testid="ews-whatif-profile">
          Early Warning profile: {selection.high_or_critical.toLocaleString()}{" "}
          High or Critical, {selection.current_bad.toLocaleString()} already
          bad, {selection.forward_risk.toLocaleString()} forward risk. Source
          Early Warning Score {selection.ews_score.toFixed(1)}{" "}
          {selection.ews_severity}.
        </p>

        {/* §32: what share of each parent this cohort is. */}
        <div className="mt-3 rounded-md border border-border
                        bg-surface-muted/30 p-3"
             data-testid="ews-whatif-materiality">
          <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
            This selected cohort represents
          </p>
          <div className="mt-1 flex flex-wrap gap-4 text-[12px]">
            {(["classification", "product", "retail"] as const).map((key) => {
              const share = selection.materiality?.[key];
              if (!share) return null;
              return (
                <span key={key} className="text-text-secondary">
                  <span className="font-medium text-text-primary">
                    {share.exposure_pct.toFixed(1)}%
                  </span>{" "}
                  of {key === "retail" ? "total Retail" : key} exposure ·{" "}
                  {share.accounts_pct.toFixed(1)}% of its accounts
                </span>
              );
            })}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => void openCustomers()}
                  data-testid="ews-whatif-view-customers">
            <Users className="mr-1 size-3.5" aria-hidden />
            {showCustomers ? "Hide the selected customers"
                           : "View selected customers"}
          </Button>
          <details className="text-[11px] text-text-secondary">
            <summary className="cursor-pointer rounded-full border
                                border-border px-2.5 py-1"
                     data-testid="ews-whatif-definition">
              View selection definition
            </summary>
            <pre className="mt-2 max-w-full overflow-x-auto rounded border
                            border-border bg-surface-muted/40 p-2 text-[10px]">
{JSON.stringify({
  selection_id: selection.selection_id,
  source_module: selection.source_module,
  source_route: selection.source_route,
  source_level: selection.source_level,
  filters: selection.source_filters,
  taxonomy: selection.taxonomy_version,
  created_by: selection.created_by,
}, null, 1)}
            </pre>
          </details>
        </div>

        {showCustomers ? (
          <div className="mt-3 max-h-72 overflow-auto rounded border
                          border-border"
               data-testid="ews-whatif-customer-list">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-surface">
                <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  {["Customer", "Facility", "Sub-product", "EWS", "Severity",
                    "DPD", "Stage", "Exposure"].map((one) => (
                    <th key={one} className="px-2 py-1 text-left">{one}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {customers.map((row, index) => (
                  <tr key={index} className="border-t border-border/60">
                    <td className="px-2 py-1">
                      {String(row.customer_name ?? row.customer_id ?? "")}
                    </td>
                    <td className="px-2 py-1 font-mono text-[10px]">
                      {String(row.facility_id ?? "")}
                    </td>
                    <td className="px-2 py-1">
                      {String(row.sub_product_label ?? "")}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {Number(row.ews_score ?? 0).toFixed(1)}
                    </td>
                    <td className="px-2 py-1">
                      {String(row.ews_severity ?? "")}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {String(row.dpd ?? "")}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {String(row.ifrs9_stage ?? "")}
                    </td>
                    <td className="px-2 py-1 tabular-nums">
                      {money(Number(row.gross_carrying_amount_sar ?? 0))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>

      {/* ------------------------------------------------ the baseline */}
      {baseline?.available ? (
        <Card className="p-4" data-testid="ews-whatif-baseline">
          <p className="text-sm font-semibold text-text-primary">
            Baseline, before any scenario
          </p>
          <dl className="mt-3 grid gap-3 text-[12px] sm:grid-cols-4 lg:grid-cols-6">
            {[
              ["TTC PD", pct(baseline.ifrs9.pd_ttc_12m)],
              ["PIT 12m PD", pct(baseline.ifrs9.pd_pit_12m)],
              ["Lifetime PD", pct(baseline.ifrs9.pd_pit_lifetime)],
              ["LGD", pct(baseline.ifrs9.lgd)],
              ["CCF", num(baseline.ifrs9.ccf, 3)],
              ["EAD", money(Number(baseline.ifrs9.ead_sar ?? 0))],
              ["Collateral",
               money(Number(baseline.ifrs9.collateral_value_sar ?? 0))],
              ["Base ECL", money(Number(baseline.ifrs9.ecl_base_sar ?? 0))],
              ["Upturn ECL", money(Number(baseline.ifrs9.ecl_upturn_sar ?? 0))],
              ["Downturn ECL",
               money(Number(baseline.ifrs9.ecl_downturn_sar ?? 0))],
              ["Weighted ECL",
               money(Number(baseline.ifrs9.ecl_weighted_sar ?? 0))],
              ["Coverage", `${num(baseline.ifrs9.ecl_coverage_pct, 2)}%`],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  {label}
                </dt>
                <dd className="tabular-nums text-text-primary">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-4 space-y-4">
            {baseline.cuts.filter((cut) => cut.available && cut.rows?.length)
              .map((cut) => (
              <div key={cut.key}
                   data-testid={`ews-whatif-cut-${cut.key}`}>
                <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
                  {cut.label}
                </p>
                <div className="overflow-x-auto">
                  <table className="mt-1 w-full min-w-[640px] text-[11px]">
                    <thead>
                      <tr className="text-[9px] uppercase tracking-[0.06em] text-text-muted">
                        {["Band", "Customers", "Accounts", "Exposure", "PD",
                          "LGD", "EAD", "Weighted ECL"].map((one) => (
                          <th key={one} className="px-2 py-1 text-left">
                            {one}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {cut.rows!.map((row) => (
                        <tr key={row.value}
                            className="border-t border-border/60">
                          <td className="px-2 py-1 text-text-primary">
                            {row.label}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {row.customers.toLocaleString()}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {row.accounts.toLocaleString()}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {money(row.exposure_sar)}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {pct(row.pd_pit_12m)}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {pct(row.lgd)}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {money(row.ead_sar)}
                          </td>
                          <td className="px-2 py-1 tabular-nums">
                            {money(row.ecl_weighted_sar)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card className="p-4 text-sm text-text-secondary">
          The baseline could not be read: {baseline?.because}
        </Card>
      )}

      {/* ------------------------------------------------ the scenario */}
      <Card className="p-4" data-testid="ews-whatif-composer">
        <p className="text-sm font-semibold text-text-primary">
          Run a scenario on this cohort
        </p>
        <p className="mt-1 text-[11px] text-text-muted">
          {data.methodologies.question} {data.methodologies.note}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5"
             data-testid="ews-whatif-methods">
          {[...data.methodologies.methods,
            { key: "both", name: "Run both", what: "", version: "",
              authority: "" }].map((one) => (
            <button key={one.key} type="button" onClick={() => setMethod(one.key)}
                    title={one.what}
                    data-testid={`ews-whatif-method-${one.key}`}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs transition-colors",
                      method === one.key
                        ? "border-accent bg-accent-subtle text-accent"
                        : "border-border text-text-secondary hover:bg-surface-muted")}>
              {one.name}
            </button>
          ))}
        </div>

        <div className="mt-3 flex items-end gap-2">
          <textarea
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void runScenario(typed);
              }
            }}
            rows={2}
            aria-label="Describe a scenario for this cohort"
            data-testid="ews-whatif-input"
            placeholder="Increase PIT 12-month PD by 20%"
            className="min-h-[52px] flex-1 resize-none rounded-md border
                       border-border bg-surface px-3 py-2 text-sm
                       text-text-primary placeholder:text-text-muted"
          />
          <Button size="sm" onClick={() => void runScenario(typed)}
                  disabled={busy} data-testid="ews-whatif-run">
            {busy ? <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />
                  : null}
            Run
          </Button>
        </div>

        <div className="mt-2 flex flex-wrap gap-1.5"
             data-testid="ews-whatif-prompts">
          {data.prompts.map((one) => (
            <button key={one} type="button" onClick={() => void runScenario(one)}
                    className="rounded-full border border-border px-2.5 py-1
                               text-[11px] text-text-secondary
                               transition-colors hover:bg-surface-muted">
              {one}
            </button>
          ))}
        </div>

        {problem ? (
          <p className="mt-2 text-[12px] text-negative"
             data-testid="ews-whatif-problem">{problem}</p>
        ) : null}
      </Card>

      {result ? <Result result={result} onFollowUp={runScenario} /> : null}
    </div>
  );
}

/** The result, at every level the selection sits inside. */
function Result({ result, onFollowUp }: {
  result: EwsCohortResult;
  onFollowUp: (said: string) => void;
}) {
  const challenger = result.challenger as Record<string, unknown> | undefined;
  return (
    <div className="space-y-4" data-testid="ews-whatif-result">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold text-text-primary">
            {result.shocks_described}
          </p>
          <Badge variant="outline">{result.methodology.name}</Badge>
        </div>
        <p className="mt-1 text-[11px] text-text-muted">
          {result.methodology.authority}
        </p>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[760px] text-[12px]"
                 data-testid="ews-whatif-levels">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {["Level", "Customers", "Accounts", "Exposure",
                  "Weighted ECL before", "Weighted ECL after", "Change",
                  "Change %"].map((one) => (
                  <th key={one} className="px-2 py-1 text-left">{one}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.levels.map((level) => (
                <tr key={level.level} className="border-t border-border/60"
                    data-testid={`ews-whatif-level-${level.level}`}>
                  <td className="px-2 py-1 font-medium text-text-primary">
                    {level.label}
                  </td>
                  <td className="px-2 py-1 tabular-nums">
                    {Number(level.before.customers ?? 0).toLocaleString()}
                  </td>
                  <td className="px-2 py-1 tabular-nums">
                    {Number(level.before.accounts ?? 0).toLocaleString()}
                  </td>
                  <td className="px-2 py-1 tabular-nums">
                    {money(Number(level.before.exposure_sar ?? 0))}
                  </td>
                  <td className="px-2 py-1 tabular-nums">
                    {money(Number(level.before.ecl_weighted_sar ?? 0))}
                  </td>
                  <td className="px-2 py-1 tabular-nums">
                    {money(Number(level.after.ecl_weighted_sar ?? 0))}
                  </td>
                  <td className={cn("px-2 py-1 tabular-nums",
                                    Number(level.delta.ecl_weighted_sar ?? 0) > 0
                                      ? "text-negative" : "text-positive")}>
                    {money(Number(level.delta.ecl_weighted_sar ?? 0))}
                  </td>
                  <td className={cn("px-2 py-1 tabular-nums",
                                    Number(level.delta.ecl_weighted_sar_pct ?? 0) > 0
                                      ? "text-negative" : "text-positive")}>
                    {level.delta.ecl_weighted_sar_pct === null
                     || level.delta.ecl_weighted_sar_pct === undefined
                      ? "—"
                      : `${Number(level.delta.ecl_weighted_sar_pct).toFixed(2)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {challenger ? (
        <Card className="p-4" data-testid="ews-whatif-challenger">
          <p className="text-sm font-semibold text-text-primary">
            {String(challenger.name ?? "Challenger")}
          </p>
          {challenger.available ? (
            <>
              <dl className="mt-2 grid gap-3 text-[12px] sm:grid-cols-4">
                {[
                  ["Challenger before",
                   money(Number(challenger.estimated_ecl_before_sar ?? 0))],
                  ["Challenger after",
                   money(Number(challenger.estimated_ecl_after_sar ?? 0))],
                  ["Challenger change",
                   money(Number(challenger.estimated_delta_sar ?? 0))],
                  ["Delta method change",
                   money(Number(challenger.delta_method_delta_sar ?? 0))],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                      {label}
                    </dt>
                    <dd className="tabular-nums text-text-primary">{value}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-2 text-[12px] text-text-secondary">
                {String(challenger.agreement ?? "")} {String(challenger.note ?? "")}
              </p>
            </>
          ) : (
            <p className="mt-1 text-[12px] text-text-secondary">
              Not run: {String(challenger.because ?? "")}
            </p>
          )}
        </Card>
      ) : null}

      <Card className="border-accent/30 bg-accent-subtle/20 p-4"
            data-testid="ews-whatif-interpretation">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent" aria-hidden />
          <p className="text-sm font-semibold text-text-primary">
            AI Interpretation
          </p>
        </div>
        <p className="mt-2 text-[13px] leading-relaxed text-text-primary">
          {result.interpretation}
        </p>
        {result.limitations?.length ? (
          <ul className="mt-2 space-y-0.5">
            {result.limitations.map((one) => (
              <li key={one} className="text-[11px] text-text-muted">• {one}</li>
            ))}
          </ul>
        ) : null}
      </Card>

      {result.follow_ups?.length ? (
        <Card className="p-4" data-testid="ews-whatif-follow-ups">
          <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
            What to test next
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {result.follow_ups.map((one) => (
              <button key={one} type="button" onClick={() => onFollowUp(one)}
                      className="rounded-full border border-accent/40
                                 bg-accent-subtle/50 px-2.5 py-1 text-[11px]
                                 text-accent transition-colors
                                 hover:bg-accent-subtle">
                {one}
              </button>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
