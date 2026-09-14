/**
 * The dashboard's filter state, as a pure module.
 *
 * Why this is separate from the controls that draw it
 * ---------------------------------------------------
 * A filter bar is mostly arithmetic pretending to be a widget: which chips are
 * showing, what clearing one leaves behind, whether a typed bound is usable
 * yet, whether the spec about to be sent differs from the one already
 * answered. None of that needs a DOM, and all of it is worth testing — so it
 * lives here, and the component renders it.
 *
 * The state is deliberately NOT the wire format. A half-typed range ("min: 3",
 * max still empty, or "-" on the way to "-5") is a legitimate thing for a text
 * box to hold and an illegitimate thing to send, so the draft is kept as
 * strings and `toSpec` produces the governed object. A control that could only
 * hold valid states would have to reject a keystroke, which is the behaviour
 * every reader hates.
 */

/** A range the reader is typing. Strings, because a box holds text. */
export interface DraftRange {
  min: string;
  max: string;
}

export interface FilterState {
  customer: string;
  /** Multi-selects, by column key. */
  selections: Record<string, string[]>;
  /** Ranges being typed, by column key. */
  ranges: Record<string, DraftRange>;
  period: string;
  sortBy: string;
  descending: boolean;
  limit: number;
  offset: number;
}

export interface FilterColumn {
  key: string;
  label: string;
  kind: "text" | "multi" | "range";
  field: string;
  choices: string[];
  unit: string;
}

export const EMPTY: FilterState = {
  customer: "",
  selections: {},
  ranges: {},
  period: "",
  sortBy: "ews_score",
  descending: true,
  limit: 50,
  offset: 0,
};

