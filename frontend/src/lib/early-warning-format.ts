/**
 * How an Early Warning value is written down. R2 §3.
 *
 * The acceptance run found the borrower detail showing
 *
 *     Value 75.4    Previously 71.2    Threshold 10
 *
 * which is four numbers and no information. 75.4 what — millions of riyals,
 * per cent, days, a multiple? The signal taxonomy now says which, per signal,
 * and this is the one place that turns that answer into words.
 *
 * Money is SAR
 * ------------
 * The book is kept in millions of Saudi riyals. A monetary figure is never
 * shown bare: `SAR 75.4m`, and `SAR 1.2bn` once the millions stop being
 * readable. The currency comes from the observation rather than from here, so
 * a deployment kept in another currency says so rather than lying in riyals.
 *
 * Ratios stay ratios
 * ------------------
 * A covenant written as "minimum DSCR 1.25x" is not "minimum DSCR 125%".
 * Rendering a multiple as a percentage misstates the test the borrower is
 * actually held to, which is the kind of error that ends up in a credit paper.
 */

export const MONEY = "money";
export const PERCENT = "percent";
export const RATIO = "ratio";
export const DAYS = "days";
export const NOTCHES = "notches";
export const STAGE = "stage";
export const FLAG = "flag";
export const COUNT = "count";
/** A model output on its own scale. Not a percentage, not an amount. */
export const SCORE = "score";
/**
 * A fraction of one, NOT already multiplied by a hundred. Distinct from
 * PERCENT because the modelled contagion figures sit around 0.00002, and
 * treating one as the other misstates it by two orders of magnitude.
 */
export const SHARE = "share";
/** A number of named counterparties. */
export const ENTITIES = "entities";
/** A label from a controlled vocabulary — a rating grade, an outlook. */
export const CATEGORY = "category";

/** Nothing to show. Never "0", which is a value. */
export const NOTHING = "—";

const DEFAULT_CURRENCY = "SAR";

function fixed(value: number, decimals: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Money, in the millions the book is kept in.
 *
 * `SAR 75.4m` up to a billion, `SAR 1.2bn` above it. One decimal: a facility
 * at 321.8 rounded to 322 has lost the precision the reader is checking it
 * for, and the line is no longer for keeping it.
 */
export function money(
  millions: number,
  currency: string = DEFAULT_CURRENCY,
): string {
  const abs = Math.abs(millions);
  if (abs >= 1000) return `${currency} ${fixed(millions / 1000, 1)}bn`;
  if (abs > 0 && abs < 0.1) return `${currency} ${fixed(millions, 2)}m`;
  return `${currency} ${fixed(millions, 1)}m`;
}

function plural(count: number, one: string, many: string): string {
  return Math.abs(count) === 1 ? `${count} ${one}` : `${count} ${many}`;
}

/**
 * One Early Warning value, written the way a credit officer would say it.
 *
 * `unit` comes from the signal taxonomy; `currency` from the same observation.
 * An unrecognised unit falls back to a plain number rather than guessing — a
 * currency invented for a value that is not money is worse than no unit.
 */
export function showValue(
  value: unknown,
  unit?: string | null,
  currency: string = DEFAULT_CURRENCY,
): string {
  if (value === null || value === undefined || value === "") return NOTHING;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (unit === FLAG) {
    if (typeof value === "string") {
      const said = value.trim().toLowerCase();
      if (said === "true") return "Yes";
      if (said === "false") return "No";
    }
    return String(value);
  }
  if (unit === CATEGORY) {
    // A rating grade is a label. Coercing "AA" to a number gives NaN, and
    // coercing a numeric-looking grade would put a decimal place on it.
    const said = String(value).trim();
    return said || NOTHING;
  }
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return String(value);

  switch (unit) {
    case MONEY:
      return money(number, currency);
    case PERCENT:
      return `${fixed(number, 1)}%`;
    case RATIO:
      return `${fixed(number, 2)}x`;
    case DAYS:
      return plural(Math.round(number), "day", "days");
    case NOTCHES:
      return plural(Math.round(number), "notch", "notches");
    case STAGE:
      return `Stage ${Math.round(number)}`;
    case SCORE:
      return fixed(number, 1);
    case SHARE:
      // Three significant figures rather than two decimals: a share of
      // 0.00002 shown to two decimals is "0", which reads as nothing there.
      return number === 0
        ? "0"
        : number.toLocaleString("en-US", { maximumSignificantDigits: 3 });
    case ENTITIES:
      return plural(Math.round(number), "entity", "entities");
    default:
      return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
}

/**
 * A movement, always signed, so a fall is never read as a level.
 *
 * A movement in money is still money; a movement in a percentage is expressed
 * in POINTS, because "utilisation rose 8%" and "utilisation rose 8 points"
 * are different claims and only one of them is what the signal measured.
 */
export function showMovement(
  movement: unknown,
  unit?: string | null,
  currency: string = DEFAULT_CURRENCY,
): string {
  if (movement === null || movement === undefined || movement === "") {
    return NOTHING;
  }
  const number = typeof movement === "number" ? movement : Number(movement);
  if (!Number.isFinite(number)) return NOTHING;
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  const size = Math.abs(number);
  switch (unit) {
    case MONEY:
      return `${sign}${money(size, currency)}`;
    case PERCENT:
      return `${sign}${fixed(size, 1)} points`;
    case RATIO:
      return `${sign}${fixed(size, 2)}x`;
    case DAYS:
      return `${sign}${plural(Math.round(size), "day", "days")}`;
    case NOTCHES:
      return `${sign}${plural(Math.round(size), "notch", "notches")}`;
    case FLAG:
    case STAGE:
      return NOTHING;
    default:
      return `${sign}${size.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  }
}
