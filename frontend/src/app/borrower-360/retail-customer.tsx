"use client";

/**
 * Customer 360, on the retail book.
 *
 * The same route, the same shell and the same interaction pattern as the
 * screen it replaces — search, open, read across tabs, come back — bound to the
 * customer the retail book actually publishes. The corporate screen's panels
 * read `/corporate/*`, which answers 503 on this installation because the book
 * behind them was retired; a page that renders empty company-financial panels
 * over a retail endpoint would be worse than the 503.
 *
 * Two rules run through it.
 *
 * **A customer value is reported once.** Income, obligations, the debt burden
 * and disposable income belong to the CUSTOMER. They repeat on every facility
 * row in the book, and summing them would multiply a salary by the number of
 * facilities. The endpoint says so in its own notes, and they are shown.
 *
 * **An origination input is not a current input.** The application scorecard is
 * reconstructed from what was known when the facility was written; the
 * behavioural scorecard from what is known now. Each says which, with its model
 * id, version and date, so nobody reads one as the other.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { BackLink } from "@/components/layout/back-link";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import type {
  RetailCustomer,
  RetailCustomerRow,
  RetailFacilityScore,
  RetailScoreBlock,
} from "@/lib/api";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "facilities", label: "Facilities" },
  { id: "history", label: "History" },
  { id: "scores", label: "Scores" },
  { id: "warnings", label: "Warnings" },
];

function sar(value: unknown, digits = 0): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `SAR ${n.toLocaleString("en-US", { minimumFractionDigits: digits,
                                            maximumFractionDigits: digits })}`;
}

function num(value: unknown, digits = 0): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: digits,
                                     maximumFractionDigits: digits });
}

function pct(value: unknown, digits = 1): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function words(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value).replace(/_/g, " ");
}

/** One label and value, the way the screen it replaces showed a field. */
function Field({ label, value, note }: {
  label: string; value: React.ReactNode; note?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">
        {label}
      </div>
      <div className="truncate text-[13px] text-text-primary" title={note}>
        {value}
      </div>
    </div>
  );
}

