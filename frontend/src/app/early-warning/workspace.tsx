"use client";

/**
 * The Early Warning Score workspace: one screen, five levels.
 *
 *     TOTAL RETAIL -> PRODUCT -> SUB-PRODUCT -> CUSTOMER -> FACILITY / SIGNAL
 *
 * The level lives in the address, so the Cockpit can link straight to a
 * filtered sub-portfolio, the browser's own Back button walks back up, and a
 * reader can send somebody the exact screen they are looking at. Every figure
 * comes from `/retail/ews/*`, which reads the Early Warning Score domain and
 * nothing else.
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import {
  ArrowLeft, ChevronRight, GitBranch, History, ListChecks, Network,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type EwsClassification,
  type EwsCustomers,
  type EwsInterpretation,
  type EwsPortfolio,
  type EwsProduct,
  type EwsProductCard,
  type EwsSubProductCard,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { EwsChat } from "./chat";
import { CustomerCard } from "./customer-card";
import { CustomerDetail } from "./customer-detail";
import {
  ActiveFilters, CardTrends, Commentary, CountsRow, ExportToWhatIf,
  Interpretation, Kpi, LAYERS, Materiality, Severity, TopReasons, count, money,
  signed,
} from "./parts";
import { EwsSignalsView } from "./signals-view";

type Level = "portfolio" | "product" | "classification" | "sub_product"
  | "customers" | "customer";

/**
 * The management reading of whatever level is on screen.
 *
 * Read separately from the level's figures so a slow interpretation never
 * holds up the numbers, and so a level that cannot be interpreted still
 * renders everything else.
 */
function useInterpretation(opts: {
  level: string; product?: string; classification?: string;
  sub_product?: string; month?: string;
}) {
  const load = React.useCallback(
    () => api.ewsInterpretation(opts),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [opts.level, opts.product, opts.classification, opts.sub_product,
     opts.month]);
  const { data } = useAsync<EwsInterpretation>(load, [load]);
  return data ?? null;
}

