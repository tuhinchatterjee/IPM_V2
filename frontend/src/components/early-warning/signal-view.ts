/**
 * §28, §29 — how the governed early-warning signal is presented.
 *
 * Every decision the Early Warning screens make about ORDER, GROUPING and
 * WORDING lives here rather than inside a component, because each of them is
 * a rule somebody can be wrong about and a component is a bad place to argue
 * with one.
 *
 * The rule the whole file exists for: there is no score, and nothing here may
 * invent one. A borrower is not "0.72 risky"; it has conditions, in families,
 * with a lifecycle, and the screen orders by counts a reader can reproduce.
 * The moment a sort key here becomes a weighted sum, the transparency the
 * backend went to some trouble to preserve is gone at the last step.
 */

import type { SignalObservation, SignalStanding } from "@/lib/api";

// ---------------------------------------------------------------- severity

export const SEVERITY_RANK: Record<string, number> = {
  SEVERE: 3,
  CONCERN: 2,
  WATCH: 1,
};

export const SEVERITY_LABEL: Record<string, string> = {
  SEVERE: "Severe",
  CONCERN: "Concern",
  WATCH: "Watch",
};

/** The visual weight a severity gets. Three levels, matching the taxonomy. */
export function tone(severity: string): "danger" | "warning" | "muted" {
  if (severity === "SEVERE") return "danger";
  if (severity === "CONCERN") return "warning";
  return "muted";
}

// --------------------------------------------------------------- lifecycle

export const LIFECYCLE_ORDER = [
  "WORSENING",
  "NEW",
  "PERSISTING",
  "IMPROVING",
  "CURED",
  "UNAVAILABLE",
] as const;

export const LIFECYCLE_LABEL: Record<string, string> = {
  NEW: "New",
  PERSISTING: "Still firing",
  WORSENING: "Worse",
  IMPROVING: "Better",
  CURED: "Cured",
  UNAVAILABLE: "Not tested",
};

/**
 * Which conditions a reader should look at first inside one borrower.
 *
 * Worsening before new before merely persisting: a condition that got worse
 * since the last reporting date is the one that changed, and a screen that
 * buries it under three conditions in their fourth quiet quarter is a screen
 * that hides the news. Severity breaks ties, then the label, so the order is
 * total and does not depend on the order the API happened to return.
 */
export function byUrgency(
  a: SignalObservation,
  b: SignalObservation,
): number {
  const life =
    LIFECYCLE_ORDER.indexOf(a.lifecycle as never) -
    LIFECYCLE_ORDER.indexOf(b.lifecycle as never);
  if (life !== 0) return life;
  const sev =
    (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0);
  if (sev !== 0) return sev;
  return a.label.localeCompare(b.label);
}

// ----------------------------------------------------------------- grouping

export interface FamilyGroup {
  family: string;
  label: string;
  fired: SignalObservation[];
  severity: string;
}

/**
 * Fired conditions, grouped by family, families ordered by what they carry.
 *
 * Grouping is not decoration. §25 counts FAMILIES rather than signals because
 * five liquidity conditions off one utilisation number is one fact told five
 * ways; a screen that lists them flat re-tells it five times and undoes the
 * argument.
 */
export function byFamily(standing: SignalStanding): FamilyGroup[] {
  const groups = new Map<string, FamilyGroup>();
  for (const observation of standing.fired) {
    const found = groups.get(observation.family);
    if (found) {
      found.fired.push(observation);
      if (
        (SEVERITY_RANK[observation.severity] ?? 0) >
        (SEVERITY_RANK[found.severity] ?? 0)
      ) {
        found.severity = observation.severity;
      }
    } else {
      groups.set(observation.family, {
        family: observation.family,
        label: observation.family_label || observation.family,
        fired: [observation],
        severity: observation.severity,
      });
    }
  }
  return [...groups.values()]
    .map((group) => ({ ...group, fired: [...group.fired].sort(byUrgency) }))
    .sort(
      (a, b) =>
        (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) ||
        b.fired.length - a.fired.length ||
        a.label.localeCompare(b.label),
    );
}

// ------------------------------------------------------------------ wording

/** The count a row leads with: families, then conditions. Never a score. */
export function summary(standing: SignalStanding): string {
  const conditions = standing.fired.length;
  if (!conditions) return "No governed condition fires.";
  const families = standing.breadth;
  return (
    `${conditions} condition${conditions === 1 ? "" : "s"} across ` +
    `${families} famil${families === 1 ? "y" : "ies"}`
  );
}

