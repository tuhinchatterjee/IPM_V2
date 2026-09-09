import type { PlannerHealth } from "@/lib/api";

/**
 * How the planner says things.
 *
 * The sentences live here rather than in the components because the same
 * facts appear on three screens and a workbook, and three implementations of
 * "6 days overdue" is how a product ends up saying "6 days late" in one place
 * and "overdue by 6" in another. It is also the only part of the planner's
 * presentation with real branching, so it is the part worth testing.
 */

/** Semantic tone for a health colour. Never colour alone — see `HealthPill`. */
export function healthTone(
  health: PlannerHealth,
): "positive" | "warning" | "negative" | "default" {
  switch (health) {
    case "GREEN":
      return "positive";
    case "AMBER":
      return "warning";
    case "RED":
      return "negative";
    default:
      return "default";
  }
}

/**
 * A due date said the way a person would say it.
 *
 * Lateness wins over everything: somebody reading a list needs the six things
 * that are overdue to look different from the forty that are not, and a
 * column of ISO dates makes them all look the same. The date is kept
 * alongside because it is what gets quoted in a meeting.
 */
export function dueLabel(
  date: string | null,
  daysOverdue?: number | null,
  daysUntil?: number | null,
): { text: string; tone: "negative" | "warning" | "muted" | "normal" } {
  if (!date) return { text: "No date", tone: "muted" };
  if (daysOverdue && daysOverdue > 0) {
    const days = daysOverdue === 1 ? "day" : "days";
    return { text: `${daysOverdue} ${days} overdue`, tone: "negative" };
  }
  if (daysUntil === null || daysUntil === undefined) {
    return { text: date, tone: "normal" };
  }
  if (daysUntil === 0) return { text: "Due today", tone: "warning" };
  if (daysUntil === 1) return { text: "In 1 day", tone: "warning" };
  if (daysUntil <= 7) return { text: `In ${daysUntil} days`, tone: "normal" };
  return { text: date, tone: "normal" };
}

/**
 * How long ago, in the words somebody would use.
 *
 * "3 days ago" up to a fortnight, and then the date — because past about two
 * weeks "17 days ago" stops being easier to read than 2026-08-17, and starts
 * being harder.
 */
export function when(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "—";
  const days = Math.floor((now - then.getTime()) / 86_400_000);
  if (days < 0) return then.toISOString().slice(0, 10);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  return then.toISOString().slice(0, 10);
}

/**
 * The label for a claim in an AI brief.
 *
 * Short words, because they sit in a badge at the start of every line and a
 * reader scans down the column. "Reading" rather than "Inference" for the
 * same reason: it is what a person would call it.
 */
export function claimLabel(kind: string): string {
  switch (kind) {
    case "FACT":
      return "Fact";
    case "INFERENCE":
      return "Reading";
    case "RECOMMENDATION":
      return "Suggested";
    case "NOT RECORDED":
      return "Not recorded";
    default:
      return kind;
  }
}

/** Percent, clamped and rounded, for a progress bar that cannot overflow. */
export function progressWidth(percent: number): number {
  if (!Number.isFinite(percent)) return 0;
  return Math.max(0, Math.min(100, Math.round(percent)));
}
