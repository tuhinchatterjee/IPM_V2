"use client";

/**
 * The signals and rules view, inside the workspace rather than beside it.
 *
 * §29 keeps it — every trigger clickable, with its business meaning, its
 * layer and sublayer, the variables it reads, its threshold, which products
 * it applies to, whether it is internal, external or derived, how many
 * customers it caught and what that is worth. §16 of the rebuild brief says
 * it is no longer the landing screen, so it lives behind a control at the top
 * of the workspace.
 *
 * A trigger the book cannot support is listed with the reason rather than
 * hidden, because a reader who cannot see it has no way to ask why it never
 * fires.
 */

import * as React from "react";
import { ArrowLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EwsSignalDetail, type EwsSignals } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { LAYERS, Severity, count, money } from "./parts";
import { Spark } from "./spark";

export function EwsSignalsView({
  month, product, subProduct, onReason, onBack,
}: {
  month: string; product: string; subProduct: string;
  onReason: (reasonCode: string) => void;
  onBack: () => void;
}) {
  const [layer, setLayer] = React.useState("");
  const [severity, setSeverity] = React.useState("");
  const [opened, setOpened] = React.useState("");

  const load = React.useCallback(
    () => api.ewsScoreSignals({ month, product, sub_product: subProduct,
                                layer, severity }),
    [month, product, subProduct, layer, severity]);
  const { data, loading, error } = useAsync<EwsSignals>(load, [load]);

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) return <EmptyState title="The signals could not be read"
                                description={String(error)} />;
  if (!data?.available) return null;

  return (
    <div className="space-y-4" data-testid="ews-signals-view">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}
                data-testid="ews-signals-back">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Back
        </Button>
        <h2 className="text-lg font-semibold text-text-primary">
          Signals and rules
        </h2>
        <span className="text-xs text-text-muted" data-testid="ews-signals-showing">
          Showing {data.shown} of {data.total_signals} triggers,{" "}
          {count(data.total_hits)} facility hits at {data.month}
          {data.capped ? " — narrow by layer or severity to see the rest" : ""}
        </span>
      </div>

      <div className="flex flex-wrap gap-4">
        <Deck title="By layer" testId="ews-signals-by-layer"
              chips={data.by_layer.map((one) => ({
                key: one.layer,
                label: `${LAYERS.find((l) => l.key === one.layer)?.short
                  ?? one.layer_name} · ${count(one.hits)}`,
                active: layer === one.layer,
                onClick: () => setLayer(layer === one.layer ? "" : one.layer),
                testId: `ews-signals-layer-${one.layer}`,
              }))} />
        <Deck title="By severity" testId="ews-signals-by-severity"
              chips={data.by_severity.filter((one) => one.hits > 0).map((one) => ({
                key: one.severity,
                label: `${one.severity} · ${count(one.hits)}`,
                active: severity === one.severity,
                onClick: () => setSeverity(
                  severity === one.severity ? "" : one.severity),
                testId: `ews-signals-severity-${one.severity}`,
              }))} />
      </div>

      <div className="space-y-2">
        {data.signals.map((row) => (
          <Card key={row.key} className="p-0"
                data-testid={`ews-signal-${row.key}`}>
            <button type="button"
                    onClick={() => setOpened(opened === row.key ? "" : row.key)}
                    className="flex w-full flex-wrap items-center gap-2 p-3
                               text-left transition-colors hover:bg-surface-muted/50">
              <Severity band={row.severity} />
              <span className="text-sm font-medium text-text-primary">
                {row.name}
              </span>
              <span className="font-mono text-[10px] text-text-muted">
                {row.reason_code}
              </span>
              <span className="text-[11px] text-text-muted">
                {row.layer_name} / {row.sublayer_name}
              </span>
              <span className="text-[11px] text-text-muted">
                {row.source_class}
              </span>
              {!row.available ? (
                <span className="rounded border border-warning/40
                                 bg-warning-subtle px-1.5 py-0.5 text-[10px]
                                 text-warning">
                  declared, not evaluated
                </span>
              ) : null}
              {row.needs_new_observation ? (
                <span className="rounded border border-border px-1.5 py-0.5
                                 text-[10px] text-text-muted">
                  fires only on a new bureau observation
                </span>
              ) : null}
              <span className="ml-auto flex items-center gap-3 text-[11px]
                               tabular-nums text-text-secondary">
                <span>{count(row.customers)} customers</span>
                <span>{money(row.exposure_sar)}</span>
                <span className={cn(row.change > 0 ? "text-negative"
                  : row.change < 0 ? "text-positive" : "text-text-muted")}>
                  {row.change > 0 ? "+" : ""}{row.change}
                </span>
                <ChevronRight className={cn("size-3.5 transition-transform",
                                            opened === row.key && "rotate-90")}
                              aria-hidden />
              </span>
            </button>

            {opened === row.key ? (
              <SignalDetail signalKey={row.key} month={data.month}
                            onReason={onReason} />
            ) : null}
          </Card>
        ))}
      </div>
    </div>
  );
}

