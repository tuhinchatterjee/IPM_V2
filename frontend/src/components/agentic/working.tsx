"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowUpRight, GitBranch } from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  type Live,
  type Stage,
  announcement,
  caption,
  completed,
  elapsed,
  escalation,
  isWorking,
  pollAfter,
  specialistCount,
  specialistLine,
  statusLine,
  SHORT,
} from "./officer";
import { Pulse, usePrefersReducedMotion } from "./pulse";

/**
 * The officer working indicator. §6–§11.
 *
 * One line while work is happening:
 *
 *     ▁▂▇▃▁  Chief Orchestrator is working
 *            Coordinating 4 specialists · Ratings · IFRS 9 · DPD · Covenants
 *            Validating 6 calculations                                  12s
 *
 * and one line when it stops:
 *
 *     ✓      Coordinated by Chief Orchestrator
 *            4 specialists · 6 analyses · 3 domains · all checks passed
 *
 * Why it does not dominate
 * ------------------------
 * §8 asks for it to be compact and §63 asks the Cockpit to stay calm at
 * 1440×900. It is one card, three lines at most, with a fixed minimum height
 * so the stage changing does not move the page under the reader's cursor —
 * §10's "not cause layout shift", which is easy to lose the moment a caption
 * wraps to two lines.
 *
 * What it never shows
 * -------------------
 * §7: no hidden chain-of-thought. The only strings rendered here are the
 * structured stage captions and counts the run recorded. There is no path from
 * a model's intermediate text to this component.
 */
export function Working({
  runId,
  initial,
  onSettled,
  className,
}: {
  runId: number | null | undefined;
  /** The block the Ask response already carried, so the first paint is real. */
  initial?: Live | null;
  onSettled?: (live: Live) => void;
  className?: string;
}) {
  const live = useLiveRun(runId, initial);
  const reduced = usePrefersReducedMotion();
  const settled = React.useRef(false);

  React.useEffect(() => {
    if (!live || settled.current || isWorking(live)) return;
    settled.current = true;
    onSettled?.(live);
  }, [live, onSettled]);

  if (!live) return null;

  const working = isWorking(live);
  const moved = escalation(live);
  const specialists = specialistLine(live);
  const time = elapsed(live.elapsed_ms);

  return (
    <div
      className={cn(
        "min-h-[3.25rem] rounded-md border border-border bg-surface-sunken px-3 py-2",
        className,
      )}
      data-testid="officer-indicator"
      data-stage={live.stage}
      data-officer={live.officer_title || ""}
    >
      {/* The live region carries the same words the eye reads, so a screen
          reader and a sighted reader are told the same thing. §10. */}
      <p className="sr-only" role="status" aria-live="polite">
        {announcement(live)}
      </p>

      <div className="flex items-start gap-2.5">
        <span className="mt-0.5">
          <Pulse stage={live.stage as Stage} reducedMotion={reduced} />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm font-medium text-text-primary">
              {working
                ? statusLine(live)
                : live.officer_title
                  ? `Completed by ${live.officer_title}`
                  : "Completed"}
            </span>
            {time && (
              <span className="mono shrink-0 text-[11px] text-text-muted tabular">
                {time}
              </span>
            )}
          </div>

          {specialists && (
            <p className="mt-0.5 truncate text-xs text-text-secondary">
              <span className="text-text-muted">
                {specialistCount(live)} ·{" "}
              </span>
              {specialists}
            </p>
          )}

          <p className="mt-0.5 text-xs text-text-muted">
            {working ? caption(live) : (live.caption ?? SHORT[live.stage as Stage])}
          </p>

          {moved && <Escalation line={moved.line} reason={moved.reason} />}

          {working && <Passed stages={completed(live)} />}
        </div>
      </div>
    </div>
  );
}

/**
 * §9's transition.
 *
 * "Escalating to Portfolio Risk Lead" with the structural reason under it. It
 * is styled as an ordinary note rather than as a warning, because §9 is
 * explicit that escalation must not look like a failure — the request grew,
 * which is a fact about the request, not a problem with the product.
 */
