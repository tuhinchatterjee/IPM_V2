/**
 * How a metric is allowed to read on screen.
 *
 * Separated from the components so it can be tested directly, and because two
 * things here can be got wrong by presentation alone with the backend
 * perfectly correct: a number formatted as if it were something else, and a
 * period rule shown as the raw token nobody outside this codebase can parse.
 */

// A relative path rather than the "@/" alias: this module is imported
// directly by `node --test`, which strips types but does not resolve the
// alias for a value import. One formatter, reachable from both.
import { count, money, percent } from "../../lib/format.ts";

/**
 * A metric's own unit and decimals decide how it reads.
 *
 * Deliberately narrow: these units are the ones `backend/metrics/formula.py`
 * declares, and anything outside them falls back rather than guessing.
 *
 * A missing value is a dash, never a zero. "0.00%" and "we could not compute
 * this" are different statements, and a dashboard that renders the second as
 * the first is a dashboard that lies quietly.
 */
export function formatMetric(
  value: number | null | undefined,
  unit?: string,
  decimals?: number,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const places = decimals ?? 2;
  switch (unit) {
    case "percent":
      return percent(value, places);
    case "currency":
      return money(value, Math.abs(value) >= 1000 ? 0 : places);
    case "count":
      return count(value);
    case "days":
      return `${count(value)} days`;
    case "ratio":
    case "index":
    case "score":
      return value.toFixed(places);
    default:
      return Number.isInteger(value) ? count(value) : value.toFixed(places);
  }
}

/**
 * The period rule, in words.
 *
 * "latest_matured" is the one a reader would otherwise get wrong: it is not
 * the latest month. A scorecard's Gini for last month does not exist, because
 * none of those accounts has had time to default.
 */
export function readablePeriodRule(rule: string): string {
  switch (rule) {
    case "latest_available":
      return "The most recent period the data holds";
    case "latest_matured":
      return "The most recent period whose performance window has closed";
    case "rolling_window":
      return "A rolling window";
    default:
      return "Whichever period is selected";
  }
}
