"use client";

/**
 * The What-If thread a cohort arrives in, having been exported from Early
 * Warning Score.
 *
 * A thread, and not a form
 * -----------------------
 * This page used to hold one result and replace it every time somebody ran
 * something. That is the wrong shape for the work: a scenario is rarely the
 * end of a question, it is the middle of one — you stress the cohort, see
 * where it landed, narrow to the part that moved, run it again, and compare.
 * Replacing the answer each time threw away the comparison the reader was
 * building, and left them retyping what they had already asked.
 *
 * So it is a conversation. What you asked and what came back stack downwards
 * in the order they happened, the composer stays at the bottom where your
 * hands are, and nothing that has been answered is taken away.
 *
 * The reading is done by the engine, not here
 * -------------------------------------------
 * Typed sentences go to the governed parser in
 * `backend.retail.whatif_language`, which is the reader the rest of What-If
 * uses. This page briefly carried its own — six regular expressions — and the
 * result was a thread that understood less than the composer on the next
 * screen. A sentence the parser cannot read comes back as a QUESTION in the
 * thread, which is an answer and not an error: the engine refuses to guess a
 * unit or a cohort, and saying so is the honest form of that refusal.
 *
 * What the cohort carries
 * -----------------------
 * The selection carries an exact list of customers and facilities, so the
 * scenario runs on precisely the people the card named. A sentence may NARROW
 * it — "stress only the forward-risk customers in this selection" — and never
 * widens it. Every result is then reported at five widths, because the same
 * riyal movement is alarming inside a sub-product and immaterial across the
 * book, and a reader needs both to decide anything.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import {
  ArrowLeft, FlaskConical, Loader2, Send, Sparkles, Users,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EwsSelectionView } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { ColourKey, CutChart, Panel, count, money } from "../charts";
import { ResultBlock } from "../result";

type Loose = Record<string, unknown>;

/**
 * `Omit` over a union collapses it to the keys they share, which for these
 * four is only `kind` — so `Omit<Turn, "id">` rejected every field. Mapping
 * over the members keeps them apart.
 */
type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;

type Turn =
  | { id: number; kind: "said"; text: string }
  | { id: number; kind: "result"; said: string; result: Loose }
  | { id: number; kind: "asked"; question: string; readAs: string[] }
  | { id: number; kind: "note"; text: string; tone: "warn" | "note" };

/**
 * The scenarios offered beside the composer.
 *
 * Chips, rather than a menu of parameters, because the engine reads sentences
 * and the fastest way to show somebody that is to hand them one to press. Each
 * is a complete instruction the parser resolves — nothing here is a keyword
 * the page translates.
 */
const CHIPS: string[] = [
  "Increase PIT 12-month PD by 20%",
  "Increase LGD by 5%",
  "Reduce verified income by 10%",
  "Increase household expense burden by 10%",
  "Move 20% of 30-59 DPD exposure to 90+",
  "Move 15% of Stage 1 exposure to Stage 2",
  "Move 20% of behavioural score band B to C band",
  "Increase card utilisation by 10 percentage points",
  "Increase CCF by 10 percentage points",
  "Reduce collateral value by 15%",
  "Stress only the forward-risk customers in this selection",
  "Stress only the customers who are already bad",
];

const METHODS: { key: string; label: string; hint: string }[] = [
  { key: "delta", label: "Delta method",
    hint: "Deterministic recalculation of the IFRS 9 identity. The "
        + "calculation of record." },
  { key: "xgboost", label: "XGBoost challenger",
    hint: "A gradient-boosted estimator fitted on this book. Shown for "
        + "comparison, never substituted." },
  { key: "both", label: "Run both",
    hint: "Calculates the scenario twice and compares them. Where they "
        + "disagree, the Delta method stands." },
];

