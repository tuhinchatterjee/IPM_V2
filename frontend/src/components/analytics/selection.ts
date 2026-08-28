/**
 * What a reader has chosen to look at, as state rather than as side effects.
 *
 * §47 asks for legend filtering, series selection, category selection, a range
 * brush, and a reset that undoes all of it. Written as event handlers those
 * five features become five booleans scattered across a component, and the bug
 * they produce is always the same one: Reset clears three of them.
 *
 * So the whole of it is one immutable value and one reducer. React-free and
 * pure, which is why it can be asserted directly — the interesting failures
 * here are about what a combination of choices MEANS, and a test can ask that
 * question without a browser.
 *
 * The rule that makes this safe
 * -----------------------------
 * Nothing here computes an analytical figure. A hidden series is still in the
 * result and still in the export; a brushed range narrows what is DRAWN and
 * never what was calculated. That boundary is the same one the visualisation
 * registry keeps, and for the same reason: a chart that quietly recomputed
 * would put a number on screen no engine produced and no Trace covers.
 */

export interface Range {
  /** Inclusive row indices into the result, in its own order. */
  from: number;
  to: number;
}

export interface Selection {
  /** Series keys the reader has switched off in the legend. */
  hidden: string[];
  /** The one series being examined alone, if any. */
  isolated: string | null;
  /** Categories (x values) the reader has picked out. */
  picked: string[];
  /** The visible window over the rows, when the reader has brushed one. */
  range: Range | null;
  /** Keyboard focus, as a row index. -1 when nothing is focused. */
  focused: number;
}

export const EMPTY: Selection = {
  hidden: [],
  isolated: null,
  picked: [],
  range: null,
  focused: -1,
};

export type Action =
  | { type: "toggle-series"; key: string }
  | { type: "isolate-series"; key: string }
  | { type: "toggle-category"; value: string }
  | { type: "set-range"; range: Range | null }
  | { type: "focus"; index: number }
  | { type: "move-focus"; delta: number; count: number }
  | { type: "reset" };

/**
 * The next selection, given what the reader just did.
 *
 * Every branch returns a new object. A reducer that mutated would work
 * perfectly until the day something memoised on identity, and then would stop
 * repainting the legend with no error anywhere.
 */
export function reduce(state: Selection, action: Action): Selection {
  switch (action.type) {
    case "toggle-series": {
      const hidden = state.hidden.includes(action.key)
        ? state.hidden.filter((k) => k !== action.key)
        : [...state.hidden, action.key];
      // Switching a series back on while another is isolated is a
      // contradiction — the reader is asking for more than one thing again, so
      // isolation ends.
      return { ...state, hidden, isolated: null };
    }

    case "isolate-series":
      // Clicking the isolated series again returns to all of them, which is
      // what a second click on a "show only this" control has to mean.
      return state.isolated === action.key
        ? { ...state, isolated: null, hidden: [] }
        : { ...state, isolated: action.key, hidden: [] };

    case "toggle-category": {
      const picked = state.picked.includes(action.value)
        ? state.picked.filter((v) => v !== action.value)
        : [...state.picked, action.value];
      return { ...state, picked };
    }

    case "set-range":
      return { ...state, range: action.range };

    case "focus":
      return { ...state, focused: action.index };

    case "move-focus": {
      if (action.count <= 0) return { ...state, focused: -1 };
      // From nothing, an arrow key starts at the first row rather than
      // wrapping to the last — a reader pressing Right expects to begin.
      const start = state.focused < 0 ? (action.delta > 0 ? -1 : 0) : state.focused;
      const next = (start + action.delta + action.count) % action.count;
      return { ...state, focused: next };
    }

    case "reset":
      return EMPTY;

    default:
      return state;
  }
}

/** Whether the reader has changed anything, which is what enables Reset. */
export function isTouched(state: Selection): boolean {
  return (
    state.hidden.length > 0 ||
    state.isolated !== null ||
    state.picked.length > 0 ||
    state.range !== null
  );
}

/**
 * Which series are drawn, in their original order.
 *
 * Isolation wins over hiding: a reader who asked to see one series alone has
 * made the more specific request, and honouring both would show nothing.
 */
export function visibleSeries<T extends { key: string }>(
  series: T[],
  state: Selection,
): T[] {
  if (state.isolated) {
    const only = series.filter((s) => s.key === state.isolated);
    // An isolated series that is no longer in the result — the analysis was
    // re-run with different measures — must not blank the chart.
    return only.length > 0 ? only : series;
  }
  const shown = series.filter((s) => !state.hidden.includes(s.key));
  // Hiding every series is a state a reader can reach by clicking through a
  // legend. An empty chart is not an answer, so the last one stays.
  return shown.length > 0 ? shown : series;
}

/**
 * The rows drawn, after any brushed range.
 *
 * Category picking deliberately does NOT filter the rows. A picked category is
 * emphasis — the reader is pointing at something while still seeing it in
 * context — and dropping the other rows would change what the chart says about
 * the whole population.
 */
export function visibleRows<T>(rows: T[], state: Selection): T[] {
  if (!state.range) return rows;
  const from = Math.max(0, Math.min(state.range.from, rows.length - 1));
  const to = Math.max(from, Math.min(state.range.to, rows.length - 1));
  return rows.slice(from, to + 1);
}

/** Whether a row should be drawn as picked out. */
export function isPicked(state: Selection, value: unknown): boolean {
  return state.picked.length > 0 && state.picked.includes(String(value));
}

/**
 * How opaque a row should be drawn.
 *
 * Emphasis by fading the rest rather than by highlighting the chosen one: a
 * highlight colour would collide with the series colours, which already carry
 * meaning.
 */
export function emphasis(state: Selection, value: unknown): number {
  if (state.picked.length === 0) return 1;
  return isPicked(state, value) ? 1 : 0.28;
}

/**
 * What the reader has chosen, in a sentence.
 *
 * Shown next to Reset, and included in the question "Ask about this" carries,
 * so a follow-up asked from a filtered chart says what it was looking at.
 */
export function describe(
  state: Selection,
  labels: Record<string, string> = {},
): string {
  const parts: string[] = [];
  if (state.isolated) {
    parts.push(`showing ${labels[state.isolated] ?? state.isolated} alone`);
  } else if (state.hidden.length > 0) {
    parts.push(
      `${state.hidden.length} series hidden: ` +
        state.hidden.map((k) => labels[k] ?? k).join(", "),
    );
  }
  if (state.picked.length > 0) {
    parts.push(
      state.picked.length === 1
        ? `${state.picked[0]} picked out`
        : `${state.picked.length} categories picked out`,
    );
  }
  if (state.range) {
    parts.push(`rows ${state.range.from + 1} to ${state.range.to + 1}`);
  }
  return parts.join(" · ");
}
