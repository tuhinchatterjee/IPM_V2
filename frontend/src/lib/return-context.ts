/**
 * Where "Back" goes, as a contract rather than a guess.
 *
 * The problem
 * -----------
 * CreditProbe has thirty-four screens and almost all of them are reachable
 * from more than one place. A Trace can be opened from the Cockpit, from a
 * message inside an Investigation, from a Lens tile, from a saved Analysis and
 * from a Playbook run. A dataset can be opened from Data Builder, from a
 * relationship map and from a Trace node. A "Back to Trace & Lineage" button on
 * the Trace page is therefore wrong five times out of six, and the browser's
 * own Back is the only honest control on the screen — which is a way of saying
 * the product has no navigation model at all.
 *
 * The contract
 * ------------
 * A link that leaves one screen for another carries WHERE IT CAME FROM. The
 * destination reads it and renders a Back control that names the place it will
 * return you to.
 *
 * Two query parameters do the carrying — `returnTo` and `returnLabel` — and a
 * third, `returnType`, records what kind of thing the source was so a
 * destination can adapt its wording and a broken source can be recognised
 * rather than followed into a 404. They survive a refresh and a shared link,
 * which `history.state` would not.
 *
 * `returnTo` is a complete in-product URL, so everything §6 asks to be
 * preserved travels inside it and needs no parameter of its own:
 *
 *     scroll anchor            /investigations/12#turn-3
 *     selected tab             /projects/4?tab=investigations
 *     selected visualization   /analysis/91?view=chart
 *     selected trace mode      /trace/57?mode=lineage&node=join_1
 *     period                   /data-builder/dataset/ecl_facility?period=2025Q2
 *
 * The builders below are the only sanctioned way to construct one. A call site
 * that hand-rolls the string gets the anchor wrong once and nobody notices for
 * a release, so there are no hand-rolled ones: every source in the product has
 * a named function here, and each of them is unit-tested.
 */

import { isInternalPath, withReturnTo, type ReturnTo } from "./links.ts";

export type { ReturnTo } from "./links.ts";
export { isInternalPath, withReturnTo } from "./links.ts";

/**
 * What kind of thing the reader came from.
 *
 * Carried so a destination can say "Back to this investigation" rather than
 * "Back", and so a Back control whose target no longer exists can fall back to
 * that type's index instead of to the browser's history.
 */
export type SourceType =
  | "cockpit"
  | "investigation"
  | "project"
  | "analysis"
  | "lens"
  | "borrower"
  | "dataset"
  | "trace"
  | "playbook"
  | "workflow"
  | "studio"
  | "unknown";

/** Full return context: where, what it says, and what kind of thing it is. */
export interface ReturnContext extends ReturnTo {
  type: SourceType;
}

/** The index each source type falls back to when the exact source is gone. */
export const INDEX_OF: Record<SourceType, ReturnTo> = {
  cockpit: { href: "/", label: "Cockpit" },
  investigation: { href: "/investigations", label: "Investigations" },
  project: { href: "/projects", label: "Projects" },
  analysis: { href: "/analyses", label: "Analyses" },
  lens: { href: "/lenses", label: "Lenses" },
  borrower: { href: "/early-warning", label: "Early Warning" },
  dataset: { href: "/data-builder/browse", label: "Data Builder" },
  trace: { href: "/trace", label: "Trace & Lineage" },
  playbook: { href: "/playbooks", label: "Playbooks" },
  workflow: { href: "/reviews", label: "My reviews" },
  studio: { href: "/studio", label: "Analysis Studio" },
  unknown: { href: "/", label: "Back" },
};

const TYPES = new Set<string>(Object.keys(INDEX_OF));

/** Whether a `returnType` that arrived in a query string is one we know. */
export function asSourceType(value: string | null | undefined): SourceType {
  return value && TYPES.has(value) ? (value as SourceType) : "unknown";
}

/**
 * Attach a full return context to a link.
 *
 * `withReturnTo` carries the href and the label; this adds the source type,
 * which is what lets a destination recover when the source has been deleted
 * between the click and the Back.
 */
export function linkBack(href: string, from: ReturnContext): string {
  const carried = withReturnTo(href, from.href, from.label);
  return `${carried}&returnType=${encodeURIComponent(from.type)}`;
}

/* ------------------------------------------------------------ the sources */

/** The scroll anchor of one turn inside an Investigation thread. */
export function turnAnchor(sequence: number): string {
  return `turn-${sequence}`;
}

/**
 * A message inside an Investigation.
 *
 * The anchor is the whole point. §5 asks for "Back to exact
 * Investigation/message/analysis anchor", and a Back that lands on the top of a
 * fourteen-turn thread has technically returned you to the right screen and
 * practically lost your place.
 */