export function EwsWorkspace() {
  const query = useSearchParams();
  const month = query.get("month") ?? "";
  const product = query.get("product") ?? "";
  // Salaried / Non-Salaried: the first cut inside a product, §5.
  const classification = query.get("cls") ?? "";
  const subProduct = query.get("sub") ?? "";
  const customer = query.get("customer") ?? "";
  const cohort = query.get("cohort") ?? "";
  const reason = query.get("reason") ?? "";
  const layer = query.get("layer") ?? "";
  const dpdBucket = query.get("dpd") ?? "";
  const stage = query.get("stage") ?? "";
  const scoreMin = query.get("min") ?? "";
  const search = query.get("q") ?? "";
  const view = query.get("view") ?? "";

  const push = React.useCallback((next: Record<string, string>) => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) if (value) params.set(key, value);
    params.sort();
    const search_ = params.toString();
    // A push that changes nothing still re-renders the route, and the first
    // one — adding `month=` where the address had no query at all — remounted
    // the subtree and threw away whatever the chat had just answered. Compare
    // first, and say nothing when there is nothing to say.
    const current = new URLSearchParams(window.location.search);
    current.sort();
    if (current.toString() === search_) return;
    window.history.pushState({}, "",
      search_ ? `?${search_}` : window.location.pathname);
  }, []);

  const state = React.useMemo(() => ({
    month, product, cls: classification, sub: subProduct, customer, cohort,
    reason, layer, dpd: dpdBucket, stage, min: scoreMin, q: search, view,
  }), [month, product, classification, subProduct, customer, cohort, reason,
       layer, dpdBucket, stage, scoreMin, search, view]);

  const go = React.useCallback((next: Partial<typeof state>) => {
    push({ ...state, ...next } as Record<string, string>);
  }, [push, state]);

  /** Drop everything below the level being opened, so Back means something. */
  const open = React.useCallback((next: {
    product?: string; cls?: string; sub?: string; customer?: string;
    cohort?: string; view?: string; reason?: string; layer?: string;
  }) => {
    push({
      month,
      product: next.product ?? "",
      cls: next.cls ?? "",
      sub: next.sub ?? "",
      customer: next.customer ?? "",
      cohort: next.cohort ?? "",
      reason: next.reason ?? "",
      layer: next.layer ?? "",
      view: next.view ?? "",
    });
  }, [push, month]);

  const load = React.useCallback(() => api.ewsScorePortfolio(month), [month]);
  const { data, loading, error } = useAsync<EwsPortfolio>(load, [load]);

  const level: Level = customer ? "customer"
    : cohort || reason || layer || dpdBucket || stage || scoreMin || search
      ? "customers"
      : subProduct ? "sub_product"
        : classification ? "classification"
          : product ? "product" : "portfolio";

  const chatLevel = customer ? "customer"
    : product || subProduct ? "product" : "portfolio";

  const fromChat = React.useCallback((filters: Record<string, unknown>) => {
    const next: Record<string, string> = { ...state };
    // `month` is deliberately not in this list: the chat answers about the
    // month the screen is already showing, so carrying it back would push a
    // change that is not one.
    for (const key of ["product", "sub_product", "cohort", "reason",
                       "customer"]) {
      const value = filters[key];
      if (typeof value === "string" && value) {
        next[key === "sub_product" ? "sub" : key] = value;
      }
    }
    push(next);
  }, [push, state]);

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) {
    return <EmptyState title="The Early Warning Score domain could not be read"
                       description={String(error)} />;
  }
  if (!data) return null;
  if (!data.available) {
    return <EmptyState
      title="The Early Warning Score domain has not been built"
      description={data.because
        ?? "Run scripts/bootstrap_retail_installation.py."} />;
  }

  const chips: { label: string; onClear?: () => void }[] = [
    { label: data.month },
  ];
  if (product) {
    chips.push({
      label: data.products.find((p) => p.product_code === product)
        ?.product_label ?? product,
      onClear: () => open({}),
    });
  }
  if (subProduct) {
    chips.push({ label: data.sub_product_labels?.[subProduct] ?? subProduct,
                 onClear: () => open({ product }) });
  }
  if (cohort) {
    chips.push({ label: cohort.replace(/_/g, " "),
                 onClear: () => go({ cohort: "" }) });
  }
  if (reason) {
    chips.push({ label: `reason ${reason}`, onClear: () => go({ reason: "" }) });
  }
  if (layer) {
    chips.push({ label: LAYERS.find((l) => l.key === layer)?.short ?? layer,
                 onClear: () => go({ layer: "" }) });
  }
  if (customer) chips.push({ label: customer });

  return (
    <div className="space-y-5" data-testid="ews-workspace">
      {/* ------------------------------------------------- the chat, top */}
      <EwsChat month={data.month} product={product} subProduct={subProduct}
               customer={customer} level={chatLevel} onFilters={fromChat} />

      {/* ------------------------------------------------- the controls */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-[10px] font-semibold uppercase
                             tracking-[0.1em] text-text-muted">
              Month
            </span>
            <select value={data.month}
                    onChange={(event) => go({ month: event.target.value })}
                    data-testid="ews-month"
                    className="rounded-md border border-border bg-surface
                               px-2.5 py-1.5 text-sm">
              {data.months.slice().reverse().map((one) => (
                <option key={one} value={one}>{one}</option>
              ))}
            </select>
          </label>
          <ActiveFilters chips={chips} testId="ews-active-filters" />
        </div>
        <div className="flex items-center gap-2">
          <Button variant={view === "signals" ? "default" : "outline"} size="sm"
                  onClick={() => open({ product, sub: subProduct,
                                        view: view === "signals" ? "" : "signals" })}
                  data-testid="ews-open-signals">
            <ListChecks className="mr-1 size-3.5" aria-hidden />
            Signals and rules
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/early-warning/model" data-testid="ews-open-model">
              <Network className="mr-1 size-3.5" aria-hidden />
              View Model
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/early-warning/model/tree"
                  data-testid="ews-open-model-tree">
              <GitBranch className="mr-1 size-3.5" aria-hidden />
              View Model Tree
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/early-warning/model-log"
                  data-testid="ews-open-model-log">
              <History className="mr-1 size-3.5" aria-hidden />
              Model Log
            </Link>
          </Button>
        </div>
      </div>

      {view === "signals" ? (
        <EwsSignalsView month={data.month} product={product}
                        subProduct={subProduct}
                        onReason={(code) => open({ product,
                                                   cls: classification,
                                                   sub: subProduct,
                                                   reason: code,
                                                   cohort: "all" })}
                        onBack={() => open({ product, cls: classification,
                                             sub: subProduct })} />
      ) : level === "customer" ? (
        <CustomerDetail customerId={customer} month={data.month}
                        onBack={() => go({ customer: "" })} />
      ) : level === "customers" ? (
        <CustomerList state={state} data={data} go={go} open={open} />
      ) : level === "sub_product" ? (
        <SubProductLevel product={product} classification={classification}
                         subProduct={subProduct}
                         month={data.month} open={open} />
      ) : level === "classification" ? (
        <ClassificationLevel product={product} code={classification}
                             month={data.month} open={open} />
      ) : level === "product" ? (
        <ProductLevel product={product} month={data.month} open={open} />
      ) : (
        <PortfolioLevel data={data} open={open} />
      )}
    </div>
  );
}

// ===================================================== level 1: total retail

