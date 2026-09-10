"use client";

/**
 * The live process panel: Show process / Hide process.
 *
 * What it renders is what the backend PERSISTED. There is no timer that
 * advances a step because time passed, and no stage drawn as complete
 * because a later one started. A future step is drawn as plainly
 * prospective -- an empty circle and muted text -- because a checkmark on
 * something that has not happened is a lie the user cannot detect.
 *
 * Accessibility: the collapsed line is a real button with aria-expanded; the
 * live region announces the STAGE, politely, not every event, so a screen
 * reader is not re-read a queue of substeps as they stream.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { RunView, Step } from "./reducer";
import { collapsedSummary, failedStage } from "./reducer";

const PREFERENCE_KEY = "cockpit-v4:process-panel-open";

function readPreference(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(PREFERENCE_KEY) === "open";
  } catch {
    return false;
  }
}

function writePreference(open: boolean): void {
  try {
    window.localStorage.setItem(PREFERENCE_KEY, open ? "open" : "closed");
  } catch {
    /* a browser that refuses storage still gets a working panel */
  }
}

function Marker({ state }: { state: Step["state"] }) {
  const glyph =
    state === "done" ? "✓" : state === "failed" ? "✕" : state === "running" ? "●" : "○";
  const tone =
    state === "done"
      ? "text-emerald-600"
      : state === "failed"
        ? "text-rose-600"
        : state === "running"
          ? "text-sky-600"
          : "text-slate-300";
  return (
    <span aria-hidden className={`w-4 shrink-0 text-center ${tone}`}>
      {glyph}
    </span>
  );
}

function stateWord(state: Step["state"]): string {
  return state === "prospective" ? "not started" : state;
}

export function ProcessPanel({
  view,
  operatorView = false,
  onCancel,
  onRetryStatus,
}: {
  view: RunView;
  operatorView?: boolean;
  onCancel?: () => void;
  onRetryStatus?: () => void;
}) {
  const [open, setOpen] = useState<boolean>(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const autoExpanded = useRef("");

  useEffect(() => {
    setOpen(readPreference());
  }, []);

  // A failure auto-expands its own step, once, without stealing the user's
  // choice to close the panel again afterwards.
  const failed = failedStage(view);
  useEffect(() => {
    if (failed && autoExpanded.current !== failed) {
      autoExpanded.current = failed;
      setOpen(true);
      setExpanded((prev) => ({ ...prev, [failed]: true }));
    }
  }, [failed]);

  const summary = useMemo(() => collapsedSummary(view), [view]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    writePreference(next);
  };

  return (
    <section
      className="rounded-lg border border-slate-200 bg-slate-50/60 text-sm"
      aria-label="Process"
    >
      <div className="flex items-center justify-between gap-3 px-3 py-2">
        <p className="min-w-0 truncate text-slate-700" aria-live="polite">
          {summary}
        </p>
        <div className="flex shrink-0 items-center gap-2">
          {!view.terminal && onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-white"
            >
              Stop
            </button>
          ) : null}
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            aria-controls="cockpit-v4-process-detail"
            className="rounded px-2 py-1 text-xs font-medium text-sky-700 hover:bg-white"
          >
            {open ? "Hide process ▴" : "Show process ▾"}
          </button>
        </div>
      </div>

      {view.connection === "lost" ? (
        <p className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          CONNECTION_LOST — this browser stopped receiving updates. The last
          stage it saw was{" "}
          <strong>{view.steps.find((s) => s.state === "running")?.label ?? "—"}</strong>
          . This says nothing about whether the request itself failed.{" "}
          {onRetryStatus ? (
            <button
              type="button"
              onClick={onRetryStatus}
              className="underline underline-offset-2"
            >
              Check its status
            </button>
          ) : null}
        </p>
      ) : null}

      {open ? (
        <div
          id="cockpit-v4-process-detail"
          className="border-t border-slate-200 px-3 py-2"
        >
          <ol className="space-y-1">
            {view.steps.map((step) => {
              const isOpen = Boolean(expanded[step.stage]);
              const hasDetail = step.substeps.length > 0;
              return (
                <li key={step.stage}>
                  <div className="flex items-start gap-2">
                    <Marker state={step.state} />
                    <div className="min-w-0 flex-1">
                      <button
                        type="button"
                        disabled={!hasDetail}
                        onClick={() =>
                          setExpanded((prev) => ({
                            ...prev,
                            [step.stage]: !prev[step.stage],
                          }))
                        }
                        aria-expanded={isOpen}
                        className={`flex w-full items-baseline justify-between gap-3 text-left ${
                          step.state === "prospective"
                            ? "text-slate-400"
                            : "text-slate-800"
                        } ${hasDetail ? "hover:underline" : "cursor-default"}`}
                      >
                        <span className="truncate">
                          {step.label}
                          <span className="sr-only"> — {stateWord(step.state)}</span>
                        </span>
                        <span className="shrink-0 tabular-nums text-xs text-slate-500">
                          {step.state === "prospective"
                            ? "not started"
                            : `${Math.max(0, Math.round(step.elapsedMs / 100) / 10)}s`}
                        </span>
                      </button>
                      {step.detail && step.state !== "prospective" ? (
                        <p className="truncate text-xs text-slate-500">
                          {step.detail}
                        </p>
                      ) : null}

                      {isOpen ? (
                        <ul className="mt-1 space-y-1 border-l border-slate-200 pl-3">
                          {step.substeps.map((sub, i) => (
                            <li key={`${sub.operation}-${i}`} className="text-xs">
                              <span
                                className={
                                  sub.status === "failed" || sub.status === "rejected"
                                    ? "text-rose-700"
                                    : "text-slate-600"
                                }
                              >
                                {sub.message}
                              </span>
                              {operatorView && sub.operation ? (
                                <span className="ml-2 text-slate-400">
                                  {sub.operation}
                                  {sub.detailRef ? ` · ${sub.detailRef}` : ""}
                                </span>
                              ) : null}
                              {sub.errorId ? (
                                <span className="ml-2 font-mono text-rose-600">
                                  {sub.errorId}
                                </span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>

          <p className="mt-2 border-t border-slate-200 pt-2 text-xs text-slate-500">
            Memory maintenance is separate and never holds this answer open.
          </p>
          {view.errorId ? (
            <p className="mt-1 text-xs text-slate-600">
              Support reference <span className="font-mono">{view.errorId}</span>
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
