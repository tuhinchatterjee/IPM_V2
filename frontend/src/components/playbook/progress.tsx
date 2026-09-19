"use client";

import * as React from "react";

import { draftSections, elapsed, stateLabel, type StreamStep } from "@/lib/stream";

/**
 * What a generation is doing, while it does it.
 *
 * This exists because a working seven-minute run and a dead one looked
 * identical. The screen showed one line of text that did not move, no spinner,
 * no clock, and a heartbeat that the parser discarded — so the only way to
 * find out whether anything was happening was to press Send again, which
 * started a second paid generation. That is how a real run ended up with four
 * identical messages and no file.
 *
 * What it shows, and why each part is honest:
 *
 *   the step list   named by the backend from the tool's own arguments, ticked
 *                   off as each one starts. Every entry corresponds to a real
 *                   event; none is predicted.
 *   elapsed time    a clock. Chapter 15 permits elapsed time and forbids "a
 *                   timer that pretends progress" — this measures, it does not
 *                   forecast.
 *   sections so far counted from the draft text that has actually arrived. A
 *                   count with no denominator, because the document does not
 *                   declare how many sections it will have and inventing one
 *                   is the invented completion figure chapter 12 forbids.
 *   still connected from the heartbeat, which says the connection is open and
 *                   how long the worker has been quiet — never that a file is
 *                   70% built.
 *
 * There is deliberately NO percentage. Writing is most of the wall time and
 * one step of five, so a step bar would sit near empty for almost the whole
 * run: the same lie as one stuck at 95%, told backwards.
 */

/**
 * The wall clock, in whole seconds, ticking only while something is running.
 *
 * Through `useSyncExternalStore` rather than a `setState` in an effect: the
 * clock is external state, React is told how to subscribe to it, and nothing
 * impure runs during render.
 */
function useNow(running: boolean): number {
  const subscribe = React.useCallback(
    (onChange: () => void) => {
      if (!running) return () => {};
      const id = window.setInterval(onChange, 1000);
      return () => window.clearInterval(id);
    },
    [running],
  );
  return React.useSyncExternalStore(
    subscribe,
    () => Math.floor(Date.now() / 1000),
    // Server render: no clock, and no hydration mismatch from pretending one.
    () => 0,
  );
}

/**
 * Elapsed seconds since the generation started.
 *
 * Two measurements, never a forecast. `at` is how long the generation had been
 * running when the newest event was written, by the server's clock; the local
 * seconds since that event arrived are added on top, because during the
 * minutes when the model is writing no events arrive at all and a display
 * frozen on the last one is the frozen screen this component exists to end.
 *
 * The anchor is adjusted during render when `at` changes — React's own
 * pattern for deriving state from a prop — so there is no effect writing
 * state, and the clock it reads is the pure snapshot above.
 */
function useElapsed(at: number, running: boolean): number {
  const now = useNow(running);
  const [anchor, setAnchor] = React.useState({ at, clock: now });

  if (anchor.at !== at) setAnchor({ at, clock: now });
  if (!running || !anchor.clock) return at;
  return at + Math.max(0, now - anchor.clock);
}

export interface GenerationProgressProps {
  running: boolean;
  /** Job states seen so far, in order, each with the offset it happened at. */
  steps: StreamStep[];
  /** Steps a document tool announced before starting them. */
  plan: string[];
  /** Seconds since the generation started, from the newest server event. */
  at: number;
  /** Seconds the worker has been silent, from the newest heartbeat. */
  quietFor: number;
  /** The document as it is being written. */
  draft: string;
}

export function GenerationProgress({
  running,
  steps,
  plan,
  at,
  quietFor,
  draft,
}: GenerationProgressProps) {
  const [open, setOpen] = React.useState(false);
  const total = useElapsed(at, running);

  const current = steps[steps.length - 1];
  const sections = draftSections(draft);

  if (!running && !steps.length) return null;

  return (
    <div
      className="space-y-2 rounded-lg border border-border bg-surface-sunken p-3"
      data-testid="playbook-progress"
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm text-text-primary">
          {current
            ? stateLabel(current.state, current.detail)
            : "Starting"}
          {current?.state === "drafting" && sections > 0 && (
            <span className="text-text-muted">
              {" "}
              — {sections} section{sections === 1 ? "" : "s"} so far
            </span>
          )}
        </p>
        <p className="meta tabular-nums" data-testid="playbook-elapsed">
          {elapsed(total)}
        </p>
      </div>

      {/* The heading above already names the current step. A list that
          repeats it, and nothing else, says the same thing twice — so the
          history appears once there IS a history, or once a tool has said
          what is coming. */}
      {(steps.length > 1 || plan.length > 0) && (
      <ol className="space-y-1" data-testid="playbook-steps">
        {steps.map((step, i) => (
          <li
            key={`${step.state}-${step.at}-${i}`}
            className="flex items-baseline gap-2 text-xs"
          >
            <span
              aria-hidden
              className={
                step.done ? "text-positive" : "text-text-secondary"
              }
            >
              {step.done ? "✓" : "●"}
            </span>
            <span className="flex-1 text-text-secondary">
              {stateLabel(step.state, step.detail)}
              {/* The one measurement that says where the time went, and the
                  reason this list beats a single unchanging line. */}
              {!step.done && step.state === "drafting" && sections > 0 && (
                <span className="text-text-muted">
                  {" "}
                  — {sections} section{sections === 1 ? "" : "s"} so far
                </span>
              )}
            </span>
            <span className="meta tabular-nums text-text-muted">
              {elapsed(step.at)}
            </span>
          </li>
        ))}
        {/* Steps a tool named but has not reached. Shown hollow, so what is
            coming is visible without claiming any of it has happened. */}
        {plan.slice(steps.length ? 1 : 0).map((step) => (
          <li
            key={`plan-${step}`}
            className="flex items-baseline gap-2 text-xs text-text-muted"
          >
            <span aria-hidden>○</span>
            <span className="flex-1">{step}</span>
          </li>
        ))}
      </ol>
      )}

      {running && (
        <p className="meta" data-testid="playbook-heartbeat">
          still connected
          {quietFor > 0 && ` · last event ${elapsed(quietFor)} ago`}
        </p>
      )}

      {draft && (
        <div className="border-t border-border pt-2">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-xs text-text-secondary hover:text-text-primary"
            aria-expanded={open}
            data-testid="playbook-draft-toggle"
          >
            {open ? "▾" : "▸"} Writing the report…{" "}
            <span className="text-text-muted">
              ({sections} section{sections === 1 ? "" : "s"}, click to{" "}
              {open ? "hide" : "watch"})
            </span>
          </button>
          {open && (
            <pre
              className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-surface p-2 text-xs text-text-secondary"
              data-testid="playbook-draft"
            >
              {/* The tail, not the whole thing. Watching a document being
                  written means seeing the end of it, and holding megabytes of
                  text in a DOM node helps nobody. */}
              {draft.length > 4000 ? draft.slice(-4000) : draft}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