function Deck({ title, chips, testId }: {
  title: string;
  chips: { key: string; label: string; active: boolean; onClick: () => void;
           testId: string }[];
  testId?: string;
}) {
  if (!chips.length) return null;
  return (
    <div className="min-w-0">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em]
                    text-text-muted">{title}</p>
      <div className="flex flex-wrap gap-1.5" data-testid={testId}>
        {chips.map((chip) => (
          <button key={chip.key} type="button" onClick={chip.onClick}
                  data-testid={chip.testId}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-[11px] transition-colors",
                    chip.active
                      ? "border-accent bg-accent-subtle text-accent"
                      : "border-border text-text-secondary hover:bg-surface-muted")}>
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function SignalDetail({ signalKey, month, onReason }: {
  signalKey: string; month: string;
  onReason: (reasonCode: string) => void;
}) {
  const load = React.useCallback(
    () => api.ewsScoreSignal(signalKey, month), [signalKey, month]);
  const { data, loading } = useAsync<EwsSignalDetail>(load, [load]);
  if (loading && !data) return <Skeleton className="m-3 h-24" />;
  if (!data?.available) return null;
  return (
    <div className="space-y-3 border-t border-border p-3"
         data-testid={`ews-signal-detail-${signalKey}`}>
      <p className="text-xs text-text-secondary">{data.meaning}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]
                      sm:grid-cols-4">
        <Fact label="Reads" value={data.column
          + (data.comparator_column ? ` against ${data.comparator_column}` : "")} />
        <Fact label="Condition" value={data.expression} />
        <Fact label="Threshold" value={`${data.threshold} ${data.unit}`} />
        <Fact label="Threshold source" value={data.threshold_source} />
        <Fact label="Applies to" value={data.products
          .map((p) => p.replace(/_/g, " ").toLowerCase()).join(", ")} />
        <Fact label="Classification" value={data.source_class} />
        <Fact label="Already bad" value={count(data.current_bad)} />
        <Fact label="Forward risk" value={count(data.forward_risk)} />
      </div>
      {data.absent_because ? (
        <p className="rounded border border-warning/40 bg-warning-subtle/40 p-2
                      text-[11px] text-text-secondary">
          {data.absent_because}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-[160px_minmax(0,1fr)]">
        <Spark label="Customers, 6 months" height={40}
               points={data.trend.map((point) => ({ month: point.month,
                                                    value: point.customers }))}
               testId={`ews-signal-trend-${signalKey}`} />
        <div>
          <p className="mb-1 text-[9px] uppercase tracking-[0.08em] text-text-muted">
            By product
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
            {data.by_product.map((one) => (
              <span key={one.product_code} className="text-text-muted">
                {one.product_label}:{" "}
                <span className="font-medium tabular-nums text-text-secondary">
                  {count(one.customers)}
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>
      <p className="text-[11px] italic text-text-muted">
        {data.recommended_review}
      </p>
      <Button size="sm" variant="outline"
              onClick={() => onReason(data.reason_code)}
              data-testid={`ews-signal-open-${signalKey}`}>
        Open the {count(data.customers)} customers this caught
      </Button>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[9px] uppercase tracking-[0.06em] text-text-muted">
        {label}
      </p>
      <p className="text-text-secondary">{value}</p>
    </div>
  );
}
