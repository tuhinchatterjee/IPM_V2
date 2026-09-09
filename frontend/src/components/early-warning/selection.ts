/**
 * What the Early Warning screen is currently looking at, kept in the URL.
 *
 * The selection is the whole navigation model of this screen: a band, a
 * segment, a grouping and an obligor, each narrowing the last. Keeping it in
 * the query string is what makes a link shareable and Back meaningful, and
 * both of those are worth more than a tidier component.
 *
 * The rules that are easy to get wrong, and are tested here rather than
 * discovered in the browser:
 *
 *  - An empty selection writes no key at all, so the bare URL is clean.
 *  - A selection that changes nothing must not create a history entry, or
 *    Back has to be pressed twice to undo one click.
 *  - Clearing a selection is a step like any other, so it IS pushed: a
 *    reader who closes a borrower and wants it back presses Back.
 */

export const SELECTION_KEYS = ["band", "segment", "customer", "level"] as const;

export type SelectionKey = (typeof SELECTION_KEYS)[number];
export type Selection = Record<SelectionKey, string | null>;

export const EMPTY: Selection = {
  band: null, segment: null, customer: null, level: null,
};

/** The selection a query string describes. */
export function read(search: string): Selection {
  const params = new URLSearchParams(search);
  return {
    band: params.get("band"),
    segment: params.get("segment"),
    customer: params.get("customer"),
    level: params.get("level"),
  };
}

/** The query string a selection writes, keys omitted rather than blank. */
export function write(selection: Selection): string {
  const params = new URLSearchParams();
  SELECTION_KEYS.forEach((key) => {
    if (selection[key]) params.set(key, selection[key]!);
  });
  return params.toString();
}

/** The selection after one change. */
export function merge(current: Selection, next: Partial<Selection>): Selection {
  return { ...current, ...next };
}

/**
 * Whether this change is a step a reader could want back.
 *
 * Re-clicking the selected band deselects it, which IS a step. Clicking a
 * band that is already selected to the same value is not, and pushing it
 * would make Back a no-op the first time it is pressed.
 */
export function isAStep(current: Selection, next: Selection): boolean {
  return write(current) !== write(next);
}
