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
      onClick={() => onOpen(item)}
      className="w-full rounded border border-slate-200 bg-white px-4 py-3 text-left transition hover:border-slate-400 hover:bg-slate-50"
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm font-medium text-slate-900">
          {item.headline}
        </span>
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-[11px] font-medium ${
            SEVERITY[item.severity] ?? SEVERITY.low
          }`}
        >
          {item.severity}
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-600">{item.one_line}</p>
      <p className="mt-1.5 text-[11px] uppercase tracking-wide text-slate-400">
        {item.reporting_quarter}
        {item.comparison_quarter ? ` vs ${item.comparison_quarter}` : ""} ·{" "}
        {item.metric_label}
      </p>
    </button>
  );
}

function Section({
  title,
  blurb,
  items,
  note,
  onOpen,
  testId,
}: {
  title: string;
  blurb: string;
  items: AttentionItem[];
  note?: string;
  onOpen: (item: AttentionItem) => void;
  testId: string;
}) {
  return (
    <section className="space-y-2" data-testid={testId}>
      <div>
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        <p className="text-xs text-slate-500">{blurb}</p>
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <Card key={item.item_id} item={item} onOpen={onOpen} />
        ))}
      </div>
      {note ? (
        <p className="text-xs text-slate-500" data-testid={`${testId}-note`}>
          {note}
        </p>
      ) : null}
    </section>
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

  return (
    <div className="space-y-6" data-testid="attention-panel">
      <Section
        testId="segments-requiring-attention"
        title="Segments requiring attention"
        blurb={`Movements in the recorded book at ${feed.reporting_quarter}, against the previous quarter and the same quarter a year earlier.`}
        items={feed.segments_requiring_attention}
        note={feed.segment_note}
        onOpen={onOpen}
      />
      <Section
        testId="ecl-highlights"
        title={`Latest-quarter ECL highlights`}
        blurb={`What moved in expected credit loss at ${feed.reporting_quarter}${
          feed.prior_quarter ? `, against ${feed.prior_quarter}` : ""
        }.`}
        items={feed.ecl_highlights}
        onOpen={onOpen}
      />
      <p className="text-[11px] text-slate-400" data-testid="attention-footnote">
        {feed.ownership.note} Computed from release {feed.release_id} in{" "}
        {feed.computed_ms} ms with no model call.
      </p>
    </div>
  );
}