export function fromInvestigation(
  id: number,
  title: string,
  sequence?: number | null,
): ReturnContext {
  const anchor =
    sequence === null || sequence === undefined ? "" : `#${turnAnchor(sequence)}`;
  return {
    href: `/investigations/${id}${anchor}`,
    label: title || "this investigation",
    type: "investigation",
  };
}

/** A Project, optionally on the tab the reader had open. */
export function fromProject(
  id: number,
  name: string,
  tab?: string | null,
): ReturnContext {
  const query = tab ? `?tab=${encodeURIComponent(tab)}` : "";
  return {
    href: `/projects/${id}${query}`,
    label: name || "this project",
    type: "project",
  };
}

/** The anchor of one saved Analysis in the Analyses list. */
export function analysisAnchor(id: number): string {
  return `analysis-${id}`;
}

/**
 * A saved Analysis.
 *
 * There is deliberately no per-saved-analysis page: a saved analysis IS a run,
 * and the thing to open is its Trace or the investigation it came from. So
 * "Back to Saved Analysis" means the Analyses list, landed on that row — which
 * is where the reader was standing when they clicked.
 */
export function fromSavedAnalysis(id: number, title: string): ReturnContext {
  return {
    href: `/analyses#${analysisAnchor(id)}`,
    label: title || "this analysis",
    type: "analysis",
  };
}

/** A Lens. `cro` is the built-in executive one and has its own route. */
export function fromLens(lensId: string, name: string): ReturnContext {
  const href = lensId === "cro" ? "/lenses/cro" : `/lenses/${encodeURIComponent(lensId)}`;
  return { href, label: name || "this lens", type: "lens" };
}

/** The anchor of one scored facility row on the Early Warning screen. */
export function facilityAnchor(accountId: string): string {
  return `facility-${accountId}`;
}

/**
 * A borrower on the Early Warning screen, by the facility being read.
 *
 * Early Warning has no per-borrower page: a borrower is an expanded row in a
 * list of a hundred, and which one is open is the only thing that distinguishes
 * two visits to the same URL. So the return href carries both the selection and
 * the anchor — "Back to Al Rajhi Contracting" has to reopen THAT row and land
 * on it, or it has returned the reader to a screen and lost their place on it.
 */
export function fromBorrower(
  accountId: string,
  name: string,
): ReturnContext {
  return {
    href:
      `/early-warning?facility=${encodeURIComponent(accountId)}` +
      `#${facilityAnchor(accountId)}`,
    label: name || accountId || "this borrower",
    type: "borrower",
  };
}

/**
 * A dataset in Data Builder, at the period that was being read.
 *
 * §5: "Data Builder → Dataset → Relationship → Back to exact Dataset/period".
 * The period is the reason this is not just a path — a relationship map opened
 * from Q2 2025 that returns you to the default period has silently moved the
 * reader a quarter without telling them.
 */
export function fromDataset(
  name: string,
  period?: string | null,
): ReturnContext {
  const query = period ? `?period=${encodeURIComponent(period)}` : "";
  return {
    href: `/data-builder/dataset/${encodeURIComponent(name)}${query}`,
    label: name,
    type: "dataset",
  };
}

/**
 * One node on one Trace, in the mode it was being viewed in.
 *
 * §5: "Trace → Open Dataset in Data Builder → Back to same Trace node".
 * Returning to the Trace with nothing selected, in the default mode, after the
 * reader had drilled into a join in Lineage view, is the failure this prevents.
 */
export function fromTraceNode(
  runId: number,
  mode?: string | null,
  nodeId?: string | null,
): ReturnContext {
  const params = new URLSearchParams();
  if (mode) params.set("mode", mode);
  if (nodeId) params.set("node", nodeId);
  const query = params.toString();
  return {
    href: `/trace/${runId}${query ? `?${query}` : ""}`,
    label: "this trace",
    type: "trace",
  };
}

/** The Cockpit, where a global investigation starts. */
export function fromCockpit(): ReturnContext {
  return { href: "/", label: "Cockpit", type: "cockpit" };
}

/** A playbook run. */
export function fromPlaybook(): ReturnContext {
  return { href: "/playbooks", label: "Playbooks", type: "playbook" };
}

/**
 * A return context read back out of a URL's query parameters.
 *
 * Only same-origin relative paths are honoured: a `returnTo` arrives in a query
 * string, so trusting it would let any link anywhere turn a Back button into an
 * off-site redirect. Anything that fails the test falls back to the caller's
 * own default, which is why a screen opened directly still has a sensible Back
 * rather than a dead one.
 */
export function readReturn(
  href: string | null,
  label: string | null,
  type: string | null,
  fallback: ReturnTo,
): ReturnContext {
  if (!href || !isInternalPath(href)) {
    return { ...fallback, type: asSourceType(type) };
  }
  return { href, label: label || "Back", type: asSourceType(type) };
}
