"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * CreditProbe's visual identity, which is almost entirely restraint.
 *
 * The rule
 * --------
 * **Motion means the machine is working.** Nothing in this product animates for
 * decoration. When something moves, a reader can trust that something is
 * happening; the moment it stops, the interface is still and the answer is
 * final. That is the whole vocabulary, and its value comes from never being
 * spent anywhere else.
 *
 * What that rules out
 * -------------------
 * Glowing panels, gradient sweeps across cards, pulsing borders on things that
 * are merely selected, spinners that keep turning after the work is done. A
 * product for people who sign off numbers cannot look like it is thinking when
 * it is not.
 *
 * Reduced motion
 * --------------
 * Every animation here is disabled under `prefers-reduced-motion`, and the
 * components stay visible and legible without it — the line becomes a static
 * rule, the pulse a static dot. Motion carries emphasis, never the message.
 */

/**
 * A spectral line across the top of whatever is working.
 *
 * One hairline, travelling. Placed on the composer while a question is being
 * answered and on a panel while its analysis runs.
 */
export function AiSpectralLine({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "pointer-events-none absolute inset-x-0 top-0 h-px overflow-hidden",
        className,
      )}
    >
      <div
        className={cn(
          "h-px w-1/3 animate-[ai-sweep_1.6s_var(--ease-out-quiet)_infinite]",
          "bg-gradient-to-r from-transparent via-ai to-transparent",
          "motion-reduce:animate-none motion-reduce:w-full motion-reduce:bg-ai-edge",
        )}
      />
    </div>
  );
}

/**
 * A small pulse beside a label, for a step that is currently running.
 *
 * Two rings rather than a spinner: a spinner reads as "waiting for a server",
 * and this is meant to read as "reasoning is happening here".
 */
export function AiPulse({
  className,
  label,
}: {
  className?: string;
  /** Announced to screen readers. Motion is not information on its own. */
  label?: string;
}) {
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)}>
      <span
        aria-hidden
        className={cn(
          "absolute inset-0 rounded-full bg-ai opacity-60",
          "animate-[ai-pulse_1.8s_var(--ease-out-quiet)_infinite]",
          "motion-reduce:animate-none",
        )}
      />
      <span aria-hidden className="relative inline-flex size-2 rounded-full bg-ai" />
      {label && <span className="sr-only">{label}</span>}
    </span>
  );
}

/**
 * The stages of an answer, named while they happen.
 *
 * A progress bar for work whose duration is unknown is a lie told smoothly.
 * This says what is being done instead — reading the question, composing the
 * plan, running it, checking the result — which is both honest and more
 * interesting than a percentage.
 */
export const AI_STAGES = [
  "Reading the question",
  "Composing the analysis",
  "Running it against the governed data",
  "Checking the result against what was asked",
] as const;

export function AiThinking({
  className,
  stages = AI_STAGES,
  /** How long each stage is shown before the next, in ms. */
  every = 2200,
}: {
  className?: string;
  stages?: readonly string[];
  every?: number;
}) {
  const [index, setIndex] = React.useState(0);

  React.useEffect(() => {
    // Stops at the last stage rather than looping. Looping back to "reading
    // the question" after two minutes suggests it started over, which is the
    // one thing the reader must not be told falsely.
    if (index >= stages.length - 1) return;
    const timer = window.setTimeout(() => setIndex((i) => i + 1), every);
    return () => window.clearTimeout(timer);
  }, [index, stages.length, every]);

  return (
    <p
      className={cn("flex items-center gap-2 text-body text-text-muted", className)}
      aria-live="polite"
    >
      <AiPulse />
      <span className="font-prose">{stages[index]}…</span>
    </p>
  );
}

/**
 * A luminous edge on a node that is currently reasoning.
 *
 * Used in Trace, where a reader needs to see which step is live without
 * hunting. Returns a class rather than an element so it can be composed onto
 * whatever the node already is.
 */
export function aiActiveEdge(active: boolean): string {
  return active
    ? cn(
        "ring-1 ring-ai-edge",
        "animate-[ai-breathe_2.4s_var(--ease-out-quiet)_infinite]",
        "motion-reduce:animate-none",
      )
    : "";
}
