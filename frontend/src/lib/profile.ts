/**
 * Which product this installation serves.
 *
 * The conversion to Saudi retail is a profile, not a fork: the corporate
 * screens remain in the source so the other book can be restored, and this is
 * what decides which of them the product actually serves.
 *
 * Read from the environment the launcher exports, defaulting to retail because
 * that is what this installation IS — a missing variable must not quietly serve
 * a corporate screen whose datasets were retired, which renders as an empty
 * period list and a row of journeys that cannot run.
 */

export const RETAIL = "retail";

export function productProfile(): string {
  const configured = process.env.NEXT_PUBLIC_PRODUCT_PROFILE;
  return (configured ?? RETAIL).trim().toLowerCase() || RETAIL;
}

export function isRetail(): boolean {
  return productProfile() === RETAIL;
}
