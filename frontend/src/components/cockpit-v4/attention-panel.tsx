"use client";

/**
 * The two analytical sections on the Cockpit home page.
 *
 * Everything here is already computed. The component fetches one endpoint,
 * renders what came back, and holds no analytical logic of its own: no
 * ranking, no thresholds, no derived percentage. If a number is on the
 * screen, the server put it there with its evidence attached, which is what
 * makes "click through to the evidence" a real promise rather than a button.
 *
 * A failure here is a COMPONENT failure. The section says so, carries its
 * reference, and leaves the rest of the Cockpit alone — a dashboard that
 * cannot compute is not a backend that is down.
 */

import * as React from "react";

import {
  readAttention,
  type AttentionFeed,
  type AttentionItem,
} from "./client";

/** "2026Q2" reads as "Q2 2026" on a cover line, which is how it is spoken. */
export function quarterLabel(quarter: string): string {
  const match = /^(\d{4})(Q[1-4])$/.exec((quarter ?? "").trim());
  return match ? `${match[2]} ${match[1]}` : (quarter ?? "");
}

const DOT: Record<string, string> = {
  high: "bg-rose-500",
  moderate: "bg-amber-500",
  low: "bg-slate-300",
  informational: "bg-sky-500",
};

const SEVERITY: Record<string, string> = {
  high: "bg-rose-100 text-rose-800 border-rose-200",
  moderate: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-slate-100 text-slate-700 border-slate-200",
  informational: "bg-sky-100 text-sky-800 border-sky-200",
};

function Card({
  item,
  onOpen,
}: {
  item: AttentionItem;
  onOpen: (item: AttentionItem) => void;
}) {
  return (
    <button
      type="button"
      data-testid="attention-card"
      data-item-id={item.item_id}
      data-segment={item.segment}
      data-scope={item.scope}
      data-severity={item.severity}
      onClick={() => onOpen(item)}
      className="flex w-full items-start gap-3 border-b border-slate-100 px-5 py-4 text-left transition last:border-b-0 hover:bg-slate-50"
    >
      <span
        aria-hidden="true"
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
          DOT[item.severity] ?? DOT.low
        }`}
      />
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-medium text-slate-900">
          {item.headline}
        </span>
        <span className="mt-1 block text-sm text-slate-500">
          <span className="text-slate-600">{item.metric_label}</span>
          {" · "}
          {item.one_line}
        </span>
      </span>
      <span
        className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
          SEVERITY[item.severity] ?? SEVERITY.low
        }`}
      >
        {item.severity}
      </span>
    </button>
  );
}

export function AttentionPanel({
  onOpen,
}: {
  onOpen: (item: AttentionItem) => void;
}) {
  const [feed, setFeed] = React.useState<AttentionFeed | null>(null);
  const [failure, setFailure] = React.useState<{
    message: string;
    reference: string;
  } | null>(null);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const loaded = await readAttention();
        if (live) setFeed(loaded);
      } catch (caught) {
        if (!live) return;
        const detail = (caught as { detail?: { detail?: Record<string, string> } })
          ?.detail;
        const body = (detail as { detail?: Record<string, string> })?.detail ??
          (detail as Record<string, string> | undefined);
        setFailure({
          message:
            body?.message ??
            "The segment attention feed could not be computed.",
          reference: body?.error_reference ?? "",
        });
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  if (failure) {
    return (
      <section
        className="rounded border border-amber-200 bg-amber-50 px-4 py-3"
        data-testid="attention-unavailable"
      >
        <h2 className="text-sm font-semibold text-amber-900">
          Segment attention feed unavailable
        </h2>
        <p className="mt-1 text-sm text-amber-800">{failure.message}</p>
        {failure.reference ? (
          <p className="mt-1 text-xs text-amber-700">
            Reference {failure.reference}
          </p>
        ) : null}
        <p className="mt-1 text-xs text-amber-700">
          Ask is unaffected — the question box above still works.
        </p>
      </section>
    );
  }

  if (!feed) {
    return (
      <p className="text-xs text-slate-400" data-testid="attention-loading">
        Reading the latest quarter…
      </p>
    );
  }

  const quarter = quarterLabel(feed.reporting_quarter);
  const segments = feed.segments_requiring_attention;
  const highlights = feed.ecl_highlights;

  return (
    <div className="space-y-10" data-testid="attention-panel">
      <section data-testid="segments-requiring-attention" className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-lg font-semibold text-slate-900">
            Segments requiring attention
          </h2>
          <span
            data-testid="attention-reporting-period"
            className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-400"
          >
            Reporting period {quarter}
          </span>
        </div>
        <p className="text-sm text-slate-600" data-testid="attention-summary">
          CreditProbe reviewed {quarter} against{" "}
          {quarterLabel(feed.prior_quarter)} and{" "}
          {quarterLabel(feed.prior_year_quarter)} and identified{" "}
          {segments.length}{" "}
          {segments.length === 1 ? "segment issue" : "segment issues"}.
        </p>

        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          {segments.length ? (
            segments.map((item) => (
              <Card key={item.item_id} item={item} onOpen={onOpen} />
            ))
          ) : (
            <p className="px-5 py-6 text-sm text-slate-500">
              No segment movement cleared the materiality floor for {quarter}.
            </p>
          )}
        </div>
        {feed.segment_note ? (
          <p
            className="text-xs text-slate-500"
            data-testid="segments-requiring-attention-note"
          >
            {feed.segment_note}
          </p>
        ) : null}
      </section>

      <section data-testid="ecl-highlights" className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="text-lg font-semibold text-slate-900">
            Latest-quarter ECL highlights
          </h2>
          <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-400">
            {quarter} vs {quarterLabel(feed.prior_quarter)}
          </span>
        </div>
        <p className="text-sm text-slate-600">
          {highlights.length} distinct ECL{" "}
          {highlights.length === 1 ? "development" : "developments"} — by
          sector, by borrower and across the book.
        </p>
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          {highlights.map((item) => (
            <Card key={item.item_id} item={item} onOpen={onOpen} />
          ))}
        </div>
      </section>

      <p className="text-[11px] text-slate-400" data-testid="attention-footnote">
        {feed.ownership.note} Computed from release {feed.release_id} in{" "}
        {feed.computed_ms} ms with no model call.
      </p>
    </div>
  );
}
