"use client";

/**
 * Early Warning, as a management portfolio.
 *
 * What this replaces, and why
 * ---------------------------
 * The screen here answered one question — which alerts fired? — as a flat list
 * of five hundred cards, with a headline that read ALERTS 500 while the rule
 * chips underneath it added up to 5,952. A Head of Retail Risk opens Early
 * Warning to ask a different question: where is the book going wrong, how
 * badly, and who is it. That question has a shape:
 *
 *     PORTFOLIO -> PRODUCT -> SUBSEGMENT -> CUSTOMER -> FACILITY / SIGNAL
 *
 * Nothing underneath changed. The twenty governed rules are still the signal
 * layer; this reads the precomputed roll-up of them and lets a reader walk
 * down. The rules screen is still there, one click away, and every level
 * names the rules behind it.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { ArrowLeft, ChevronRight } from "lucide-react";

import { TrendChart } from "@/components/analytics/charts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type EwsCounts,
  type EwsCustomerRow,
  type EwsCustomers,
  type EwsPortfolio,
  type EwsProduct,
  type EwsStory,
  type EwsSubsegments,
  type EwsTrendPoint,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/** The five scored layers, in the order the methodology declares them. */
const LAYERS: { key: string; label: string; short: string }[] = [
  { key: "repayment", label: "Repayment behaviour", short: "Repayment" },
  { key: "affordability", label: "Affordability & income", short: "Affordability" },
  { key: "score", label: "Score dynamics", short: "Score" },
  { key: "structure", label: "Facility structure", short: "Structure" },
  { key: "bureau", label: "Bureau & external signals", short: "Bureau" },
];

/** The sixth layer carries no rules in this rulebook, and says so. */
const CYCLE_NOTE =
  "Cycle sensitivity is the sixth layer of the methodology and carries no "
  + "rules in retail-ews-rulebook-1.0.0. It is shown here rather than omitted "
  + "so the absence is visible.";