function pct(value: unknown, places = 2): string {
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(places)}%` : "—";
}

function num(value: unknown, places = 4): string {
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
  const [downloading, setDownloading] = React.useState("");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [showCustomers, setShowCustomers] = React.useState(false);
  const [customers, setCustomers] =
    React.useState<Record<string, unknown>[]>([]);
  const foot = React.useRef<HTMLDivElement>(null);
  const nextId = React.useRef(1);

  const add = React.useCallback((turn: WithoutId<Turn>) => {
    setTurns((was) => [...was, { ...turn, id: nextId.current++ } as Turn]);
  }, []);

  // The thread grows downwards and the newest turn is the one being read, so
  // the page follows it. Only when a turn is ADDED — scrolling on every render
  // would fight a reader who has scrolled back to compare two results, which
  // is the main reason the thread keeps them.
  React.useEffect(() => {
    if (turns.length) {
      foot.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [turns.length]);

  const run = React.useCallback(async (said: string) => {
    const sentence = said.trim();
    if (!sentence || busy) return;
    setTyped("");
    add({ kind: "said", text: sentence });
    setBusy(true);
    try {
      const got = await api.ewsSelectionRun({
        selection_id: selectionId, said: sentence, method });
      if (got.needs_clarification) {
        add({ kind: "asked", question: String(got.question ?? ""),
              readAs: (got.read_as as string[]) ?? [] });
      } else {
        add({ kind: "result", said: sentence,
              result: got as unknown as Loose });
      }
    } catch (failed) {
      add({ kind: "note", tone: "warn", text: String(failed) });
    } finally {
      setBusy(false);
    }
  }, [add, busy, method, selectionId]);

  const download = React.useCallback(async (said: string) => {
    setDownloading(said);
    try {
      const { blob, filename } = await api.ewsSelectionWorkbook({
        selection_id: selectionId, said, method });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (failed) {
      add({ kind: "note", tone: "warn",
            text: `The workbook could not be built: ${String(failed)}` });
    } finally {
      setDownloading("");
    }
  }, [add, method, selectionId]);

  const openCustomers = React.useCallback(async () => {
    setShowCustomers((was) => !was);
    if (customers.length) return;
    try {
      const got = await api.ewsSelectionCustomers(selectionId, 200);
      setCustomers(got.customers);
    } catch (failed) {
      add({ kind: "note", tone: "warn", text: String(failed) });
    }
  }, [add, customers.length, selectionId]);

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
    <div className="space-y-4 pb-2" data-testid="ews-whatif-thread">
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
            {selection.source_rulebook_version} · exported {selection.created_at}
          </span>
        </div>
        <dl className="mt-3 grid gap-3 text-[12px] sm:grid-cols-3 lg:grid-cols-6">
          {[
            ["Month", selection.source_month],
            ["Portfolio", selection.source_product || "Total Retail"],
            ["Classification", selection.source_classification || "—"],
            ["Sub-product", selection.source_sub_product || "—"],
            ["Selection",
             `${count(selection.selected_customer_count)} customers / `
             + `${count(selection.selected_account_count)} accounts`],
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
          Early Warning profile: {count(selection.high_or_critical)} High or
          Critical, {count(selection.current_bad)} already bad,{" "}
          {count(selection.forward_risk)} forward risk. Source Early Warning
          Score {selection.ews_score.toFixed(1)} {selection.ews_severity}.
        </p>

        <div className="mt-3 rounded-md border border-border bg-surface-muted/30 p-3"
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

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void openCustomers()}
                  data-testid="ews-whatif-view-customers">
            <Users className="mr-1 size-3.5" aria-hidden />
            {showCustomers ? "Hide the selected customers"
                           : "View selected customers"}
          </Button>
          <details className="text-[11px] text-text-secondary">
            <summary className="cursor-pointer rounded-full border border-border
                                px-2.5 py-1"
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
          <div className="mt-3 max-h-72 overflow-auto rounded border border-border"
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
                    <td className="px-2 py-1">{String(row.ews_severity ?? "")}</td>
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
        <>
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
          </Card>

          {/* The same cuts, drawn. The tables below hold the figures; these
              hold the shape, which is what a reader is looking for when they
              ask where the risk sits. */}
          <Panel title="The cohort, drawn"
                 note="Every cut of the selection as it stands before any scenario runs."
                 testId="ews-whatif-cohort-charts">
            <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
              {baseline.cuts.filter((cut) => cut.available && cut.rows?.length)
                .map((cut) => (
                <div key={cut.key} data-testid={`ews-whatif-chart-${cut.key}`}>
                  <p className="mb-1 text-[10px] uppercase tracking-[0.08em]
                                text-text-muted">
                    {cut.label}
                  </p>
                  <CutChart cut={cut as never} height={190} />
                </div>
              ))}
            </div>
            <div className="mt-3"><ColourKey /></div>
          </Panel>

          <details className="rounded-lg border border-border px-4 py-2"
                   data-testid="ews-whatif-cut-tables">
            <summary className="cursor-pointer text-[12px] text-text-secondary">
              The same cuts, as figures
            </summary>
            <div className="mt-3 space-y-4">
              {baseline.cuts.filter((cut) => cut.available && cut.rows?.length)
                .map((cut) => (
                <div key={cut.key} data-testid={`ews-whatif-cut-${cut.key}`}>
                  <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
                    {cut.label}
                  </p>
                  <div className="overflow-x-auto">
                    <table className="mt-1 w-full min-w-[640px] text-[11px]">
                      <thead>
                        <tr className="text-[9px] uppercase tracking-[0.06em] text-text-muted">
                          {["Band", "Customers", "Accounts", "Exposure", "PD",
                            "LGD", "EAD", "Weighted ECL"].map((one) => (
                            <th key={one} className="px-2 py-1 text-left">{one}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {cut.rows!.map((row) => (
                          <tr key={row.value} className="border-t border-border/60">
                            <td className="px-2 py-1 text-text-primary">
                              {row.label}
                            </td>
                            <td className="px-2 py-1 tabular-nums">
                              {count(row.customers)}
                            </td>
                            <td className="px-2 py-1 tabular-nums">
                              {count(row.accounts)}
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
          </details>
        </>
      ) : (
        <Card className="p-4 text-sm text-text-secondary">
          The baseline could not be read: {baseline?.because}
        </Card>
      )}

      {/* ------------------------------------------------------ the thread */}
      <div className="space-y-3" data-testid="ews-whatif-turns">
        {turns.map((turn) => {
          if (turn.kind === "said") {
            return (
              <div key={turn.id} className="flex justify-end"
                   data-testid="whatif-turn-said">
                <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-accent
                                px-3.5 py-2 text-[13px] text-accent-contrast">
                  {turn.text}
                </div>
              </div>
            );
          }
          if (turn.kind === "asked") {
            return (
              <Card key={turn.id}
                    className="border-warning/40 bg-warning-subtle/30 p-4"
                    data-testid="whatif-turn-asked">
                <p className="text-[13px] text-text-primary">{turn.question}</p>
                {turn.readAs.length ? (
                  <p className="mt-1 text-[11px] text-text-muted">
                    What was understood: {turn.readAs.join("; ")}.
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {CHIPS.slice(0, 4).map((one) => (
                    <button key={one} type="button" onClick={() => void run(one)}
                            className="rounded-full border border-border px-2.5
                                       py-1 text-[11px] text-text-secondary
                                       hover:bg-surface-muted">
                      {one}
                    </button>
                  ))}
                </div>
              </Card>
            );
          }
          if (turn.kind === "note") {
            return (
              <Card key={turn.id}
                    className={cn("p-3 text-[12px]",
                                  turn.tone === "warn"
                                    ? "border-negative/40 text-negative"
                                    : "text-text-secondary")}
                    data-testid="whatif-turn-note">
                {turn.text}
              </Card>
            );
          }
          return (
            <ResultBlock key={turn.id} result={turn.result}
                         onFollowUp={(said) => void run(said)}
                         onDownload={() => void download(turn.said)}
                         downloading={downloading === turn.said} />
          );
        })}
        <div ref={foot} />
      </div>

      {/* ---------------------------------------------- the composer, below */}
      <Card className="sticky bottom-3 z-10 border-border/80 bg-surface/95 p-4
                       shadow-lg backdrop-blur"
            data-testid="ews-whatif-composer">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[11px] uppercase tracking-[0.08em] text-text-muted">
            Methodology
          </p>
          {METHODS.map((one) => (
            <button key={one.key} type="button" onClick={() => setMethod(one.key)}
                    title={one.hint}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                      method === one.key
                        ? "border-accent bg-accent-muted/40 text-text-primary"
                        : "border-border text-text-secondary hover:bg-surface-muted")}
                    data-testid={`ews-whatif-method-${one.key}`}>
              {one.label}
            </button>
          ))}
          <span className="text-[11px] text-text-muted">
            {METHODS.find((one) => one.key === method)?.hint}
          </span>
        </div>

        <div className="mt-2 flex items-end gap-2">
          <textarea
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void run(typed);
              }
            }}
            rows={2}
            placeholder="Describe a change to this cohort — or ask to narrow it."
            className="min-h-[46px] flex-1 resize-y rounded-lg border border-border
                       bg-surface px-3 py-2 text-[13px] text-text-primary
                       outline-none focus:border-accent"
            data-testid="ews-whatif-input" />
          <Button onClick={() => void run(typed)} disabled={busy || !typed.trim()}
                  data-testid="ews-whatif-run">
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden />
                  : <Send className="size-4" aria-hidden />}
            <span className="ml-1">Run</span>
          </Button>
        </div>
        <p className="mt-1 text-[10px] text-text-muted">
          Enter to run · Shift+Enter for a new line
        </p>

        <div className="mt-2 flex flex-wrap gap-1.5"
             data-testid="ews-whatif-chips">
          {CHIPS.map((one) => (
            <button key={one} type="button" onClick={() => void run(one)}
                    disabled={busy}
                    className="rounded-full border border-border px-2.5 py-1
                               text-[11px] text-text-secondary transition-colors
                               hover:bg-surface-muted disabled:opacity-50"
                    data-testid="ews-whatif-chip">
              {one}
            </button>
          ))}
        </div>
      </Card>
    </div>
  );
}