function usable(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  // A lone "-" or "." is a keystroke on the way to a number, not a bound.
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** Whether a range the reader has typed says anything yet. */
export function rangeIsSet(range: DraftRange | undefined): boolean {
  if (!range) return false;
  return usable(range.min) !== null || usable(range.max) !== null;
}

/**
 * A range whose minimum is above its maximum matches nothing.
 *
 * Worth naming rather than sending: an empty table is indistinguishable from
 * a finding, and the reader who typed 900 into the wrong box has no way to
 * tell which they are looking at.
 */
export function rangeIsImpossible(range: DraftRange | undefined): boolean {
  if (!range) return false;
  const low = usable(range.min);
  const high = usable(range.max);
  return low !== null && high !== null && low > high;
}

export function problems(state: FilterState): string[] {
  const found: string[] = [];
  for (const [key, range] of Object.entries(state.ranges)) {
    if (rangeIsImpossible(range)) {
      found.push(
        `${key}: the minimum is above the maximum, so nothing can match.`,
      );
    }
  }
  return found;
}

/** Whether anything at all is narrowing the book. */
export function isNarrowed(state: FilterState): boolean {
  if (state.customer.trim() !== "") return true;
  if (Object.values(state.selections).some((v) => v.length > 0)) return true;
  return Object.values(state.ranges).some(rangeIsSet);
}

/** How many filters are active — what the "Clear all" button counts. */
export function activeCount(state: FilterState): number {
  let count = state.customer.trim() === "" ? 0 : 1;
  for (const chosen of Object.values(state.selections)) {
    if (chosen.length > 0) count += 1;
  }
  for (const range of Object.values(state.ranges)) {
    if (rangeIsSet(range)) count += 1;
  }
  return count;
}

/** The governed object the server is sent. Half-typed bounds are left out. */
export function toSpec(state: FilterState): Record<string, unknown> {
  const filters: Record<string, unknown> = {};
  if (state.customer.trim() !== "") filters.customer = state.customer.trim();
  for (const [key, chosen] of Object.entries(state.selections)) {
    if (chosen.length > 0) filters[key] = chosen;
  }
  for (const [key, range] of Object.entries(state.ranges)) {
    if (!rangeIsSet(range) || rangeIsImpossible(range)) continue;
    const bound: Record<string, number> = {};
    const low = usable(range.min);
    const high = usable(range.max);
    if (low !== null) bound.min = low;
    if (high !== null) bound.max = high;
    filters[key] = bound;
  }
  return {
    period: state.period,
    filters,
    sort_by: state.sortBy,
    descending: state.descending,
    limit: state.limit,
    offset: state.offset,
  };
}

/** Toggle one value of a multi-select. */
export function toggle(
  state: FilterState,
  key: string,
  value: string,
): FilterState {
  const chosen = state.selections[key] ?? [];
  const next = chosen.includes(value)
    ? chosen.filter((v) => v !== value)
    : [...chosen, value];
  const selections = { ...state.selections };
  if (next.length === 0) delete selections[key];
  else selections[key] = next;
  // Any change to what is being looked at returns to the first page. Keeping
  // the offset would answer a new question with page four of the old one.
  return { ...state, selections, offset: 0 };
}

export function setRange(
  state: FilterState,
  key: string,
  edge: "min" | "max",
  text: string,
): FilterState {
  const current = state.ranges[key] ?? { min: "", max: "" };
  const range = { ...current, [edge]: text };
  const ranges = { ...state.ranges };
  if (range.min.trim() === "" && range.max.trim() === "") delete ranges[key];
  else ranges[key] = range;
  return { ...state, ranges, offset: 0 };
}

export function setCustomer(state: FilterState, text: string): FilterState {
  return { ...state, customer: text, offset: 0 };
}

/** Clear one filter — what a chip's × does. */
export function clearOne(state: FilterState, key: string): FilterState {
  if (key === "customer") return { ...state, customer: "", offset: 0 };
  const selections = { ...state.selections };
  const ranges = { ...state.ranges };
  delete selections[key];
  delete ranges[key];
  return { ...state, selections, ranges, offset: 0 };
}

/**
 * Clear every filter, and nothing else.
 *
 * The month, the sort and the page size are not filters — they are how the
 * reader is looking, not what at. "Clear all" that also reset the as-of month
 * would move the reader to a different month without saying so.
 */
export function clearAll(state: FilterState): FilterState {
  return {
    ...state,
    customer: "",
    selections: {},
    ranges: {},
    offset: 0,
  };
}

/** Sorting by a column, with a second press reversing it. */
export function sortOn(state: FilterState, field: string): FilterState {
  if (state.sortBy === field) {
    return { ...state, descending: !state.descending, offset: 0 };
  }
  // A new column starts descending for a score and ascending for a name:
  // "the worst first" and "A first" are both what a reader means by one click.
  const numeric = !field.endsWith("_band") && field !== "customer_name" &&
    field !== "customer_id" && field !== "segment" &&
    field !== "dominant_driver";
  return { ...state, sortBy: field, descending: numeric, offset: 0 };
}

export function page(state: FilterState, offset: number): FilterState {
  return { ...state, offset: Math.max(0, offset) };
}

/** Whether two states would send the same request — what debouncing needs. */
export function sameRequest(a: FilterState, b: FilterState): boolean {
  return JSON.stringify(toSpec(a)) === JSON.stringify(toSpec(b));
}

/**
 * Read a state back out of the URL, so a filtered view can be shared and
 * walked back to. The keys are the column keys, which is what makes the
 * address readable: `?ews_band=HIGH,VERY_HIGH&dpd_min=30`.
 */
export function fromQuery(
  search: string,
  columns: FilterColumn[],
): FilterState {
  const query = new URLSearchParams(search);
  const state: FilterState = {
    ...EMPTY,
    selections: {},
    ranges: {},
    period: query.get("period") ?? "",
    // `q`, not `customer`. The Early Warning address already uses `customer`
    // for the OPENED borrower's id, and two meanings for one key would make
    // a shared link open a drilldown for a search term.
    customer: query.get("q") ?? "",
    sortBy: query.get("sort") ?? EMPTY.sortBy,
    descending: query.get("dir") !== "asc",
  };
  for (const column of columns) {
    if (column.kind === "multi") {
      const raw = query.get(column.key);
      if (raw) state.selections[column.key] = raw.split(",").filter(Boolean);
    } else if (column.kind === "range") {
      const min = query.get(`${column.key}_min`) ?? "";
      const max = query.get(`${column.key}_max`) ?? "";
      if (min || max) state.ranges[column.key] = { min, max };
    }
  }
  return state;
}

/** Write the state into a query string. The inverse of `fromQuery`. */
export function toQuery(state: FilterState): string {
  const query = new URLSearchParams();
  if (state.period) query.set("period", state.period);
  if (state.customer.trim()) query.set("q", state.customer.trim());
  for (const [key, chosen] of Object.entries(state.selections)) {
    if (chosen.length > 0) query.set(key, chosen.join(","));
  }
  for (const [key, range] of Object.entries(state.ranges)) {
    if (range.min.trim()) query.set(`${key}_min`, range.min.trim());
    if (range.max.trim()) query.set(`${key}_max`, range.max.trim());
  }
  if (state.sortBy !== EMPTY.sortBy) query.set("sort", state.sortBy);
  if (!state.descending) query.set("dir", "asc");
  return query.toString();
}
