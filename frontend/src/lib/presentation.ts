/**
 * How one analysis is presented, remembered per analysis.
 *
 * §47: "Persist presentation preference per analysis/thread where
 * appropriate." Where appropriate is doing real work in that sentence. A
 * reader who switched a twenty-five-row breakdown to a table did so because
 * THAT result reads better as a table, not because they prefer tables — so the
 * preference is keyed to the run, and the next question they ask starts from
 * the registry's judgement again.
 *
 * It lives in the browser rather than on the server on purpose. This is how
 * one person likes to read one answer on one machine; sending it to the
 * backend would make it a property of the analysis, so a colleague opening the
 * same run would find it in a form somebody else chose.
 *
 * Every read and every write is wrapped: a private window, cleared site data
 * or a browser configured to block storage must produce the registry's default
 * and no error, because a chart that fails to draw is a worse outcome than a
 * preference that is not remembered.
 */

/** What can be remembered about how one result is shown. */
export interface Presentation {
  /** Chart or table, where the reader has overridden the registry. */
  showing?: "chart" | "table";
  /** The chart form, where the reader chose one of the alternatives. */
  kind?: string;
}

const PREFIX = "creditprobe.presentation.";
const CHANGED = "creditprobe:presentation";

/** Analyses whose presentation is remembered, so the store cannot grow forever. */
const KEEP = 60;
const INDEX_KEY = "creditprobe.presentation.index";

function key(runId: number | string): string {
  return `${PREFIX}${runId}`;
}

export function readPresentation(runId: number | string): Presentation {
  try {
    const raw = window.localStorage.getItem(key(runId));
    if (!raw) return {};
    const found = JSON.parse(raw) as Presentation;
    return typeof found === "object" && found !== null ? found : {};
  } catch {
    return {};
  }
}

/**
 * Remember how this analysis is being read.
 *
 * Merged rather than replaced, so choosing a chart form does not forget that
 * the reader had switched to a table and back.
 */
export function writePresentation(
  runId: number | string,
  change: Presentation,
): void {
  try {
    const merged = { ...readPresentation(runId), ...change };
    window.localStorage.setItem(key(runId), JSON.stringify(merged));
    remember(String(runId));
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    // Site data is blocked. The choice still applies to this page; it simply
    // will not be there tomorrow, which is the right way for this to fail.
  }
}

export function forgetPresentation(runId: number | string): void {
  try {
    window.localStorage.removeItem(key(runId));
    window.dispatchEvent(new Event(CHANGED));
  } catch {
    /* nothing to forget */
  }
}

/**
 * Keep the most recent runs and drop the rest.
 *
 * Without this, a year of reading leaves a thousand dead keys in local storage
 * for analyses nobody will open again — small, but it is somebody's browser.
 */
function remember(runId: string): void {
  try {
    const raw = window.localStorage.getItem(INDEX_KEY);
    const seen: string[] = raw ? (JSON.parse(raw) as string[]) : [];
    const next = [runId, ...seen.filter((id) => id !== runId)];
    for (const stale of next.slice(KEEP)) {
      window.localStorage.removeItem(key(stale));
    }
    window.localStorage.setItem(INDEX_KEY, JSON.stringify(next.slice(0, KEEP)));
  } catch {
    /* the index is a convenience, never a requirement */
  }
}

export function subscribePresentation(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * Which of chart and table to show, given the registry and the reader.
 *
 * Pure, so the precedence — reader over registry, registry over nothing — can
 * be asserted without a browser. The registry's judgement is a default and
 * never a lock; a reader who asked for the figures gets the figures.
 */
export function showingFor(
  registryDefault: "chart" | "table",
  remembered: Presentation,
): "chart" | "table" {
  return remembered.showing ?? registryDefault;
}
