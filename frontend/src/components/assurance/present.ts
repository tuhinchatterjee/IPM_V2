import type { AssuranceReview, DimensionCell, ReviewRow } from "@/lib/api";

/**
 * The presentation decisions the assurance surfaces make, as functions.
 * Part F, §184, §187, §211.
 *
 * Why these are not inline in the components
 * -------------------------------------------
 * Because they are the rules, and the rules are the thing worth testing. A
 * component test would prove that a `<span>` rendered; these functions decide
 * whether a reader is told "this passed" or "we did not check", whether a
 * number is called accuracy, and whether a stale record presents as current.
 * Each of those is a §212 impossibility, and each is one line of code away
 * from being wrong on a screen somebody builds later.
 *
 * The rule running through all of them: an absent value is never rendered as
 * a good one. A null score is not zero, an unmeasured dimension is not a
 * pass, and a stale record is not current.
 */

/** How a dimension cell should read. §187's compact indicator. */
export function cellWord(cell: DimensionCell): string {
  switch (cell.state) {
    case "PASSED":
      return "passed";
    case "WARNING":
      return "warning";
    case "FAILED":
      return "failed";
    default:
      // §183, in one word. "Not measured" and "passed" must never be
      // rendered the same way, however tempting a neutral tick is.
      return "not measured";
  }
}

/**
 * What a reader sees where the score is.
 *
 * §184: the label comes from the payload, never from a literal here, so the
 * backend's constant is the only definition of what this number is called.
 * And where there is no number, the STATUS is shown in words rather than a
 * zero — a zero reads as a very bad score rather than as no score at all.
 */
export function scoreText(
  score: number | null,
  label: string,
  status: string,
): string {
  if (score === null) return status.replaceAll("_", " ").toLowerCase();
  // Trimmed so a caller whose surrounding label already names the figure can
  // pass an empty one without leaving a dangling space.
  return `${score.toFixed(0)} / 100 ${label.toLowerCase()}`.trim();
}

/**
 * What the reference-match line says.
 *
 * Where no approved reference exists this returns the payload's explanation
 * rather than an empty string: a blank invites the reader to conclude the
 * comparison was made and came back empty.
 */
export function referenceText(review: AssuranceReview): string {
  const reference = review.header.reference_match;
  if (!reference.available) return reference.why;
  return `${reference.value_pct}% against ${reference.source}`;
}

/**
 * The status a row should DISPLAY, as opposed to the one it recorded.
 *
 * §212's last impossibility: a record pinned to a superseded build may not
 * present as current validation. The stored status stays what it was; this
 * is what a reader should act on today.
 */
export function displayStatus(row: ReviewRow): string {
  return row.stale_reasons.length ? "STALE" : row.overall_status;
}

/** Whether a row needs somebody to look at it. §187's "open review". */
export function needsAttention(row: ReviewRow): boolean {
  return (
    row.critical_failures > 0 ||
    row.overall_status === "NEEDS_REVIEW" ||
    row.bad_feedback > 0
  );
}

/**
 * Order for the review list: the rows that need attention first, then newest.
 *
 * Deliberately not by score. Sorting by score puts the unscored records —
 * the ones the gates refused to vouch for — at whichever end the null sorts
 * to, which is exactly the wrong place either way.
 */
export function reviewOrder(rows: ReviewRow[]): ReviewRow[] {
  const rank = (row: ReviewRow): number => {
    if (row.critical_failures > 0) return 0;
    if (row.overall_status === "NEEDS_REVIEW") return 1;
    if (row.bad_feedback > 0) return 2;
    if (row.stale_reasons.length) return 3;
    return 4;
  };
  return [...rows].sort((a, b) => {
    const byRank = rank(a) - rank(b);
    return byRank !== 0 ? byRank : b.at.localeCompare(a.at);
  });
}