export function RetailCustomer360() {
  const query = useSearchParams();
  const manifest = useAsync(() => api.retailManifest(), []);
  const months = React.useMemo(
    () => (manifest.data?.months ?? []).map((m) => m.reporting_month),
    [manifest.data],
  );

  // Read ONCE as initial state: after this the reader owns them, and a
  // re-render that reset them to the link would undo whatever they did next.
  const [month, setMonth] = React.useState(() => query.get("period") ?? "");
  const [customerId, setCustomerId] = React.useState(
    () => query.get("borrower") ?? query.get("customer") ?? "");
  const [text, setText] = React.useState("");
  const [results, setResults] = React.useState<RetailCustomerRow[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [found, setFound] = React.useState<RetailCustomer | null>(null);
  const [problem, setProblem] = React.useState("");
  const [tab, setTab] = React.useState("overview");
  const [facilityId, setFacilityId] = React.useState("");
  const [score, setScore] = React.useState<RetailFacilityScore | null>(null);
  const [scoreProblem, setScoreProblem] = React.useState("");

  React.useEffect(() => {
    if (!month && months.length) setMonth(months[months.length - 1]);
  }, [months, month]);

  const search = React.useCallback(async (q: string) => {
    if (!month) return;
    setSearching(true);
    setProblem("");
    try {
      const body = await api.retailCustomers(q, month, 25);
      setResults(body.customers);
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSearching(false);
    }
  }, [month]);

  // The customer the reader is on, reloaded when they change month — the whole
  // point of a month selector on a customer screen.
  React.useEffect(() => {
    if (!customerId || !month) return;
    let live = true;
    setProblem("");
    api.retailCustomer(customerId, month)
      .then((body) => {
        if (!live) return;
        setFound(body);
        setFacilityId((current) => {
          const ids = body.facilities.map((f) => String(f.facility_id));
          return current && ids.includes(current) ? current : (ids[0] ?? "");
        });
      })
      .catch((caught) => {
        if (!live) return;
        setFound(null);
        setProblem(caught instanceof Error ? caught.message : String(caught));
      });
    return () => { live = false; };
  }, [customerId, month]);

  React.useEffect(() => {
    if (!facilityId || !month) return;
    let live = true;
    setScoreProblem("");
    api.retailFacilityScore(facilityId, month)
      .then((body) => { if (live) setScore(body); })
      .catch((caught) => {
        if (!live) return;
        setScore(null);
        setScoreProblem(
          caught instanceof Error ? caught.message : String(caught));
      });
    return () => { live = false; };
  }, [facilityId, month]);

  const customer = (found?.customer ?? {}) as Record<string, unknown>;
  const facility = (found?.facilities ?? []).find(
    (f) => String(f.facility_id) === facilityId) as
    Record<string, unknown> | undefined;

  return (
    <div className="space-y-5" data-testid="retail-customer-360">
      <BackLink href="/early-warning/signals" label="Early Warning Signals" />

      <PageHeader
        eyebrow="Intelligence"
        title="Customer 360"
        description={
          "One retail customer at one month-end: their facilities, their "
          + "repayment history, what they can afford, both scorecards with the "
          + "evidence behind them, and the warnings raised against them."
        }
      />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-4">
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Reporting month
            <select
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              aria-label="Reporting month"
              data-testid="customer-month"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px] text-text-primary"
            >
              {months.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-1 flex-col gap-1 text-[11px] text-text-muted">
            Find a customer
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void search(text);
              }}
              placeholder="Customer id, or leave blank for the largest"
              aria-label="Find a customer"
              data-testid="customer-search"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px] text-text-primary"
            />
          </label>
          <Button size="sm" onClick={() => void search(text)}
                  disabled={searching || !month}
                  data-testid="customer-search-go">
            {searching ? "Searching…" : "Search"}
          </Button>
        </CardContent>
      </Card>

      {problem ? (
        <Card className="border-negative/40 p-4 text-sm text-negative"
              data-testid="customer-problem">
          {problem}
        </Card>
      ) : null}

      {results.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">
              {results.length} customers at {month}
            </CardTitle>
          </CardHeader>
          <CardContent className="divide-y divide-border">
            {results.map((row) => (
              <button
                key={row.customer_id}
                type="button"
                data-customer-id={row.customer_id}
                aria-label={`Open customer ${row.customer_id}`}
                onClick={() => { setCustomerId(row.customer_id); setResults([]); }}
                className="flex w-full flex-wrap items-center gap-3 py-2 text-left text-[13px] transition-colors hover:bg-surface-hover"
              >
                <span className="font-medium text-text-primary">
                  {row.customer_id}
                </span>
                <Badge variant="outline">{row.facilities} facilities</Badge>
                <span className="text-text-secondary">{sar(row.exposure_sar)}</span>
                <span className="text-text-muted">{words(row.region)}</span>
                <span className="text-text-muted">{words(row.segment)}</span>
                <Badge variant={row.worst_stage >= 3 ? "negative"
                                : row.worst_stage === 2 ? "warning" : "default"}>
                  Stage {row.worst_stage}
                </Badge>
              </button>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {!customerId ? (
        <EmptyState
          title="No customer open"
          description="Search above, or arrive here from an Early Warning alert."
        />
      ) : !found ? (
        problem ? null : <Skeleton className="h-64 w-full" />
      ) : (
        <>
          <Card data-testid="customer-header">
            <CardContent className="space-y-4 pt-4">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-[18px] font-medium text-text-primary">
                  {String(customer.customer_id ?? customerId)}
                </span>
                <Badge variant="outline">{words(customer.customer_segment)}</Badge>
                <Badge variant="outline">{words(customer.region)}</Badge>
                <Badge variant="outline">{words(customer.employment_status)}</Badge>
                {customer.salary_transfer_flag ? (
                  <Badge variant="positive">Salary transferred</Badge>
                ) : (
                  <Badge variant="default">No salary transfer</Badge>
                )}
                <span className="text-[12px] text-text-muted">
                  at {found.snapshot_month} · {found.dataset_version}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-4">
                <Field label="Facilities" value={num(found.facility_count)} />
                <Field label="Gross carrying amount"
                       value={sar(found.exposure_sar)} />
                <Field label="Loss allowance (ECL)"
                       value={sar(found.ecl_final_sar, 2)} />
                <Field label="Debt burden ratio"
                       value={pct(customer.debt_burden_ratio)}
                       note={String(customer.obligation_scope_definition ?? "")} />
              </div>
            </CardContent>
          </Card>

          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === "overview" ? (
            <Card>
              <CardContent className="space-y-5 pt-4">
                <section>
                  <h3 className="mb-2 text-[13px] font-medium text-text-primary">
                    Who they are
                  </h3>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <Field label="City" value={words(customer.city)} />
                    <Field label="Branch" value={words(customer.branch_id)} />
                    <Field label="Residency"
                           value={words(customer.residency_category)} />
                    <Field label="Age band" value={words(customer.age_band)} />
                    <Field label="Dependants"
                           value={words(customer.dependants_band)} />
                    <Field label="Employer sector"
                           value={words(customer.employer_sector)} />
                    <Field label="Employment tenure"
                           value={`${num(customer.employment_tenure_months)} months`} />
                    <Field label="With the bank"
                           value={`${num(customer.customer_tenure_months)} months`} />
                  </div>
                </section>

                <section>
                  <h3 className="mb-2 text-[13px] font-medium text-text-primary">
                    What they can afford
                  </h3>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <Field label="Verified salary"
                           value={sar(customer.verified_monthly_salary_sar, 2)} />
                    <Field label="Total verified income"
                           value={sar(customer.verified_total_monthly_income_sar, 2)} />
                    <Field label="Household expenses"
                           value={sar(customer.household_expenses_sar, 2)} />
                    <Field label="Own-bank obligations"
                           value={sar(customer.monthly_own_bank_credit_obligations_sar, 2)} />
                    <Field label="External obligations"
                           value={sar(customer.monthly_external_credit_obligations_sar, 2)} />
                    <Field label="Total obligations"
                           value={sar(customer.monthly_total_credit_obligations_sar, 2)} />
                    <Field label="Disposable income"
                           value={sar(customer.disposable_income_sar, 2)} />
                    <Field label="Balance buffer"
                           value={`${num(customer.balance_buffer_months, 2)} months`} />
                  </div>
                </section>

                <section>
                  <h3 className="mb-2 text-[13px] font-medium text-text-primary">
                    Bureau and salary signals
                  </h3>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <Field label="Bureau score (lowest reading)"
                           value={num(customer.bureau_score_current)}
                           note={String(customer.bureau_basis ?? "")} />
                    <Field label="Bureau change, 3 months"
                           value={num(customer.bureau_score_change_3m)} />
                    <Field label="Missed salary cycles, 3 months"
                           value={num(customer.salary_missed_cycle_count_3m)} />
                    <Field label="Employment change reported"
                           value={words(customer.employment_change_flag)} />
                  </div>
                  <p className="mt-2 text-[11px] text-text-muted">
                    {String(customer.bureau_basis ?? "")}{" "}
                    {String(customer.bureau_source_label ?? "")} · scale{" "}
                    {String(customer.bureau_scale_id ?? "")}
                  </p>
                </section>

                {(found.notes ?? []).map((note) => (
                  <p key={note} className="text-[11px] text-text-muted">{note}</p>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {tab === "facilities" ? (
            <Card>
              <CardContent className="space-y-3 pt-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-[12px]"
                         data-testid="customer-facilities">
                    <thead>
                      <tr className="text-left text-text-muted">
                        <th className="py-1">Facility</th>
                        <th className="py-1">Product</th>
                        <th className="py-1 text-right">Gross carrying amount</th>
                        <th className="py-1 text-right">ECL</th>
                        <th className="py-1 text-right">DPD</th>
                        <th className="py-1 text-right">Stage</th>
                        <th className="py-1" />
                      </tr>
                    </thead>
                    <tbody>
                      {found.facilities.map((f) => {
                        const id = String(f.facility_id);
                        return (
                          <tr key={id}
                              className={id === facilityId
                                ? "border-t border-border bg-surface-sunken"
                                : "border-t border-border"}>
                            <td className="py-1 font-medium text-text-primary">{id}</td>
                            <td className="py-1">{words(f.product_label)}</td>
                            <td className="py-1 text-right">
                              {sar(f.gross_carrying_amount_sar, 2)}
                            </td>
                            <td className="py-1 text-right">
                              {sar(f.ecl_final_sar, 2)}
                            </td>
                            <td className="py-1 text-right">{num(f.dpd)}</td>
                            <td className="py-1 text-right">{num(f.ifrs9_stage)}</td>
                            <td className="py-1 text-right">
                              <Button size="sm" variant="outline"
                                      data-testid={`facility-open-${id}`}
                                      onClick={() => { setFacilityId(id);
                                                       setTab("scores"); }}>
                                Open
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {facility ? (
                  <div className="rounded-md border border-border p-3"
                       data-testid="facility-detail">
                    <div className="mb-2 text-[13px] font-medium text-text-primary">
                      {String(facility.facility_id)} ·{" "}
                      {words(facility.product_label)}
                    </div>
                    <div className="grid gap-3 sm:grid-cols-4">
                      <Field label="Originated"
                             value={words(facility.origination_date)} />
                      <Field label="Months on book"
                             value={num(facility.months_on_book)} />
                      <Field label="Original amount"
                             value={sar(facility.original_finance_amount_sar, 2)} />
                      <Field label="Credit limit"
                             value={sar(facility.current_credit_limit_sar, 2)} />
                      <Field label="Outstanding principal"
                             value={sar(facility.outstanding_principal_sar, 2)} />
                      <Field label="Undrawn commitment"
                             value={sar(facility.undrawn_commitment_sar, 2)} />
                      <Field label="Days past due" value={num(facility.dpd)} />
                      <Field label="IFRS 9 stage"
                             value={num(facility.ifrs9_stage)} />
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {tab === "history" ? (
            <Card>
              <CardContent className="pt-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-[12px]"
                         data-testid="customer-history">
                    <thead>
                      <tr className="text-left text-text-muted">
                        <th className="py-1">Month</th>
                        <th className="py-1 text-right">Facilities</th>
                        <th className="py-1 text-right">Gross carrying amount</th>
                        <th className="py-1 text-right">ECL</th>
                        <th className="py-1 text-right">Max DPD</th>
                        <th className="py-1 text-right">Worst stage</th>
                        <th className="py-1 text-right">Behavioural score</th>
                        <th className="py-1 text-right">Salary credited</th>
                      </tr>
                    </thead>
                    <tbody>
                      {found.history.map((h) => (
                        <tr key={h.reporting_month}
                            className="border-t border-border">
                          <td className="py-1">{h.reporting_month}</td>
                          <td className="py-1 text-right">{num(h.facilities)}</td>
                          <td className="py-1 text-right">
                            {sar(h.gross_carrying_amount_sar, 2)}
                          </td>
                          <td className="py-1 text-right">
                            {sar(h.ecl_final_sar, 2)}
                          </td>
                          <td className="py-1 text-right">{num(h.max_dpd)}</td>
                          <td className="py-1 text-right">{num(h.worst_stage)}</td>
                          <td className="py-1 text-right">
                            {num(h.behavioural_score)}
                          </td>
                          <td className="py-1 text-right">
                            {sar(h.salary_credit_sar, 2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[11px] text-text-muted">
                  {found.history.length} published months, oldest first. Each
                  row counts this customer&apos;s facilities once.
                </p>
              </CardContent>
            </Card>
          ) : null}

          {tab === "scores" ? (
            <Card>
              <CardContent className="space-y-4 pt-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[12px] text-text-muted">Facility</span>
                  <select
                    value={facilityId}
                    onChange={(e) => setFacilityId(e.target.value)}
                    aria-label="Facility"
                    data-testid="score-facility"
                    className="rounded-md border border-border bg-surface px-2 py-1 text-[12px]"
                  >
                    {found.facilities.map((f) => (
                      <option key={String(f.facility_id)}
                              value={String(f.facility_id)}>
                        {String(f.facility_id)} · {words(f.product_label)}
                      </option>
                    ))}
                  </select>
                </div>
                {scoreProblem ? (
                  <p className="text-[12px] text-negative">{scoreProblem}</p>
                ) : null}
                {score ? (
                  <>
                    <ScorePanel
                      title="Application scorecard"
                      note={"Reconstructed from the inputs as they stood AT "
                            + "ORIGINATION. These are not current values."}
                      block={score.application ?? null}
                    />
                    <ScorePanel
                      title="Behavioural scorecard"
                      note={"Reconstructed from the inputs as they stand at "
                            + "this month-end."}
                      block={score.behavioural ?? null}
                    />
                    {(score.notes ?? []).map((n) => (
                      <p key={n} className="text-[11px] text-text-muted">{n}</p>
                    ))}
                  </>
                ) : (
                  <Skeleton className="h-40 w-full" />
                )}
              </CardContent>
            </Card>
          ) : null}

          {tab === "warnings" ? (
            <Card>
              <CardContent className="space-y-2 pt-4">
                {found.alerts.length === 0 ? (
                  <EmptyState
                    title="No warning raised against this customer"
                    description={`The retail rulebook found nothing at ${found.snapshot_month}.`}
                  />
                ) : (
                  <ul className="space-y-2" data-testid="customer-alerts">
                    {found.alerts.map((a) => (
                      <li key={a.alert_id}
                          className="rounded-md border border-border p-3 text-[12px]"
                          data-alert-id={a.alert_id}>
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant={a.severity === "HIGH" ? "negative"
                                          : a.severity === "MEDIUM" ? "warning"
                                          : "default"}>
                            {a.severity}
                          </Badge>
                          <span className="font-medium text-text-primary">
                            {a.rule_name}
                          </span>
                          <span className="text-text-muted">{a.rule_id}</span>
                          {a.facility_id ? (
                            <button
                              type="button"
                              className="text-accent underline"
                              data-testid={`alert-facility-${a.facility_id}`}
                              onClick={() => {
                                setFacilityId(String(a.facility_id));
                                setTab("facilities");
                              }}
                            >
                              {a.facility_id}
                            </button>
                          ) : null}
                        </div>
                        {a.reason ? (
                          <p className="mt-1 text-text-secondary">{a.reason}</p>
                        ) : null}
                        {a.recommended_review ? (
                          <p className="mt-1 text-text-muted">{a.recommended_review}</p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          ) : null}

          <p className="text-[11px] text-text-muted">{found.disclosure}</p>

          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link
                href={`/?focus=ask&q=${encodeURIComponent(
                  `Show exposure and weighted ECL for customer ${customerId} at ${month}`)}`}
                data-testid="customer-ask"
              >
                Ask about this customer
              </Link>
            </Button>
            <Button size="sm" variant="ghost"
                    onClick={() => { setCustomerId(""); setFound(null); }}
                    data-testid="customer-close">
              Close this customer
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function ScorePanel({ title, note, block }: {
  title: string; note: string; block: RetailScoreBlock | null;
}) {
  if (!block) {
    return (
      <div className="rounded-md border border-border p-3 text-[12px]">
        <div className="font-medium text-text-primary">{title}</div>
        <p className="text-text-muted">
          This product carries no {title.toLowerCase()} at this month.
        </p>
      </div>
    );
  }
  const contributions = block.contributions ?? [];
  return (
    <div className="rounded-md border border-border p-3"
         data-testid={`score-${block.model_id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-text-primary">{title}</span>
        <Badge variant="outline">{block.model_id}</Badge>
        <Badge variant="outline">v{block.model_version}</Badge>
        {block.as_at ? (
          <span className="text-[11px] text-text-muted">
            as at {String(block.as_at)}
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-[11px] text-text-muted">{note}</p>
      <div className="mt-2 grid gap-3 sm:grid-cols-4">
        <Field label="Score" value={num(block.score)} />
        <Field label="Band" value={words(block.score_band)} />
        <Field label="Base points" value={num(block.base_points, 2)} />
        <Field label="Predicted PD (12m)"
               value={pct(block.predicted_pd_12m, 2)} />
      </div>
      {contributions.length ? (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-text-muted">
                <th className="py-1">Input</th>
                <th className="py-1">Raw value</th>
                <th className="py-1">Bin</th>
                <th className="py-1 text-right">WoE</th>
                <th className="py-1 text-right">Coefficient</th>
                <th className="py-1 text-right">Points</th>
              </tr>
            </thead>
            <tbody>
              {contributions.map((c) => (
                <tr key={c.feature} className="border-t border-border">
                  <td className="py-1">{c.business_name ?? c.feature}</td>
                  <td className="py-1">{words(c.raw)}</td>
                  <td className="py-1">{words(c.bin)}</td>
                  <td className="py-1 text-right">
                    {num(c.transformed_woe, 4)}
                  </td>
                  <td className="py-1 text-right">{num(c.coefficient, 4)}</td>
                  <td className="py-1 text-right">{num(c.points, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="mt-2 text-[11px] text-text-muted">
        Base points {num(block.base_points, 2)} + contributions{" "}
        {num(block.points_total, 2)} = score {num(block.score, 2)}.
        Target: {String(block.target_event ?? "—")}
      </p>
    </div>
  );
}
