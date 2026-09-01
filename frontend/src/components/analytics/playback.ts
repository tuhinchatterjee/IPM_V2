/**
 * Walking a result through its periods, as a state machine.
 *
 * §48: play, pause, scrub, speed, previous and next, compare two periods,
 * reset. Never autoplay, and respect a reader who has asked for reduced motion.
 *
 * Written pure and React-free for the same reason the selection reducer is:
 * the failures worth catching are about what a sequence of presses MEANS —
 * pressing Next on the last period, pressing Play at the end, choosing a
 * comparison period and then scrubbing past it — and none of those need a
 * browser to ask about.
 *
 * Presentation only
 * -----------------
 * Every period shown is already in the result. Playback moves a cursor over
 * rows the analysis returned; it never asks for a period that was not
 * calculated, and it never re-runs anything. §48 puts it plainly: trace
 * presentation-only changes without rerunning the analysis.
 */

/** Speeds offered, as multiples of the base step. */
export const SPEEDS = [0.5, 1, 2, 4] as const;
export type Speed = (typeof SPEEDS)[number];

/** How long one period is held at 1×. */
export const BASE_STEP_MS = 1400;

export interface Playback {
  /** Every period in the result, in the order the result carries them. */
  periods: string[];
  /** Where the cursor is. Always a valid index when `periods` is non-empty. */
  index: number;
  playing: boolean;
  speed: Speed;
  /** A second period held for comparison, as an index. Null when comparing off. */
  compare: number | null;
}

export type Action =
  | { type: "play" }
  | { type: "pause" }
  | { type: "toggle" }
  | { type: "tick" }
  | { type: "seek"; index: number }
  | { type: "step"; delta: number }
  | { type: "speed"; speed: Speed }
  | { type: "compare"; index: number | null }
  | { type: "reset" };

export function start(periods: string[]): Playback {
  return {
    periods,
    index: 0,
    // Never autoplay. A chart that starts moving on its own takes the reader's
    // attention before they have read the first period, and there is no way to
    // ask it to go back to what they were looking at.
    playing: false,
    speed: 1,
    compare: null,
  };
}

export function reduce(state: Playback, action: Action): Playback {
  const count = state.periods.length;

  switch (action.type) {
    case "play":
      if (count < 2) return state;
      // Pressing Play at the end restarts rather than doing nothing. A dead
      // button at the end of a sequence reads as broken.
      return {
        ...state,
        playing: true,
        index: state.index >= count - 1 ? 0 : state.index,
      };

    case "pause":
      return { ...state, playing: false };

    case "toggle":
      return reduce(state, { type: state.playing ? "pause" : "play" });

    case "tick": {
      if (!state.playing || count < 2) return state;
      const next = state.index + 1;
      // Stop at the end rather than looping. A loop makes it impossible to see
      // the last period without catching it in passing, and this is a control
      // for reading a result, not a screensaver.
      return next >= count
        ? { ...state, index: count - 1, playing: false }
        : { ...state, index: next };
    }

    case "seek": {
      if (count === 0) return state;
      const index = Math.max(0, Math.min(action.index, count - 1));
      // Scrubbing means the reader has taken over, so playback stops.
      return { ...state, index, playing: false };
    }

    case "step": {
      if (count === 0) return state;
      const index = Math.max(0, Math.min(state.index + action.delta, count - 1));
      return { ...state, index, playing: false };
    }

    case "speed":
      return { ...state, speed: action.speed };

    case "compare": {
      if (action.index === null) return { ...state, compare: null };
      if (count === 0) return state;
      const index = Math.max(0, Math.min(action.index, count - 1));
      // Comparing a period with itself is not a comparison. Choosing the
      // current period turns comparison off, which is also how the button
      // toggles.
      return { ...state, compare: index === state.index ? null : index };
    }

    case "reset":
      return start(state.periods);

    default:
      return state;
  }
}

/** How long to hold each period, at the current speed. */
export function stepMs(state: Playback): number {
  return Math.round(BASE_STEP_MS / state.speed);
}

/** The period on screen. */
export function current(state: Playback): string {
  return state.periods[state.index] ?? "";
}

/** The period being compared against, if any. */
export function comparison(state: Playback): string {
  return state.compare === null ? "" : (state.periods[state.compare] ?? "");
}

export function atStart(state: Playback): boolean {
  return state.index <= 0;
}

export function atEnd(state: Playback): boolean {
  return state.index >= state.periods.length - 1;
}

/**
 * Whether playback is worth offering at all.
 *
 * One period is a snapshot, and a play button over a snapshot is a control
 * that does nothing. Two is the minimum that can move.
 */
export function isEligible(periods: string[]): boolean {
  return periods.length >= 2;
}

/**
 * The distinct periods in a result, in the order they appear.
 *
 * Taken from the rows rather than sorted here: the result already carries the
 * order the analysis chose, and re-sorting "Q1 2026" against "Q4 2025"
 * alphabetically is how a trend chart silently runs backwards.
 */
export function periodsIn(
  rows: Array<Record<string, unknown>>,
  key: string,
): string[] {
  const seen: string[] = [];
  for (const row of rows) {
    const value = row[key];
    if (value === null || value === undefined) continue;
    const text = String(value);
    if (!seen.includes(text)) seen.push(text);
  }
  return seen;
}

/**
 * The rows for what is on screen: the current period, and the compared one.
 *
 * Both are returned together and in period order, so a comparison draws as two
 * groups rather than as one period that mysteriously has twice the rows.
 */
export function rowsFor<T extends Record<string, unknown>>(
  rows: T[],
  key: string,
  state: Playback,
): T[] {
  const wanted = new Set<string>([current(state)]);
  const other = comparison(state);
  if (other) wanted.add(other);
  if (wanted.size === 0) return rows;
  return rows.filter((row) => wanted.has(String(row[key])));
}

/**
 * The caption under the control.
 *
 * Says where the cursor is and what it is being compared with, because a
 * reader who looked away needs to know which period the figures on screen
 * belong to without pressing anything.
 */
export function caption(state: Playback): string {
  if (state.periods.length === 0) return "";
  const at = `${current(state)} · ${state.index + 1} of ${state.periods.length}`;
  const other = comparison(state);
  return other ? `${at} · compared with ${other}` : at;
}