function PortfolioLevel({ data, open }: {
  data: EwsPortfolio;
  open: (next: { product?: string; cls?: string; sub?: string;
                 cohort?: string; reason?: string }) => void;
}) {
  const head = data.headline;
  const move = data.movement;
  const reading = useInterpretation({ level: "portfolio", month: data.month });
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5"
           data-testid="ews-headline">
        <Kpi label="Total retail customers" value={count(head.customers)}
             testId="ews-kpi-customers" />
        <Kpi label="Customers with an active EWS"
             value={count(head.customers_warned)}
             sub={move ? `${signed(move.customers_warned, 0)} on ${data.previous_month}`
                       : undefined}
             onClick={() => open({ cohort: "all" })} hint="Open the list"
             testId="ews-kpi-warned" />
        <Kpi label="High or critical" value={count(head.high_or_critical)}
             tone="warning"
             sub={move ? `${signed(move.high_or_critical ?? 0, 0)} on ${data.previous_month}`
                       : undefined}
             onClick={() => open({ cohort: "critical" })} hint="Open the list"
             testId="ews-kpi-high-critical" />
        <Kpi label="Current bad / delinquent" value={count(head.current_bad)}
             tone="negative"
             sub={move ? `${signed(move.current_bad, 0)} on ${data.previous_month}`
                       : undefined}
             onClick={() => open({ cohort: "current_bad" })}
             hint="Open the list" testId="ews-kpi-bad" />
        <Kpi label="Forward risk, still performing"
             value={count(head.forward_risk)} tone="warning"
             sub={move ? `${signed(move.forward_risk, 0)} on ${data.previous_month}`
                       : undefined}
             onClick={() => open({ cohort: "forward_risk" })}
             hint="Open the list" testId="ews-kpi-forward" />
        <Kpi label="Exposure under warning"
             value={money(head.exposure_warned_sar)}
             testId="ews-kpi-exposure" />
        <Kpi label="% retail exposure under warning"
             value={`${head.exposure_warned_pct.toFixed(1)}%`}
             testId="ews-kpi-exposure-pct" />
        <Kpi label="Portfolio EWS score" value={head.ews_score.toFixed(1)}
             sub={move ? `${signed(move.ews_score)} on ${data.previous_month}`
                       : undefined}
             testId="ews-kpi-score" />
        <Kpi label="Portfolio severity"
             value={<Severity band={head.severity_band} />}
             testId="ews-kpi-band" />
        <Kpi label="Default-entry rate"
             value={`${head.odr_pct.toFixed(2)}%`}
             sub={`${count(head.default_entries)} of ${count(head.default_eligible)} eligible`}
             testId="ews-kpi-odr" />
      </div>

      <Interpretation reading={reading}
                      testId="ews-portfolio-interpretation" />

      <p className="text-[11px] leading-relaxed text-text-muted"
         data-testid="ews-definitions">
        Customers, not alerts: {count(head.customers_warned)} of{" "}
        {count(head.customers)} retail customers carry an Early Warning Score
        at or above {data.definitions.warning_cutoff
          ? data.definitions.warning_cutoff.replace(/^A customer is warned at an Early Warning Score of /, "")
              .replace(/ or above\.$/, "")
          : ""} at {data.month}, scored by model {data.model_version} from the{" "}
        <span className="font-medium text-text-secondary">
          {data.domain_name}
        </span>{" "}
        domain.{" "}
        <span className="font-medium text-text-secondary">Current bad</span>{" "}
        {data.definitions.current_bad}{" "}
        <span className="font-medium text-text-secondary">Forward risk</span>{" "}
        {data.definitions.forward_risk}
      </p>

      <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2"
           data-testid="ews-product-cards">
        {data.products.map((card) => (
          <ProductCard key={card.product_code} card={card}
                       onOpen={() => open({ product: card.product_code })}
                       onReason={(code) => open({
                         product: card.product_code, cohort: "all",
                         reason: code })} />
        ))}
      </div>
    </div>
  );
}

