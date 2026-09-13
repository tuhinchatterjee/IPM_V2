"use client";

/**
 * One customer, compact, with the empty right-hand side put to work.
 *
 * §11 asks for the card NOT to grow: the facts a credit officer reads stay on
 * the left and the space to their right — which was blank — carries three
 * six-month sparklines. The row has to answer "what is wrong, how severe is
 * it, and is it getting worse" without anybody opening Customer 360.
 *
 * Three charts, not four. There is no bureau series, because the bank does not
 * receive a bureau file every month; drawing one would be inventing movement
 * nobody observed. Bureau appears as its last observed score, the date of that
 * observation, and how old it is.
 */

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import type { EwsCustomerRow } from "@/lib/api";
import { cn } from "@/lib/utils";

import { LayerChip, LAYERS, money, Severity } from "./parts";
import { Spark } from "./spark";

export function CustomerCard({
  row, threshold, onOpen,
}: {
  row: EwsCustomerRow;
  threshold: number;
  onOpen: (customerId: string) => void;
}) {
  const series = row.series ?? [];
  const material = LAYERS
    .map((layer) => ({ layer, value: row.layers?.[layer.key] ?? 0 }))
    .filter((one) => one.value > 0)
    .sort((a, b) => b.value - a.value);

  return (
    <Card className="p-0 transition-colors hover:border-border-strong"
          data-testid={`ews-customer-${row.customer_id}`}>
      <div className="grid gap-4 p-3.5 lg:grid-cols-[minmax(0,1fr)_320px]">
        {/* ---------------------------------------------- the facts, left */}
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => onOpen(row.customer_id)}
                    className="text-sm font-semibold text-accent hover:underline"
                    data-testid={`ews-open-${row.customer_id}`}>
              {row.customer_name || row.customer_id}
            </button>
            <span className="font-mono text-[11px] text-text-muted">
              {row.customer_id}
            </span>
            <Severity band={row.ews_severity} />
            <span className="text-[11px] tabular-nums text-text-secondary">
              EWS <span className="font-semibold text-text-primary">
                {row.ews_score.toFixed(1)}
              </span>
              <span className="text-text-muted"> / warned at {threshold}</span>
            </span>
            {row.current_bad ? (
              <Badge variant="negative" data-testid="ews-bad-yes">
                Already bad
              </Badge>
            ) : null}
            {row.forward_risk ? (
              <Badge variant="warning" data-testid="ews-forward-yes">
                Forward risk
              </Badge>
            ) : null}
            {row.hard_trigger_applied ? (
              <span className="rounded border border-negative/30
                               bg-negative-subtle px-1.5 py-0.5 text-[10px]
                               text-negative"
                    title="A hard trigger floors this score regardless of the
                           weighted roll-up.">
                hard trigger
              </span>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]
                          sm:grid-cols-4">
            <Fact label="Product" value={row.product_label} />
            <Fact label="Sub-product" value={row.sub_product_label} />
            <Fact label="Facilities" value={String(row.facilities)} />
            <Fact label="Exposure" value={money(row.exposure_sar)} />
            <Fact label="DPD"
                  value={row.dpd == null ? "—" : `${row.dpd.toFixed(0)}`}
                  tone={row.dpd && row.dpd >= 30 ? "negative" : undefined} />
            <Fact label="Stage"
                  value={row.ifrs9_stage == null ? "—"
                    : String(row.ifrs9_stage.toFixed(0))} />
            <Fact label="Behavioural"
                  testId={`ews-behavioural-${row.customer_id}`}
                  value={row.behavioural_score == null
                    ? "not yet scored"
                    : `${row.behavioural_score.toFixed(0)}`
                      + (row.behavioural_score_band
                        ? ` ${row.behavioural_score_band}` : "")}
                  note={row.behavioural_score == null
                    ? row.behavioural_score_absent_because
                    : row.behavioural_score_change != null
                      ? `${row.behavioural_score_change > 0 ? "+" : ""}`
                        + `${row.behavioural_score_change.toFixed(0)} on the month`
                      : undefined}
                  tone={(row.behavioural_score_change ?? 0) < 0
                    ? "negative" : undefined} />
            <Fact label="Application"
                  value={row.application_score == null ? "—"
                    : `${row.application_score.toFixed(0)}`
                      + (row.application_score_band
                        ? ` ${row.application_score_band}` : "")} />
            <Fact label="% of sub-product"
                  value={`${row.share_of_sub_product_pct.toFixed(2)}%`} />
            <Fact label="% of product"
                  value={`${row.share_of_product_pct.toFixed(2)}%`} />
            <Fact label="% of retail"
                  value={`${row.share_of_portfolio_pct.toFixed(3)}%`} />
            <Fact label="Bureau" testId={`ews-bureau-${row.customer_id}`}
                  value={row.bureau_score == null ? "—"
                    : `${row.bureau_score.toFixed(0)}`
                      + (row.bureau_band ? ` ${row.bureau_band}` : "")}
                  note={row.bureau_last_observed
                    ? `seen ${row.bureau_last_observed}`
                      + (row.bureau_recency_months != null
                        ? `, ${row.bureau_recency_months.toFixed(0)}mo old` : "")
                    : undefined} />
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {material.length ? material.map((one) => (
              <LayerChip key={one.layer.key} layer={one.layer}
                         value={one.value}
                         testId={`ews-layer-${row.customer_id}-${one.layer.key}`} />
            )) : (
              <span className="text-[11px] text-text-muted">
                No layer is scoring for this customer.
              </span>
            )}
            {row.reasons?.map((reason) => (
              <span key={reason.code}
                    title={reason.name}
                    data-testid={`ews-reason-chip-${reason.code}`}
                    className="rounded border border-border px-1.5 py-0.5
                               font-mono text-[10px] text-text-secondary">
                {reason.code}
              </span>
            ))}
          </div>
        </div>

        {/* ------------------------------------- the three charts, right */}
        <div className="grid grid-cols-3 gap-3 border-t border-border pt-3
                        lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0"
             data-testid={`ews-charts-${row.customer_id}`}>
          <Spark label="EWS score" testId={`ews-spark-score-${row.customer_id}`}
                 points={series.map((p) => ({ month: p.month,
                                              value: p.ews_score }))}
                 bands={[{ value: threshold, label: "warning" }]}
                 tone="accent" />
          <Spark label="DPD" testId={`ews-spark-dpd-${row.customer_id}`}
                 points={series.map((p) => ({ month: p.month, value: p.dpd }))}
                 bands={[{ value: 30, label: "30 days" }]}
                 tone="negative" empty="no DPD history" />
          <Spark label="Behavioural"
                 testId={`ews-spark-behavioural-${row.customer_id}`}
                 points={series.map((p) => ({ month: p.month,
                                              value: p.behavioural_score }))}
                 tone="warning" empty="not yet scored" />
          <p className="col-span-3 text-[9px] text-text-muted">
            Six months. No bureau series is drawn: the bank does not receive a
            monthly bureau file, so the last observed score and its date are
            shown on the left instead.
          </p>
        </div>
      </div>

      <button type="button" onClick={() => onOpen(row.customer_id)}
              className="flex w-full items-center justify-between border-t
                         border-border px-3.5 py-1.5 text-[11px]
                         text-text-muted transition-colors
                         hover:bg-surface-muted hover:text-text-secondary">
        <span>
          {row.primary_layer_name
            ? `Worst layer: ${row.primary_layer_name}`
            : "Nothing firing"}
          {row.triggers_fired
            ? ` · ${row.triggers_fired} trigger${row.triggers_fired === 1 ? "" : "s"} firing`
            : ""}
        </span>
        <span className="flex items-center gap-1">
          Open the customer
          <ChevronRight className="size-3" aria-hidden />
        </span>
      </button>
    </Card>
  );
}

function Fact({ label, value, note, tone, testId }: {
  label: string; value: string; note?: string;
  tone?: "negative"; testId?: string;
}) {
  return (
    <div className="min-w-0" data-testid={testId}>
      <p className="truncate text-[9px] uppercase tracking-[0.06em] text-text-muted">
        {label}
      </p>
      <p className={cn("truncate font-medium tabular-nums text-text-primary",
                       tone === "negative" && "text-negative")}
         title={note}>
        {value}
      </p>
      {note ? (
        <p className="truncate text-[9px] text-text-muted" title={note}>
          {note}
        </p>
      ) : null}
    </div>
  );
}
