"use client";

/**
 * The Early Warning methodology, in full.
 *
 * §9 of the acceptance brief asks for a methodology page that is not a place
 * to fit a model. Everything on this screen describes the model that is
 * ALREADY RUNNING: the twenty governed rules of
 * `retail-ews-rulebook-1.0.0`, the six layers they roll up into, the
 * arithmetic of the roll-up, and every input the rules read.
 *
 * The variable dictionary is the part that makes it a methodology rather than
 * a rule list. For each of the twenty-seven inputs it states the business
 * meaning, whether it is internal to the bank / external / derived, the raw
 * input behind it, the transformation applied, which direction is worse, how
 * often it refreshes, which products it applies to, the weight it carries
 * through its layer, and the reason code it generates. Those come from the
 * backend, which builds them by walking the rules — so a rule that starts
 * reading a new column cannot leave this page behind.
 *
 * Nothing here is an ANB model or a SAMA requirement, and the page says so
 * above the fold.
 */

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, ChevronDown, ChevronRight, ListChecks } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EwsMethodology, type EwsMethodologyLayer,
         type EwsRuleView, type EwsVariable } from "@/lib/api";
import { EWS_METHODOLOGY_DESCRIPTION, EWS_PHASE } from "@/lib/ews";
import { useAsync } from "@/lib/hooks";
import { isRetail } from "@/lib/profile";
import { cn } from "@/lib/utils";
import { SeverityBadge } from "../retail-portfolio";

function sourceTone(kind: string): string {
  switch (kind) {
    case "Internal":
      return "bg-accent-subtle text-accent border-accent/30";
    case "External":
      return "bg-warning-subtle text-warning border-warning/30";
    default:
      return "bg-surface-muted text-text-secondary border-border";
  }
}

/** Internal / External / Derived, as a chip. §11 asks for it on every input. */
function SourceChip({ kind }: { kind: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px]"
        + " font-semibold uppercase tracking-[0.06em]",
        sourceTone(kind),
      )}
      data-testid={`ews-source-${kind.toLowerCase()}`}
    >
      {kind}
    </span>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-muted">
        {label}
      </p>
      <p className="mt-0.5 text-sm text-text-primary">{children}</p>
    </div>
  );
}