function Escalation({ line, reason }: { line: string; reason: string }) {
  return (
    <p className="mt-1 flex items-start gap-1.5 text-xs text-text-secondary">
      <ArrowUpRight
        className="mt-0.5 size-3 shrink-0 text-accent"
        aria-hidden
      />
      <span className="min-w-0">
        <span className="font-medium text-text-primary">{line}</span>
        {reason && <span className="text-text-muted"> — {reason}</span>}
      </span>
    </p>
  );
}

/**
 * §8's optional compact list of completed stages.
 *
 * Dots rather than words: five stage names is a paragraph, and what a reader
 * takes from it is "several things have already happened", which four filled
 * dots say faster.
 */
function Passed({ stages }: { stages: Stage[] }) {
  if (stages.length < 2) return null;
  return (
    <span
      className="mt-1.5 flex items-center gap-1"
      title={stages.map((s) => SHORT[s]).join(" → ")}
    >
      {stages.map((stage) => (
        <span
          key={stage}
          className="size-1 rounded-full bg-pulse/50"
          aria-hidden
        />
      ))}
      <span className="sr-only">
        Completed: {stages.map((s) => SHORT[s]).join(", ")}.
      </span>
    </span>
  );
}

/**
 * The completion line, on its own. §11.
 *
 * Shown under a finished answer rather than in place of the indicator, so the
 * reader can see who did the work without the pulse still beating beside it.
 * §11: "This line may link to Trace. Do not clutter the main interpretation."
 */
export function CompletionLine({
  line,
  runId,
  traceHref,
  className,
}: {
  line: string;
  runId?: number | null;
  traceHref?: string;
  className?: string;
}) {
  if (!line) return null;
  return (
    <p
      className={cn(
        "flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-text-muted",
        className,
      )}
      data-testid="completion-line"
    >
      <span>{line}</span>
      {traceHref && (
        <Link
          href={traceHref}
          className="inline-flex items-center gap-1 text-accent hover:underline"
        >
          <GitBranch className="size-3" aria-hidden />
          Trace
        </Link>
      )}
      {runId ? (
        <span className="mono text-text-muted/70">run {runId}</span>
      ) : null}
    </p>
  );
}

/**
 * Poll a run's live status while it is working.
 *
 * Holds one piece of state carrying WHICH run it belongs to, so a second
 * question asked before the first settled cannot paint the first one's stage
 * under the second one's answer. Loading is derived — "asked for a run we
 * have not heard from yet" — rather than being a flag that has to be flipped
 * in step with the fetch.
 *
 * Polling stops the moment the run reaches a terminal stage. §10: "stop
 * completely when work is done."
 */
export function useLiveRun(
  runId: number | null | undefined,
  initial?: Live | null,
): Live | null {
  const [loaded, setLoaded] = React.useState<{
    runId: number | null;
    live: Live | null;
  } | null>(initial && runId ? { runId, live: initial } : null);

  React.useEffect(() => {
    if (!runId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const found = (await api.agenticLive(runId)) as Live;
        if (!live) return;
        setLoaded({ runId, live: found });
        if (isWorking(found)) {
          timer = setTimeout(tick, pollAfter(found.elapsed_ms ?? 0));
        }
      } catch {
        // A run we cannot read is not an error worth a panel: the answer
        // itself is unaffected, and the indicator simply stops updating.
        if (live) setLoaded((now) => now ?? { runId, live: null });
      }
    };

    void tick();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [runId]);

  // No run to poll, but a caller may still have something real to show: that
  // is `PendingOfficer`, which has the previewed officer and the stage but no
  // agent run yet, because the request has not reached the server. Returning
  // null here made `Working` render nothing for it, so the indicator §6 and §8
  // ask for — an officer named the moment work starts — never appeared, and
  // the Cockpit kept its spinner.
  if (!runId) return initial ?? null;
  if (loaded && loaded.runId === runId) return loaded.live;
  return initial ?? null;
}
