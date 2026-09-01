"use client";

import * as React from "react";
import {
  Columns2,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import * as playback from "./playback";

/**
 * Walking a result through its periods.
 *
 * §48. The state machine is in `playback.ts` and is tested there; this is the
 * control surface and the timer.
 *
 * Two rules the brief states and this honours literally:
 *
 * **Never autoplay.** Nothing moves until somebody presses Play.
 *
 * **Respect reduced motion.** A reader who has asked their operating system
 * for less movement is not asking for a slower animation — they are asking not
 * to have one. So the timer never starts for them, and the control degrades to
 * previous, next and scrub, which does everything Play does at the reader's
 * own pace.
 *
 * Presentation only. Every period shown was already calculated and is already
 * in the result; the cursor moves over rows, and nothing is re-run.
 */
export function PeriodPlayback({
  state,
  dispatch,
  className,
}: {
  state: playback.Playback;
  dispatch: React.Dispatch<playback.Action>;
  className?: string;
}) {
  const reduced = usePrefersReducedMotion();

  // The timer. Cleared and rebuilt whenever the speed or the playing state
  // changes, so a speed chosen mid-playback takes effect on the next period
  // rather than after the current one finishes at the old speed.
  React.useEffect(() => {
    if (!state.playing || reduced) return;
    const timer = window.setInterval(
      () => dispatch({ type: "tick" }),
      playback.stepMs(state),
    );
    return () => window.clearInterval(timer);
  }, [state.playing, state.speed, reduced, dispatch, state]);

  // A reader who turns reduced motion on mid-playback should not have to press
  // Pause. This is a genuine external-system synchronisation, which is what an
  // effect is for.
  React.useEffect(() => {
    if (reduced && state.playing) dispatch({ type: "pause" });
  }, [reduced, state.playing, dispatch]);

  if (!playback.isEligible(state.periods)) return null;

  return (
    <div
      className={cn("flex flex-wrap items-center gap-1", className)}
      role="group"
      aria-label="Period playback"
    >
      <Button
        variant="ghost"
        size="sm"
        onClick={() => dispatch({ type: "step", delta: -1 })}
        disabled={playback.atStart(state)}
        title="Previous period"
        aria-label="Previous period"
      >
        <SkipBack aria-hidden />
      </Button>

      {!reduced && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => dispatch({ type: "toggle" })}
          title={state.playing ? "Pause" : "Play through the periods"}
          aria-label={state.playing ? "Pause" : "Play"}
          data-testid="playback-toggle"
        >
          {state.playing ? <Pause aria-hidden /> : <Play aria-hidden />}
        </Button>
      )}

      <Button
        variant="ghost"
        size="sm"
        onClick={() => dispatch({ type: "step", delta: 1 })}
        disabled={playback.atEnd(state)}
        title="Next period"
        aria-label="Next period"
      >
        <SkipForward aria-hidden />
      </Button>

      <input
        type="range"
        min={0}
        max={state.periods.length - 1}
        value={state.index}
        onChange={(e) => dispatch({ type: "seek", index: Number(e.target.value) })}
        aria-label="Period"
        aria-valuetext={playback.current(state)}
        className="h-1 w-28 accent-[var(--ipm-accent)]"
        data-testid="playback-scrub"
      />

      <span className="mono px-1 text-[11px] text-text-muted" role="status">
        {playback.caption(state)}
      </span>

      {!reduced && (
        <select
          value={state.speed}
          onChange={(e) =>
            dispatch({
              type: "speed",
              speed: Number(e.target.value) as playback.Speed,
            })
          }
          aria-label="Playback speed"
          className="rounded border border-border bg-surface px-1 py-0.5 text-[11px] text-text-secondary"
        >
          {playback.SPEEDS.map((speed) => (
            <option key={speed} value={speed}>
              {speed}×
            </option>
          ))}
        </select>
      )}

      <Button
        variant="ghost"
        size="sm"
        onClick={() =>
          dispatch({
            type: "compare",
            // Comparing against where the reader started is the comparison
            // they almost always want: "how does now differ from the opening
            // position?"
            index: state.compare === null ? 0 : null,
          })
        }
        aria-pressed={state.compare !== null}
        title={
          state.compare === null
            ? `Compare with ${state.periods[0]}`
            : "Stop comparing"
        }
      >
        <Columns2 aria-hidden />
        Compare
      </Button>

      {(state.index !== 0 || state.compare !== null || state.speed !== 1) && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => dispatch({ type: "reset" })}
          title="Back to the first period"
        >
          <RotateCcw aria-hidden />
          Reset
        </Button>
      )}
    </div>
  );
}

/**
 * Whether this reader has asked for less movement.
 *
 * `useSyncExternalStore` rather than an effect with setState: the media query
 * IS an external store, and subscribing to it is exactly what the hook is for.
 * The server snapshot is `false` so the markup matches on hydration, and the
 * real value arrives on the client's first commit.
 */
export function usePrefersReducedMotion(): boolean {
  return React.useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}
