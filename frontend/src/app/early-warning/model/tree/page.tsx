"use client";

/**
 * The model as a tree, because that is the shape it actually has.
 *
 * View Model already lists everything the Early Warning Score is made of, and
 * a list is the wrong shape for a thing with four layers, nineteen sub-layers
 * and seventy variables hanging off them. A reader asked "where does the
 * bureau score enter?" has to scan; on a tree they follow a line.
 *
 * Every node is served from the model configuration through `/retail/ews/model`
 * — the weights, the classifiers, the triggers, the action dimensions and the
 * product applicability are read, never transcribed. Nothing here knows what
 * the model contains; it knows how to draw whatever the model says.
 */

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, ChevronDown, ChevronRight, Network } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EwsModel, type EwsModelLayer, type EwsSublayer } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { isRetail } from "@/lib/profile";
import { cn } from "@/lib/utils";

export default function EwsModelTreePage() {
  const load = React.useCallback(() => api.ewsScoreModel(), []);
  const { data, loading, error } = useAsync<EwsModel>(load, [load]);

  if (!isRetail()) {
    return (
      <div className="space-y-6">
        <PageHeader title="Early Warning Score model tree"
                    description="This page draws the retail Early Warning Score." />
        <EmptyState title="Not a retail installation"
                    description="The forward-risk signal is on the Model Lab." />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="ews-model-tree-page">
      <PageHeader
        eyebrow="Intelligence"
        title="Early Warning Score — model tree"
        description="Every layer, sub-layer, classifier, trigger and variable, drawn from the model configuration."
        status="live"
        phase="Governed model on synthetic demonstration data"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning/model" data-testid="ews-tree-to-model">
                <Network aria-hidden />
                View Model
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning" data-testid="ews-tree-back">
                <ArrowLeft aria-hidden />
                Back to the workspace
              </Link>
            </Button>
          </div>
        }
      />

      {loading && !data ? <Skeleton className="h-96 w-full" /> : null}
      {error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {String(error)}
        </Card>
      ) : null}

      {data ? (
        <>
          <Card className="border-warning/40 bg-warning-subtle/40 p-4
                           text-sm text-text-secondary">
            {data.disclaimer}
          </Card>

          <Card className="p-5" data-testid="ews-tree-root">
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-semibold text-text-primary">
                {data.name}
              </h2>
              <span className="font-mono text-xs text-text-muted">
                {data.model_version}
              </span>
            </div>
            <p className="mt-1 text-xs text-text-secondary">
              {Object.entries(data.counts).map(([key, value]) =>
                `${key.replace(/_/g, " ")}: ${value}`).join(" · ")}
            </p>

            <div className="mt-4 space-y-2">
              {data.layers.map((layer, index) => (
                <LayerNode key={layer.key} layer={layer}
                           last={index === data.layers.length - 1}
                           bureau={layer.key === "bureau"
                             ? data.bureau_recency : undefined} />
              ))}
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}

/** One trunk: a layer, its weights, and everything under it. */
function LayerNode({ layer, last, bureau }: {
  layer: EwsModelLayer;
  last: boolean;
  bureau?: Record<string, unknown>;
}) {
  const [open, setOpen] = React.useState(layer.key === "behavioural");
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="relative pl-5" data-testid={`ews-tree-layer-${layer.key}`}>
      {/* The connectors. A tree people can follow with a finger. */}
      <span aria-hidden
            className={cn("absolute left-1 top-0 w-px bg-border",
                          last && !open ? "h-4" : "h-full")} />
      <span aria-hidden className="absolute left-1 top-4 h-px w-3 bg-border" />

      <button type="button" onClick={() => setOpen((was) => !was)}
              className="flex w-full flex-wrap items-center gap-2 rounded-md
                         px-2 py-1.5 text-left transition-colors
                         hover:bg-surface-muted"
              data-testid={`ews-tree-toggle-${layer.key}`}>
        <Chevron className="size-3.5 shrink-0 text-text-muted" aria-hidden />
        <span className="text-sm font-semibold text-text-primary">
          {layer.name}
        </span>
        <span className="rounded-full border border-border px-2 py-0.5
                         text-[10px] text-text-muted">
          {layer.kind} layer
        </span>
        <span className="text-[11px] tabular-nums text-text-secondary">
          base weight {(layer.weight * 100).toFixed(0)}%
        </span>
        <span className="text-[11px] text-text-muted">
          {layer.sublayers.length} sub-layers ·{" "}
          {layer.sublayers.reduce((sum, one) => sum + one.classifiers.length, 0)}{" "}
          classifiers ·{" "}
          {layer.sublayers.reduce((sum, one) => sum + one.triggers.length, 0)}{" "}
          triggers
        </span>
        {typeof layer.customers === "number" ? (
          <span className="ml-auto text-[11px] tabular-nums text-text-muted">
            {layer.customers.toLocaleString()} customers firing
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="ml-2 space-y-1.5 border-l border-border pl-3 pb-2">
          <p className="pt-1 text-[11px] leading-relaxed text-text-secondary">
            {layer.purpose}
          </p>
          {bureau ? <BureauDecay bureau={bureau} /> : null}
          {layer.sublayers.map((sub) => (
            <SublayerNode key={sub.key} sub={sub} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** The bureau layer's weight, drawn against the age of its observation.
 *
 * Not a sparkline. A sparkline answers "where is this now and which way has
 * it moved", which is the right question for a customer's arrears and the
 * wrong one for a model parameter: the curve has no latest month and has not
 * moved, and asking that of it prints a movement nobody should read. This
 * draws the curve itself, with the weight it starts from and the floor it
 * settles on named on the axis, because those two numbers are the shape.
 */
function BureauDecay({ bureau }: { bureau: Record<string, unknown> }) {
  const curve = ((bureau.curve ?? bureau.table ?? []) as {
    age_months: number; effective_weight_pct: number }[])
    .filter((row) => Number.isFinite(row?.effective_weight_pct));
  const table = ((bureau.table ?? []) as {
    age_months: number; effective_weight_pct: number }[]);
  if (!curve.length) return null;

  const W = 260, H = 64, PAD = 4;
  const ages = curve.map((row) => row.age_months);
  const values = curve.map((row) => row.effective_weight_pct);
  const maxAge = Math.max(...ages) || 1;
  const top = Math.max(...values);
  const floor = Math.min(...values);
  const span = top - floor || 1;
  const x = (age: number) => (age / maxAge) * W;
  const y = (value: number) =>
    PAD + (H - PAD * 2) * (1 - (value - floor) / span);
  const path = curve
    .map((row, i) => `${i ? "L" : "M"}${x(row.age_months).toFixed(1)},`
                     + `${y(row.effective_weight_pct).toFixed(1)}`)
    .join(" ");

  return (
    <div className="rounded-md border border-border bg-surface-muted/30 p-3"
         data-testid="ews-tree-bureau-decay">
      <p className="text-[11px] font-medium text-text-primary">
        Effective weight decays with the age of the pull
      </p>
      <p className="mt-0.5 font-mono text-[10px] text-text-secondary">
        {String(bureau.formula ?? "")}
      </p>
      <div className="mt-2 flex items-end gap-2">
        <div className="flex h-16 flex-col justify-between
                        text-[9px] tabular-nums text-text-muted">
          <span>{top.toFixed(1)}%</span>
          <span>{floor.toFixed(1)}%</span>
        </div>
        <div className="min-w-0">
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
               className="w-full max-w-[260px]" role="img"
               data-testid="ews-tree-bureau-curve"
               aria-label={`Bureau weight falls from ${top.toFixed(1)} per cent`
                           + ` at a fresh pull to a floor of ${floor.toFixed(1)}`
                           + ` per cent by ${maxAge} months`}>
            <line x1={0} x2={W} y1={y(floor)} y2={y(floor)}
                  stroke="var(--ipm-border-strong)" strokeWidth={0.75}
                  strokeDasharray="2 2" />
            <path d={path} fill="none" stroke="var(--ipm-accent)"
                  strokeWidth={1.5} strokeLinecap="round"
                  strokeLinejoin="round" />
            {table.map((row) => (
              <circle key={row.age_months} r={1.75}
                      cx={x(row.age_months)} cy={y(row.effective_weight_pct)}
                      fill="var(--ipm-accent)" />
            ))}
          </svg>
          <div className="flex justify-between text-[9px] tabular-nums
                          text-text-muted">
            <span>fresh pull</span>
            <span>{maxAge} months old</span>
          </div>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-3 text-[10px] text-text-muted">
        {table.map((row) => (
          <span key={row.age_months}>
            {row.age_months}m:{" "}
            <span className="tabular-nums text-text-secondary">
              {row.effective_weight_pct.toFixed(1)}%
            </span>
          </span>
        ))}
      </div>
      <p className="mt-1 text-[10px] text-text-muted">
        {String(bureau.basis ?? "")}
      </p>
    </div>
  );
}

/** One branch: a sub-layer, its classifiers and its triggers. */
function SublayerNode({ sub }: { sub: EwsSublayer }) {
  const [open, setOpen] = React.useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="relative pl-4"
         data-testid={`ews-tree-sublayer-${sub.key}`}>
      <span aria-hidden className="absolute left-0 top-3 h-px w-3 bg-border" />
      <button type="button" onClick={() => setOpen((was) => !was)}
              className="flex w-full flex-wrap items-center gap-2 rounded-md
                         px-1.5 py-1 text-left transition-colors
                         hover:bg-surface-muted">
        <Chevron className="size-3 shrink-0 text-text-muted" aria-hidden />
        <span className="text-[12px] font-medium text-text-primary">
          {sub.name}
        </span>
        <span className="text-[10px] tabular-nums text-text-muted">
          {(sub.weight * 100).toFixed(0)}% within the layer
        </span>
        <span className="text-[10px] text-text-muted">
          {sub.classifiers.length} classifiers · {sub.triggers.length} triggers
        </span>
      </button>

      {open ? (
        <div className="ml-1.5 space-y-2 border-l border-border pl-3 py-1">
          <p className="text-[11px] text-text-secondary">{sub.purpose}</p>

          {sub.classifiers.length ? (
            <div data-testid={`ews-tree-classifiers-${sub.key}`}>
              <p className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                Classifier variables — stable context, they never fire
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {sub.classifiers.map((one) => (
                  <li key={one.key} className="text-[11px] text-text-secondary">
                    <span className="font-medium text-text-primary">
                      {one.name}
                    </span>{" "}
                    <span className="font-mono text-[10px] text-text-muted">
                      {one.column}
                    </span>{" "}
                    — {one.meaning}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {sub.triggers.length ? (
            <div data-testid={`ews-tree-triggers-${sub.key}`}>
              <p className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                Trigger variables — live deterioration events
              </p>
              <ul className="mt-0.5 space-y-1">
                {sub.triggers.map((one) => (
                  <li key={one.key}
                      className="rounded border border-border/60 px-2 py-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="rounded-full border border-border px-1.5
                                       text-[9px] uppercase text-text-muted">
                        {one.severity}
                      </span>
                      <span className="text-[11px] font-medium text-text-primary">
                        {one.name}
                      </span>
                      <span className="font-mono text-[10px] text-text-muted">
                        {one.reason_code}
                      </span>
                      {one.needs_new_observation ? (
                        <span className="rounded-full border border-border px-1.5
                                         text-[9px] text-text-muted">
                          only on a new observation
                        </span>
                      ) : null}
                      {typeof one.customers === "number" ? (
                        <span className="ml-auto text-[10px] tabular-nums text-text-muted">
                          {one.customers.toLocaleString()} customers
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-0.5 text-[10px] text-text-secondary">
                      {one.meaning}
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] text-text-muted">
                      {one.expression}
                    </p>
                    {one.products?.length ? (
                      <p className="mt-0.5 text-[10px] text-text-muted">
                        Applies to: {one.products.join(", ")}
                      </p>
                    ) : null}
                    {one.absent_because ? (
                      <p className="mt-0.5 text-[10px] italic text-text-muted">
                        Declared and never evaluated: {one.absent_because}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