function money(value: number | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  if (Math.abs(n) >= 1e9) return `SAR ${(n / 1e9).toFixed(2)}bn`;
  if (Math.abs(n) >= 1e6) return `SAR ${(n / 1e6).toFixed(1)}mn`;
  return `SAR ${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function count(value: number | null | undefined): string {
  return value == null ? "—" : Number(value).toLocaleString();
}

function signed(value: number | null | undefined, places = 1): string {
  if (value == null) return "—";
  const n = Number(value);
  return `${n >= 0 ? "+" : ""}${n.toFixed(places)}`;
}

function bandTone(band: string): string {
  switch ((band || "").toUpperCase()) {
    case "CRITICAL":
      return "bg-negative-subtle text-negative border-negative/30";
    case "HIGH":
      return "bg-warning-subtle text-warning border-warning/30";
    case "MEDIUM":
      return "bg-accent-subtle text-accent border-accent/30";
    default:
      return "bg-surface-muted text-text-secondary border-border";
  }
}

export function SeverityBadge({ band, className }: { band: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px]"
        + " font-semibold uppercase tracking-[0.08em]",
        bandTone(band), className,
      )}
      data-testid={`ews-severity-${(band || "").toLowerCase()}`}
    >
      {band || "—"}
    </span>
  );
}

function Kpi({
  label, value, sub, testId, tone, onClick, hint,
}: {
  label: string; value: React.ReactNode; sub?: React.ReactNode;
  testId?: string; tone?: "negative" | "warning" | "default";
  /** §7: a headline count that is a cohort opens that cohort. */
  onClick?: () => void; hint?: string;
}) {
  const body = (
    <>
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        {label}
      </p>
      <p className={cn(
        "mt-1 text-2xl font-semibold tabular-nums",
        tone === "negative" && "text-negative",
        tone === "warning" && "text-warning",
      )}>
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-xs text-text-muted">{sub}</p> : null}
      {onClick ? (
        <p className="mt-1 text-[10px] text-accent">{hint ?? "Open the list"}</p>
      ) : null}
    </>
  );
  if (!onClick) {
    return <Card className="p-4" data-testid={testId}>{body}</Card>;
  }
  return (
    <Card className="p-0" data-testid={testId}>
      <button type="button" onClick={onClick}
              className="w-full p-4 text-left transition-colors hover:bg-surface-muted/60">
        {body}
      </button>
    </Card>
  );
}

/** A layer's 25-month trend, small enough to sit six to a row. */
function LayerSpark({
  label, points, layer,
}: { label: string; points: EwsTrendPoint[]; layer: string }) {
  const data = points.map((p) => ({
    month: p.month, value: Number(p.layers?.[layer] ?? 0),
  }));
  const last = data.length ? data[data.length - 1].value : 0;
  const first = data.length ? data[0].value : 0;
  return (
    <div className="min-w-0" data-testid={`ews-layer-trend-${layer}`}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="truncate text-xs font-medium text-text-secondary">{label}</p>
        <span className="shrink-0 text-xs tabular-nums text-text-primary">
          {last.toFixed(1)}
          <span className={cn(
            "ml-1 text-[10px]",
            last - first > 0 ? "text-negative" : "text-positive",
          )}>
            {signed(last - first)}
          </span>
        </span>
      </div>
      <TrendChart
        data={data}
        xKey="month"
        series={[{ key: "value", label, slot: 0 }]}
        height={72}
      />
    </div>
  );
}

function CountsRow({ counts }: { counts: EwsCounts }) {
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
      <Figure label="Customers" value={count(counts.customers)} />
      <Figure label="With a warning" value={count(counts.customers_warned)} />
      <Figure label="Already bad" value={count(counts.current_bad)}
              tone="negative" />
      <Figure label="Forward risk, performing"
              value={count(counts.forward_risk)} tone="warning" />
      <Figure label="Exposure" value={money(counts.exposure_sar)} />
      <Figure label="Exposure warned" value={money(counts.exposure_warned_sar)} />
      <Figure label="Share warned"
              value={`${(counts.exposure_warned_pct ?? 0).toFixed(1)}%`} />
      <Figure label="Alerts" value={count(counts.alerts)} />
    </div>
  );
}

function Figure({
  label, value, tone,
}: { label: string; value: React.ReactNode; tone?: "negative" | "warning" }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[10px] font-semibold uppercase tracking-[0.1em] text-text-muted">
        {label}
      </p>
      <p className={cn(
        "text-sm font-medium tabular-nums",
        tone === "negative" && "text-negative",
        tone === "warning" && "text-warning",
      )}>{value}</p>
    </div>
  );
}

/**
 * §17: the prebuilt Credit Card story.
 *
 * Two halves of five, because they are two different jobs. The customers on
 * the left have already cost the bank money and the work on them is
 * collections and provisioning. The five on the right are paying every month
 * and are the only ones whose outcome can still be changed — which is the
 * entire argument for having an early warning system at all.
 *
 * Nobody chose these ten. They are the worst of each cohort by EWS score,
 * read from the same panel as the rest of the screen, and each line under a
 * name is built from that customer's own numbers.
 */
function StoryCard({
  month, onOpen,
}: { month: string; onOpen: (customerId: string) => void }) {
  const load = React.useCallback(() => api.ewsStory(month), [month]);
  const { data, loading, error } = useAsync<EwsStory>(load, [load]);

  if (loading && !data) return <Skeleton className="h-64 w-full" />;
  if (error || !data || !data.available) return null;

  const halves: { key: string; label: string; half: typeof data.current_bad;
                  definition: string; tone: "negative" | "warning" }[] = [
    { key: "current_bad", label: "Already bad", half: data.current_bad,
      definition: data.definitions.current_bad, tone: "negative" },
    { key: "forward_risk", label: "Still performing, high forward risk",
      half: data.forward_risk, definition: data.definitions.forward_risk,
      tone: "warning" },
  ];

  return (
    <Card className="p-5" data-testid="ews-story">
      <h2 className="text-base font-semibold text-text-primary">{data.title}</h2>
      <p className="mt-1.5 text-sm text-text-secondary">{data.narrative}</p>
      <div className="mt-4 grid gap-5 xl:grid-cols-2">
        {halves.map((side) => (
          <div key={side.key} data-testid={`ews-story-${side.key}`}>
            <div className="flex flex-wrap items-baseline gap-2">
              <p className={cn(
                "text-[10px] font-semibold uppercase tracking-[0.12em]",
                side.tone === "negative" ? "text-negative" : "text-warning",
              )}>
                {side.label}
              </p>
              <span className="text-xs text-text-muted">
                {count(side.half.customers.length)} of {count(side.half.total)}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-text-muted">{side.definition}</p>
            <ul className="mt-2 space-y-2">
              {side.half.customers.map((row) => (
                <li key={`${row.customer_id}-${row.product_code}`}>
                  <button
                    type="button"
                    onClick={() => onOpen(row.customer_id)}
                    data-testid={`ews-story-customer-${row.customer_id}`}
                    className="w-full rounded-md border border-border p-2.5 text-left transition-colors hover:bg-surface-muted/60"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-text-primary">
                        {row.customer_id}
                      </span>
                      <SeverityBadge band={row.severity} />
                      <span className="text-xs tabular-nums text-text-muted">
                        EWS {row.ews_score.toFixed(1)}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-text-secondary">
                      {row.because}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="mt-4 text-[11px] text-text-muted">{data.note}</p>
    </Card>
  );
}

/** One product card: score, severity, counts, trends and generated prose. */
function ProductCard({
  product, onOpen,
}: { product: EwsProduct; onOpen: (code: string) => void }) {
  const move = product.movement;
  return (
    <Card className="p-5" data-testid={`ews-product-${product.product_code}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-text-primary">
              {product.product_label}
            </h3>
            <SeverityBadge band={product.severity_band} />
          </div>
          <p className="mt-0.5 text-xs text-text-muted">
            Overall early-warning score{" "}
            <span className="font-medium tabular-nums text-text-primary">
              {product.ews_score.toFixed(1)}
            </span>
            {move ? (
              <>
                {" "}· {signed(move.ews_score)} on {product.previous_month}
                {move.severity_from !== move.severity_to
                  ? ` · moved from ${move.severity_from} to ${move.severity_to}`
                  : null}
              </>
            ) : null}
          </p>
        </div>
        <Button variant="outline" size="sm"
                onClick={() => onOpen(product.product_code)}
                data-testid={`ews-open-${product.product_code}`}>
          View details <ChevronRight className="ml-1 size-3.5" aria-hidden />
        </Button>
      </div>

      <div className="mt-4"><CountsRow counts={product} /></div>

      <div className="mt-5">
        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Overall score, 25 months
        </p>
        <TrendChart
          data={product.trend.map((p) => ({ month: p.month, score: p.ews_score }))}
          xKey="month"
          series={[{ key: "score", label: "EWS score", slot: 1 }]}
          height={120}
        />
      </div>

      <div className="mt-5">
        <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Layer trends
          <InfoPopover title="The six layers">
            <p>
              The twenty governed rules roll up into six layers. Five carry
              rules and are scored here.
            </p>
            <p>{CYCLE_NOTE}</p>
          </InfoPopover>
        </div>
        <div className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
          {LAYERS.map((layer) => (
            <LayerSpark key={layer.key} label={layer.label} layer={layer.key}
                        points={product.trend} />
          ))}
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-text-muted">
              Cycle sensitivity
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
              No rules in this rulebook, so nothing is scored.
            </p>
          </div>
        </div>
      </div>

      <div className="mt-5 rounded-md border border-border bg-surface-muted p-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          What changed
        </p>
        <p className="mt-1 text-sm leading-relaxed text-text-secondary"
           data-testid={`ews-commentary-${product.product_code}`}>
          {product.commentary}
        </p>
      </div>
    </Card>
  );
}

