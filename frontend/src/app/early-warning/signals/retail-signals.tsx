"use client";

/**
 * Early Warning Signals, on the retail book.
 *
 * The same route and the same shape as the screen it replaces: named
 * conditions with thresholds somebody owns, in families, filterable, each one
 * opening the customer it was raised against. There is no score on this page
 * and no column that could be sorted into one — a customer is not "0.72 risky",
 * they have a delinquency that worsened, a salary that stopped arriving and a
 * buffer that ran out, and each of those is a number a credit officer can check
 * against the book.
 *
 * The corporate screen reads `/early-warning/signals`, which answers 503 here:
 * its book was retired by the conversion. This reads the retail rulebook.
 *
 * Every alert carries the return context, so opening a customer and coming
 * back lands on the SAME filtered list rather than on a fresh one.
 */

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import type { RetailAlert } from "@/lib/api";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { withReturnTo } from "@/lib/return-to";

const SEVERITIES = ["ALL", "HIGH", "MEDIUM", "LOW"] as const;
type Severity = (typeof SEVERITIES)[number];

const PAGE = 25;

//: The four products this book holds, and the ALL that is not a product.
const PRODUCTS: { value: string; label: string }[] = [
  { value: "ALL", label: "All products" },
  { value: "CREDIT_CARD", label: "Credit Card" },
  { value: "PERSONAL_LOAN", label: "Personal Finance" },
  { value: "AUTO_LOAN", label: "Auto Finance" },
  { value: "HOME_LOAN", label: "Home Finance" },
];

//: How a triage list may be ordered. Severity is ordered by what it MEANS
//: rather than by its spelling, on the server, so CRITICAL is first however
//: the words happen to sort.
const SORTS: { value: string; label: string }[] = [
  { value: "severity", label: "Severity, then exposure" },
  { value: "exposure", label: "Exposure behind it" },
  { value: "rule", label: "Rule" },
  { value: "customer", label: "Customer" },
];

