import type {
  PlaybookAvailability,
  PlaybookFigure,
  PlaybookPackStatus,
  PlaybookSeverity,
  PlaybookState,
} from "@/lib/api";

/**
 * The presentation rules of the Playbook, as pure functions.
 *
 * They live here rather than inside the components for the same reason the
 * Planner's do: each one is a decision somebody could reasonably make the
 * other way, and the next person to tidy up a figure cell must not be able to
 * quietly turn an immature cohort into 0.0%.
 *
 * The rule the whole area rests on:
 *
 *   A MISSING OR IMMATURE DENOMINATOR IS NEVER RENDERED AS A NUMBER, AND
 *   NEVER AS A BARE DASH.
 *
 * The backend has already decided which of five different facts applies, and
 * has put the rounded string on the snapshot. These functions render that
 * decision. They do not re-round, re-derive, or fall back to zero, because a
 * screen that computed its own display would eventually disagree with the PDF
 * sent to the same committee on the same morning.
 */

export type Tone = "default" | "accent" | "info" | "warning" | "positive" | "negative";

/**
 * What each absence MEANS, in the words a reader needs.
 *
 * Not decoration. "Not yet matured" tells somebody to come back next quarter;
 * "No data" tells them the population is empty and to check their filter;
 * "Calculation failed" tells them to raise it with a data steward. Showing all
 * three as a dash makes those three afternoons identical.
 */
const AVAILABILITY_LABEL: Record<PlaybookAvailability, string> = {
  OK: "",
  NO_DATA: "No data",
  NOT_MATURED: "Not yet matured",
  CALCULATION_FAILED: "Calculation failed",
  NOT_AUTHORISED: "Not authorised",
  PERIOD_MISSING: "Period not loaded",
  METRIC_UNAVAILABLE: "Metric unavailable",
};

const AVAILABILITY_TONE: Record<PlaybookAvailability, Tone> = {
  OK: "default",
  NO_DATA: "info",
  NOT_MATURED: "info",
  CALCULATION_FAILED: "negative",
  NOT_AUTHORISED: "warning",
  PERIOD_MISSING: "warning",
  METRIC_UNAVAILABLE: "warning",
};

export function availabilityLabel(availability: string): string {
  return (
    AVAILABILITY_LABEL[availability as PlaybookAvailability] ?? availability
  );
}

export function availabilityTone(availability: string): Tone {
  return AVAILABILITY_TONE[availability as PlaybookAvailability] ?? "warning";
}

export type FigureReading =
  | { kind: "value"; text: string }
  | { kind: "unavailable"; label: string; tone: Tone; reason: string }
  | { kind: "uncalculated"; text: string };

/**
 * How one figure reads. The single decision the whole area depends on.
 *
 * Three outcomes and no fourth: a value, a NAMED absence, or "not yet
 * calculated" for a block laid out but never generated. There is deliberately
 * no branch that produces an empty string or a bare dash, because a reader
 * fills those in with an assumption.
 */
export function figureReading(figure: PlaybookFigure | null): FigureReading {
  if (!figure) {
    return { kind: "uncalculated", text: "Not yet calculated" };
  }
  if (figure.availability !== "OK") {
    return {
      kind: "unavailable",
      label: availabilityLabel(figure.availability),
      tone: availabilityTone(figure.availability),
      reason: figure.unavailable_reason,
    };
  }
  return { kind: "value", text: figure.display_value };
}

export type MovementReading =
  | { kind: "none"; text: string }
  | { kind: "flat"; text: string }
  | { kind: "moved"; up: boolean; good: boolean; text: string };

/**
 * How a figure moved, read in the direction the METRIC cares about.
 *
 * `higher_is_better` comes from the metric definition, so a rising default
 * rate reads as bad and a rising coverage ratio reads as good without this
 * function knowing anything about either metric. A component that assumed
 * "up is good" would colour half a credit pack backwards.
 *
 * Where either side is missing this returns `none` rather than a movement:
 * a change computed against an absent comparison is the most confidently
 * wrong sentence a pack can contain.
 */
export function movementReading(
  figure: PlaybookFigure | null,
): MovementReading {
  if (!figure || figure.availability !== "OK") {
    return { kind: "none", text: "" };
  }
  if (figure.value === null || figure.comparison_value === null) {
    return { kind: "none", text: "No comparable prior figure" };
  }
  const change = figure.value - figure.comparison_value;
  const period = figure.comparison_period || "the previous period";
  if (Math.abs(change) < 1e-9) {
    return { kind: "flat", text: `Unchanged on ${period}` };
  }
  // A metric's `decimals` is a governance statement about how precisely the
  // number is meaningful. When the move does not survive that precision, an
  // arrow between two identical figures — "▲ from 0.3% on 2024-12" against a
  // reading of 0.3% — reads to a committee as a defect, and quoting the extra
  // digits to justify it would be false precision. Say what is true instead.
  if (figure.display_value === figure.comparison_display) {
    return {
      kind: "flat",
      text: `${figure.comparison_display} on ${period} — no change at the `
            + `precision this metric is reported to`,
    };
  }
  const up = change > 0;
  // `higher_is_better` may be null for a metric with no agreed direction —
  // a count, say. Treated as "not good, not bad" rather than guessed.
  const good = figure.higher_is_better === null ? false : up === figure.higher_is_better;
  return {
    kind: "moved",
    up,
    good,
    text: `${up ? "▲" : "▼"} from ${figure.comparison_display} on ${period}`,
  };
}