/** Level three: one product, cut by a dimension its own data supports. */
function SubsegmentView({
  product, month, onOpen, onBack,
}: {
  product: string; month: string;
  onOpen: (dimension: string, value: string) => void; onBack: () => void;
}) {
  const [dimension, setDimension] = React.useState("");
  const load = React.useCallback(
    () => api.ewsSubsegments(product, month, dimension),
    [product, month, dimension]);
  const { data, loading, error } = useAsync<EwsSubsegments>(load, [load]);

  if (loading && !data) return <Skeleton className="h-64 w-full" />;
  if (error) return <EmptyState title="Subsegments could not be read"
                                description={String(error)} />;
  if (!data) return null;

  return (
    <div className="space-y-4" data-testid="ews-subsegments">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onBack}
                  data-testid="ews-back-to-products">
            <ArrowLeft className="mr-1 size-3.5" aria-hidden /> All products
          </Button>
          <h2 className="text-lg font-semibold text-text-primary">
            {data.product_label}
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
            Break down by
          </span>
          {data.dimensions.map((d) => (
            <button
              key={d.column}
              type="button"
              onClick={() => setDimension(d.column)}
              data-testid={`ews-dimension-${d.column}`}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs transition-colors",
                d.column === data.dimension
                  ? "border-accent bg-accent-subtle text-accent"
                  : "border-border text-text-secondary hover:bg-surface-muted",
              )}
            >
              {d.label}
            </button>
          ))}
        </div>
      </div>

      {data.subsegments.length === 0 ? (
        <EmptyState
          title="No subsegments for this cut"
          description={`${data.product_label} carries no values for `
            + `${data.dimension_label} in the published book.`} />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {data.subsegments.map((cut) => (
            <Card key={cut.value} className="p-4"
                  data-testid={`ews-subsegment-${cut.value}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate text-sm font-semibold text-text-primary">
                      {data.dimension_label}: {cut.value}
                    </h3>
                    <SeverityBadge band={cut.severity_band} />
                  </div>
                  <p className="mt-0.5 text-xs text-text-muted">
                    Score{" "}
                    <span className="tabular-nums text-text-primary">
                      {cut.ews_score.toFixed(1)}
                    </span>
                    {cut.movement
                      ? <> · {signed(cut.movement.ews_score)} on {data.previous_month}</>
                      : null}
                    {" "}· worst layer{" "}
                    <span className="text-text-primary">{cut.primary_layer_name}</span>
                  </p>
                </div>
                <Button size="sm" variant="outline"
                        onClick={() => onOpen(data.dimension, cut.value)}
                        data-testid={`ews-open-customers-${cut.value}`}>
                  Customers <ChevronRight className="ml-1 size-3.5" aria-hidden />
                </Button>
              </div>

              <div className="mt-3"><CountsRow counts={cut} /></div>

              {cut.top_reasons.length ? (
                <div className="mt-3">
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
                    Top reason codes
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {cut.top_reasons.map((r) => (
                      <Link key={r.rule_id}
                            href={`/early-warning/signals?rule=${encodeURIComponent(r.rule_id)}`}
                            className="rounded-full border border-border px-2 py-0.5 text-[11px] text-text-secondary hover:bg-surface-muted"
                            data-testid={`ews-reason-${r.rule_id}`}>
                        {r.rule_id} · {r.rule_name} · {count(r.customers)}
                      </Link>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="mt-3">
                <TrendChart
                  data={cut.trend.map((p) => ({ month: p.month, score: p.ews_score }))}
                  xKey="month"
                  series={[{ key: "score", label: "EWS score", slot: 2 }]}
                  height={90}
                />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Level four: the customers. The behavioural score is a column here, always,
 * because "always show it where available" is the whole point of this list.
 */
function CustomerList({
  month, product, dimension, value, cohort, onCohort, onOpen, onBack,
}: {
  month: string; product: string; dimension: string; value: string;
  // The cohort lives in the address, not in this component. §16 asks the
  // Cockpit to link straight to "the 391 customers who are already bad", and
  // a filter held in component state is a filter no link can name.
  cohort: string; onCohort: (next: string) => void;
  onOpen: (customerId: string) => void; onBack: () => void;
}) {
  const load = React.useCallback(
    () => api.ewsCustomers({ month, product, dimension, value, cohort,
                             limit: 200 }),
    [month, product, dimension, value, cohort]);
  const { data, loading, error } = useAsync<EwsCustomers>(load, [load]);

  if (loading && !data) return <Skeleton className="h-64 w-full" />;
  if (error) return <EmptyState title="The customer list could not be read"
                                description={String(error)} />;
  if (!data) return null;

  return (
    <div className="space-y-4" data-testid="ews-customer-list">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}
                data-testid="ews-back-to-subsegments">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Back
        </Button>
        <h2 className="text-lg font-semibold text-text-primary">
          Customers
          {value ? <span className="text-text-muted"> · {value}</span> : null}
          {!value && product ? (
            <span className="text-text-muted"> · {product.replace(/_/g, " ").toLowerCase()}</span>
          ) : null}
          {!value && !product ? (
            <span className="text-text-muted"> · whole book</span>
          ) : null}
        </h2>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {data.cohorts.map((c) => (
          <button
            key={c.key}
            type="button"
            onClick={() => onCohort(c.key)}
            title={c.definition}
            data-testid={`ews-cohort-${c.key}`}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              c.key === data.cohort
                ? "border-accent bg-accent-subtle text-accent"
                : "border-border text-text-secondary hover:bg-surface-muted",
            )}
          >
            {c.label} <span className="tabular-nums">({count(c.customers)})</span>
          </button>
        ))}
      </div>

      <p className="text-xs text-text-muted">
        <span className="font-medium text-text-secondary">Already bad</span>{" "}
        {data.definitions.current_bad}{" "}
        <span className="font-medium text-text-secondary">Forward risk</span>{" "}
        {data.definitions.forward_risk}
      </p>

      {data.customers.length === 0 ? (
        <EmptyState title="No customers in this cohort"
                    description="Nothing matched this filter at this month-end." />
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-muted text-left">
                <tr className="text-[10px] uppercase tracking-[0.1em] text-text-muted">
                  <th className="px-3 py-2 font-semibold">Customer</th>
                  <th className="px-3 py-2 font-semibold">Product</th>
                  <th className="px-3 py-2 text-right font-semibold">Exposure</th>
                  <th className="px-3 py-2 text-right font-semibold">% sub</th>
                  <th className="px-3 py-2 text-right font-semibold">% prod</th>
                  <th className="px-3 py-2 text-right font-semibold">% book</th>
                  <th className="px-3 py-2 text-right font-semibold">DPD</th>
                  <th className="px-3 py-2 text-right font-semibold">Stage</th>
                  <th className="px-3 py-2 font-semibold">Bad now</th>
                  <th className="px-3 py-2 font-semibold">Forward</th>
                  <th className="px-3 py-2 text-right font-semibold">EWS</th>
                  <th className="px-3 py-2 font-semibold">Severity</th>
                  <th className="px-3 py-2 text-right font-semibold">Behav.</th>
                  <th className="px-3 py-2 text-right font-semibold">Move</th>
                  <th className="px-3 py-2 text-right font-semibold">App.</th>
                  <th className="px-3 py-2 font-semibold">Worst layer</th>
                  <th className="px-3 py-2 font-semibold">Top reasons</th>
                </tr>
              </thead>
              <tbody>
                {data.customers.map((row) => (
                  <CustomerRow key={`${row.customer_id}-${row.product_code}`}
                               row={row} onOpen={onOpen} />
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-3 py-2 text-xs text-text-muted"
             data-testid="ews-customer-list-count">
            Showing {count(data.shown)} of {count(data.total)} rows in this
            cohort, covering {count(data.total_customers)}{" "}
            {data.total_customers === 1 ? "customer" : "customers"}. One row per
            customer per product, so a customer who holds two products appears
            against each.
          </p>
        </Card>
      )}
    </div>
  );
}

function CustomerRow({
  row, onOpen,
}: { row: EwsCustomerRow; onOpen: (id: string) => void }) {
  return (
    <tr className="border-b border-border last:border-0 hover:bg-surface-muted"
        data-testid={`ews-customer-${row.customer_id}`}>
      <td className="px-3 py-2">
        <button type="button" onClick={() => onOpen(row.customer_id)}
                className="font-medium text-accent hover:underline">
          {row.customer_id}
        </button>
        <span className="ml-1 text-[11px] text-text-muted">
          {row.facilities} fac.
        </span>
      </td>
      <td className="px-3 py-2 text-text-secondary">{row.product_label}</td>
      <td className="px-3 py-2 text-right tabular-nums">{money(row.exposure_sar)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-text-muted">
        {row.share_of_subsegment_pct.toFixed(2)}%
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-text-muted">
        {row.share_of_product_pct.toFixed(2)}%
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-text-muted">
        {row.share_of_portfolio_pct.toFixed(3)}%
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{row.dpd ?? "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{row.ifrs9_stage ?? "—"}</td>
      <td className="px-3 py-2">
        {row.current_bad
          ? <Badge variant="negative" data-testid="ews-bad-yes">Yes</Badge>
          : <span className="text-xs text-text-muted">No</span>}
      </td>
      <td className="px-3 py-2">
        {row.forward_risk
          ? <Badge variant="warning" data-testid="ews-forward-yes">Yes</Badge>
          : <span className="text-xs text-text-muted">No</span>}
      </td>
      <td className="px-3 py-2 text-right font-medium tabular-nums">
        {row.ews_score.toFixed(1)}
      </td>
      <td className="px-3 py-2"><SeverityBadge band={row.severity} /></td>
      <td className="px-3 py-2 text-right tabular-nums"
          data-testid={`ews-behavioural-${row.customer_id}`}>
        {row.behavioural_score == null ? (
          // §6 asks for the behavioural score on every row. Where there is
          // none there is a reason, and a dash is not it.
          <span title={row.behavioural_score_absent_because}
                className="text-[11px] font-normal text-text-muted">
            not yet scored
          </span>
        ) : (
          <>
            {row.behavioural_score.toFixed(0)}
            {row.behavioural_score_band
              ? <span className="ml-1 text-[11px] text-text-muted">
                  {row.behavioural_score_band}
                </span>
              : null}
          </>
        )}
      </td>
      <td className={cn(
        "px-3 py-2 text-right tabular-nums",
        (row.behavioural_score_change ?? 0) < 0 ? "text-negative" : "text-text-muted",
      )}>
        {row.behavioural_score_change == null
          ? "—" : signed(row.behavioural_score_change, 0)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-text-muted">
        {row.application_score == null ? "—" : row.application_score.toFixed(0)}
      </td>
      <td className="px-3 py-2 text-xs text-text-secondary">
        {row.primary_layer_name || "—"}
      </td>
      <td className="px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {row.top_rules.length === 0
            ? <span className="text-xs text-text-muted">—</span>
            : row.top_rules.map((id, i) => (
                <span key={`${id}-${i}`}
                      title={row.top_rule_names[i] || id}
                      className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary">
                  {id}
                </span>
              ))}
        </div>
      </td>
    </tr>
  );
}

/** Level five: one customer, every month, every layer. */
function CustomerDetail({
  customerId, month, onBack,
}: { customerId: string; month: string; onBack: () => void }) {
  const load = React.useCallback(
    () => api.ewsCustomer(customerId, month), [customerId, month]);
  const { data, loading, error } = useAsync(load, [load]);

  if (loading && !data) return <Skeleton className="h-72 w-full" />;
  if (error) return <EmptyState title="This customer could not be read"
                                description={String(error)} />;
  if (!data) return null;

  const history = data.history;
  return (
    <div className="space-y-5" data-testid="ews-customer-detail">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}
                data-testid="ews-back-to-customers">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Back
        </Button>
        <h2 className="text-lg font-semibold text-text-primary">
          {data.customer_id}
        </h2>
        <SeverityBadge band={data.severity} />
        {data.current_bad
          ? <Badge variant="negative">Already bad</Badge>
          : data.forward_risk
            ? <Badge variant="warning">Forward risk, performing</Badge>
            : null}
        <Link href={`/borrower-360?borrower=${encodeURIComponent(data.customer_id)}`
                    + `&period=${encodeURIComponent(data.month)}`}
              className="text-xs text-accent hover:underline"
              data-testid="ews-open-customer-360">
          Open in Customer 360
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi label="EWS score" value={data.ews_score.toFixed(1)} />
        <Kpi label="Behavioural score"
             value={data.behavioural_score?.toFixed(0) ?? "Not yet scored"}
             sub={data.behavioural_score != null
               ? (data.behavioural_score_previous != null
                  ? `was ${data.behavioural_score_previous.toFixed(0)}`
                  : undefined)
               : data.behavioural_score_absent_because}
             testId="ews-detail-behavioural" />
        <Kpi label="Exposure" value={money(data.exposure_sar)} />
        <Kpi label="Facilities" value={count(data.facilities)} />
        <Kpi label="Products" value={data.products.join(", ") || "—"} />
      </div>

      <Card className="p-5">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Overall EWS score, 25 months
        </p>
        <TrendChart
          data={history.map((h) => ({ month: h.month, score: h.ews_score }))}
          xKey="month"
          series={[{ key: "score", label: "EWS score", slot: 1 }]}
          height={140}
        />
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
            Behavioural score
          </p>
          <TrendChart
            data={history.map((h) => ({ month: h.month,
                                        value: h.behavioural_score ?? 0 }))}
            xKey="month"
            series={[{ key: "value", label: "Behavioural score", slot: 3 }]}
            height={110} />
        </Card>
        <Card className="p-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
            Days past due
          </p>
          <TrendChart
            data={history.map((h) => ({ month: h.month, value: h.dpd ?? 0 }))}
            xKey="month"
            series={[{ key: "value", label: "DPD", slot: 4 }]}
            height={110} />
        </Card>
        <Card className="p-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
            IFRS 9 stage and exposure
          </p>
          <TrendChart
            data={history.map((h) => ({ month: h.month,
                                        stage: h.ifrs9_stage ?? 0 }))}
            xKey="month"
            series={[{ key: "stage", label: "Stage", slot: 5 }]}
            height={110} />
        </Card>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-text-primary">
          Layer by layer
        </h3>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data.layers.map((layer) => (
            <Card key={layer.key} className="p-4"
                  data-testid={`ews-detail-layer-${layer.key}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">
                    {layer.name}
                  </p>
                  <p className="mt-0.5 text-xs text-text-muted">
                    {layer.source_class} · weight {(layer.weight * 100).toFixed(0)}%
                    {layer.families.length
                      ? ` · ${layer.families.join(", ")}` : null}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold tabular-nums">
                    {layer.value.toFixed(1)}
                  </p>
                  <p className="text-[11px] text-text-muted">
                    {layer.previous == null
                      ? "no prior month"
                      : `was ${layer.previous.toFixed(1)} · ${signed(layer.movement)}`}
                  </p>
                </div>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-text-secondary">
                {layer.purpose}
              </p>
              <div className="mt-2">
                <TrendChart
                  data={layer.trend}
                  xKey="month"
                  series={[{ key: "value", label: layer.name, slot: 0 }]}
                  height={90} />
              </div>
            </Card>
          ))}
          {data.layers_without_rules.map((layer) => (
            <Card key={String(layer.key)} className="p-4">
              <p className="text-sm font-medium text-text-primary">
                {String(layer.name)}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-text-muted">
                {String(layer.absent_because)}
              </p>
            </Card>
          ))}
        </div>
      </div>

      <Card className="p-4" data-testid="ews-reason-timeline">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Reason-code timeline
        </p>
        <div className="space-y-1.5">
          {history.filter((h) => h.top_rules.length).slice().reverse()
            .map((h) => (
            <div key={h.month} className="flex flex-wrap items-center gap-2 text-xs">
              <span className="w-16 shrink-0 tabular-nums text-text-muted">
                {h.month}
              </span>
              <SeverityBadge band={h.severity} />
              {h.top_rules.map((id) => (
                <Link key={id}
                      href={`/early-warning/signals?rule=${encodeURIComponent(id)}`}
                      className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-secondary hover:bg-surface-muted">
                  {id}
                </Link>
              ))}
            </div>
          ))}
          {history.every((h) => !h.top_rules.length) ? (
            <p className="text-xs text-text-muted">
              No governed signal has fired against this customer in the window.
            </p>
          ) : null}
        </div>
      </Card>
    </div>
  );
}

/**
 * The whole hierarchy, with the level in the URL.
 *
 * In the URL rather than in component state, so a Cockpit issue can link
 * straight to `?product=CREDIT_CARD&dimension=card_behaviour_segment&value=
 * TRANSACTOR&cohort=current_bad`, the browser Back button walks back up the
 * levels, and a reader can send somebody the exact screen they are looking at.
 */
export function RetailEarlyWarningPortfolio() {
  // The level is READ from the address, never mirrored into component state.
  //
  // `window.history.pushState` is integrated with the Next router, so a push
  // below re-renders this component with the new params and the browser's own
  // Back button walks back up the levels — no mount effect copying the query
  // into state, and no popstate listener to keep in step with it.
  const query = useSearchParams();
  const month = query.get("month") ?? "";
  const product = query.get("product") ?? "";
  const dimension = query.get("dimension") ?? "";
  const value = query.get("value") ?? "";
  const customer = query.get("customer") ?? "";
  const cohort = query.get("cohort") ?? "";

  const push = React.useCallback((next: Record<string, string>) => {
    if (typeof window === "undefined") return;
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v) q.set(k, v);
    const search = q.toString();
    window.history.pushState({}, "", search ? `?${search}` : window.location.pathname);
  }, []);

  // The headline follows the product selector. It did not, so choosing Credit
  // Card left twelve whole-book figures above a Credit Card breakdown.
  const load = React.useCallback(
    () => api.ewsPortfolio(month, product), [month, product]);
  const { data, loading, error } = useAsync<EwsPortfolio>(load, [load]);

  const go = (next: {
    product?: string; dimension?: string; value?: string; customer?: string;
    month?: string; cohort?: string;
  }) => {
    push({
      month: next.month ?? month,
      product: next.product ?? "",
      dimension: next.dimension ?? "",
      value: next.value ?? "",
      customer: next.customer ?? "",
      cohort: next.cohort ?? "",
    });
  };

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) {
    return <EmptyState title="Early warning could not be read"
                       description={String(error)} />;
  }
  if (!data) return null;
  if (!data.available) {
    return <EmptyState title="The early-warning panel has not been built"
                       description={data.because
                         ?? "Run scripts/bootstrap_retail_installation.py."} />;
  }

  const head = data.headline;

  return (
    <div className="space-y-6" data-testid="ews-portfolio">
      {/* -------------------------------------------------- the controls */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
              Month
            </span>
            <select
              value={data.month}
              onChange={(e) => go({ month: e.target.value, product, dimension,
                                    value, customer })}
              data-testid="ews-month"
              className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm"
            >
              {data.months.slice().reverse().map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
              Product
            </span>
            <select
              value={product}
              onChange={(e) => go({ product: e.target.value })}
              data-testid="ews-product-select"
              className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm"
            >
              <option value="">All products</option>
              {data.products.map((p) => (
                <option key={p.product_code} value={p.product_code}>
                  {p.product_label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* ------------------------------------------------- the headline */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Total customers" value={count(head.customers)}
             testId="ews-kpi-customers" />
        <Kpi label="With an EWS signal" value={count(head.customers_warned)}
             sub={`${count(head.alerts)} alerts`} testId="ews-kpi-warned" />
        <Kpi label="Critical" value={count(head.severity.CRITICAL)}
             tone="negative" testId="ews-kpi-critical" />
        <Kpi label="High" value={count(head.severity.HIGH)} tone="warning"
             testId="ews-kpi-high" />
        <Kpi label="Medium" value={count(head.severity.MEDIUM)}
             testId="ews-kpi-medium" />
        <Kpi label="Low" value={count(head.severity.LOW)} testId="ews-kpi-low" />
        <Kpi label="Already bad / delinquent" value={count(head.current_bad)}
             tone="negative" testId="ews-kpi-bad"
             onClick={() => go({ product, cohort: "current_bad" })}
             hint="Open these customers"
             sub={data.movement ? `${signed(data.movement.current_bad, 0)} on ${data.previous_month}` : undefined} />
        <Kpi label="Forward risk, still performing"
             value={count(head.forward_risk)} tone="warning"
             testId="ews-kpi-forward"
             onClick={() => go({ product, cohort: "forward_risk" })}
             hint="Open these customers"
             sub={data.movement ? `${signed(data.movement.forward_risk, 0)} on ${data.previous_month}` : undefined} />
        <Kpi label="Exposure under warning"
             value={money(head.exposure_warned_sar)} testId="ews-kpi-exposure" />
        <Kpi label="% of retail exposure"
             value={`${head.exposure_warned_pct.toFixed(1)}%`}
             testId="ews-kpi-exposure-pct" />
        <Kpi label="Portfolio EWS score" value={head.ews_score.toFixed(1)}
             sub={data.movement
               ? `${signed(data.movement.ews_score)} on ${data.previous_month}`
               : undefined}
             testId="ews-kpi-score" />
        <Kpi label="Portfolio severity"
             value={<SeverityBadge band={head.severity_band} />}
             testId="ews-kpi-band" />
      </div>

      <p className="text-xs text-text-muted">
        Customers, not alerts: {count(head.customers_warned)}{" "}
        {data.product_label
          ? `${data.product_label.toLowerCase()} customers carry`
          : "customers carry"}{" "}
        the {count(head.alerts)} signals raised at {data.month} under rulebook{" "}
        {data.rulebook_version}.{" "}
        {data.product_label
          ? "Exposure share is of the whole retail book, not of this product. "
          : ""}
        <span className="font-medium text-text-secondary">Already bad</span>{" "}
        {data.definitions.current_bad}{" "}
        <span className="font-medium text-text-secondary">Forward risk</span>{" "}
        {data.definitions.forward_risk}
      </p>

      {/* --------------------------------------------------- the levels */}
      {customer ? (
        <CustomerDetail customerId={customer} month={data.month}
                        onBack={() => go({ product, dimension, value, cohort })} />
      ) : (value || cohort) ? (
        <CustomerList month={data.month} product={product} dimension={dimension}
                      value={value} cohort={cohort || "all"}
                      onCohort={(next) => go({ product, dimension, value,
                                               cohort: next })}
                      onOpen={(id) => go({ product, dimension, value, cohort,
                                           customer: id })}
                      onBack={() => go(value ? { product } : {})} />
      ) : product ? (
        <SubsegmentView product={product} month={data.month}
                        onOpen={(d, v) => go({ product, dimension: d, value: v })}
                        onBack={() => go({})} />
      ) : (
        <div className="space-y-4">
          <Card className="p-5">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
              Portfolio EWS score, 25 months
            </p>
            <TrendChart
              data={data.trend.map((p) => ({ month: p.month, score: p.ews_score }))}
              xKey="month"
              series={[{ key: "score", label: "EWS score", slot: 1 }]}
              height={140} />
          </Card>
          <StoryCard month={data.month}
                     onOpen={(id) => go({ product: "CREDIT_CARD",
                                          customer: id })} />
          <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
            {data.products.map((p) => (
              <ProductCard key={p.product_code} product={p}
                           onOpen={(code) => go({ product: code })} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