/**
 * What moved since last time, as a phrase, or nothing.
 *
 * Deliberately returns "" rather than "no change" when nothing moved: a row
 * that says "no change" in every quarter trains people to stop reading the
 * column.
 */
export function movement(standing: SignalStanding): string {
  const parts: string[] = [];
  if (standing.worsening) parts.push(`${standing.worsening} worse`);
  const fresh = standing.fired.filter((o) => o.lifecycle === "NEW").length;
  if (fresh) parts.push(`${fresh} new`);
  if (standing.improving) parts.push(`${standing.improving} better`);
  if (standing.cured.length) parts.push(`${standing.cured.length} cured`);
  return parts.join(", ");
}

/**
 * The caveat a borrower's detail must carry when conditions were not tested.
 *
 * §7. "Nothing fires" and "nothing could be tested" are different answers and
 * only one of them is reassuring, so a standing with untested conditions
 * never presents as clean.
 */
export function notTested(standing: SignalStanding): string {
  const count = standing.untested.length;
  if (!count) return "";
  return (
    `${count} governed condition${count === 1 ? "" : "s"} could not be ` +
    `tested for this borrower. ${count === 1 ? "It is" : "They are"} listed ` +
    `below with the reason.`
  );
}

/**
 * Whether anything on this standing is the BOOKED accounting position.
 *
 * §20: an early-warning prediction is never described as a stage
 * classification. Keeping the two separable at the presentation layer is how
 * that stays true when somebody writes a caption.
 */
export function booked(standing: SignalStanding): SignalObservation[] {
  return standing.fired.filter((o) => o.booked_accounting);
}

/** Evidence pointing the other way, named. §26 asks for it by name. */
export function conflicting(standing: SignalStanding): string {
  if (!standing.conflict.length) return "";
  const labels = standing.conflict.map((family) => {
    const found = standing.fired.find((o) => o.family === family);
    return (found?.family_label ?? family).toLowerCase();
  });
  return `Evidence points the other way in ${andList(labels)}.`;
}

export function andList(items: string[]): string {
  const kept = items.filter(Boolean);
  if (!kept.length) return "";
  if (kept.length === 1) return kept[0];
  return `${kept.slice(0, -1).join(", ")} and ${kept[kept.length - 1]}`;
}

// ----------------------------------------------------------------- ordering

/**
 * The order the overview lists borrowers in — the backend's ranking, restated
 * so a client-side re-sort cannot silently disagree with it.
 *
 * Breadth, severity, persistence, worsening, then the borrower id. Every step
 * is a count, and the last one makes the order total, so two runs over the
 * same book produce the same screen.
 */
export function byEvidence(a: SignalStanding, b: SignalStanding): number {
  return (
    b.breadth - a.breadth ||
    (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) ||
    b.persistence - a.persistence ||
    b.worsening - a.worsening ||
    a.borrower_id.localeCompare(b.borrower_id)
  );
}

/** The filters the overview offers. Each is a question, not a score band. */
export const LENSES = [
  { id: "all", label: "All", means: "Every borrower carrying a condition." },
  {
    id: "new",
    label: "New this quarter",
    means: "At least one condition that was not present last quarter.",
  },
  {
    id: "worsening",
    label: "Worsening",
    means: "At least one condition further past its threshold than before.",
  },
  {
    id: "persisting",
    label: "Still firing",
    means: "Conditions that were already firing at the previous date.",
  },
  {
    id: "severe",
    label: "Severe",
    means: "At least one condition the taxonomy classes as severe.",
  },
  {
    id: "multi",
    label: "Three or more families",
    means: "Independent evidence agreeing across three or more families.",
  },
] as const;

export type LensId = (typeof LENSES)[number]["id"];

export function matches(standing: SignalStanding, lens: LensId): boolean {
  switch (lens) {
    case "new":
      return standing.fired.some((o) => o.lifecycle === "NEW");
    case "worsening":
      return standing.worsening > 0;
    case "persisting":
      return standing.persistence > 0;
    case "severe":
      return standing.severity === "SEVERE";
    case "multi":
      return standing.breadth >= 3;
    default:
      return true;
  }
}
