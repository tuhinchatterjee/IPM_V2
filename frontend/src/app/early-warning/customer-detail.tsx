"use client";

/**
 * One customer, all the way down.
 *
 * §12: the overall score and its six-month trend, the four layer scores with
 * their own trends where the layer is dynamic, the sublayers under them, every
 * variable with its raw value and what it was compared against, the triggers
 * that fired with their six action dimensions, the facilities, and the
 * customer's share of sub-portfolio, product and retail exposure.
 *
 * The bureau layer does not get a trend, and says why: the bank does not
 * receive a monthly bureau file, so what is shown is the last dated
 * observation and how old it is.
 */

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api, type EwsCustomerDetail as Detail, type EwsLayerDetail,
  type EwsSublayer, type EwsTrigger,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { ExportToWhatIf, Kpi, Severity, money, signed } from "./parts";
import { Spark } from "./spark";

export function CustomerDetail({ customerId, month, onBack }: {
  customerId: string;
  month: string;
  /** Absent when this is embedded in Customer 360, which has its own tabs. */
  onBack?: () => void;
}) {
  const load = React.useCallback(
    () => api.ewsScoreCustomer(customerId, month), [customerId, month]);
  const { data, loading, error } = useAsync<Detail>(load, [load]);

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) return <EmptyState title="This customer could not be read"
                                description={String(error)} />;
  if (!data?.available) {
    return <EmptyState title="Not in the Early Warning Score domain"
                       description={data?.because ?? ""} />;
  }

  const history = data.history;
  const recent = history.slice(-6);

  return (
    <div className="space-y-5" data-testid="ews-customer-detail">
      <div className="flex flex-wrap items-center gap-2">
        {onBack ? (
          <Button variant="ghost" size="sm" onClick={onBack}
                  data-testid="ews-back-to-customers">
            <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Back
          </Button>
        ) : null}
        <h2 className="text-lg font-semibold text-text-primary">
          {data.customer_name}
        </h2>
        <span className="font-mono text-xs text-text-muted">
          {data.customer_id}
        </span>
        <Severity band={data.ews_severity} />
        {data.current_bad
          ? <Badge variant="negative">Already bad</Badge>
          : data.forward_risk
            ? <Badge variant="warning">Forward risk, performing</Badge>
            : null}
        {/* This customer's own facilities, handed to What-If as a cohort of
            one: §31 asks for the export here as well as on every card above,
            and a single customer is the smallest honest selection. */}
        <ExportToWhatIf
          testId="ews-export-customer"
          label="Export to What-If"
          scope={{ month: data.month, level: "customer",
                   customer_id: data.customer_id }} />
        {/* Embedded in Customer 360 there is nothing to open: the reader is
            already there, and the useful link is the one back to the Early
            Warning workspace, where this customer sits in a population. */}
        {onBack ? (
          <Link href={`/borrower-360?borrower=${encodeURIComponent(data.customer_id)}`
                      + `&period=${encodeURIComponent(data.month)}`}
                className="flex items-center gap-1 text-xs text-accent hover:underline"
                data-testid="ews-open-customer-360">
            Open in Customer 360
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        ) : (
          <Link href={`/early-warning?customer=${encodeURIComponent(data.customer_id)}`
                      + `&month=${encodeURIComponent(data.month)}`}
                className="flex items-center gap-1 text-xs text-accent hover:underline"
                data-testid="ews-open-workspace">
            Open in Early Warning Score
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        )}
      </div>

      {/* ------------------------------------------------- overall block */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Early Warning Score" value={data.ews_score.toFixed(1)}
             sub={data.movement != null
               ? `${signed(data.movement)} on ${data.previous_month}`
               : "no prior month"}
             testId="ews-detail-score" />
        <Kpi label="Severity" value={<Severity band={data.ews_severity} />}
             sub={`warned at ${data.ews_threshold}`}
             testId="ews-detail-severity" />
        <Kpi label="Behavioural score"
             value={data.behavioural_score?.toFixed(0) ?? "Not yet scored"}
             sub={data.behavioural_score != null
               ? (data.behavioural_score_previous != null
                 ? `was ${data.behavioural_score_previous.toFixed(0)}`
                 : data.behavioural_score_band)
               : data.behavioural_score_absent_because}
             testId="ews-detail-behavioural" />
        <Kpi label="Exposure" value={money(data.exposure_sar)}
             sub={`${data.facility_count} facilit`
                  + `${data.facility_count === 1 ? "y" : "ies"}`} />
        <Kpi label="Product" value={data.product_label}
             sub={data.sub_product_label} />
        <Kpi label="Share of retail exposure"
             value={`${data.exposure_share.portfolio_pct.toFixed(3)}%`}
             sub={`${data.exposure_share.product_pct.toFixed(2)}% of product · `
                  + `${data.exposure_share.sub_product_pct.toFixed(2)}% of `
                  + "sub-portfolio"}
             testId="ews-detail-exposure-share" />
      </div>

      {data.hard_trigger_applied ? (
        <Card className="border-negative/40 bg-negative-subtle/30 p-3"
              data-testid="ews-detail-hard-trigger">
          <p className="text-xs text-text-secondary">
            <span className="font-semibold text-negative">
              Hard trigger applied:
            </span>{" "}
            {data.hard_triggers.find((h) => h.key === data.hard_trigger_applied)
              ?.name}. {data.hard_triggers.find(
                (h) => h.key === data.hard_trigger_applied)?.because}
          </p>
        </Card>
      ) : null}

      <Card className="p-4">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">
              Early Warning Score, {history.length} month
              {history.length === 1 ? "" : "s"} on book
            </p>
            <div className="grid grid-cols-3 gap-4">
              <Spark label="EWS score" height={56}
                     points={recent.map((h) => ({ month: h.month,
                                                  value: h.ews_score }))}
                     bands={[{ value: data.ews_threshold, label: "warning" }]}
                     testId="ews-detail-spark-score" />
              <Spark label="DPD" height={56} tone="negative"
                     points={recent.map((h) => ({ month: h.month,
                                                  value: h.dpd }))}
                     bands={[{ value: 30, label: "30 days" }]}
                     testId="ews-detail-spark-dpd" />
              <Spark label="Behavioural" height={56} tone="warning"
                     points={recent.map((h) => ({
                       month: h.month, value: h.behavioural_score }))}
                     empty="not yet scored"
                     testId="ews-detail-spark-behavioural" />
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">
              Bureau, as last observed
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs"
                 data-testid="ews-detail-bureau">
              <Small label="Last observed score"
                     value={data.bureau.score?.toFixed(0) ?? "—"} />
              <Small label="Band" value={data.bureau.band || "—"} />
              <Small label="Observation date"
                     value={data.bureau.last_observed || "—"} />
              <Small label="Recency"
                     value={data.bureau.recency_months != null
                       ? `${data.bureau.recency_months.toFixed(0)} months`
                       : "—"} />
              <Small label="At origination"
                     value={data.bureau.at_origination?.toFixed(0) ?? "—"} />
              <Small label="New pull this month"
                     value={data.bureau.observed_this_month ? "Yes" : "No"} />
            </div>
            <p className="mt-2 text-[10px] leading-relaxed text-text-muted">
              {data.bureau.no_trend_because} {data.bureau.proxy_label}
            </p>
          </div>
        </div>
      </Card>

      {/* --------------------------------------------------- four layers */}
      <section className="space-y-3" data-testid="ews-detail-layers">
        <h3 className="text-sm font-semibold text-text-primary">
          The four layers
        </h3>
        {data.layers.map((layer) => (
          <LayerPanel key={layer.key} layer={layer} />
        ))}
      </section>

      {/* --------------------------------------------------- facilities */}
      <Card className="overflow-hidden" data-testid="ews-detail-facilities">
        <p className="border-b border-border px-4 py-2.5 text-[10px]
                      font-semibold uppercase tracking-[0.1em] text-text-muted">
          Facilities and exposure contribution
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-surface-muted text-left">
              <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {["Facility", "Product", "Sub-product", "Exposure",
                  "% of customer", "DPD", "Stage", "Months on book", "EWS",
                  "Severity", "Triggers"].map((column) => (
                  <th key={column} className="px-3 py-2 font-semibold">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.facilities.map((one) => (
                <tr key={one.facility_id}
                    className="border-b border-border last:border-0">
                  <td className="px-3 py-2 font-mono text-[11px]">
                    {one.facility_id}
                  </td>
                  <td className="px-3 py-2">{one.product_label}</td>
                  <td className="px-3 py-2 text-text-secondary">
                    {one.sub_product_label}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {money(one.exposure_sar)}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-text-muted">
                    {one.share_of_customer_pct.toFixed(0)}%
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {one.dpd?.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {one.ifrs9_stage?.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-text-muted">
                    {one.months_on_book?.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-2 font-medium tabular-nums">
                    {one.ews_score.toFixed(1)}
                  </td>
                  <td className="px-3 py-2">
                    <Severity band={one.ews_severity} />
                  </td>
                  <td className="px-3 py-2 tabular-nums">
                    {one.triggers_fired}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ------------------------------------------ the warning history */}
      <Card className="overflow-hidden" data-testid="ews-detail-history">
        <p className="border-b border-border px-4 py-2.5 text-[10px]
                      font-semibold uppercase tracking-[0.1em] text-text-muted">
          Warning history — every month in the domain
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-surface-muted text-left">
              <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {["Month", "EWS", "Severity", "DPD", "Stage", "Behavioural",
                  "Triggers", "Reason codes"].map((column) => (
                  <th key={column} className="px-3 py-2 font-semibold">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.slice().reverse().map((one) => (
                <tr key={one.month}
                    className="border-b border-border last:border-0">
                  <td className="px-3 py-1.5 tabular-nums">{one.month}</td>
                  <td className="px-3 py-1.5 font-medium tabular-nums">
                    {one.ews_score.toFixed(1)}
                  </td>
                  <td className="px-3 py-1.5">
                    <Severity band={one.severity} />
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {one.dpd?.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {one.ifrs9_stage?.toFixed(0) ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {one.behavioural_score?.toFixed(0) ?? "not yet scored"}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {one.triggers_fired}
                  </td>
                  <td className="px-3 py-1.5">
                    <span className="flex flex-wrap gap-1">
                      {one.reasons.map((code) => (
                        <span key={code}
                              className="rounded border border-border px-1
                                         font-mono text-[10px] text-text-secondary">
                          {code}
                        </span>
                      ))}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[9px] uppercase tracking-[0.06em] text-text-muted">
        {label}
      </p>
      <p className="truncate font-medium tabular-nums text-text-primary">
        {value}
      </p>
    </div>
  );
}

function LayerPanel({ layer }: { layer: EwsLayerDetail }) {
  const [open, setOpen] = React.useState(layer.score > 0);
  const fired = layer.sublayers.flatMap((sub) =>
    sub.triggers.filter((trigger) => trigger.fired));
  return (
    <Card className="overflow-hidden"
          data-testid={`ews-detail-layer-${layer.key}`}>
      <button type="button" onClick={() => setOpen((was) => !was)}
              aria-expanded={open}
              className="flex w-full items-start gap-3 p-4 text-left
                         transition-colors hover:bg-surface-muted/50">
        {open ? <ChevronDown className="mt-1 size-4 shrink-0 text-text-muted" aria-hidden />
              : <ChevronRight className="mt-1 size-4 shrink-0 text-text-muted" aria-hidden />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-text-primary">
              {layer.name}
            </span>
            <Severity band={layer.severity} />
            <span className="text-sm font-semibold tabular-nums text-text-primary">
              {layer.score.toFixed(1)}
            </span>
            {layer.movement != null ? (
              <span className={cn("text-xs tabular-nums",
                                  layer.movement > 0 ? "text-negative"
                                                     : "text-positive")}>
                {signed(layer.movement)} on the month
              </span>
            ) : (
              <span className="text-xs text-text-muted">no prior month</span>
            )}
            <span className="text-[11px] text-text-muted">
              weight {(layer.weight * 100).toFixed(0)}% ·{" "}
              {layer.kind === "dynamic" ? "dynamic" : "classifier"} layer ·{" "}
              {fired.length} trigger{fired.length === 1 ? "" : "s"} firing
            </span>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-text-secondary">
            {layer.purpose}
          </p>
          {layer.top_sublayer ? (
            <p className="mt-1 text-[11px] text-text-muted">
              Worst sub-layer: {layer.top_sublayer}
            </p>
          ) : null}
        </div>
        {layer.dynamic ? (
          <div className="w-28 shrink-0">
            <Spark label="6 months" height={34}
                   points={layer.trend.map((point) => ({
                     month: point.month, value: point.value }))}
                   testId={`ews-detail-layer-trend-${layer.key}`} />
          </div>
        ) : (
          <p className="w-28 shrink-0 text-right text-[10px] text-text-muted"
             data-testid={`ews-detail-layer-no-trend-${layer.key}`}>
            No monthly trend: this layer moves only when a new observation
            arrives.
          </p>
        )}
      </button>

      {open ? (
        <div className="space-y-3 border-t border-border p-4">
          {layer.sublayers.map((sub) => (
            <SublayerPanel key={sub.key} sublayer={sub} />
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function SublayerPanel({ sublayer }: { sublayer: EwsSublayer }) {
  const fired = sublayer.triggers.filter((trigger) => trigger.fired);
  const quiet = sublayer.triggers.filter((trigger) => !trigger.fired);
  return (
    <div className="rounded-md border border-border p-3"
         data-testid={`ews-sublayer-${sublayer.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-text-primary">
          {sublayer.name}
        </span>
        <span className="text-xs font-semibold tabular-nums text-text-primary">
          {sublayer.score.toFixed(1)}
        </span>
        <span className="text-[10px] text-text-muted">
          weight {(sublayer.weight * 100).toFixed(0)}% within the layer
        </span>
      </div>
      <p className="mt-0.5 text-[11px] text-text-secondary">
        {sublayer.purpose}
      </p>

      {sublayer.classifiers.length ? (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1"
             data-testid={`ews-classifiers-${sublayer.key}`}>
          {sublayer.classifiers.map((one) => (
            <span key={one.key} className="text-[10px] text-text-muted"
                  title={`${one.meaning} (${one.source_class}, ${one.column})`}>
              {one.name}:{" "}
              <span className="font-medium text-text-secondary">
                {one.value == null || one.value === "" ? "—" : String(one.value)}
              </span>
            </span>
          ))}
        </div>
      ) : null}

      {fired.length ? (
        <div className="mt-2 space-y-2">
          {fired.map((trigger) => (
            <TriggerRow key={trigger.key} trigger={trigger} />
          ))}
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-text-muted">
          Nothing firing here. {quiet.length} trigger
          {quiet.length === 1 ? "" : "s"} evaluated and quiet
          {quiet.some((t) => !t.available)
            ? `; ${quiet.filter((t) => !t.available).length} declared but not `
              + "evaluated on this book"
            : ""}.
        </p>
      )}
    </div>
  );
}

function TriggerRow({ trigger }: { trigger: EwsTrigger }) {
  const action = trigger.action;
  return (
    <div className="rounded border border-border bg-surface-muted/40 p-2.5"
         data-testid={`ews-trigger-${trigger.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Severity band={trigger.severity} />
        <span className="text-xs font-medium text-text-primary">
          {trigger.name}
        </span>
        <span className="font-mono text-[10px] text-text-muted">
          {trigger.reason_code}
        </span>
        <span className="text-[10px] text-text-muted">
          {trigger.source_class}
        </span>
        {trigger.contribution != null ? (
          <span className="text-[10px] tabular-nums text-text-secondary">
            contributes {trigger.contribution.toFixed(0)}
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-[11px] text-text-secondary">{trigger.meaning}</p>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]
                      sm:grid-cols-4">
        <Small label="Variable" value={trigger.column} />
        <Small label="Raw value"
               value={trigger.raw_value != null
                 ? trigger.raw_value.toLocaleString(undefined,
                     { maximumFractionDigits: 2 }) : "—"} />
        <Small label="Compared against"
               value={trigger.comparator_value != null
                 ? trigger.comparator_value.toLocaleString(undefined,
                     { maximumFractionDigits: 2 })
                 : `${trigger.threshold}`} />
        <Small label="Threshold"
               value={`${trigger.threshold} ${trigger.unit}`} />
      </div>
      {action ? (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10px]"
             data-testid={`ews-action-${trigger.key}`}>
          {[["Direction", action.direction],
            ["Magnitude", action.magnitude?.toFixed(2) ?? "—"],
            ["Velocity", action.velocity?.toFixed(2) ?? "—"],
            ["Momentum", action.momentum],
            ["Persistence", action.persistence != null
              ? `${action.persistence.toFixed(0)} month`
                + `${action.persistence === 1 ? "" : "s"}` : "—"],
            ["Recency", action.recency != null
              ? `${action.recency.toFixed(0)} month`
                + `${action.recency === 1 ? "" : "s"}` : "—"],
          ].map(([label, value]) => (
            <span key={label} className="text-text-muted">
              {label}:{" "}
              <span className="font-medium text-text-secondary">{value}</span>
            </span>
          ))}
        </div>
      ) : null}
      <p className="mt-1 text-[10px] italic text-text-muted">
        {trigger.recommended_review}
      </p>
    </div>
  );
}
