/**
 * Step-list progress, as data. The shared half of the CreditProbe agentic
 * progress experience.
 *
 * Why this sits beside `officer.ts` rather than inside a product
 * --------------------------------------------------------------
 * The Cockpit's working indicator answers "who is working, and on what" for a
 * run that has ONE current stage. Early Warning needs a different shape — a
 * list of stages, each with its own status and its own duration, some with
 * analyses nested under them — because an Early Warning turn is an
 * investigation the reader is meant to watch take shape.
 *
 * Those are two presentations of the same idea, and the parts that are
 * genuinely common live here: the status vocabulary, the marks, the time
 * formatting, the polling cadence and the sentence a screen reader is given.
 * What is NOT common — which stages exist, what they are called, what the
 * substeps mean — arrives as data from the product's own backend, which is
 * the only place that can know it.
 *
 * No React in this file, so the rules about what the panel SAYS can be tested
 * without rendering anything. That is the split `officer.ts` established and
 * it has earned its keep.
 *
 * What never appears here
 * -----------------------
 * A label. Every sentence the reader sees comes from the server's governed
 * vocabulary, so the wording is reviewable in one place and a product cannot
 * quietly invent a stage name in the browser. The only strings written below
 * are the ones a screen reader needs to turn a mark into a word.
 */

/** What a step can be. Mirrors the backend's `progress.py`. */
export type StepStatus = "waiting" | "active" | "done" | "note" | "stopped";

export interface ProgressSubstep {
  key: string;
  label: string;
  status: StepStatus;
  completed_ms: number | null;
  rows: number;
}

export interface ProgressStep {
  key: string;
  label: string;
  status: StepStatus;
  started_ms: number | null;
  completed_ms: number | null;
  elapsed_ms: number | null;
  substeps: ProgressSubstep[];
  detail: Record<string, unknown>;
}

export interface ProgressDocument {
  turn_id: string;
  version: number;
  sequence: number;
  steps: ProgressStep[];
  summary: Record<string, unknown>;
  elapsed_ms: number;
  active: boolean;
  outcome: string;
  completion_line: string;
}

/** What the poll returns, including the ordinary "nothing to show" answer. */
export interface ProgressReply extends Partial<ProgressDocument> {
  watching: boolean;
  version: number;
}

/**
 * The contract version this client understands.
 *
 * A document from a newer server is not rendered half-understood: the panel
 * falls back to a plain working state, which is honest, rather than to a list
 * with rows missing.
 */
export const SUPPORTED_VERSION = 1;

export function understands(document: {
  version?: number;
} | null | undefined): boolean {
  if (!document) return false;
  const version = document.version ?? 0;
  // A document with no version at all is not "version zero", it is not a
  // progress document. Treating a missing field as 0 would make every
  // malformed reply look like one this client understands.
  return version >= 1 && version <= SUPPORTED_VERSION;
}

/**
 * Elapsed time at the precision a reader can use.
 *
 * One decimal under a minute, because "31.8s" is read as "about half a
 * minute" and "31800ms" is read twice. Minutes after that. The backend
 * formats the same way; this exists so a ticking clock in the browser does
 * not drift into a different style from the durations beside it.
 */
export function seconds(ms: number | null | undefined): string {
  if (!ms || ms < 0) return "";
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const total = Math.floor(ms / 1000);
  const rest = total % 60;
  return rest ? `${Math.floor(total / 60)}m ${rest}s` : `${Math.floor(total / 60)}m`;
}

/**
 * How long to wait before asking again.
 *
 * The same curve the Cockpit's indicator uses, and for the same reason: the
 * early stages are quick and a reader watching a stale line thinks nothing is
 * happening, while a long investigation polled every second is a hundred
 * requests to watch a list that is not changing.
 */
export function pollAfter(elapsedMs: number): number {
  if (elapsedMs < 5_000) return 700;
  if (elapsedMs < 30_000) return 1_500;
  return 4_000;
}

/** Which step the reader should be looking at, if any. */
export function current(document: ProgressDocument | null): ProgressStep | null {
  if (!document) return null;
  return document.steps.find((s) => s.status === "active") ?? null;
}

export function finished(document: ProgressDocument | null): boolean {
  return Boolean(document && !document.active);
}

/**
 * How many governed analyses have reported, and how many are expected.
 *
 * Both numbers come from the document — the plan named them, the executor
 * reported them — so a progress bar built on this is counting real work
 * rather than guessing at a percentage.
 */
export function analyses(step: ProgressStep | null | undefined): {
  done: number;
  total: number;
} {
  const subs = step?.substeps ?? [];
  return {
    // Counted by whether the analysis REPORTED, not by its mark. An analysis
    // that was planned and then declined carries a note and no completion
    // time, and counting it as done would tell the reader six analyses ran
    // when four did.
    done: subs.filter((s) => s.completed_ms !== null).length,
    total: subs.length,
  };
}

/** The word a mark stands for, for readers who cannot see the mark. */
export const STATUS_WORDS: Record<StepStatus, string> = {
  waiting: "not started",
  active: "in progress",
  done: "completed",
  note: "note",
  stopped: "stopped",
};

/**
 * What a screen reader is told while the panel updates.
 *
 * One sentence naming the step that is running, not a re-reading of the whole
 * list. A live region that re-announces eleven rows every second is worse
 * than no live region at all, which is why this returns the active step alone
 * and the component throttles how often it changes.
 */
export function announcement(document: ProgressDocument | null): string {
  if (!document) return "";
  if (!document.active) {
    return document.completion_line || "Analysis complete.";
  }
  const step = current(document);
  if (!step) return "Working.";
  const { done, total } = analyses(step);
  if (total > 0) {
    return `${step.label}. ${done} of ${total} analyses complete.`;
  }
  return step.label;
}

/**
 * The Details rows. §18.
 *
 * Ordered here rather than by object key order, so the table reads the same
 * way every time. Anything the server did not send is left out rather than
 * shown empty — a row saying "Scope —" tells the reader nothing except that
 * somebody wrote a row.
 */
const DETAIL_ORDER: { key: string; label: string }[] = [
  { key: "mode", label: "Mode" },
  { key: "functionality", label: "Functionality" },
  { key: "scope", label: "Scope" },
  { key: "period", label: "Period" },
  { key: "analyses", label: "Analyses completed" },
  { key: "evidence_check", label: "Evidence check" },
  { key: "deferred", label: "Additional analysis deferred" },
];

export function details(
  document: ProgressDocument | null,
): { label: string; value: string }[] {
  if (!document) return [];
  const summary = document.summary ?? {};
  const rows = DETAIL_ORDER.filter((row) => {
    const value = summary[row.key];
    return value !== undefined && value !== null && value !== "";
  }).map((row) => ({ label: row.label, value: String(summary[row.key]) }));
  const time = seconds(document.elapsed_ms);
  if (time) rows.push({ label: "Elapsed", value: time });
  return rows;
}
