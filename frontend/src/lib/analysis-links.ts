/**
 * Three different things are called "an analysis", and only one of them has a
 * page in the Analysis Library.
 *
 * The failure this fixes
 * ----------------------
 * Clicking the analysis under a composed answer navigated to
 *
 *     Analysis Library / dynamic_analysis
 *
 * which reported: "'dynamic_analysis' is not a registered CreditProbe
 * analysis." It is not, and it never was. `dynamic_analysis` is the marker the
 * runtime puts on a plan it composed for one question — there is no library
 * entry to open, because the thing did not exist until somebody asked.
 *
 * The three things
 * ----------------
 * **An Analysis Run** is a computation that happened. It has a run id, a
 * result and a Trace, and that is what a reader wants when they click a
 * composed answer: how was THIS produced.
 *
 * **An Analysis Studio Method** is a registered, reusable methodology with a
 * definition, a version and validation behind it. It has a library page.
 * Only a real method id may link to one.
 *
 * **A Saved Analysis** is a run somebody kept, in Work → Analyses. It points at
 * whichever of the other two it came from.
 */

/** Ids the runtime uses for things that are not registered methods. */
const NOT_A_METHOD = new Set(["dynamic_analysis", "", "metadata"]);

/** Certifications that mean no method definition exists to open. */
const NO_DEFINITION = new Set(["dynamic", "metadata"]);

/**
 * Whether this analysis has a definition in the library to open.
 *
 * Both tests matter. The id catches a composed plan whatever it claims about
 * its certification, and the certification catches a registered-looking id on
 * something that was never registered.
 */
export function isRegisteredMethod(
  analysisId?: string | null,
  certification?: string | null,
): boolean {
  const id = (analysisId ?? "").trim();
  if (!id || NOT_A_METHOD.has(id)) return false;
  if (id.startsWith("capability_")) return false;
  return !NO_DEFINITION.has((certification ?? "").trim());
}

/**
 * Where the method definition lives, or null when there is no definition.
 *
 * Returning null rather than a best guess is the whole point: a link that
 * lands on "not a registered analysis" is worse than no link, because the
 * reader concludes something is broken rather than that there is nothing
 * there.
 */
export function methodHref(
  analysisId?: string | null,
  certification?: string | null,
): string | null {
  return isRegisteredMethod(analysisId, certification)
    ? `/engine-builder/${analysisId}`
    : null;
}

/** Where the run that produced these figures can be inspected. */
export function runHref(runId?: number | null): string | null {
  return runId ? `/trace/${runId}` : null;
}

/**
 * The one link that is always right for a step.
 *
 * The method where there is one, the run that produced it otherwise. A
 * composed analysis has no definition and always has a Trace, so a reader
 * never reaches a dead end.
 */
export function stepHref(
  analysisId?: string | null,
  certification?: string | null,
  runId?: number | null,
): string | null {
  return methodHref(analysisId, certification) ?? runHref(runId);
}
