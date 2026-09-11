"use client";

/**
 * The right-side detail card for one attention item.
 *
 * It renders the eight things a senior credit officer needs to decide whether
 * to look further: what the issue is, why it appeared, what changed, the
 * numbers, what moved alongside it, what to review next, the trace, and a way
 * to start investigating.
 *
 * On "possible drivers": every line says "coincides with" or "associated
 * with", because that is what the data supports. Two aggregates moving in the
 * same quarter is an association. The drawer does not upgrade one into a
 * cause, and neither does the server that produced it.
 */

import * as React from "react";

import { investigate, type AttentionItem } from "./client";

export function AttentionDrawer({
  item,
  onClose,
  onInvestigate,
  operatorView = false,
}: {
  item: AttentionItem | null;
  onClose: () => void;
  onInvestigate: (thread: {
    threadId: string;
    item: AttentionItem;
    suggested: string[];
  }) => void;
  operatorView?: boolean;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [showTrace, setShowTrace] = React.useState(false);

  React.useEffect(() => {
    setError("");
    setBusy(false);
    setShowTrace(false);
  }, [item?.item_id]);

  React.useEffect(() => {
    if (!item) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, onClose]);

  if (!item) return null;

  const drill = item.drilldown;

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const opened = await investigate(item.item_id);
      onInvestigate({
        threadId: opened.thread_id,
        item,
        suggested: opened.suggested_questions,
      });
    } catch {
      setBusy(false);
      setError("The investigation could not be opened. Nothing was started.");
    }
  };

  return (
    <aside
      data-testid="attention-drawer"
      data-item-id={item.item_id}
      aria-label={item.headline}
      className="fixed right-0 top-0 z-40 flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-slate-200 bg-white shadow-xl"
    >
      <header className="sticky top-0 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4">
        <div>
          <h2
            className="text-sm font-semibold text-slate-900"
            data-testid="attention-drawer-title"
          >
            {item.headline}
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {item.segment} · {item.reporting_quarter}
            {item.comparison_quarter ? ` vs ${item.comparison_quarter}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          data-testid="attention-drawer-close"
          className="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
          aria-label="Close"
        >
          ✕
        </button>
      </header>

      <div className="space-y-5 px-5 py-4 text-sm text-slate-700">
        <section data-testid="attention-drawer-why">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Why it appeared
          </h3>
          <p className="mt-1">{item.why_it_appeared}</p>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            What changed
          </h3>
          <p className="mt-1">{item.what_changed}</p>
        </section>

        <section data-testid="attention-drawer-numbers">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Key numbers
          </h3>
          <dl className="mt-1 divide-y divide-slate-100">
            {item.key_numbers.map((entry) => (
              <div
                key={entry.label}
                className="flex items-baseline justify-between gap-4 py-1.5"
              >
                <dt className="text-xs text-slate-500">{entry.label}</dt>
                <dd className="font-mono text-sm text-slate-900">
                  {entry.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {item.possible_drivers.length ? (
          <section data-testid="attention-drawer-drivers">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Possible drivers
            </h3>
            <ul className="mt-1 space-y-1.5">
              {item.possible_drivers.map((driver, index) => (
                <li key={`${driver.metric}-${index}`} className="text-sm">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] uppercase tracking-wide text-slate-600">
                    {driver.relationship}
                  </span>{" "}
                  {driver.statement}
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-[11px] text-slate-400">
              Recorded alongside this movement. Association, not established
              cause.
            </p>
          </section>
        ) : null}

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            What to review next
          </h3>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {item.what_to_review_next.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {drill ? (
            <p
              className="mt-2 text-xs text-slate-500"
              data-testid="attention-drawer-drilldown"
            >
              {drill.note} This segment has {drill.borrower_count} borrowers at{" "}
              {item.reporting_quarter}.
            </p>
          ) : null}
        </section>

        <section>
          <button
            type="button"
            onClick={() => setShowTrace((open) => !open)}
            data-testid="attention-drawer-trace-toggle"
            className="text-xs text-slate-500 underline"
          >
            {showTrace ? "Hide trace" : "Trace and evidence"}
          </button>
          {showTrace ? (
            <pre
              data-testid="attention-drawer-trace"
              className="mt-2 max-h-64 overflow-auto rounded bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100"
            >
              {JSON.stringify(item.evidence, null, 2)}
            </pre>
          ) : null}
          {operatorView ? (
            <p className="mt-1 text-[11px] text-slate-400">
              Full technical record: {item.evidence_url}
            </p>
          ) : null}
        </section>
      </div>

      <footer className="sticky bottom-0 border-t border-slate-200 bg-white px-5 py-4">
        {error ? (
          <p
            className="mb-2 text-xs text-rose-700"
            data-testid="attention-drawer-error"
          >
            {error}
          </p>
        ) : null}
        <button
          type="button"
          onClick={() => void start()}
          disabled={busy}
          data-testid="attention-investigate"
          className="w-full rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          {busy ? "Opening…" : "Investigate further"}
        </button>
        <p className="mt-1.5 text-[11px] text-slate-400">
          Opens a Cockpit conversation already holding this segment, quarter and
          movement. You will not need to restate them.
        </p>
      </footer>
    </aside>
  );
}
