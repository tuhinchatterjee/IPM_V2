/**
 * The pure parts of the feedback surfaces. §7, §16, §25, §31.
 *
 * Extracted so they can be tested without a browser. Everything here is a
 * decision about what a user sees, and every one of them has a wrong version
 * that looks fine until somebody reads the screen carefully.
 */

/** §7's ratings that open the structured detail panel. */
export const WANTS_DETAIL = ["PARTLY", "NO"] as const;

/**
 * Whether a rating opens the detail panel.
 *
 * The list comes from the backend at runtime; this is the fallback for a
 * prompt fetched before the server answered, and it agrees with the server
 * because both are the same two ratings. A YES that opened a "what went
 * wrong" panel would be asking somebody to justify agreeing.
 */
export function opensDetail(rating: string, from?: readonly string[]): boolean {
  const list = from && from.length > 0 ? from : WANTS_DETAIL;
  return list.includes(rating);
}

/**
 * Whether the acknowledgement is safe to show. §25.
 *
 * The text comes from the backend, where a test asserts it. This is the
 * second line of defence, in the place a promise would actually be read: a
 * string that claims the product has learned something is not rendered at
 * all, and the neutral fallback is shown instead.
 */
const PROMISES = [
  "has learned",
  "have learned",
  "learned this",
  "will remember",
  "now knows",
  "retrained",
  "updated the model",
];

export const NEUTRAL_ACKNOWLEDGEMENT = "Thank you. Recorded.";

export function safeAcknowledgement(said: string): string {
  const lowered = String(said ?? "").toLowerCase();
  return PROMISES.some((promise) => lowered.includes(promise))
    ? NEUTRAL_ACKNOWLEDGEMENT
    : String(said ?? "");
}

/**
 * One row of the learning area, as the few fields worth scanning.
 *
 * Rendering the whole object would be honest and unreadable; picking fields
 * by name and falling back to the whole object keeps a row legible without
 * hiding one whose shape this screen has not been taught. The fallback is the
 * part that matters: a silent empty row is how a new object type becomes
 * invisible.
 */
const SCANNED = [
  "rating",
  "status",
  "label",
  "question",
  "failure_class",
  "release_id",
  "task",
  "explanation",
  "categories",
  "reviewer",
  "created_at",
  "at",
] as const;

export function summarise(row: Record<string, unknown>): string {
  const found = SCANNED.filter(
    (key) => row[key] !== undefined && row[key] !== "",
  ).map((key) => `${key}: ${JSON.stringify(row[key])}`);
  return found.length > 0 ? found.join("\n") : JSON.stringify(row, null, 2);
}

/**
 * How a count that was never measured is shown. §27.
 *
 * "not measured", never 0. A metric reported as zero is a claim that it was
 * measured and came out at nothing, which is the opposite of what None means.
 */
export function figure(value: number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined) return "not measured";
  return `${value}${suffix}`;
}
