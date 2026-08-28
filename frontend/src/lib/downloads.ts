/**
 * The parts of a download that are decisions rather than rendering.
 *
 * React-free on purpose, so the two rules that actually go wrong — which name
 * a saved file gets, and what a button says while it is working — can be
 * asserted directly rather than through a component.
 */

/** `attachment; filename="X.xlsx"; filename*=UTF-8''X.xlsx` */
const QUOTED = /filename="([^"]+)"/;
const EXTENDED = /filename\*=UTF-8''([^;]+)/i;

/**
 * The filename the server chose, from its Content-Disposition header.
 *
 * The server sanitised a name already — for Windows, for a question mark in a
 * question, for a slash in a period label. Deriving a second name here would
 * only create a chance for the two to disagree, so this reads the server's and
 * falls back only when there is nothing to read.
 *
 * The quoted form is preferred over the RFC 5987 `filename*` form because it
 * is the one already decoded; the extended form is percent-encoded and is used
 * only when no quoted name is present.
 */
export function filenameFrom(disposition: string | null, fallback: string): string {
  const header = disposition ?? "";
  const quoted = QUOTED.exec(header);
  if (quoted?.[1]) return quoted[1];

  const extended = EXTENDED.exec(header);
  if (extended?.[1]) {
    try {
      return decodeURIComponent(extended[1]);
    } catch {
      return extended[1];
    }
  }
  return fallback;
}

export type DownloadPhase = "idle" | "working" | "done" | "failed";

/**
 * What the button says, in each state.
 *
 * §45 asks for a spinner, a success and a failure. The label carries the state
 * in words as well as in the icon: a tick alone tells a screen reader nothing,
 * and tells a person glancing at a busy header only that something happened.
 */
export function captionFor(phase: DownloadPhase, label: string): string {
  if (phase === "working") return "Preparing workbook…";
  if (phase === "done") return "Workbook ready";
  return label;
}
