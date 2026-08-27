"use client";

import * as React from "react";

/**
 * "Which row is that?"
 *
 * §51 asks that an inline evidence token highlight the corresponding table or
 * chart element. The connection between a sentence and a row is the thing a
 * reader reconstructs by hand every time — the answer says Contracting rose
 * most, and they scan twenty-eight rows looking for Contracting.
 *
 * The link is by the token's LABEL, matched against the identity column of the
 * table. That is deliberately loose: it is a presentation aid, not a lineage
 * claim. When nothing matches, nothing highlights and no error is raised —
 * a token whose figure came from a values block rather than a row is still a
 * perfectly good token.
 *
 * Highlight state is per answer rather than global, so two answers in one
 * thread never highlight each other.
 */

interface Highlight {
  /** The identity currently pointed at, or null. */
  active: string | null;
  /** Point at one, or clear. */
  point: (label: string | null) => void;
}

const HighlightContext = React.createContext<Highlight>({
  active: null,
  point: () => {},
});

export function HighlightProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = React.useState<string | null>(null);
  const point = React.useCallback(
    (label: string | null) => setActive((current) => (current === label ? null : label)),
    [],
  );
  const value = React.useMemo(() => ({ active, point }), [active, point]);
  return (
    <HighlightContext.Provider value={value}>{children}</HighlightContext.Provider>
  );
}

export function useHighlight(): Highlight {
  return React.useContext(HighlightContext);
}

/**
 * Whether this row is the one being pointed at.
 *
 * Compared case-insensitively and trimmed, because the token's label comes
 * from a narrative sentence and the cell from a result row, and "Contracting "
 * and "contracting" are the same sector.
 */
export function isPointedAt(
  active: string | null,
  values: (string | number | null | undefined)[],
): boolean {
  if (!active) return false;
  const wanted = active.trim().toLowerCase();
  if (!wanted) return false;
  return values.some(
    (value) =>
      typeof value === "string" && value.trim().toLowerCase() === wanted,
  );
}
