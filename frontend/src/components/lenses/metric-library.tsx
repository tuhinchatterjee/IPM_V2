"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, Loader2, Plus, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, type MetricHit, type MetricPanel } from "@/lib/api";

/**
 * The Metric Library: everything CreditProbe governs, by category.
 *
 * §5. Two ways in, because people arrive knowing two different things.
 *
 * Somebody who knows what the metric is called types it, and the typeahead
 * answers — that path scales past a hundred metrics because the list never
 * gets longer than eight however many exist.
 *
 * Somebody who knows the AREA but not the name browses. Categories are the
 * governed data domains, which is why they are worth browsing: they are the
 * same boundary the permission model uses, so the shape of the library is the
 * shape of what a person may actually read rather than a filing decision
 * somebody made.
 *
 * A category opens closed and holds its count, so the page is a short list of
 * areas rather than a hundred rows. That is what makes it scalable in the way
 * that matters: the first screen is readable at any catalogue size.
 */
export function MetricLibrary({
  onPick,
  chosen = [],
  domain = "",
  portfolio = "",
}: {
  onPick: (metricId: string, name: string) => void;
  /** Metric ids already on the lens, so the library can say so. */
  chosen?: string[];
  domain?: string;
  portfolio?: string;
}) {
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<MetricHit[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [answered, setAnswered] = React.useState("");
  const [catalogue, setCatalogue] = React.useState<
    { domain: string; metrics: MetricPanel[] }[] | null
  >(null);
  const [open, setOpen] = React.useState<string>("");
  const [detail, setDetail] = React.useState<string>("");

  const text = query.trim();

  React.useEffect(() => {
    let live = true;
    void api
      .metricCatalogue()
      .then((body) => {
        if (live) setCatalogue(body.domains);
      })
      .catch(() => {
        if (live) setCatalogue([]);
      });
    return () => {
      live = false;
    };
  }, []);

  React.useEffect(() => {
    // No early setState: an empty box has no results by derivation — `showing`
    // below is gated on the answer matching what is typed — so there is
    // nothing to clear and nothing to cascade.
    if (!text) return;
    let live = true;
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const body = await api.searchMetrics(text, 10, domain, portfolio);
        if (!live) return;
        setHits(body.results);
        setAnswered(text);
      } finally {
        if (live) setSearching(false);
      }
    }, 160);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [text, domain, portfolio]);

  const showing = answered === text ? hits : [];

  return (
    <div className="space-y-3" data-testid="metric-library">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-muted"
          aria-hidden
        />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the library — coverage, watchlist, cure rate, gini"
          aria-label="Search the metric library"
          className="h-9 w-full rounded-md border border-border bg-surface pl-8 pr-8 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        {searching && (
          <Loader2
            className="absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 animate-spin text-text-muted"
            aria-hidden
          />
        )}
      </div>

      {text && showing.length > 0 && (
        <ul className="divide-y divide-border overflow-hidden rounded-md border border-border">
          {showing.map((hit) => (
            <Row
              key={hit.metric_id}
              metricId={hit.metric_id}
              name={hit.name}
              domain={hit.domain}
              unit={hit.unit}
              definition={hit.definition}
              formula={hit.formula}
              why={hit.why}
              already={chosen.includes(hit.metric_id)}
              expanded={detail === hit.metric_id}
              onToggle={() =>
                setDetail((d) => (d === hit.metric_id ? "" : hit.metric_id))
              }
              onPick={() => onPick(hit.metric_id, hit.name)}
            />
          ))}
        </ul>
      )}

      {text && showing.length === 0 && !searching && (
        <p className="rounded-md border border-border px-3 py-2.5 text-xs text-text-muted">
          Nothing in the library matches that. Try a shorter word — the search
          knows the names people actually use, not only the canonical ones — or
          define a new metric.
        </p>
      )}

      {!text && (
        <div className="space-y-1.5">
          <p className="text-[11px] text-text-muted">
            Or browse by category. Categories are the governed data domains, so
            what is listed here is what you are allowed to read.
          </p>
          {catalogue === null && <Loader2 className="size-4 animate-spin" aria-hidden />}
          {(catalogue ?? []).map((group) => (
            <div
              key={group.domain}
              className="overflow-hidden rounded-md border border-border"
            >
              <button
                type="button"
                onClick={() =>
                  setOpen((o) => (o === group.domain ? "" : group.domain))
                }
                aria-expanded={open === group.domain}
                className="flex w-full items-center justify-between gap-2 bg-surface px-3 py-2 text-left transition-colors hover:bg-surface-hover"
              >
                <span className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
                  {open === group.domain ? (
                    <ChevronDown className="size-3.5" aria-hidden />
                  ) : (
                    <ChevronRight className="size-3.5" aria-hidden />
                  )}
                  {group.domain}
                </span>
                <span className="text-[11px] text-text-muted">
                  {group.metrics.length}
                </span>
              </button>
              {open === group.domain && (
                <ul className="divide-y divide-border border-t border-border">
                  {group.metrics.map((metric) => (
                    <Row
                      key={metric.metric_id}
                      metricId={metric.metric_id}
                      name={metric.name}
                      domain={metric.domain}
                      unit={metric.unit}
                      definition={metric.definition}
                      formula={metric.formula}
                      why=""
                      already={chosen.includes(metric.metric_id)}
                      expanded={detail === metric.metric_id}
                      onToggle={() =>
                        setDetail((d) =>
                          d === metric.metric_id ? "" : metric.metric_id,
                        )
                      }
                      onPick={() => onPick(metric.metric_id, metric.name)}
                    />
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * One metric in the library.
 *
 * The row carries what a person needs to choose — the name, the unit, the
 * definition and the formula — and hides the rest behind "Details", because
 * a governed metric's full panel is thirty fields and a list of thirty-field
 * panels is not a list.
 */
function Row({
  metricId,
  name,
  domain,
  unit,
  definition,
  formula,
  why,
  already,
  expanded,
  onToggle,
  onPick,
}: {
  metricId: string;
  name: string;
  domain: string;
  unit: string;
  definition: string;
  formula: string;
  why: string;
  already: boolean;
  expanded: boolean;
  onToggle: () => void;
  onPick: () => void;
}) {
  return (
    <li className="bg-surface px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={onToggle}
          className="min-w-0 flex-1 text-left"
          aria-expanded={expanded}
        >
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-sm text-text-primary">{name}</span>
            <span className="rounded border border-border px-1 text-[10px] text-text-muted">
              {unit}
            </span>
            <span className="text-[11px] text-text-muted">{domain}</span>
          </span>
          {definition && (
            <span className="mt-0.5 block line-clamp-2 text-[11px] leading-relaxed text-text-secondary">
              {definition}
            </span>
          )}
          {formula && (
            <span className="mt-0.5 block truncate font-mono text-[10px] text-text-muted">
              {formula}
            </span>
          )}
          {why && (
            <span className="mt-0.5 block text-[11px] text-text-muted">
              {why}
            </span>
          )}
        </button>
        <Button
          size="sm"
          variant={already ? "ghost" : "outline"}
          disabled={already}
          onClick={onPick}
          data-testid="library-add"
          aria-label={already ? `${name} is already on the lens` : `Add ${name}`}
        >
          {already ? (
            "On the lens"
          ) : (
            <>
              <Plus aria-hidden />
              Add
            </>
          )}
        </Button>
      </div>
      {expanded && <Details metricId={metricId} />}
    </li>
  );
}

/**
 * A metric's full definition, fetched when somebody asks for it.
 *
 * Fetched rather than carried: the search returns ten rows and the full
 * explanation of one is bigger than all ten summaries together, so loading
 * every one to show none would make the library slower the more of it you
 * could see.
 */
function Details({ metricId }: { metricId: string }) {
  const [shown, setShown] = React.useState<{
    plain: string[];
    sql: string;
    formula: string;
  } | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void api
      .explainMetric(metricId)
      .then((body) => {
        if (live)
          setShown({
            plain: body.plain_english,
            sql: body.sql || body.sql_unavailable,
            formula: body.formula_detail || body.formula,
          });
      })
      .catch((e) => {
        if (live) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, [metricId]);

  if (error) return <p className="mt-2 text-[11px] text-negative">{error}</p>;
  if (!shown)
    return (
      <p className="mt-2 flex items-center gap-1.5 text-[11px] text-text-muted">
        <Loader2 className="size-3 animate-spin" aria-hidden />
        Reading the definition
      </p>
    );

  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2">
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
          Formula
        </p>
        <p className="mt-0.5 break-words font-mono text-[11px] text-text-primary">
          {shown.formula}
        </p>
      </div>
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
          How it is executed
        </p>
        <ol className="mt-0.5 list-inside list-decimal space-y-0.5">
          {shown.plain.map((step, index) => (
            <li key={index} className="text-[11px] leading-relaxed text-text-secondary">
              {step}
            </li>
          ))}
        </ol>
      </div>
      <details>
        <summary className="cursor-pointer text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
          Query
        </summary>
        <pre className="mt-1 max-h-56 overflow-auto rounded bg-surface-muted p-2 font-mono text-[10px] leading-relaxed text-text-secondary">
          {shown.sql}
        </pre>
      </details>
    </div>
  );
}