function sar(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `SAR ${n.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function RetailSignals() {
  const manifest = useAsync(() => api.retailManifest(), []);
  const months = React.useMemo(
    () => (manifest.data?.months ?? []).map((m) => m.reporting_month),
    [manifest.data],
  );
  const [month, setMonth] = React.useState("");
  const [severity, setSeverity] = React.useState<Severity>("ALL");
  const [family, setFamily] = React.useState("ALL");
  // A triage list nobody can narrow to a product is a list nobody uses: 5,952
  // alerts over four products, and the person reading it owns one of them
  // this morning. Same for the customer somebody has just been asked about.
  const [product, setProduct] = React.useState("ALL");
  const [customer, setCustomer] = React.useState("");
  const [typed, setTyped] = React.useState("");
  const [sort, setSort] = React.useState("severity");
  const [shown, setShown] = React.useState(PAGE);

  React.useEffect(() => {
    if (!month && months.length) setMonth(months[months.length - 1]);
  }, [months, month]);

  const found = useAsync(
    () => api.retailEarlyWarning(
      month, severity === "ALL" ? "" : severity, 500,
      { product: product === "ALL" ? "" : product, customer, sort }),
    [month, severity, product, customer, sort],
    { enabled: Boolean(month) },
  );

  const alerts: RetailAlert[] = React.useMemo(() => {
    const rows = found.data?.alerts ?? [];
    return family === "ALL"
      ? rows
      : rows.filter((a) => a.rule_family === family);
  }, [found.data, family]);

  const families = React.useMemo(() => {
    const seen = new Set<string>();
    for (const a of found.data?.alerts ?? []) seen.add(a.rule_family);
    return ["ALL", ...[...seen].sort()];
  }, [found.data]);

  // Where a customer opened from here comes back to. The filters are in the
  // href, so Back lands on the list the reader was actually reading.
  const listHref =
    `/early-warning/signals?month=${encodeURIComponent(month)}`
    + `&severity=${severity}&family=${encodeURIComponent(family)}`
    + `&product=${encodeURIComponent(product)}`
    + `&customer=${encodeURIComponent(customer)}&sort=${sort}`;

  return (
    <div className="space-y-5" data-testid="retail-signals">
      <PageHeader
        eyebrow="Intelligence"
        title="Early Warning Signals"
        description={
          "Named retail conditions with thresholds somebody owns, evaluated "
          + "against the published book. Every alert says what it measured, "
          + "what it compared against and what to do about it."
        }
      />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-4">
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Month
            <select
              value={month}
              onChange={(e) => { setMonth(e.target.value); setShown(PAGE); }}
              aria-label="Reporting month"
              data-testid="signals-month"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            >
              {months.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Severity
            <select
              value={severity}
              onChange={(e) => { setSeverity(e.target.value as Severity);
                                 setShown(PAGE); }}
              aria-label="Severity"
              data-testid="signals-severity"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            >
              {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Family
            <select
              value={family}
              onChange={(e) => { setFamily(e.target.value); setShown(PAGE); }}
              aria-label="Rule family"
              data-testid="signals-family"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            >
              {families.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Product
            <select
              value={product}
              onChange={(e) => { setProduct(e.target.value); setShown(PAGE); }}
              aria-label="Product"
              data-testid="signals-product"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            >
              {PRODUCTS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Order
            <select
              value={sort}
              onChange={(e) => { setSort(e.target.value); setShown(PAGE); }}
              aria-label="Order the alerts"
              data-testid="signals-sort"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Customer or facility
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { setCustomer(typed.trim());
                                         setShown(PAGE); }
              }}
              onBlur={() => { setCustomer(typed.trim()); setShown(PAGE); }}
              placeholder="RC-0017728"
              aria-label="Find a customer or facility"
              data-testid="signals-customer"
              className="w-40 rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            />
          </label>
          <Button size="sm" variant="ghost"
                  onClick={() => { setSeverity("ALL"); setFamily("ALL");
                                   setProduct("ALL"); setCustomer("");
                                   setTyped(""); setSort("severity");
                                   setShown(PAGE); }}
                  data-testid="signals-clear">
            Clear filters
          </Button>
        </CardContent>
      </Card>

      {found.loading ? <Skeleton className="h-64 w-full" /> : null}
      {found.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {found.error}
        </Card>
      ) : null}

      {found.data ? (
        <>
          <Card>
            <CardContent className="grid gap-3 pt-4 sm:grid-cols-4">
              <Figure label="Alerts" value={alerts.length.toLocaleString()} />
              <Figure label="Customers"
                      value={found.data.distinct_customers.toLocaleString()} />
              <Figure label="Exposure affected"
                      value={sar(found.data.affected_exposure_sar)} />
              <Figure label="Rulebook"
                      value={found.data.rulebook_version} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[14px]">By rule</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {found.data.by_rule.map((r) => (
                <Badge key={r.rule_id} variant="outline">
                  {r.rule_id} · {r.rule_name} · {r.alerts.toLocaleString()}
                </Badge>
              ))}
            </CardContent>
          </Card>

          {alerts.length === 0 ? (
            <EmptyState
              title="Nothing matches these filters"
              description="Widen the severity or the family, or choose another month."
            />
          ) : (
            <Card>
              <CardContent className="divide-y divide-border pt-2"
                           data-testid="signals-list">
                {alerts.slice(0, shown).map((a) => (
                  <div key={a.alert_id} className="py-3 text-[12px]"
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
                      <Badge variant="outline">{a.rule_family}</Badge>
                      <span className="text-text-muted">
                        {a.scope === "CUSTOMER" ? "customer" : "facility"}
                      </span>
                    </div>
                    {a.reason ? (
                      <p className="mt-1 text-text-secondary">{a.reason}</p>
                    ) : null}
                    {a.recommended_review ? (
                      <p className="mt-1 text-text-muted">{a.recommended_review}</p>
                    ) : null}
                    <div className="mt-2 flex flex-wrap items-center gap-3">
                      <Button size="sm" variant="outline" asChild>
                        <Link
                          href={withReturnTo(
                            `/borrower-360?borrower=${encodeURIComponent(a.customer_id)}`
                            + `&period=${encodeURIComponent(month)}`,
                            listHref,
                            "Early Warning Signals")}
                          data-testid={`open-customer-${a.customer_id}`}
                        >
                          Open {a.customer_id}
                        </Link>
                      </Button>
                      {a.facility_id ? (
                        <span className="text-text-muted">{a.facility_id}</span>
                      ) : null}
                      {a.affected_facility_count ? (
                        <span className="text-text-muted">
                          {a.affected_facility_count} facilities
                        </span>
                      ) : null}
                    </div>
                  </div>
                ))}
                {alerts.length > shown ? (
                  <div className="pt-3">
                    <Button size="sm" variant="ghost"
                            onClick={() => setShown((n) => n + PAGE)}
                            data-testid="signals-more">
                      Show {Math.min(PAGE, alerts.length - shown)} more
                    </Button>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          )}

          {(found.data.notes ?? []).map((n) => (
            <p key={n} className="text-[11px] text-text-muted">{n}</p>
          ))}
          <p className="text-[11px] text-text-muted">{found.data.disclosure}</p>
        </>
      ) : null}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">
        {label}
      </div>
      <div className="text-[15px] font-medium text-text-primary">{value}</div>
    </div>
  );
}
