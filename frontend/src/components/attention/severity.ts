/**
 * How a Risk Case is presented. §39, §41–§43, §46.
 *
 * Pure, so the rules about ordering, wording and emphasis can be tested
 * without rendering. The component beside this decides only how it looks.
 *
 * The one rule worth stating: ordering NEVER happens here. §46 says the order
 * must not depend on model prose, and the guarantee is that the backend stores
 * a `priority` integer computed from the severity arithmetic — this module
 * sorts by that integer and by nothing else. A comparator that read the
 * conclusion text would be exactly the failure §46 names.
 */

import type { RiskCase } from "@/lib/api";

export type Severity = "critical" | "high" | "medium" | "low";

/** The four bands, worst first. */
export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];

export const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

/**
 * The visual register for each band.
 *
 * §10's rule holds here too — text plus icon, not colour alone — so every row
 * carries the word as well as the tone. Critical and high share the negative
 * register because both mean "somebody should look at this today"; the
 * difference is the word, and the word is always there.
 */
export const SEVERITY_TONE: Record<string, string> = {
  critical: "bg-negative-muted text-negative",
  high: "bg-negative-muted text-negative",
  medium: "bg-warning-muted text-warning",
  low: "bg-surface-sunken text-text-muted",
};

export const LEVEL_LABEL: Record<string, string> = {
  PORTFOLIO: "Portfolio",
  SEGMENT: "Segment",
  BORROWER: "Borrower",
  DATA_QUALITY: "Data",
};

/** §40's filter tabs, in the order they appear. */
export const FILTERS = [
  "ALL",
  "PORTFOLIO",
  "SEGMENTS",
  "BORROWERS",
  "DATA",
] as const;

export type Filter = (typeof FILTERS)[number];

export const FILTER_LABEL: Record<Filter, string> = {
  ALL: "All",
  PORTFOLIO: "Portfolio",
  SEGMENTS: "Segments",
  BORROWERS: "Borrowers",
  DATA: "Data",
};

/** Which level a filter tab shows. "ALL" shows every level. */
export const FILTER_LEVEL: Record<Filter, string> = {
  ALL: "",
  PORTFOLIO: "PORTFOLIO",
  SEGMENTS: "SEGMENT",
  BORROWERS: "BORROWER",
  DATA: "DATA_QUALITY",
};

/** The count badge for a tab, from the backend's own grouped query. */
export function countFor(
  filter: Filter,
  counts: Record<string, number> | undefined,
): number {
  if (!counts) return 0;
  if (filter === "ALL") return counts.ALL ?? 0;
  return counts[FILTER_LEVEL[filter]] ?? 0;
}

/**
 * §46's ordering: the stored priority, then severity, then age.
 *
 * Every term is a number the backend computed. Nothing here reads a sentence.
 */
export function byPriority(a: RiskCase, b: RiskCase): number {
  if (b.priority !== a.priority) return b.priority - a.priority;
  if (b.severity_score !== a.severity_score)
    return b.severity_score - a.severity_score;
  return (b.created_at ?? "").localeCompare(a.created_at ?? "");
}

export function sorted(cases: RiskCase[]): RiskCase[] {
  return [...cases].sort(byPriority);
}

/**
 * The second line of a case row: what it is about, in the fewest words.
 *
 * Level-specific because the four levels are about different things. §42 asks
 * a segment row to show its share of the portfolio; §43 asks a borrower row to
 * show exposure and the current position. A single generic line would show
 * neither well.
 */
export function subtitle(found: RiskCase): string {
  const parts: string[] = [];
  if (found.exposure != null && found.level !== "DATA_QUALITY") {
    parts.push(`${format(found.exposure)} ${found.exposure_unit || ""}`.trim());
  }
  if (found.level === "BORROWER" && found.entity_kind === "customer") {
    const stage = signal(found, "Stage");
    if (stage) parts.push(stage);
  }
  if (found.level === "SEGMENT") {
    const share = shareOfBook(found);
    if (share) parts.push(share);
  }
  if (found.level === "DATA_QUALITY") {
    parts.push(found.entity);
  }
  if (found.period) parts.push(found.period);
  return parts.filter(Boolean).join(" · ");
}

function signal(found: RiskCase, startsWith: string): string {
  return (found.signals ?? []).find((s) => s.startsWith(startsWith)) ?? "";
}

function shareOfBook(found: RiskCase): string {
  const segment = (found.evidence?.segment ?? {}) as Record<string, unknown>;
  const share = segment.share_of_book;
  if (typeof share !== "number") return "";
  return `${(share * 100).toFixed(1)}% of the book`;
}

/** A figure at the precision a credit officer reads it. */
export function format(value: number): string {
  const size = Math.abs(value);
  if (size >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (size >= 10) return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/**
 * How complete the evidence behind a case is, in words.
 *
 * §54's principle applied to a case: a percentage on its own invites a reader
 * to treat 0.8 as "80% true", which it is not — it is "four of the five things
 * we would expect to have are attached".
 */
export function coverage(found: RiskCase): string {
  const value = found.evidence_coverage ?? 0;
  if (value >= 0.99) return "Fully evidenced";
  if (value >= 0.6) return "Mostly evidenced";
  if (value > 0) return "Partly evidenced";
  return "Evidence not yet attached";
}

/**
 * Whether a case wants attention right now, as opposed to eventually.
 *
 * Used for the small marker on a row. Deliberately narrow: if half the list is
 * marked urgent then nothing is.
 */
export function isUrgent(found: RiskCase): boolean {
  if (!found.open) return false;
  return found.overdue || found.severity === "critical";
}

/** The date a reader can act on, without a time nobody needs. */
export function dueLabel(found: RiskCase): string {
  if (!found.due_at || !found.open) return "";
  const due = new Date(found.due_at);
  if (Number.isNaN(due.getTime())) return "";
  const days = Math.round((due.getTime() - Date.now()) / 86_400_000);
  if (days < 0) return `${Math.abs(days)}d overdue`;
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  if (days <= 14) return `due in ${days}d`;
  return `due ${due.toISOString().slice(0, 10)}`;
}
