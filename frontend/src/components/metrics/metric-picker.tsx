"use client";

import * as React from "react";
import { Loader2, Search } from "lucide-react";

import { api, type MetricHit, type MetricUnavailable } from "@/lib/api";

/**
 * Finding a metric by typing part of what you call it.
 *
 * §8.3 asks that this does not open with the whole catalogue. Sixty-odd
 * governed metrics in a scrolling list is a list nobody reads: people give up
 * and rebuild a number they already had, which is how two definitions of
 * "default rate" end up on two dashboards.
 *
 * So it starts empty and answers what you type. Every suggestion says WHY it
 * matched — "alias: bad rate" under a result named "Retail Default Rate" —
 * because a suggestion whose reason is invisible looks like a bug.
 *
 * When nothing matches but the words name something CreditProbe knows it
 * cannot calculate here, the reason is shown instead of an empty list.
 */
export function MetricPicker({
  onPick,
  placeholder = "Search metrics — delinquency, coverage, gini, npl",
  domain = "",
  autoFocus = false,
}: {
  onPick: (hit: MetricHit) => void;
  placeholder?: string;
  domain?: string;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [active, setActive] = React.useState(0);
  // The query the answer belongs to travels WITH it. Otherwise a suggestion
  // for "del" is still on screen while somebody is typing "delinq 30", which
  // reads as the picker widening rather than narrowing.
  const [answer, setAnswer] = React.useState<{
    for: string;
    hits: MetricHit[];
    absent: MetricUnavailable[];
  }>({ for: "", hits: [], absent: [] });

  const text = query.trim();
  const current = answer.for === text;
  const hits = current ? answer.hits : [];
  const absent = current ? answer.absent : [];

  React.useEffect(() => {
    const wanted = query.trim();
    if (!wanted) return;
    // Debounced, because every keystroke would otherwise be a request and the
    // answers would arrive out of order.
    let live = true;
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const body = await api.searchMetrics(wanted, 8, domain);
        if (!live) return;
        setAnswer({
          for: wanted,
          hits: body.results,
          absent: body.unavailable,
        });
        setActive(0);
        setError(null);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (live) setBusy(false);
      }
    }, 160);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [query, domain]);

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((i) => Math.min(i + 1, hits.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter" && hits[active]) {
      event.preventDefault();
      onPick(hits[active]);
      setQuery("");
    }
  }

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-muted"
          aria-hidden
        />
        <input
          value={query}
          autoFocus={autoFocus}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label="Search metrics"
          className="h-9 w-full rounded-md border border-border bg-surface pl-8 pr-8 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        {busy && (
          <Loader2
            className="absolute right-2.5 top-1/2 size-3.5 -translate-y-1/2 animate-spin text-text-muted"
            aria-hidden
          />
        )}
      </div>

      {error && <p className="text-xs text-negative">{error}</p>}

      {hits.length > 0 && (
        <ul className="divide-y divide-border overflow-hidden rounded-md border border-border">
          {hits.map((hit, index) => (
            <li key={hit.metric_id}>
              <button
                type="button"
                onMouseEnter={() => setActive(index)}
                onClick={() => {
                  onPick(hit);
                  setQuery("");
                }}
                className={`block w-full px-3 py-2 text-left ${
                  index === active ? "bg-surface-muted" : "bg-surface"
                }`}
              >
                <span className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm text-text-primary">{hit.name}</span>
                  <span className="text-[11px] text-text-muted">
                    {hit.domain}
                  </span>
                  {!hit.governed && (
                    <span className="text-[11px] text-warning">User built</span>
                  )}
                </span>
                <span className="mt-0.5 block text-[11px] text-text-muted">
                  {hit.why}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {text && current && !busy && hits.length === 0 && (
        <div className="rounded-md border border-border px-3 py-2.5">
          {absent.length > 0 ? (
            absent.map((entry) => (
              <div key={entry.metric_id} className="text-xs leading-relaxed">
                <p className="text-text-secondary">
                  {entry.name} is not available in this deployment.
                </p>
                <p className="mt-0.5 text-text-muted">{entry.because}</p>
                {entry.needs.length > 0 && (
                  <p className="mt-0.5 text-text-muted">
                    Would need: {entry.needs.join("; ")}
                  </p>
                )}
              </div>
            ))
          ) : (
            <p className="text-xs text-text-muted">
              Nothing in the catalogue matches that. Try a shorter word — the
              search matches names, the aliases people actually use, and the
              fields a metric reads.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
