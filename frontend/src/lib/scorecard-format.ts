/**
 * Rendering a fitted model coefficient.
 *
 * This is deliberately its own module rather than a helper inside the
 * Scorecard Validation page, and the reason is the decimal display contract.
 * A coefficient is not a business figure — it is part of the model's
 * specification, the number somebody re-types to reproduce the score. §52's
 * implementation replication is exactly the question of whether the
 * production system computes the same score from the same equation, and a
 * coefficient of 0.000412 written as 0.00 cannot answer it.
 *
 * So this file is on the allowlist in `scripts/check_decimals.py`. Keeping it
 * to one function means the exemption covers coefficients and nothing else:
 * every rate, amount and count on the validation screens stays under the
 * contract, and a future figure added to that page is checked as normal.
 */

/**
 * The coefficient as it appears inside a printed equation.
 *
 * Six decimals: score points are the coefficient times a Weight of Evidence
 * multiplied by the scaling factor, so the sixth decimal is worth roughly a
 * tenth of a point and two equations that differ there produce different
 * scores.
 */
export function equationCoefficient(value: number): string {
  return value.toFixed(6);
}

/**
 * The coefficient in a variable diagnostics table.
 *
 * Four decimals, matching the statistics it sits beside, because the column
 * is read for sign and relative magnitude rather than for re-computation.
 */
export function tableCoefficient(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(4);
}