function ProductCard({ card, onOpen, onReason }: {
  card: EwsProductCard;
  onOpen: () => void;
  onReason: (reasonCode: string) => void;
}) {
  return (
    <Card className="p-4" data-testid={`ews-product-${card.product_code}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-text-primary">
              {card.product_label}
            </h3>
            <Severity band={card.severity_band} />
          </div>
          <p className="mt-0.5 text-xs text-text-muted">
            EWS score{" "}
            <span className="font-semibold tabular-nums text-text-primary">
              {card.ews_score.toFixed(1)}
            </span>
            {card.movement ? (
              <span className={cn("ml-1.5 tabular-nums",
                                  card.movement.ews_score > 0
                                    ? "text-negative" : "text-positive")}>
                {signed(card.movement.ews_score, 2)} on the month
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ExportToWhatIf
            testId={`ews-export-product-${card.product_code}`}
            label="Export to What-If"
            scope={{ month: card.month, level: "product",
                     product: card.product_code }} />
          <Button size="sm" variant="outline" onClick={onOpen}
                  data-testid={`ews-open-product-${card.product_code}`}>
            Sub-portfolios
            <ChevronRight className="ml-1 size-3.5" aria-hidden />
          </Button>
        </div>
      </div>

      <div className="mt-3"><CountsRow counts={card} /></div>

      <div className="mt-4">
        <CardTrends trend={card.trend}
                    testId={`ews-trends-${card.product_code}`} />
      </div>

      <div className="mt-4">
        <p className="mb-1.5 text-[10px] font-semibold uppercase
                      tracking-[0.1em] text-text-muted">
          Top five warning reasons
        </p>
        <TopReasons reasons={card.top_reasons} onOpen={onReason}
                    testId={`ews-reasons-${card.product_code}`} />
      </div>

      <div className="mt-3">
        <Commentary text={card.commentary}
                    testId={`ews-commentary-${card.product_code}`} />
      </div>
    </Card>
  );
}

// ========================================================= level 2: product

function ProductLevel({ product, month, open }: {
  product: string; month: string;
  open: (next: { product?: string; cls?: string; sub?: string;
                 cohort?: string; reason?: string }) => void;
}) {
  const load = React.useCallback(
    () => api.ewsScoreProduct(product, month), [product, month]);
  const { data, loading, error } = useAsync<EwsProduct>(load, [load]);
  const reading = useInterpretation({ level: "product", product, month });

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) return <EmptyState title="This product could not be read"
                                description={String(error)} />;
  if (!data?.available) {
    return <EmptyState title="Not a retail product"
                       description={data?.because ?? ""} />;
  }

  return (
    <div className="space-y-5" data-testid="ews-product-view">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => open({})}
                data-testid="ews-back-to-portfolio">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Total retail
        </Button>
        <h2 className="text-lg font-semibold text-text-primary">
          {data.product_label} Early Warning Score
        </h2>
        <Severity band={data.headline.severity_band} />
        <span className="text-sm tabular-nums text-text-secondary">
          {data.headline.ews_score.toFixed(1)}
          {data.movement ? (
            <span className={cn("ml-1.5 text-xs",
                                data.movement.ews_score > 0
                                  ? "text-negative" : "text-positive")}>
              {signed(data.movement.ews_score, 2)}
            </span>
          ) : null}
        </span>
        <div className="ml-auto">
          <ExportToWhatIf testId="ews-export-product"
                          scope={{ month, level: "product", product }} />
        </div>
      </div>

      <Interpretation reading={reading} testId="ews-product-interpretation" />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Customers" value={count(data.headline.customers)} />
        <Kpi label="Warned" value={count(data.headline.customers_warned)}
             onClick={() => open({ product, cohort: "all" })}
             hint="Open the list" />
        <Kpi label="High or critical"
             value={count(data.headline.high_or_critical)} tone="warning"
             onClick={() => open({ product, cohort: "critical" })}
             hint="Open the list" />
        <Kpi label="Already bad" value={count(data.headline.current_bad)}
             tone="negative"
             onClick={() => open({ product, cohort: "current_bad" })}
             hint="Open the list" />
        <Kpi label="Forward risk" value={count(data.headline.forward_risk)}
             tone="warning"
             onClick={() => open({ product, cohort: "forward_risk" })}
             hint="Open the list" />
        <Kpi label="Exposure warned"
             value={money(data.headline.exposure_warned_sar)}
             sub={`${data.headline.exposure_warned_pct.toFixed(1)}% of the product`} />
      </div>

      <div data-testid="ews-classifications">
        <p className="mb-2 text-[10px] font-semibold uppercase
                      tracking-[0.1em] text-text-muted">
          Salaried and Non-Salaried
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          {(data.classifications ?? []).map((card) => (
            <Card key={card.classification} className="p-4"
                  data-testid={`ews-classification-${card.classification}`}>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button"
                        onClick={() => open({ product,
                                              cls: card.classification })}
                        className="text-base font-semibold text-text-primary
                                   hover:underline"
                        data-testid={`ews-open-classification-${card.classification}`}>
                  {card.classification_label}
                </button>
                <Severity band={card.severity_band} />
                <span className="text-[11px] tabular-nums text-text-secondary">
                  {card.ews_score.toFixed(1)}
                  {card.movement
                    ? ` ${signed(card.movement.ews_score, 2)}` : ""}
                </span>
                <div className="ml-auto">
                  <ExportToWhatIf
                    testId={`ews-export-classification-${card.classification}`}
                    label="Export to What-If"
                    scope={{ month, level: "classification", product,
                             classification: card.classification }} />
                </div>
              </div>
              <p className="mt-1 text-[11px] text-text-muted">
                {card.derivation}
              </p>
              <div className="mt-3">
                <CountsRow counts={card} />
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <CardTrends trend={card.trend}
                            testId={`ews-classification-trends-${card.classification}`} />
                <Materiality
                  materiality={card.materiality}
                  testId={`ews-classification-materiality-${card.classification}`} />
              </div>
              <p className="mt-2 text-[10px] text-text-muted">
                Default-entry rate {card.odr_pct.toFixed(2)}% ·{" "}
                {(card.salary_transfer_pct ?? 0).toFixed(1)}% transfer salary
              </p>
              <div className="mt-3">
                <TopReasons reasons={card.top_reasons}
                            onOpen={(codeId) => open({
                              product, cls: card.classification,
                              reason: codeId, cohort: "all" })}
                            testId={`ews-classification-reasons-${card.classification}`} />
              </div>
            </Card>
          ))}
        </div>
      </div>

      <Card className="p-4">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">
              Six months
            </p>
            <CardTrends trend={data.trend} testId="ews-product-trends" />
            <div className="mt-3">
              <Commentary text={data.commentary}
                          testId="ews-product-commentary" />
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">
              Top five warning reasons
            </p>
            <TopReasons reasons={data.top_reasons}
                        onOpen={(code) => open({ product, cohort: "all",
                                                 reason: code })}
                        testId="ews-product-reasons" />
            <p className="mt-3 text-[11px] text-text-muted">
              <span className="font-medium text-text-secondary">
                Model weights for this product:
              </span>{" "}
              {LAYERS.map((layer) =>
                `${layer.short} ${((data.weights[layer.key] ?? 0) * 100).toFixed(0)}%`
              ).join(" · ")}. {data.emphasis}
            </p>
          </div>
        </div>
      </Card>

      <section className="space-y-3" data-testid="ews-sub-products">
        <h3 className="text-sm font-semibold text-text-primary">
          Sub-portfolios, worst first
        </h3>
        {/* Said, because a reader who adds the customer counts up will not
            get the product's — a customer holding two cards in different
            tiers is one customer and belongs to both. The facility counts do
            add up exactly, and the exposure does. */}
        <p className="text-[11px] text-text-muted"
           data-testid="ews-sub-products-note">
          Customer counts overlap: a customer holding two facilities in
          different sub-portfolios is counted once in each, so the
          sub-portfolios sum to more customers than the product has. Facilities
          and exposure add up exactly.
        </p>
        <div className="grid grid-cols-1 gap-4 2xl:grid-cols-2">
          {data.sub_products.map((card) => (
            <SubProductCard key={card.sub_product} card={card}
                            onOpen={() => open({ product,
                                                 sub: card.sub_product })}
                            onReason={(code) => open({
                              product, sub: card.sub_product, cohort: "all",
                              reason: code })} />
          ))}
        </div>
      </section>
    </div>
  );
}

function SubProductCard({ card, onOpen, onReason }: {
  card: EwsSubProductCard;
  onOpen: () => void;
  onReason: (reasonCode: string) => void;
}) {
  return (
    <Card className="p-4" data-testid={`ews-sub-${card.sub_product}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold text-text-primary">
              {card.sub_product_label}
            </h4>
            <Severity band={card.severity_band} />
            <span className="text-xs tabular-nums text-text-secondary">
              {card.ews_score.toFixed(1)}
              {card.movement ? (
                <span className={cn("ml-1", card.movement.ews_score > 0
                  ? "text-negative" : "text-positive")}>
                  {signed(card.movement.ews_score, 2)}
                </span>
              ) : null}
            </span>
          </div>
          <p className="mt-0.5 text-[11px] text-text-muted">{card.meaning}</p>
        </div>
        <Button size="sm" variant="outline" onClick={onOpen}
                data-testid={`ews-open-sub-${card.sub_product}`}>
          Customers
          <ChevronRight className="ml-1 size-3.5" aria-hidden />
        </Button>
      </div>

      <div className="mt-3"><CountsRow counts={card} /></div>
      <div className="mt-4">
        <CardTrends trend={card.trend}
                    testId={`ews-sub-trends-${card.sub_product}`} />
      </div>
      <div className="mt-4">
        <p className="mb-1.5 text-[10px] font-semibold uppercase
                      tracking-[0.1em] text-text-muted">
          Top five warning signals
        </p>
        <TopReasons reasons={card.top_reasons} onOpen={onReason}
                    testId={`ews-sub-reasons-${card.sub_product}`} />
      </div>
      <div className="mt-3">
        <Commentary text={card.commentary}
                    testId={`ews-sub-commentary-${card.sub_product}`} />
      </div>
      <p className="mt-2 text-[10px] text-text-muted">
        <span className="font-medium">How this sub-portfolio is defined: </span>
        {card.derivation}. It carries{" "}
        {card.share_of_product_exposure_pct.toFixed(1)}% of the
        product&rsquo;s exposure.
      </p>
    </Card>
  );
}

// ============================================ level 2b: Salaried / Non-Salaried

/**
 * One classification inside one product, and the sub-products under it.
 *
 * The first cut a retail committee makes, because the two halves of a book
 * behave differently under the same shock: a salaried customer's income
 * arrives on a date, a non-salaried customer's does not.
 */
function ClassificationLevel({ product, code, month, open }: {
  product: string; code: string; month: string;
  open: (next: { product?: string; cls?: string; sub?: string;
                 cohort?: string; reason?: string }) => void;
}) {
  const load = React.useCallback(
    () => api.ewsScoreClassification(product, code, month),
    [product, code, month]);
  const { data, loading, error } = useAsync<EwsClassification>(load, [load]);
  const reading = useInterpretation({
    level: "classification", product, classification: code, month });

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) return <EmptyState title="This classification could not be read"
                                description={String(error)} />;
  if (!data?.available) {
    return <EmptyState title="Not a governed classification"
                       description={data?.because ?? ""} />;
  }

  const head = data.headline;
  return (
    <div className="space-y-5" data-testid="ews-classification-view">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => open({})}>
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Total retail
        </Button>
        <Button variant="ghost" size="sm" onClick={() => open({ product })}
                data-testid="ews-back-to-product">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden />
          {data.product_label}
        </Button>
        <h2 className="text-lg font-semibold text-text-primary">
          {data.classification_label}
        </h2>
        <Severity band={head.severity_band} />
        <span className="text-[11px] text-text-muted">{data.derivation}</span>
        <div className="ml-auto">
          <ExportToWhatIf
            testId="ews-export-classification"
            scope={{ month, level: "classification", product,
                     classification: code }} />
        </div>
      </div>

      <Interpretation reading={reading}
                      testId="ews-classification-interpretation" />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="EWS score" value={head.ews_score.toFixed(1)}
             sub={data.movement
               ? `${signed(data.movement.ews_score, 2)} on the month`
               : undefined}
             testId="ews-classification-score" />
        <Kpi label="Customers" value={count(head.customers)} />
        <Kpi label="Accounts" value={count(head.facilities)} />
        <Kpi label="Already bad" value={count(head.current_bad)}
             tone="negative"
             onClick={() => open({ product, cls: code,
                                   cohort: "current_bad" })}
             hint="Open the list" />
        <Kpi label="Forward risk" value={count(head.forward_risk)}
             tone="warning"
             onClick={() => open({ product, cls: code,
                                   cohort: "forward_risk" })}
             hint="Open the list" />
        <Kpi label="Exposure warned" value={money(head.exposure_warned_sar)}
             sub={`${head.exposure_warned_pct.toFixed(1)}% of this classification`} />
      </div>

      <Card className="p-4">
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">Six months</p>
            <CardTrends trend={data.trend}
                        testId="ews-classification-trends" />
            <div className="mt-3">
              <Materiality materiality={data.materiality}
                           testId="ews-classification-materiality" />
            </div>
            <p className="mt-2 text-[10px] text-text-muted">
              {data.salary_transfer_pct.toFixed(1)}% of this classification
              transfers salary to the bank. Salary transfer is where income
              lands; the classification is whether it is a salary.
            </p>
          </div>
          <div>
            <TopReasons reasons={data.top_reasons}
                        onOpen={(codeId) => open({ product, cls: code,
                                                   reason: codeId,
                                                   cohort: "all" })}
                        testId="ews-classification-reasons" />
            <div className="mt-3">
              <Commentary text={data.commentary}
                          testId="ews-classification-commentary" />
            </div>
          </div>
        </div>
      </Card>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase
                      tracking-[0.1em] text-text-muted"
           data-testid="ews-classification-subproducts-heading">
          Sub-products · {data.sub_product_taxonomy_version}
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          {data.sub_products.map((card) => (
            <Card key={card.sub_product} className="p-4"
                  data-testid={`ews-sub-${card.sub_product}`}>
              <div className="flex flex-wrap items-center gap-2">
                <button type="button"
                        onClick={() => open({ product, cls: code,
                                              sub: card.sub_product })}
                        className="text-base font-semibold text-text-primary
                                   hover:underline"
                        data-testid={`ews-open-sub-${card.sub_product}`}>
                  {card.sub_product_label}
                </button>
                <Severity band={card.severity_band} />
                <span className="text-[11px] tabular-nums text-text-secondary">
                  {card.ews_score.toFixed(1)}
                  {card.movement
                    ? ` ${signed(card.movement.ews_score, 2)}` : ""}
                </span>
                <div className="ml-auto">
                  <ExportToWhatIf
                    testId={`ews-export-sub-${card.sub_product}`}
                    label="Export to What-If"
                    scope={{ month, level: "sub_product", product,
                             classification: code,
                             sub_product: card.sub_product }} />
                </div>
              </div>
              <p className="mt-1 text-[11px] text-text-muted">
                {card.derivation}
              </p>
              <div className="mt-3">
                <CountsRow counts={card} />
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <CardTrends trend={card.trend}
                            testId={`ews-sub-trends-${card.sub_product}`} />
                <Materiality materiality={card.materiality}
                             testId={`ews-sub-materiality-${card.sub_product}`} />
              </div>
              <div className="mt-3">
                <TopReasons reasons={card.top_reasons}
                            onOpen={(codeId) => open({
                              product, cls: code, sub: card.sub_product,
                              reason: codeId, cohort: "all" })}
                            testId={`ews-sub-reasons-${card.sub_product}`} />
              </div>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}


// ===================================================== level 3: sub-product

function SubProductLevel({ product, classification, subProduct, month, open }: {
  product: string; classification: string; subProduct: string; month: string;
  open: (next: { product?: string; cls?: string; sub?: string;
                 cohort?: string; reason?: string }) => void;
}) {
  // Inside a classification the sub-product is read from the classification,
  // so its materiality can be measured against Salaried or Non-Salaried as
  // well as against the product and the whole book.
  const load = React.useCallback(
    () => (classification
      ? api.ewsScoreClassification(product, classification, month)
      : api.ewsScoreProduct(product, month)),
    [product, classification, month]);
  const { data, loading, error } =
    useAsync<EwsProduct | EwsClassification>(load, [load]);
  const reading = useInterpretation({
    level: "sub_product", product, classification, sub_product: subProduct,
    month });

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) return <EmptyState title="This sub-portfolio could not be read"
                                description={String(error)} />;
  const card = data?.sub_products.find((one) => one.sub_product === subProduct);
  if (!card) {
    return <EmptyState title="No such sub-portfolio"
                       description={`${subProduct} is not a sub-portfolio of `
                         + `${data?.product_label ?? product}.`} />;
  }

  return (
    <div className="space-y-5" data-testid="ews-sub-product-view">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => open({})}>
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Total retail
        </Button>
        <Button variant="ghost" size="sm" onClick={() => open({ product })}
                data-testid="ews-back-to-product">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden />
          {data?.product_label}
        </Button>
        {classification ? (
          <Button variant="ghost" size="sm"
                  onClick={() => open({ product, cls: classification })}
                  data-testid="ews-back-to-classification">
            <ArrowLeft className="mr-1 size-3.5" aria-hidden />
            {card.classification_label
             ?? (data as EwsClassification)?.classification_label}
          </Button>
        ) : null}
        <h2 className="text-lg font-semibold text-text-primary">
          {card.sub_product_label}
        </h2>
        <Severity band={card.severity_band} />
        {card.severity_reading?.near ? (
          <span className="text-[11px] text-text-muted"
                data-testid="ews-sub-near-band">
            {card.severity_reading.label}
          </span>
        ) : null}
        <div className="ml-auto">
          <ExportToWhatIf
            testId="ews-export-sub-product"
            scope={{ month, level: "sub_product", product,
                     classification, sub_product: subProduct }} />
        </div>
      </div>

      <Interpretation reading={reading}
                      testId="ews-sub-product-interpretation" />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="EWS score" value={card.ews_score.toFixed(1)}
             sub={card.movement ? `${signed(card.movement.ews_score, 2)} on the month`
                                : undefined} />
        <Kpi label="Customers" value={count(card.customers)} />
        <Kpi label="Warned" value={count(card.customers_warned)}
             onClick={() => open({ product, cls: classification,
                                   sub: subProduct, cohort: "all" })}
             hint="Open the list" />
        <Kpi label="Already bad" value={count(card.current_bad)}
             tone="negative"
             onClick={() => open({ product, cls: classification,
                                   sub: subProduct, cohort: "current_bad" })}
             hint="Open the list" />
        <Kpi label="Forward risk" value={count(card.forward_risk)}
             tone="warning"
             onClick={() => open({ product, cls: classification,
                                   sub: subProduct, cohort: "forward_risk" })}
             hint="Open the list" />
        <Kpi label="Exposure warned" value={money(card.exposure_warned_sar)}
             sub={`${card.exposure_warned_pct.toFixed(1)}% of the sub-portfolio`} />
      </div>

      <Card className="p-4">
        <div className="grid gap-5 lg:grid-cols-2">
          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">Six months</p>
            <CardTrends trend={card.trend} testId="ews-sub-view-trends" />
            <div className="mt-3">
              <Materiality materiality={card.materiality}
                           testId="ews-sub-view-materiality" />
            </div>
            <div className="mt-3">
              <Commentary text={card.commentary}
                          testId="ews-sub-view-commentary" />
            </div>
          </div>
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase
                          tracking-[0.1em] text-text-muted">
              Top five warning signals
            </p>
            <TopReasons reasons={card.top_reasons}
                        onOpen={(code) => open({ product, sub: subProduct,
                                                 cohort: "all", reason: code })}
                        testId="ews-sub-view-reasons" />
          </div>
        </div>
      </Card>

      <div className="pt-1">
        <Button size="sm" onClick={() => open({ product, sub: subProduct,
                                                cohort: "all" })}
                data-testid="ews-open-sub-customers">
          Open the {count(card.customers_warned)} warned customers
          <ChevronRight className="ml-1 size-3.5" aria-hidden />
        </Button>
      </div>
    </div>
  );
}

// ==================================================== level 4: the customers

function CustomerList({ state, data, go, open }: {
  state: Record<string, string>;
  data: EwsPortfolio;
  go: (next: Record<string, string>) => void;
  open: (next: { product?: string; sub?: string; cohort?: string;
                 customer?: string; reason?: string }) => void;
}) {
  const [shown, setShown] = React.useState(25);
  const cohort = state.cohort || "all";
  const load = React.useCallback(() => api.ewsScoreCustomers({
    month: data.month, product: state.product,
    classification: state.cls, sub_product: state.sub,
    cohort, reason: state.reason, layer: state.layer,
    dpd_bucket: state.dpd, stage: state.stage, score_min: state.min,
    search: state.q, limit: 200,
  }), [data.month, state.product, state.cls, state.sub, cohort, state.reason,
       state.layer, state.dpd, state.stage, state.min, state.q]);
  const { data: served, loading, error } = useAsync<EwsCustomers>(load, [load]);

  if (loading && !served) return <Skeleton className="h-96 w-full" />;
  if (error) return <EmptyState title="The customer list could not be read"
                                description={String(error)} />;
  if (!served) return null;

  const back = state.sub ? () => open({ product: state.product,
                                        sub: state.sub })
    : state.product ? () => open({ product: state.product })
      : () => open({});

  return (
    <div className="space-y-4" data-testid="ews-customer-list">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={back}
                data-testid="ews-back-from-customers">
          <ArrowLeft className="mr-1 size-3.5" aria-hidden /> Back
        </Button>
        <h2 className="text-lg font-semibold text-text-primary">
          Customers
        </h2>
        <span className="text-xs text-text-muted">
          {count(served.total)} match · showing {Math.min(shown, served.customers.length)}
        </span>
        <div className="ml-auto">
          {/* The filtered cohort, not the whole book: whatever these filters
              currently match is what gets written into the selection. */}
          <ExportToWhatIf
            testId="ews-export-cohort"
            label={`Export ${count(served.total)} customers to What-If`}
            scope={{ month: state.month, level: "cohort",
                     product: state.product, classification: state.cls,
                     sub_product: state.sub, cohort: state.cohort,
                     reason: state.reason, layer: state.layer,
                     dpd_bucket: state.dpd, stage: state.stage,
                     score_min: state.min ? Number(state.min) : undefined }} />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5" data-testid="ews-cohorts">
        {served.cohorts.map((one) => (
          <button key={one.key} type="button" title={one.definition}
                  onClick={() => { go({ cohort: one.key }); setShown(25); }}
                  data-testid={`ews-cohort-${one.key}`}
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs transition-colors",
                    one.key === served.cohort
                      ? "border-accent bg-accent-subtle text-accent"
                      : "border-border text-text-secondary hover:bg-surface-muted")}>
            {one.label}{" "}
            <span className="tabular-nums">({count(one.customers)})</span>
          </button>
        ))}
      </div>

      <Card className="p-3">
        <div className="flex flex-wrap items-end gap-3"
             data-testid="ews-filters">
          <Filter label="Layer" value={state.layer}
                  onChange={(value) => { go({ layer: value }); setShown(25); }}
                  testId="ews-filter-layer"
                  options={[["", "Any layer"],
                            ...LAYERS.map((l) => [l.key, l.name] as [string, string])]} />
          <Filter label="DPD bucket" value={state.dpd}
                  onChange={(value) => { go({ dpd: value }); setShown(25); }}
                  testId="ews-filter-dpd"
                  options={[["", "Any"],
                            ...served.dpd_buckets.map((b) => [b, b] as [string, string])]} />
          <Filter label="Stage" value={state.stage}
                  onChange={(value) => { go({ stage: value }); setShown(25); }}
                  testId="ews-filter-stage"
                  options={[["", "Any"], ["1", "Stage 1"], ["2", "Stage 2"],
                            ["3", "Stage 3"]]} />
          <Filter label="Minimum score" value={state.min}
                  onChange={(value) => { go({ min: value }); setShown(25); }}
                  testId="ews-filter-score"
                  options={[["", "Any"], ["20", "20 and above"],
                            ["45", "45 and above"], ["70", "70 and above"]]} />
          <label className="flex flex-col gap-1 text-[10px] uppercase
                            tracking-[0.08em] text-text-muted">
            Name, id or facility
            <input defaultValue={state.q}
                   onKeyDown={(event) => {
                     if (event.key === "Enter") {
                       go({ q: (event.target as HTMLInputElement).value });
                       setShown(25);
                     }
                   }}
                   placeholder="RC-0017858"
                   data-testid="ews-filter-search"
                   className="w-44 rounded-md border border-border bg-surface
                              px-2 py-1 text-[13px] normal-case tracking-normal" />
          </label>
          <Button size="sm" variant="ghost"
                  onClick={() => { go({ cohort: "all", layer: "", dpd: "",
                                        stage: "", min: "", q: "",
                                        reason: "" }); setShown(25); }}
                  data-testid="ews-filters-clear">
            Clear filters
          </Button>
        </div>
      </Card>

      <p className="text-[11px] text-text-muted">
        <span className="font-medium text-text-secondary">Current bad</span>{" "}
        {served.definitions.current_bad}{" "}
        <span className="font-medium text-text-secondary">Forward risk</span>{" "}
        {served.definitions.forward_risk} {served.name_note}
      </p>

      {served.customers.length === 0 ? (
        <EmptyState title="No customer matches"
                    description="Widen the cohort or clear a filter." />
      ) : (
        <div className="space-y-3">
          {served.customers.slice(0, shown).map((row) => (
            <CustomerCard key={`${row.customer_id}-${row.worst_facility_id}`}
                          row={row}
                          threshold={row.ews_threshold ?? 20}
                          onOpen={(id) => go({ customer: id })} />
          ))}
          {served.customers.length > shown ? (
            <Button size="sm" variant="outline"
                    onClick={() => setShown((n) => n + 25)}
                    data-testid="ews-show-more">
              Show {Math.min(25, served.customers.length - shown)} more
            </Button>
          ) : null}
          <p className="text-[11px] text-text-muted">
            Showing {Math.min(shown, served.customers.length)} of{" "}
            {count(served.total)} customers matching these filters
            {served.total > served.customers.length
              ? `; the server sends the worst ${served.customers.length} at a time.`
              : "."}
          </p>
        </div>
      )}
    </div>
  );
}

function Filter({ label, value, options, onChange, testId }: {
  label: string; value: string; options: [string, string][];
  onChange: (value: string) => void; testId?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[10px] uppercase
                      tracking-[0.08em] text-text-muted">
      {label}
      <select value={value} onChange={(event) => onChange(event.target.value)}
              data-testid={testId}
              className="rounded-md border border-border bg-surface px-2 py-1
                         text-[13px] normal-case tracking-normal">
        {options.map(([key, name]) => (
          <option key={key} value={key}>{name}</option>
        ))}
      </select>
    </label>
  );
}
