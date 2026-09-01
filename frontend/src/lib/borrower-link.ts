/**
 * The Early Warning → Borrower 360 deep link. R2 §4.
 *
 * The acceptance run found that opening a borrower from an Early Warning row
 * dropped everything the reader had already established. Borrower 360 opened
 * on its landing table, at whatever the latest quarter happened to be, and the
 * officer had to type the name they had just clicked on — after which they
 * were looking at a different period from the one the signal fired in.
 *
 * So the link carries both facts, and this module is the single place that
 * knows their names. Two surfaces agreeing on a URL by coincidence is how a
 * deep link quietly stops working.
 *
 * Period spelling
 * ---------------
 * The book stores a period as `Q2 2026`. A URL with a space in it is a URL
 * people mangle, so the link writes `Q2-2026` and the reader turns it back.
 * Both spellings are accepted on the way in: a link someone typed, pasted or
 * kept from an older build should still land on the right quarter.
 */

/** The borrower identifier, named as the mandate names it. */
export const BORROWER_PARAM = "customer_id";
/** Its earlier spelling, still honoured so old links keep working. */
export const LEGACY_BORROWER_PARAM = "borrower";
export const PERIOD_PARAM = "period";

/** A minimal view of URLSearchParams, so a plain object can be tested. */
export type Params = { get(name: string): string | null };

/** `Q2-2026` and `Q2 2026` are the same quarter. */
export function normalisePeriod(raw: string | null | undefined): string {
  const text = (raw ?? "").trim();
  if (!text) return "";
  const quarter = /^(Q[1-4])[\s_-]?(\d{4})$/i.exec(text);
  if (quarter) return `${quarter[1].toUpperCase()} ${quarter[2]}`;
  const reversed = /^(\d{4})[\s_-]?(Q[1-4])$/i.exec(text);
  if (reversed) return `${reversed[2].toUpperCase()} ${reversed[1]}`;
  return text;
}

/** The URL spelling: no spaces to be mangled in transit. */
export function periodForUrl(period: string | null | undefined): string {
  return normalisePeriod(period).replace(/\s+/g, "-");
}

/**
 * Where an Early Warning row points. The period is omitted rather than sent
 * empty: `?period=` would ask Borrower 360 for a quarter called nothing.
 */
export function borrower360Href(
  customerId: string,
  period?: string | null,
): string {
  const id = (customerId ?? "").trim();
  if (!id) return "/borrower-360";
  const query = new URLSearchParams({ [BORROWER_PARAM]: id });
  const when = periodForUrl(period);
  if (when) query.set(PERIOD_PARAM, when);
  return `/borrower-360?${query.toString()}`;
}

/** The borrower the link names, or "" for a plain visit to the landing table. */
export function borrowerFrom(params: Params | null | undefined): string {
  if (!params) return "";
  const named = params.get(BORROWER_PARAM) ?? params.get(LEGACY_BORROWER_PARAM);
  return (named ?? "").trim();
}

/** The quarter the link names, in the book's own spelling. */
export function periodFrom(params: Params | null | undefined): string {
  if (!params) return "";
  return normalisePeriod(params.get(PERIOD_PARAM));
}