const SEVERITY_TONE: Record<PlaybookSeverity, Tone> = {
  CRITICAL: "negative",
  HIGH: "negative",
  MEDIUM: "warning",
  LOW: "info",
  INFO: "default",
};

export function severityTone(severity: string): Tone {
  return SEVERITY_TONE[severity as PlaybookSeverity] ?? "default";
}

const PACK_STATUS_TONE: Record<PlaybookPackStatus, Tone> = {
  DRAFT: "default",
  DATA_PENDING: "warning",
  GENERATING: "info",
  CONTRIBUTOR_REVIEW: "info",
  REVIEW: "info",
  CHANGES_REQUESTED: "warning",
  READY_FOR_APPROVAL: "accent",
  APPROVED: "positive",
  PUBLISHED: "positive",
  SUPERSEDED: "default",
  ARCHIVED: "default",
};

export function packStatusTone(status: string): Tone {
  return PACK_STATUS_TONE[status as PlaybookPackStatus] ?? "default";
}

const STATE_TONE: Record<PlaybookState, Tone> = {
  GREEN: "positive",
  AMBER: "warning",
  RED: "negative",
};

export function stateTone(state: string): Tone {
  return STATE_TONE[state as PlaybookState] ?? "negative";
}

/**
 * Which lifecycle steps are offered from where.
 *
 * The same transitions the backend's own state machine allows. A button that
 * leads to a 422 teaches people the product is unreliable, so this list is
 * kept deliberately narrow: where the two disagree, the backend wins and the
 * button should not have been there.
 */
export const NEXT_STATUS: Record<
  string,
  { status: string; label: string; hint: string }[]
> = {
  DRAFT: [
    { status: "CONTRIBUTOR_REVIEW", label: "Send to contributors",
      hint: "The people who own sections read theirs." },
    { status: "DATA_PENDING", label: "Waiting on data",
      hint: "Say the pack is blocked on a data load." },
  ],
  DATA_PENDING: [
    { status: "DRAFT", label: "Back to drafting", hint: "The data arrived." },
  ],
  CONTRIBUTOR_REVIEW: [
    { status: "REVIEW", label: "Send for review",
      hint: "The named reviewers read the whole pack." },
    { status: "DRAFT", label: "Back to drafting", hint: "" },
  ],
  REVIEW: [
    { status: "READY_FOR_APPROVAL", label: "Ready for approval",
      hint: "Nothing is blocking; the chair can sign it." },
    { status: "CHANGES_REQUESTED", label: "Changes requested", hint: "" },
  ],
  CHANGES_REQUESTED: [
    { status: "DRAFT", label: "Back to drafting", hint: "" },
  ],
  READY_FOR_APPROVAL: [
    { status: "APPROVED", label: "Approve",
      hint: "Your name goes on this pack. It becomes read-only." },
    { status: "CHANGES_REQUESTED", label: "Changes requested", hint: "" },
  ],
  APPROVED: [
    { status: "PUBLISHED", label: "Publish to the committee", hint: "" },
  ],
};

export function nextStatuses(status: string) {
  return NEXT_STATUS[status] ?? [];
}

/** An approved or published pack is a record, and records are not edited. */
export function isLocked(status: string): boolean {
  return ["APPROVED", "PUBLISHED", "SUPERSEDED", "ARCHIVED"].includes(status);
}

/** Whether a pack is still being worked on, for a "what is open" list. */
export function isOpen(status: string): boolean {
  return !isLocked(status);
}

/**
 * A file size a person can read.
 *
 * Here rather than in the component for the same reason everything else is:
 * the rule for the area is that a screen renders, and does not compute. A
 * byte count is not a governed figure, but a component doing arithmetic on
 * one is a component where somebody will later do arithmetic on a figure.
 */
export function fileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "unknown size";
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ------------------------------------------------------------------- dates

/** A timestamp a person can read, falling back to the raw value honestly. */
export function formatWhen(value: string | null | undefined): string {
  if (!value) return "at an unrecorded time";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value;
  return at.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A date without a time, for meeting dates and due dates. */
export function formatDay(value: string | null | undefined): string {
  if (!value) return "no date set";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value;
  return at.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/**
 * How far off a date is, in the words somebody would actually use.
 *
 * `now` is a parameter rather than a call to `Date.now()` inside, so this is
 * testable and so a list rendered across midnight cannot show two different
 * answers for two rows read a millisecond apart.
 */
export function daysUntil(
  value: string | null | undefined,
  now: number = Date.now(),
): string {
  if (!value) return "no date set";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value;
  const days = Math.round((at.getTime() - now) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  if (days > 0) return `in ${days} days`;
  return `${Math.abs(days)} days ago`;
}