/** One input, with the ten facts §9 requires. */
function VariableCard({ v }: { v: EwsVariable }) {
  return (
    <div
      className="rounded-md border border-border bg-surface-muted/40 p-3"
      data-testid={`ews-variable-${v.name}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold text-text-primary">{v.label}</p>
        <code className="rounded bg-surface px-1 py-0.5 text-[11px] text-text-muted">
          {v.name}
        </code>
        <SourceChip kind={v.source_class} />
        {v.unit ? (
          <span className="text-[11px] text-text-muted">in {v.unit}</span>
        ) : null}
      </div>
      <p className="mt-2 text-sm text-text-secondary">{v.meaning}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Fact label="Raw input">{v.raw_input}</Fact>
        <Fact label="Transformation">{v.transformation}</Fact>
        <Fact label="Direction of risk">{v.direction}</Fact>
        <Fact label="Refresh frequency">{v.refresh}</Fact>
        <Fact label="Applicable products">
          {v.products.length ? v.products.map((p) => p.replace(/_/g, " ").toLowerCase())
            .join(", ") : "—"}
        </Fact>
        <Fact label="Weight carried">
          {v.layer_names.length
            ? `${v.layer_names.join(", ")} — ${(v.layer_weight * 100).toFixed(0)}% of the overall score`
            : "None. This input carries no risk weight."}
        </Fact>
        <Fact label="Reason codes generated">
          <span className="font-mono text-xs">{v.reason_codes.join(", ") || "—"}</span>
        </Fact>
        <Fact label="Rules that read it">
          {v.rule_names.join("; ")}
        </Fact>
      </div>
    </div>
  );
}

function RuleLine({ rule }: { rule: EwsRuleView }) {
  return (
    <Link
      href={`/early-warning/signals?rule=${encodeURIComponent(rule.rule_id)}`}
      className="block rounded-md border border-border p-3 transition-colors hover:bg-surface-muted/60"
      data-testid={`ews-method-rule-${rule.rule_id}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <code className="text-[11px] text-text-muted">{rule.rule_id}</code>
        <span className="text-sm font-medium text-text-primary">{rule.name}</span>
        <SeverityBadge band={rule.severity} />
        <span className="text-[11px] text-text-muted">{rule.scope.toLowerCase()} scope</span>
      </div>
      <code className="mt-1.5 block text-xs text-text-secondary">{rule.expression}</code>
      <p className="mt-1 text-xs text-text-muted">
        Threshold {rule.threshold} {rule.unit}. {rule.threshold_source}
      </p>
    </Link>
  );
}

/** A layer, closed by default; opening it shows its rules and its inputs. */
function LayerSection({ layer }: { layer: EwsMethodologyLayer }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Card className="overflow-hidden" data-testid={`ews-method-layer-${layer.key}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 p-4 text-left transition-colors hover:bg-surface-muted/50"
      >
        {open
          ? <ChevronDown className="mt-1 size-4 shrink-0 text-text-muted" aria-hidden />
          : <ChevronRight className="mt-1 size-4 shrink-0 text-text-muted" aria-hidden />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-text-primary">{layer.name}</span>
            <SourceChip kind={layer.source_class} />
            <Badge variant={layer.has_rules ? "default" : "warning"}>
              {layer.has_rules
                ? `${layer.rule_count} rule${layer.rule_count === 1 ? "" : "s"}`
                : "no rules in this rulebook"}
            </Badge>
            <span className="text-xs tabular-nums text-text-muted">
              weight {(layer.weight * 100).toFixed(0)}%
            </span>
            <span className="text-xs text-text-muted">
              {layer.variable_detail.length} input
              {layer.variable_detail.length === 1 ? "" : "s"}
            </span>
          </div>
          <p className="mt-1 text-sm text-text-secondary">{layer.purpose}</p>
          {layer.absent_because ? (
            <p className="mt-1 text-xs text-warning">{layer.absent_because}</p>
          ) : null}
        </div>
      </button>
      {open ? (
        <div className="space-y-4 border-t border-border p-4">
          <p className="text-xs text-text-muted">
            <span className="font-medium text-text-secondary">Why this weight: </span>
            {layer.weight_because || "This layer carries no weight."}
          </p>
          <p className="text-xs text-text-muted">
            <span className="font-medium text-text-secondary">Refresh: </span>
            {layer.refresh}
          </p>
          {layer.rules.length ? (
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
                Rules in this layer
              </p>
              <div className="space-y-2">
                {layer.rules.map((r) => <RuleLine key={r.rule_id} rule={r} />)}
              </div>
            </div>
          ) : null}
          {layer.variable_detail.length ? (
            <div data-testid={`ews-method-variables-${layer.key}`}>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
                Every input these rules read
              </p>
              <div className="space-y-2">
                {layer.variable_detail.map((v) => <VariableCard key={v.name} v={v} />)}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

export default function MethodologyPage() {
  const detail = useAsync(() => api.ewsMethodology(), []);
  const m: EwsMethodology | null = detail.data ?? null;

  if (!isRetail()) {
    return (
      <div className="space-y-7">
        <PageHeader title="Early Warning methodology"
                    description="This page describes the retail early-warning rulebook." />
        <Card className="p-6 text-sm text-text-secondary">
          This installation is not a retail book. The forward-risk signal and
          its validation record are on the Model Lab.
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-7" data-testid="ews-methodology">
      <PageHeader
        title="Early Warning methodology"
        description={EWS_METHODOLOGY_DESCRIPTION}
        status="partial"
        phase={EWS_PHASE}
        actions={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning" data-testid="ews-back-to-portfolio">
                <ArrowLeft aria-hidden />
                Portfolio
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning/signals">
                <ListChecks aria-hidden />
                Signals
              </Link>
            </Button>
          </div>
        }
      />

      {detail.loading ? <Skeleton className="h-96 w-full" /> : null}
      {detail.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {detail.error}
        </Card>
      ) : null}

      {m ? (
        <>
          <Card className="border-warning/40 bg-warning-subtle/40 p-4 text-sm text-text-secondary"
                data-testid="ews-method-disclosure">
            {m.disclaimer}
          </Card>

          {/* --- the identity of the model ----------------------------- */}
          <Card className="p-5" data-testid="ews-method-identity">
            <h2 className="text-base font-semibold text-text-primary">{m.name}</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Fact label="Rulebook version">
                <span className="font-mono text-xs">{m.rulebook_version}</span>
              </Fact>
              <Fact label="Layer definition version">
                <span className="font-mono text-xs">{m.layers_version}</span>
              </Fact>
              <Fact label="Panel version">
                <span className="font-mono text-xs">{m.panel_version}</span>
              </Fact>
              <Fact label="Latest scoring date">{m.latest_scoring_date}</Fact>
              <Fact label="Months scored">{m.months_scored}</Fact>
              <Fact label="Inputs read">{m.variable_count}</Fact>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Fact label="Purpose">{m.purpose}</Fact>
              <Fact label="Target">{m.target}</Fact>
              <Fact label="Prediction horizon">{m.horizon}</Fact>
              <Fact label="Eligible population">{m.eligible_population}</Fact>
            </div>
          </Card>

          {/* --- how the score is built -------------------------------- */}
          <Card className="p-5" data-testid="ews-method-scoring">
            <h2 className="text-base font-semibold text-text-primary">
              How the score is built
            </h2>
            <div className="mt-3 space-y-3">
              <Fact label="Layer score">{m.scoring.layer_score}</Fact>
              <Fact label="Overall customer score">{m.scoring.overall_score}</Fact>
              <Fact label="Population score">{m.scoring.population_score}</Fact>
            </div>
            <div className="mt-4 grid gap-6 sm:grid-cols-2">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-muted">
                  Customer severity bands
                </p>
                <ul className="mt-1.5 space-y-1">
                  {m.scoring.customer_bands.map((b) => (
                    <li key={b.band} className="flex items-center gap-2 text-sm">
                      <SeverityBadge band={b.band} />
                      <span className="tabular-nums text-text-secondary">
                        score {b.from} and above
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-text-muted">
                  Population severity bands
                </p>
                <ul className="mt-1.5 space-y-1">
                  {m.scoring.population_bands.map((b) => (
                    <li key={b.band} className="flex items-center gap-2 text-sm">
                      <SeverityBadge band={b.band} />
                      <span className="tabular-nums text-text-secondary">
                        score {b.from} and above
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-text-muted">
                  A product and a customer cannot share a band table: a product
                  at 60 would mean its average warned customer carries a
                  critical signal, which no real book reaches.
                </p>
              </div>
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Fact label="Already bad, at this month-end">
                {m.definitions.current_bad}
              </Fact>
              <Fact label="Forward risk, still performing">
                {m.definitions.forward_risk}
              </Fact>
            </div>
          </Card>

          {/* --- the six layers ---------------------------------------- */}
          <section className="space-y-3" data-testid="ews-method-layers">
            <h2 className="text-base font-semibold text-text-primary">
              The six layers
            </h2>
            <p className="text-sm text-text-secondary">
              Open a layer to see the rules in it and every input those rules
              read. Five layers carry weight; the sixth is shown rather than
              omitted so its absence is visible.
            </p>
            {m.layers.map((layer) => (
              <LayerSection key={layer.key} layer={layer} />
            ))}
          </section>

          {/* --- what is not a risk layer ------------------------------ */}
          {m.not_a_risk_layer.map((entry) => (
            <Card key={entry.family} className="p-4"
                  data-testid={`ews-method-not-risk-${entry.family}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-text-primary">
                  {entry.family.replace(/_/g, " ")}
                </span>
                <Badge variant="warning">not a risk layer</Badge>
                <span className="text-xs text-text-muted">
                  {entry.rules.length} rule{entry.rules.length === 1 ? "" : "s"}
                </span>
              </div>
              <p className="mt-1 text-sm text-text-secondary">{entry.because}</p>
              <div className="mt-2 space-y-2">
                {entry.rules.map((r) => <RuleLine key={r.rule_id} rule={r} />)}
              </div>
            </Card>
          ))}

          {/* --- internal / external / derived -------------------------- */}
          <Card className="p-5" data-testid="ews-method-sources">
            <h2 className="text-base font-semibold text-text-primary">
              Internal, external and derived
            </h2>
            <div className="mt-3 space-y-3">
              {Object.entries(m.source_classes).map(([kind, meaning]) => (
                <div key={kind} className="flex gap-3">
                  <div className="w-20 shrink-0 pt-0.5"><SourceChip kind={kind} /></div>
                  <p className="text-sm text-text-secondary">{meaning}</p>
                </div>
              ))}
            </div>
            <p className="mt-4 rounded-md border border-warning/40 bg-warning-subtle/40 p-3 text-sm text-text-secondary"
               data-testid="ews-bureau-note">
              {m.bureau_note}
            </p>
          </Card>

          {/* --- every input, in one table ------------------------------ */}
          <section className="space-y-3" data-testid="ews-method-dictionary">
            <h2 className="text-base font-semibold text-text-primary">
              Every input the rulebook reads
            </h2>
            <p className="text-sm text-text-secondary">
              {m.variable_count} inputs across {m.layers.filter((l) => l.has_rules).length} layers
              that carry rules. Built by walking the rules, so an input a rule
              starts reading appears here without anyone remembering to add it.
            </p>
            <div className="space-y-2">
              {m.variables.map((v) => <VariableCard key={v.name} v={v} />)}
            </div>
          </section>

          {/* --- per product ------------------------------------------- */}
          <section className="space-y-3" data-testid="ews-method-by-product">
            <h2 className="text-base font-semibold text-text-primary">
              What applies to each product
            </h2>
            <div className="grid gap-3 lg:grid-cols-2">
              {m.by_product.map((p) => (
                <Card key={p.product_code} className="p-4"
                      data-testid={`ews-method-product-${p.product_code}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-text-primary">
                      {p.product_label}
                    </span>
                    <span className="text-xs text-text-muted">
                      {p.rule_count} of {m.layers.reduce((n, l) => n + l.rule_count, 0)} rules
                    </span>
                  </div>
                  {p.specific_to_this_product.length ? (
                    <p className="mt-2 text-xs text-text-secondary">
                      <span className="font-medium">Only this product: </span>
                      <span className="font-mono">
                        {p.specific_to_this_product.join(", ")}
                      </span>
                    </p>
                  ) : (
                    <p className="mt-2 text-xs text-text-muted">
                      No rule in the rulebook is specific to this product alone.
                    </p>
                  )}
                  <div className="mt-2 space-y-1">
                    {Object.entries(p.by_layer).map(([key, ids]) => (
                      <p key={key} className="text-xs text-text-muted">
                        <span className="font-medium text-text-secondary">
                          {m.layers.find((l) => l.key === key)?.name ?? key}:{" "}
                        </span>
                        <span className="font-mono">{ids.join(", ")}</span>
                      </p>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          </section>

          {/* --- language ---------------------------------------------- */}
          <Card className="p-5" data-testid="ews-method-glossary">
            <h2 className="text-base font-semibold text-text-primary">
              What the words mean
            </h2>
            <dl className="mt-3 space-y-3">
              {m.glossary.map((g) => (
                <div key={g.term}>
                  <dt className="text-sm font-semibold text-text-primary">{g.term}</dt>
                  <dd className="text-sm text-text-secondary">{g.meaning}</dd>
                  <dd className="text-[11px] text-text-muted">Authority: {g.authority}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-4 rounded-md border border-border bg-surface-muted/50 p-3 text-sm text-text-secondary"
               data-testid="ews-unsourced-shorthand">
              {m.unsourced_shorthand}
            </p>
          </Card>
        </>
      ) : null}
    </div>
  );
}
