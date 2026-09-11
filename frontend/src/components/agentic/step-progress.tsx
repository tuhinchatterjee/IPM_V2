"use client";

import * as React from "react";
import {
  Check,
  ChevronDown,
  CircleDot,
  Info,
  OctagonAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { usePrefersReducedMotion } from "./pulse";
import {
  type ProgressDocument,
  type ProgressStep,
  type ProgressSubstep,
  type StepStatus,
  STATUS_WORDS,
  analyses,
  announcement,
  details,
  seconds,
} from "./steps";

/**
 * The step-list progress panel. The shared presentation half.
 *
 * One row per stage the server has reported, each with a mark, a sentence and
 * a duration:
 *
 *     ✓  Understanding your question                     2.4s
 *     ✓  Resolving scope and intent                      5.1s
 *     ●  Running Early Warning analysis                  7.2s
 *          ✓ Establishing the Contracting position
 *          ● Testing concentration in high-risk obligors
 *          ○ Ranking the names driving the result
 *
 * and, once the work stops, one line:
 *
 *     ✓  Analysed in 31.8s · 6 analyses · evidence checked
 *
 * Everything it renders arrives as data. There is no label written in this
 * file and no timer that advances a step — a row appears because the server
 * said the stage began, and ticks because the server said it finished. The
 * only clock here is the one that makes the CURRENT step's elapsed figure
 * move between polls, and it never changes which step is current.
 *
 * Why a fixed left column
 * -----------------------
 * The mark, the label and the time sit in a three-column grid with the mark
 * and the time at fixed widths, so a stage changing from ○ to ✓ does not
 * shift the sentence beside it. A list that jitters as it fills in is harder
 * to read than one that does not move.
 */
export function StepProgress({
  document,
  /** Milliseconds since the request left the browser, for the live figure. */
  liveMs,
  className,
  collapsible = true,
}: {
  document: ProgressDocument | null;
  liveMs?: number;
  className?: string;
  collapsible?: boolean;
}) {
  const reduced = usePrefersReducedMotion();
  const done = Boolean(document && !document.active);
  // Collapsed once the work stops. §17: the completed panel becomes one line
  // rather than permanently occupying the thread.
  const [open, setOpen] = React.useState(true);
  const [details_, setDetails] = React.useState(false);
  const settled = React.useRef(false);

  React.useEffect(() => {
    if (done && !settled.current && collapsible) {
      settled.current = true;
      setOpen(false);
    }
  }, [done, collapsible]);

  if (!document) return null;

  const expanded = open || !collapsible;

  return (
    <div
      className={cn(
        "rounded-md border border-border bg-surface-sunken",
        className,
      )}
      data-testid="step-progress"
      data-active={document.active ? "true" : "false"}
    >
      <Announcer document={document} />

      {done && collapsible ? (
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={expanded}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-text-secondary transition-colors hover:bg-surface-hover"
          data-testid="completion-bar"
        >
          <Mark status="done" reduced={reduced} />
          <span className="min-w-0 flex-1 truncate">
            {document.completion_line || "Analysis complete"}
          </span>
          <ChevronDown
            className={cn(
              "size-3.5 shrink-0 text-text-muted transition-transform",
              expanded && "rotate-180",
            )}
            aria-hidden
          />
        </button>
      ) : null}

      {expanded && (
        <ol
          className={cn("space-y-0.5 px-3 py-2", done && collapsible && "pt-0")}
          data-testid="step-list"
        >
          {document.steps.map((step) => (
            <Row
              key={step.key}
              step={step}
              reduced={reduced}
              liveMs={document.active ? liveMs : undefined}
            />
          ))}
        </ol>
      )}

      {expanded && done && (
        <div className="border-t border-border px-3 py-1.5">
          <button
            type="button"
            onClick={() => setDetails((was) => !was)}
            aria-expanded={details_}
            className="flex items-center gap-1 text-[11px] text-text-muted transition-colors hover:text-text-secondary"
            data-testid="details-toggle"
          >
            <ChevronDown
              className={cn(
                "size-3 transition-transform",
                details_ && "rotate-180",
              )}
              aria-hidden
            />
            Details
          </button>
          {details_ && <Details document={document} />}
        </div>
      )}
    </div>
  );
}

/**
 * One stage.
 *
 * The duration shown is the stage's own measured elapsed time once it has
 * finished, and the live figure while it is running. Both are real: the first
 * came from the server's event clock, the second is the time since the
 * request left the browser, and neither is an estimate of how long the stage
 * will take.
 */
function Row({
  step,
  reduced,
  liveMs,
}: {
  step: ProgressStep;
  reduced: boolean;
  liveMs?: number;
}) {
  const running = step.status === "active";
  const time = running ? seconds(liveMs) : seconds(step.elapsed_ms);
  const { done, total } = analyses(step);

  return (
    <li data-testid={`step-${step.key}`} data-status={step.status}>
      <div className="grid grid-cols-[1rem_minmax(0,1fr)_auto] items-baseline gap-x-2 gap-y-0.5 py-0.5">
        <span className="flex h-4 items-center justify-center">
          <Mark status={step.status} reduced={reduced} />
        </span>
        <span
          className={cn(
            "min-w-0 break-words text-xs leading-relaxed",
            step.status === "done" && "text-text-secondary",
            running && "font-medium text-text-primary",
            step.status === "waiting" && "text-text-muted",
            step.status === "note" && "text-text-muted",
            step.status === "stopped" && "text-text-secondary",
          )}
        >
          {step.label}
          <span className="sr-only">, {STATUS_WORDS[step.status]}</span>
          {running && total > 0 && (
            <span className="ml-1.5 text-[11px] font-normal text-text-muted tabular">
              {done}/{total}
            </span>
          )}
        </span>
        {time ? (
          <span className="mono shrink-0 text-[11px] text-text-muted tabular">
            {time}
          </span>
        ) : (
          <span />
        )}
      </div>

      {step.substeps.length > 0 && (
        <ul className="mb-1 ml-[1.5rem] space-y-0.5" data-testid="substeps">
          {step.substeps.map((sub, i) => (
            <Substep key={`${sub.key}-${i}`} sub={sub} reduced={reduced} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** One governed analysis under the execution stage. */
function Substep({
  sub,
  reduced,
}: {
  sub: ProgressSubstep;
  reduced: boolean;
}) {
  return (
    <li
      className="grid grid-cols-[0.875rem_minmax(0,1fr)] items-baseline gap-x-2"
      data-testid={`substep-${sub.key}`}
      data-status={sub.status}
    >
      <span className="flex h-4 items-center justify-center">
        <Mark status={sub.status} reduced={reduced} small />
      </span>
      <span
        className={cn(
          "min-w-0 break-words text-[11px] leading-relaxed",
          sub.status === "active"
            ? "text-text-secondary"
            : sub.status === "waiting"
              ? "text-text-muted/70"
              : "text-text-muted",
        )}
      >
        {sub.label}
        <span className="sr-only">, {STATUS_WORDS[sub.status]}</span>
      </span>
    </li>
  );
}

/**
 * The mark. §6's four states.
 *
 * Icon and shape rather than colour alone, so a reader who cannot tell the
 * accent from the muted still sees a tick, a ring or an outline. Under
 * `prefers-reduced-motion` the running mark stops pulsing and stays a filled
 * ring in the same place, so nothing moves when the setting changes.
 */
function Mark({
  status,
  reduced,
  small,
}: {
  status: StepStatus;
  reduced: boolean;
  small?: boolean;
}) {
  const size = small ? "size-2.5" : "size-3.5";
  if (status === "done") {
    return <Check className={cn(size, "text-pulse")} aria-hidden />;
  }
  if (status === "stopped") {
    return <OctagonAlert className={cn(size, "text-warning")} aria-hidden />;
  }
  if (status === "note") {
    return <Info className={cn(size, "text-text-muted")} aria-hidden />;
  }
  if (status === "active") {
    if (reduced) {
      return <CircleDot className={cn(size, "text-pulse")} aria-hidden />;
    }
    return (
      <span
        className={cn(
          "inline-block shrink-0 rounded-full bg-pulse",
          small ? "size-1.5" : "size-2",
        )}
        style={{ animation: "step-pulse 1.8s ease-in-out infinite" }}
        aria-hidden
      />
    );
  }
  return (
    <span
      className={cn(
        "inline-block shrink-0 rounded-full border border-border-strong",
        small ? "size-1.5" : "size-2",
      )}
      aria-hidden
    />
  );
}

/** §18's operational table. Business facts only — see `steps.ts`. */
function Details({ document }: { document: ProgressDocument }) {
  const rows = details(document);
  if (rows.length === 0) return null;
  return (
    <dl
      className="mt-1.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 pb-1 text-[11px]"
      data-testid="details-table"
    >
      {rows.map((row) => (
        <React.Fragment key={row.label}>
          <dt className="text-text-muted">{row.label}</dt>
          <dd className="text-text-secondary">{row.value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

/**
 * The live region.
 *
 * Screen readers are told which stage is running, and are told it at most
 * once every few seconds however often the panel repaints. §29 asks for "no
 * rapid noisy announcements every 100ms", and a live region wired straight to
 * a polling component is exactly that — the elapsed figure alone would
 * re-announce the whole sentence on every tick.
 */
function Announcer({ document }: { document: ProgressDocument }) {
  const message = announcement(document);
  const [spoken, setSpoken] = React.useState(message);
  const latest = React.useRef(message);

  React.useEffect(() => {
    latest.current = message;
  }, [message]);

  React.useEffect(() => {
    const timer = setInterval(() => {
      setSpoken((was) => (was === latest.current ? was : latest.current));
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  // The final line matters more than the cadence, so it is rendered directly
  // rather than waiting for the next tick of a timer the work has outlived.
  return (
    <p className="sr-only" role="status" aria-live="polite">
      {document.active ? spoken : message}
    </p>
  );
}
