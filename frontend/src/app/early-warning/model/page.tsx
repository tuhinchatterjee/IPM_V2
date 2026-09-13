"use client";

/**
 * View Model: the whole Early Warning Score, made inspectable.
 *
 * §21 asks for the model to be transparent rather than described — its
 * identity and version, the flow from raw data to reason code, the four-layer
 * tree with every classifier, trigger and action dimension under it, the
 * product weight matrix, the thresholds and hard triggers, the bureau
 * treatment, the glossary and the lineage.
 *
 * Every word and number here is served from `backend/retail/ews_model.py`
 * through `/retail/ews/model`, which also attaches LIVE hit counts, so a
 * trigger the model declares and the book never fires says so on the same
 * screen that declares it. There is no methodology text in this file.
 */

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, ChevronDown, ChevronRight, Database } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api, type EwsDomainContract, type EwsModel, type EwsModelLayer,
  type EwsSublayer,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { isRetail } from "@/lib/profile";
import { cn } from "@/lib/utils";

import { Severity, count } from "../parts";

export default function EwsModelPage() {
  const load = React.useCallback(() => api.ewsScoreModel(), []);
  const { data, loading, error } = useAsync<EwsModel>(load, [load]);
  const domain = useAsync<EwsDomainContract>(
    React.useCallback(() => api.ewsScoreDomain(), []), []);

  if (!isRetail()) {
    return (
      <div className="space-y-6">
        <PageHeader title="Early Warning Score model"
                    description="This page describes the retail Early Warning Score." />
        <EmptyState title="Not a retail installation"
                    description="The forward-risk signal and its validation record are on the Model Lab." />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="ews-model-page">
      <PageHeader
        eyebrow="Intelligence"
        title="Early Warning Score — model and configuration"
        description="The model that is running: four layers, their sublayers, every classifier and trigger, and the weights and thresholds behind the score."
        // Served from the model configuration itself, not transcribed here.
        status="live"
        phase="Governed model on synthetic demonstration data"
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href="/early-warning" data-testid="ews-model-back">
              <ArrowLeft aria-hidden />
              Back to the workspace
            </Link>
          </Button>
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
          <Card className="border-warning/40 bg-warning-subtle/40 p-4 text-sm
                           text-text-secondary"
                data-testid="ews-model-disclaimer">
            {data.disclaimer}
          </Card>

          {/* ------------------------------------------------- identity */}
          <Card className="p-5" data-testid="ews-model-identity">
            <h2 className="text-base font-semibold text-text-primary">
              {data.name}
            </h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="Model version" mono value={data.model_version} />
              <Fact label="Panel version" mono value={data.panel_version} />
              <Fact label="Score range"
                    value={`${data.scale.minimum}–${data.scale.maximum}`} />
              <Fact label="Score direction" value={data.scale.direction} />
              <Fact label="Warning cutoff"
                    value={`${data.scale.warning_cutoff} and above`} />
              <Fact label="Scoring frequency" value={data.scoring_frequency} />
              <Fact label="Current model month" value={data.month} />
              <Fact label="Months scored" value={String(data.months_scored)} />
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Fact label="Purpose" value={data.purpose} />
              <Fact label="Target / outcome" value={data.target} />
              <Fact label="Warning horizon" value={data.horizon} />
              <Fact label="Eligible population"
                    value={data.eligible_population} />
            </div>
            <div className="mt-4 flex flex-wrap gap-4 text-xs text-text-muted">
              {Object.entries(data.counts).map(([key, value]) => (
                <span key={key}>
                  {key.replace(/_/g, " ")}:{" "}
                  <span className="font-semibold text-text-secondary">
                    {value}
                  </span>
                </span>
              ))}
            </div>
          </Card>

          {/* ----------------------------------------------- the flow */}
          <Card className="p-5" data-testid="ews-model-flow">
            <h2 className="text-base font-semibold text-text-primary">
              How a customer becomes a score
            </h2>
            <ol className="mt-3 space-y-1.5">
              {data.flow.map((step, index) => (
                <li key={step.step} className="flex gap-3">
                  <span className="mt-0.5 flex size-5 shrink-0 items-center
                                   justify-center rounded-full bg-accent-subtle
                                   text-[10px] font-semibold text-accent">
                    {index + 1}
                  </span>
                  <span className="min-w-0">
                    <span className="text-sm font-medium text-text-primary">
                      {step.step}
                    </span>
                    <span className="block text-xs text-text-secondary">
                      {step.detail}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </Card>

          {/* ------------------------------------------ the four layers */}
          <section className="space-y-3" data-testid="ews-model-layers">
            <h2 className="text-base font-semibold text-text-primary">
              Retail Early Warning Score — the four layers
            </h2>
            <p className="text-sm text-text-secondary">
              Open a layer for its sublayers, and each sublayer for its
              classifier variables, its triggers and the action dimensions
              computed on them. The customer count beside each is what actually
              fired at {data.month}.
            </p>
            {data.layers.map((layer) => (
              <LayerNode key={layer.key} layer={layer} />
            ))}
          </section>

          {/* -------------------------------------- action dimensions */}
          <Card className="p-5" data-testid="ews-model-action-dimensions">
            <h2 className="text-base font-semibold text-text-primary">
              The six action dimensions
            </h2>
            <p className="mt-1 text-sm text-text-secondary">
              {data.action_multiplier.meaning} The multiplier is bounded
              between {data.action_multiplier.floor} and{" "}
              {data.action_multiplier.ceiling}, and no single trigger may
              contribute more than {data.trigger_contribution_cap} points to
              its sublayer.
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.action_dimensions.map((one) => (
                <div key={one.key}
                     className="rounded-md border border-border p-3"
                     data-testid={`ews-action-${one.key}`}>
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-semibold text-text-primary">
                      {one.name}
                    </p>
                    <span className="text-[11px] tabular-nums text-text-muted">
                      weight {(one.weight * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-text-secondary">
                    {one.meaning}
                  </p>
                  <p className="mt-1 text-[11px] text-text-muted">
                    <span className="font-medium">How: </span>{one.computed}
                  </p>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    <span className="font-medium">Values: </span>{one.values}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          {/* ------------------------------------ product configuration */}
          <Card className="p-5" data-testid="ews-model-product-weights">
            <h2 className="text-base font-semibold text-text-primary">
              Product-specific configuration
            </h2>
            <p className="mt-1 text-sm text-text-secondary">
              The same four layers everywhere; different weights on them. The
              matrix lives in the model configuration, not in a screen.
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border text-left">
                  <tr className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
                    <th className="px-3 py-2 font-semibold">Product</th>
                    {data.layers.map((layer) => (
                      <th key={layer.key} className="px-3 py-2 font-semibold">
                        {layer.name}
                      </th>
                    ))}
                    <th className="px-3 py-2 font-semibold">Emphasis</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.product_weights).map(([code, weights]) => (
                    <tr key={code} className="border-b border-border last:border-0"
                        data-testid={`ews-model-weights-${code}`}>
                      <td className="px-3 py-2 font-medium">
                        {code.replace(/_/g, " ").toLowerCase()
                          .replace(/\b\w/g, (c) => c.toUpperCase())}
                      </td>
                      {data.layers.map((layer) => (
                        <td key={layer.key} className="px-3 py-2 tabular-nums">
                          {((weights[layer.key] ?? 0) * 100).toFixed(0)}%
                        </td>
                      ))}
                      <td className="px-3 py-2 text-xs text-text-muted">
                        {data.product_emphasis[code]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* --------------------------------------------- thresholds */}
          <Card className="p-5" data-testid="ews-model-thresholds">
            <h2 className="text-base font-semibold text-text-primary">
              Thresholds, cutoff and hard triggers
            </h2>
            <div className="mt-3 grid gap-6 lg:grid-cols-3">
              <div>
                <p className="text-[10px] font-semibold uppercase
                              tracking-[0.08em] text-text-muted">
                  Customer severity bands
                </p>
                <ul className="mt-1.5 space-y-1">
                  {data.severity_bands.map((band) => (
                    <li key={band.band}
                        className="flex items-center gap-2 text-sm">
                      <Severity band={band.band} />
                      <span className="tabular-nums text-text-secondary">
                        {band.from} and above
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-text-muted">
                  A customer is WARNED at {data.scale.warning_cutoff}.
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase
                              tracking-[0.08em] text-text-muted">
                  Population severity bands
                </p>
                <ul className="mt-1.5 space-y-1">
                  {data.population_bands.map((band) => (
                    <li key={band.band}
                        className="flex items-center gap-2 text-sm">
                      <Severity band={band.band} />
                      <span className="tabular-nums text-text-secondary">
                        {band.from} and above
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-text-muted">
                  A product and a customer cannot share a band table: a
                  population score carries how many are warned as well as how
                  badly.
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase
                              tracking-[0.08em] text-text-muted">
                  Severity points
                </p>
                <ul className="mt-1.5 space-y-1 text-sm">
                  {Object.entries(data.severity_points).map(([band, points]) => (
                    <li key={band} className="flex items-center gap-2">
                      <Severity band={band} />
                      <span className="tabular-nums text-text-secondary">
                        {points} points
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-text-muted">
                  {data.threshold_source}.
                </p>
              </div>
            </div>

            <div className="mt-5" data-testid="ews-model-hard-triggers">
              <p className="text-[10px] font-semibold uppercase
                            tracking-[0.08em] text-text-muted">
                Hard triggers — the only overrides of the weighted roll-up
              </p>
              <div className="mt-2 space-y-2">
                {data.hard_triggers.map((one) => (
                  <div key={one.key}
                       className="rounded-md border border-border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-text-primary">
                        {one.name}
                      </span>
                      <Severity band={one.band} />
                      <code className="rounded bg-surface-muted px-1.5 py-0.5
                                       text-[11px] text-text-secondary">
                        {one.condition}
                      </code>
                      <span className="text-[11px] tabular-nums text-text-muted">
                        floors the score at {one.floor_score}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-text-secondary">
                      {one.because}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* --------------------------------------------- bureau rule */}
          <Card className="p-5" data-testid="ews-model-bureau">
            <h2 className="text-base font-semibold text-text-primary">
              How bureau is treated
            </h2>
            <p className="mt-2 text-sm text-text-secondary">
              {data.bureau_rule.statement}
            </p>
            <div className="mt-3 grid gap-4 sm:grid-cols-3">
              <Fact label="Re-pull cadence"
                    value={`${data.bureau_rule.cadence_months.join(", ")} `
                           + "months, chosen per customer from a stable hash "
                           + "of their id"} />
              <Fact label="Event-driven pull"
                    value={`On entry to ${data.bureau_rule.delinquency_pull_at_dpd} `
                           + "days past due"} />
              <Fact label="Between observations"
                    value={"The last observed values are carried forward "
                           + "unchanged and the recency counter advances."} />
            </div>
            <p className="mt-3 rounded-md border border-warning/40
                          bg-warning-subtle/40 p-3 text-sm text-text-secondary"
               data-testid="ews-model-bureau-proxy">
              <span className="font-semibold">
                {data.bureau_rule.proxy_label}
              </span>{" "}
              {data.bureau_rule.no_agreement}
            </p>
          </Card>

          {/* ---------------------------------------- sub-product taxonomy */}
          <Card className="p-5" data-testid="ews-model-sub-products">
            <h2 className="text-base font-semibold text-text-primary">
              Sub-portfolio taxonomy
            </h2>
            <p className="mt-1 text-sm text-text-secondary">
              Stored in the model configuration and written into the domain, not
              assembled in a screen. Each is DERIVED deterministically from
              published columns, so the same facility lands in the same
              sub-portfolio on every rebuild.
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border text-left">
                  <tr className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
                    {["Code", "Sub-portfolio", "Product", "What it is",
                      "How it is derived"].map((column) => (
                      <th key={column} className="px-3 py-2 font-semibold">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.sub_products.map((one) => (
                    <tr key={one.code}
                        className="border-b border-border last:border-0">
                      <td className="px-3 py-2 font-mono text-[11px]">
                        {one.code}
                      </td>
                      <td className="px-3 py-2 font-medium">{one.label}</td>
                      <td className="px-3 py-2 text-text-secondary">
                        {one.product.replace(/_/g, " ").toLowerCase()}
                      </td>
                      <td className="px-3 py-2 text-xs text-text-secondary">
                        {one.meaning}
                      </td>
                      <td className="px-3 py-2 text-xs text-text-muted">
                        {one.derivation}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* --------------------------------------------- the glossary */}
          <Card className="p-5" data-testid="ews-model-glossary">
            <h2 className="text-base font-semibold text-text-primary">
              What the words mean
            </h2>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              {data.glossary.map((term) => (
                <div key={term.term}>
                  <dt className="text-sm font-semibold text-text-primary">
                    {term.term}
                  </dt>
                  <dd className="text-sm text-text-secondary">
                    {term.meaning}
                  </dd>
                  <dd className="text-[11px] text-text-muted">
                    Authority: {term.authority}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-4 rounded-md border border-border
                          bg-surface-muted/50 p-3 text-sm text-text-secondary"
               data-testid="ews-model-shorthand">
              {data.unsourced_shorthand}
            </p>
          </Card>

          {/* ----------------------------------------------- lineage */}
          <Card className="p-5" data-testid="ews-model-lineage">
            <div className="flex items-center gap-2">
              <Database className="size-4 text-text-muted" aria-hidden />
              <h2 className="text-base font-semibold text-text-primary">
                Lineage
              </h2>
            </div>
            <p className="mt-1 text-sm text-text-secondary">
              Every figure the workspace shows traces back through this chain.
            </p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(data.lineage).map(([key, value]) => (
                <Fact key={key} label={key.replace(/_/g, " ")}
                      value={Array.isArray(value)
                        ? `${value.length} months, ${value[0]} to ${value[value.length - 1]}`
                        : String(value)} />
              ))}
            </div>
            {domain.data?.available ? (
              <div className="mt-4 rounded-md border border-border p-3"
                   data-testid="ews-model-domain">
                <p className="text-sm font-medium text-text-primary">
                  {domain.data.domain_name} — {domain.data.domain}
                </p>
                <p className="mt-0.5 text-xs text-text-secondary">
                  {domain.data.month_count} monthly snapshots ·{" "}
                  {domain.data.field_count} fields ·{" "}
                  {count(domain.data.rows_latest_month)} rows at{" "}
                  {domain.data.months[domain.data.months.length - 1]} ·{" "}
                  {domain.data.grain}
                </p>
                {domain.data.problems.length ? (
                  <ul className="mt-2 space-y-0.5">
                    {domain.data.problems.map((problem) => (
                      <li key={problem} className="text-xs text-negative">
                        {problem}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-1 text-xs text-positive">
                    The domain holds exactly the{" "}
                    {domain.data.months_expected} months it claims to.
                  </p>
                )}
              </div>
            ) : null}
          </Card>
        </>
      ) : null}
    </div>
  );
}

function Fact({ label, value, mono }: {
  label: string; value: string; mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {label}
      </p>
      <p className={cn("mt-0.5 text-sm text-text-primary",
                       mono && "font-mono text-xs")}>
        {value}
      </p>
    </div>
  );
}

function LayerNode({ layer }: { layer: EwsModelLayer }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Card className="overflow-hidden" data-testid={`ews-model-layer-${layer.key}`}>
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
            <Badge variant={layer.kind === "dynamic" ? "default" : "warning"}>
              {layer.kind === "dynamic" ? "dynamic layer"
                                        : "classifier layer"}
            </Badge>
            <span className="text-xs tabular-nums text-text-muted">
              default weight {(layer.weight * 100).toFixed(0)}%
            </span>
            <span className="text-xs text-text-muted">
              {layer.sublayer_count} sublayers · {layer.classifier_count}{" "}
              classifiers · {layer.trigger_count} triggers
            </span>
            <span className="text-xs tabular-nums text-text-secondary">
              {count(layer.customers ?? 0)} customers firing
            </span>
          </div>
          <p className="mt-1 text-sm text-text-secondary">{layer.purpose}</p>
          <p className="mt-1 text-[11px] text-text-muted">
            <span className="font-medium">Why this weight: </span>
            {layer.weight_because}{" "}
            <span className="font-medium">Refresh: </span>{layer.refresh}
          </p>
        </div>
      </button>

      {open ? (
        <div className="space-y-3 border-t border-border p-4">
          {layer.sublayers.map((sub) => (
            <SublayerNode key={sub.key} sublayer={sub} />
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function SublayerNode({ sublayer }: { sublayer: EwsSublayer }) {
  return (
    <div className="rounded-md border border-border p-3"
         data-testid={`ews-model-sublayer-${sublayer.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-text-primary">
          {sublayer.name}
        </span>
        <span className="text-[11px] tabular-nums text-text-muted">
          weight {(sublayer.weight * 100).toFixed(0)}% within the layer
        </span>
        <span className="text-[11px] tabular-nums text-text-secondary">
          {count(sublayer.customers ?? 0)} customers firing
        </span>
      </div>
      <p className="mt-0.5 text-xs text-text-secondary">{sublayer.purpose}</p>

      {sublayer.classifiers.length ? (
        <div className="mt-2.5" data-testid={`ews-model-classifiers-${sublayer.key}`}>
          <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Classifier variables — stable context, they never fire
          </p>
          <div className="mt-1 space-y-1">
            {sublayer.classifiers.map((one) => (
              <div key={one.key} className="text-[11px]">
                <span className="font-medium text-text-primary">{one.name}</span>
                <code className="ml-1.5 rounded bg-surface-muted px-1 text-[10px] text-text-muted">
                  {one.column}
                </code>
                <span className="ml-1.5 rounded border border-border px-1 text-[9px] uppercase text-text-muted">
                  {one.source_class}
                </span>
                <span className="ml-1.5 text-text-secondary">{one.meaning}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {sublayer.triggers.length ? (
        <div className="mt-2.5" data-testid={`ews-model-triggers-${sublayer.key}`}>
          <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Trigger variables — live deterioration events
          </p>
          <div className="mt-1 space-y-1.5">
            {sublayer.triggers.map((one) => (
              <div key={one.key}
                   className={cn("rounded border p-2 text-[11px]",
                                 one.available ? "border-border"
                                   : "border-warning/40 bg-warning-subtle/30")}
                   data-testid={`ews-model-trigger-${one.key}`}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Severity band={one.severity} />
                  <span className="font-medium text-text-primary">
                    {one.name}
                  </span>
                  <code className="font-mono text-[10px] text-text-muted">
                    {one.reason_code}
                  </code>
                  <span className="rounded border border-border px-1 text-[9px] uppercase text-text-muted">
                    {one.source_class}
                  </span>
                  {one.rule_id ? (
                    <span className="text-[10px] text-text-muted">
                      continues {one.rule_id}
                    </span>
                  ) : null}
                  {one.needs_new_observation ? (
                    <span className="rounded border border-border px-1 text-[9px] text-text-muted">
                      only on a new observation
                    </span>
                  ) : null}
                  <span className="ml-auto tabular-nums text-text-secondary">
                    {count(one.customers ?? 0)} customers
                  </span>
                </div>
                <p className="mt-1 text-text-secondary">{one.meaning}</p>
                <p className="mt-1 text-text-muted">
                  <code className="rounded bg-surface-muted px-1">
                    {one.expression}
                  </code>{" "}
                  · threshold {one.threshold} {one.unit} ·{" "}
                  {one.products.map((p) => p.replace(/_/g, " ").toLowerCase())
                    .join(", ")}
                </p>
                {one.absent_because ? (
                  <p className="mt-1 text-warning">{one.absent_because}</p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
