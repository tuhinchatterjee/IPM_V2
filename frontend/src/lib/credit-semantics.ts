/**
 * What a number MEANS for credit risk, as distinct from which way it points.
 *
 * The failure this exists to prevent
 * ----------------------------------
 * A green plus sign next to an ECL increase. Colouring a figure by the sign of
 * the arithmetic is the obvious thing to do and it is wrong roughly half the
 * time in a credit book: ECL up is bad, cure rate up is good, days past due
 * down is good, collateral shortfall up is bad. A credit officer reads colour
 * before they read the number, so a wrongly coloured figure tells them the
 * opposite of the truth in the register they trust most.
 *
 * Where the answer comes from
 * ---------------------------
 * The semantic ontology, which records `higher_is_worse` for every governed
 * concept. That reaches the frontend as `direction` on a metric or an evidence
 * item, and this module turns (direction, change) into a meaning.
 *
 * When nothing governed is available the answer is "neutral" and the figure is
 * not coloured at all. That is deliberate and it is the whole safety property:
 * an uncoloured figure asks the reader to think, a miscoloured one stops them.
 * There is no name-guessing fallback here for exactly that reason.
 *
 * Kept free of React so `node --test` can assert the table directly.
 */

/** Which way is bad for a measure. From the ontology, never from the number. */
export type Direction = "up-is-bad" | "up-is-good" | "neutral";

/** What a movement means for the book. */
export type Meaning = "adverse" | "favourable" | "neutral";

/**
 * What a change of this size, in this measure, means.
 *
 * A change of zero is neutral whatever the measure: nothing moved, and
 * "unchanged, adverse" is not a thing anybody says.
 */
export function meaningOf(
  change: number | null | undefined,
  direction: Direction | undefined,
): Meaning {
  if (change === null || change === undefined || !Number.isFinite(change)) {
    return "neutral";
  }
  if (change === 0 || !direction || direction === "neutral") return "neutral";
  const rising = change > 0;
  return direction === "up-is-bad"
    ? rising
      ? "adverse"
      : "favourable"
    : rising
      ? "favourable"
      : "adverse";
}

/** The word shown beside a token. Never colour alone — §10. */
export const MEANING_LABEL: Record<Meaning, string> = {
  adverse: "adverse",
  favourable: "favourable",
  neutral: "",
};

/**
 * The token's classes for each meaning.
 *
 * Theme tokens rather than literal colours, so the eight CreditProbe themes
 * each render this in their own palette and none of them has to know it exists.
 */
export const MEANING_CLASS: Record<Meaning, string> = {
  adverse: "border-negative/30 bg-negative/10 text-negative",
  favourable: "border-positive/30 bg-positive/10 text-positive",
  neutral: "border-border bg-surface-sunken text-text-secondary",
};

/**
 * A long-form description for assistive technology.
 *
 * §10: "Never rely on color alone." A screen reader gets the sentence a
 * sighted reader gets from the colour, the icon and the label together.
 */
export function describeMeaning(
  label: string,
  display: string,
  meaning: Meaning,
): string {
  if (meaning === "neutral") return `${label} ${display}`;
  return `${label} ${display} — ${MEANING_LABEL[meaning]} for credit risk`;
}
