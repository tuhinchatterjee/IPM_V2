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
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import type { RetailAlert } from "@/lib/api";
import { api } from "@/lib/api";
import { EWS_PHASE, EWS_SIGNALS_DESCRIPTION } from "@/lib/ews";
import { useAsync } from "@/lib/hooks";
import { withReturnTo } from "@/lib/return-to";

//: The fallback, used only until the book answers. The list the screen
//: actually offers is the rulebook's own — see `severities` below.
//:
//: It was hard-coded as ALL / HIGH / MEDIUM / LOW. The rulebook's highest
//: class is CRITICAL, so the 232 alerts somebody opens this screen for could
//: not be selected, and LOW was an option no rule could ever fill.
const FALLBACK_SEVERITIES = ["ALL"] as const;
type Severity = string;

const PAGE = 25;

//: How many alerts the server sends back at once.
//:
//: It is a PAGE SIZE, and the screen must say so. What it used to do was
//: print the length of this page as the headline — "ALERTS 500" — above rule
//: chips that added up to 5,952. A Head of Retail Risk reading that number
//: concluded the book raised five hundred warnings in August. It raised
//: 5,952.
const PAGE_LIMIT = 500;

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
  // The filters this screen was left with, read ONCE from the link that
  // brought the reader back.
  //
  // Back from Customer 360 returned to the signals list with every filter
  // reset: the return href carried the product, the severity and the month,
  // and nothing read them. §13 asks for "Back to the exact filtered list",
  // and a list that comes back showing all 5,952 alerts is not that list.
  //
  // Read once and then owned by the reader: re-reading on every render would
  // undo whatever they changed next.
  const query = useSearchParams();
  const manifest = useAsync(() => api.retailManifest(), []);
  const months = React.useMemo(
    () => (manifest.data?.months ?? []).map((m) => m.reporting_month),
    [manifest.data],
  );
  const [month, setMonth] = React.useState(() => query.get("month") ?? "");
  const [severity, setSeverity] = React.useState<Severity>(
    () => query.get("severity") || "ALL");
  const [family, setFamily] = React.useState(
    () => query.get("family") || "ALL");
  // A triage list nobody can narrow to a product is a list nobody uses: 5,952
  // alerts over four products, and the person reading it owns one of them
  // this morning. Same for the customer somebody has just been asked about.
  const [product, setProduct] = React.useState(
    () => query.get("product") || "ALL");
  const [customer, setCustomer] = React.useState(
    () => query.get("customer") ?? "");
  const [typed, setTyped] = React.useState(() => query.get("customer") ?? "");
  const [sort, setSort] = React.useState(() => query.get("sort") || "severity");
  // §13: a rule chip and a layer chip are filters, and they live in the
  // address so the methodology page and the Cockpit can link straight to
  // "the 348 alerts RET-EWS-001 raised".
  const [rule, setRule] = React.useState(() => query.get("rule") || "");
  const [layer, setLayer] = React.useState(() => query.get("layer") || "");
  const [shown, setShown] = React.useState(PAGE);

  // The month actually read. Derived rather than written back into state by
  // an effect: until the manifest lands there is no month to default to, and
  // a setState in an effect to supply one is a second render for a value the
  // render already has.
  const at = month || (months.length ? months[months.length - 1] : "");

  const found = useAsync(
    () => api.retailEarlyWarning(
      at, severity === "ALL" ? "" : severity, PAGE_LIMIT,
      { product: product === "ALL" ? "" : product, customer, sort,
        rule, layer, family: family === "ALL" ? "" : family }),
    [at, severity, product, customer, sort, rule, layer, family],
    { enabled: Boolean(at) },
  );

  const alerts: RetailAlert[] = found.data?.alerts ?? [];

  // §14. `alerts.length` is the PAGE. `alert_count` is the finding.
  const matched = found.data?.alert_count ?? 0;
  const showing = React.useMemo(() => {
    const data = found.data;
    if (!data) return "";
    const on = Math.min(shown, alerts.length).toLocaleString();
    const total = (data.alert_count ?? 0).toLocaleString();
    if (data.capped) {
      return `Showing ${on} of ${total} alerts. The server sends the worst `
        + `${(data.returned ?? 0).toLocaleString()} at a time; narrow by `
        + "severity, layer, product or rule to see the rest.";
    }
    return `Showing ${on} of ${total} alerts matching these filters.`;
  }, [found.data, alerts.length, shown]);

  // What a rule id and a layer key are CALLED, read from the deck the server
  // sends rather than spelled again here.
  const ruleLabel = React.useMemo(() => {
    const one = (found.data?.by_rule ?? []).find((r) => r.rule_id === rule);
    return one ? `${one.rule_id} · ${one.rule_name}` : rule;
  }, [found.data, rule]);
  const layerLabel = React.useMemo(() => {
    const one = (found.data?.by_layer ?? []).find((l) => l.layer === layer);
    return one ? one.layer_name : layer;
  }, [found.data, layer]);

  // Said once, under each deck: these counts are the month's, not the
  // filter's, so clicking a chip narrows the list without emptying the deck a
  // reader needs in order to click a different one.
  const deckNote = found.data
    ? `Counts across all ${(found.data.deck_total ?? 0).toLocaleString()} `
      + `alerts raised at ${at}, before these filters.`
    : "";

  //: Worst first, and only the classes some rule actually raises.
  const severities = React.useMemo(() => {
    const served = found.data?.severities ?? [];
    return served.length ? ["ALL", ...served] : [...FALLBACK_SEVERITIES];
  }, [found.data]);

  // Served, not scraped off the page: built from the alerts in the browser it
  // offered five of the eleven families the month raises, because the browser
  // only ever holds the capped page.
  const families = React.useMemo(
    () => ["ALL", ...(found.data?.by_family ?? []).map((f) => f.family)],
    [found.data]);

  // Where a customer opened from here comes back to. The filters are in the
  // href, so Back lands on the list the reader was actually reading.
  const listHref =
    `/early-warning/signals?month=${encodeURIComponent(at)}`
    + `&severity=${severity}&family=${encodeURIComponent(family)}`
    + `&product=${encodeURIComponent(product)}`
    + `&customer=${encodeURIComponent(customer)}&sort=${sort}`
    + `&rule=${encodeURIComponent(rule)}&layer=${encodeURIComponent(layer)}`;

  return (
    <div className="space-y-5" data-testid="retail-signals">
      <PageHeader
        eyebrow="Intelligence"
        title="Early Warning Signals"
        description={EWS_SIGNALS_DESCRIPTION}
        status="partial"
        phase={EWS_PHASE}
      />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-4">
          <label className="flex flex-col gap-1 text-[11px] text-text-muted">
            Month
            <select
              value={at}
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
              onChange={(e) => { setSeverity(e.target.value);
                                 setShown(PAGE); }}
              aria-label="Severity"
              data-testid="signals-severity"
              className="rounded-md border border-border bg-surface px-2 py-1 text-[13px]"
            >
              {severities.map((s) => <option key={s} value={s}>{s}</option>)}
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
                                   setRule(""); setLayer("");
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
              <Figure label="Alerts matching these filters"
                      value={matched.toLocaleString()} />
              <Figure label="Customers"
                      value={found.data.distinct_customers.toLocaleString()} />
              <Figure label="Exposure affected"
                      value={sar(found.data.affected_exposure_sar)} />
              <Figure label="Rulebook"
                      value={found.data.rulebook_version} />
            </CardContent>
          </Card>

          {/* §14: what is on the screen, against what matched. */}
          <p className="text-[12px] text-text-secondary" data-testid="signals-showing">
            {showing}
          </p>

          {/* A rule or a layer chosen by a chip — or by a link from the
              methodology, the Cockpit or a customer's reason-code timeline —
              is not in any of the dropdowns above, so it is named here.
              Landing on "348 alerts" with nothing on screen saying which of
              the twenty rules that is, is a filtered list nobody can read. */}
          {rule || layer ? (
            <div className="flex flex-wrap items-center gap-2"
                 data-testid="signals-active-filters">
              <span className="text-[11px] text-text-muted">Filtered to</span>
              {rule ? (
                <button type="button" onClick={() => { setRule(""); setShown(PAGE); }}
                        data-testid="signals-clear-rule"
                        className="rounded-full border border-accent bg-accent-subtle px-2.5 py-1 text-[11px] text-accent">
                  {ruleLabel} ✕
                </button>
              ) : null}
              {layer ? (
                <button type="button" onClick={() => { setLayer(""); setShown(PAGE); }}
                        data-testid="signals-clear-layer"
                        className="rounded-full border border-accent bg-accent-subtle px-2.5 py-1 text-[11px] text-accent">
                  {layerLabel} ✕
                </button>
              ) : null}
            </div>
          ) : null}

          <ChipDeck
            title="By severity"
            note={deckNote}
            testId="signals-by-severity"
            chips={(found.data.by_severity ?? []).map((r) => ({
              key: r.severity,
              label: `${r.severity} · ${r.alerts.toLocaleString()}`,
              active: severity === r.severity,
              testId: `signals-chip-severity-${r.severity}`,
              onClick: () => { setSeverity(severity === r.severity ? "ALL" : r.severity);
                               setShown(PAGE); },
            }))}
          />

          <ChipDeck
            title="By methodology layer"
            note={"The six layers of the Early Warning methodology. Every rule "
                  + "rolls up into one of them. " + deckNote}
            testId="signals-by-layer"
            chips={(found.data.by_layer ?? []).map((r) => ({
              key: r.layer || "none",
              label: `${r.layer_name} · ${r.alerts.toLocaleString()}`,
              active: layer === r.layer && r.layer !== "",
              disabled: r.layer === "",
              testId: `signals-chip-layer-${r.layer || "none"}`,
              onClick: () => { if (!r.layer) return;
                               setLayer(layer === r.layer ? "" : r.layer);
                               setShown(PAGE); },
            }))}
          />

          <ChipDeck
            title="By product"
            note={deckNote}
            testId="signals-by-product"
            chips={(found.data.by_product ?? []).map((r) => ({
              key: r.product_code || "customer-scope",
              label: `${r.product_label} · ${r.alerts.toLocaleString()}`,
              active: product === r.product_code && r.product_code !== "",
              disabled: r.product_code === "",
              testId: `signals-chip-product-${r.product_code || "customer-scope"}`,
              onClick: () => { if (!r.product_code) return;
                               setProduct(product === r.product_code
                                          ? "ALL" : r.product_code);
                               setShown(PAGE); },
            }))}
          />

          <ChipDeck
            title="By rule"
            note={"Click a rule to see only the alerts it raised. " + deckNote}
            testId="signals-by-rule"
            chips={found.data.by_rule.map((r) => ({
              key: r.rule_id,
              label: `${r.rule_id} · ${r.rule_name} · ${r.alerts.toLocaleString()}`,
              active: rule === r.rule_id,
              testId: `signals-chip-rule-${r.rule_id}`,
              onClick: () => { setRule(rule === r.rule_id ? "" : r.rule_id);
                               setShown(PAGE); },
            }))}
          />

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
                            + `&period=${encodeURIComponent(at)}`,
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

/**
 * A row of counts that are also filters.
 *
 * The screen carried four of these decks as `Badge`s — RET-EWS-001 · 348,
 * CRITICAL · 232 — which read as controls and were not. §13 asks for every
 * chip to be clickable, so each one narrows the list and narrows the count
 * with it, and an active chip shows what the list is currently narrowed to.
 *
 * A chip can be `disabled`: the customer-scope product chip counts 1,934
 * alerts that belong to no single product, and narrowing to "no product" is
 * not a question anybody asks.
 */
function ChipDeck({
  title, note, chips, testId,
}: {
  title: string;
  note?: string;
  testId: string;
  chips: {
    key: string; label: string; active: boolean; disabled?: boolean;
    testId: string; onClick: () => void;
  }[];
}) {
  if (!chips.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-[14px]">{title}</CardTitle>
        {note ? (
          <p className="text-[11px] text-text-muted">{note}</p>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2" data-testid={testId}>
        {chips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            disabled={chip.disabled}
            aria-pressed={chip.active}
            onClick={chip.onClick}
            data-testid={chip.testId}
            className={
              "rounded-full border px-2.5 py-1 text-[11px] transition-colors "
              + (chip.disabled
                ? "cursor-default border-border bg-surface-muted/50 text-text-muted"
                : chip.active
                  ? "border-accent bg-accent-subtle text-accent"
                  : "border-border text-text-secondary hover:bg-surface-muted")
            }
          >
            {chip.label}
          </button>
        ))}
      </CardContent>
    </Card>
  );
}
