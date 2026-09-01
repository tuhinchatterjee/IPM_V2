/**
 * The officer working indicator, as data. §4, §7, §8, §9, §11.
 *
 * Pure functions, no React, so the rules about what the indicator SAYS can be
 * tested without rendering anything. The component beside this file decides
 * only how it looks.
 *
 * The stage vocabulary is a copy of the backend's, and deliberately a small
 * one: the captions come from the API (`/agentic/stages`) so the sentence a
 * user saw is the sentence recorded on the run. What lives here is the
 * ordering, the labels used when the API has not answered yet, and the rules
 * about when the indicator is visible at all.
 */

/** §7's eleven states. */
export type Stage =
  | "QUEUED"
  | "UNDERSTANDING"
  | "SCOPING"
  | "SELECTING_DATA"
  | "COORDINATING"
  | "CALCULATING"
  | "VALIDATING"
  | "INTERPRETING"
  | "COMPLETE"
  | "NEEDS_INPUT"
  | "FAILED"
  | "CANCELLED";

/** The order work moves through. */
export const SEQUENCE: Stage[] = [
  "QUEUED",
  "UNDERSTANDING",
  "SCOPING",
  "SELECTING_DATA",
  "COORDINATING",
  "CALCULATING",
  "VALIDATING",
  "INTERPRETING",
  "COMPLETE",
];

export const TERMINAL: Stage[] = [
  "COMPLETE",
  "NEEDS_INPUT",
  "FAILED",
  "CANCELLED",
];

/** The short label under the officer title. */
export const SHORT: Record<Stage, string> = {
  QUEUED: "Preparing",
  UNDERSTANDING: "Understanding",
  SCOPING: "Scoping",
  SELECTING_DATA: "Selecting data",
  COORDINATING: "Coordinating",
  CALCULATING: "Calculating",
  VALIDATING: "Validating",
  INTERPRETING: "Interpreting",
  COMPLETE: "Complete",
  NEEDS_INPUT: "Needs input",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

/** §7's own wording, used until the API's own captions arrive. */
export const CAPTIONS: Record<Stage, string> = {
  QUEUED: "CreditProbe is preparing the request.",
  UNDERSTANDING: "Understanding your question.",
  SCOPING: "Defining the population and period.",
  SELECTING_DATA: "Selecting governed data.",
  COORDINATING: "Coordinating specialist agents.",
  CALCULATING: "Running governed calculations.",
  VALIDATING: "Validating results and reconciliation.",
  INTERPRETING: "Preparing the CreditProbe reading.",
  COMPLETE: "Completed — validated.",
  NEEDS_INPUT: "CreditProbe needs your input.",
  FAILED: "CreditProbe could not complete the request.",
  CANCELLED: "Stopped at your request.",
};

/** The four officer levels. §4. */
export const TITLES: Record<number, string> = {
  1: "Credit Analyst",
  2: "Senior Credit Officer",
  3: "Portfolio Risk Lead",
  4: "Chief Orchestrator",
};

export interface Live {
  run_id?: number | null;
  stage: Stage;
  label?: string;
  caption?: string;
  detail?: string;
  officer_title?: string;
  officer_level?: number;
  status_line?: string;
  specialists?: string[];
  agent_count?: number;
  elapsed_ms?: number;
  active?: boolean;
  terminal?: boolean;
  completed?: Stage[];
  escalation_line?: string;
  selection_reason?: string;
  assurance?: string;
  failure?: string;
}

export function isTerminal(stage: Stage): boolean {
  return TERMINAL.includes(stage);
}

export function indexOf(stage: Stage): number {
  return SEQUENCE.indexOf(stage);
}

/**
 * Whether the indicator should be on screen.
 *
 * §10: "stop completely when work is done". A pulse that keeps beating after
 * the answer has arrived is the decoration §6 forbids — and worse, it teaches
 * the reader that the pulse means nothing.
 */
export function isWorking(live: Live | null): boolean {
  if (!live) return false;
  return !isTerminal(live.stage);
}

/** §4's status line. "Credit Analyst is working". */
export function statusLine(live: Live | null): string {
  if (!live) return "";
  if (live.status_line) return live.status_line;
  const title = live.officer_title || TITLES[live.officer_level ?? 1] || "";
  if (!title || isTerminal(live.stage)) return "";
  return `${title} is working`;
}

/**
 * The caption beside the pulse.
 *
 * The run's own detail wins where it has one — "Validating 6 calculations" is
 * §8's example and says more than "Validating results and reconciliation".
 */
export function caption(live: Live | null): string {
  if (!live) return "";
  return live.detail?.trim() || live.caption || CAPTIONS[live.stage] || "";
}

/**
 * The specialist line. §8: "Ratings · IFRS 9 · DPD · Covenants".
 *
 * Empty for one specialist. "Coordinating 1 specialist" is a sentence about
 * nothing, and showing it on every ordinary question would make coordination
 * look like the norm rather than the exception it is.
 */
export function specialistLine(live: Live | null): string {
  const names = live?.specialists ?? [];
  if (names.length < 2) return "";
  return names.join(" · ");
}

export function specialistCount(live: Live | null): string {
  const names = live?.specialists ?? [];
  if (names.length < 2) return "";
  return `Coordinating ${names.length} specialists`;
}

/**
 * Elapsed time, at the precision a reader can actually use.
 *
 * Seconds until a minute, then minutes. Milliseconds on screen imply a
 * precision nobody needs and make the number change too fast to read.
 */
export function elapsed(ms: number | undefined): string {
  if (!ms || ms < 0) return "";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 1) return "";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

/** Which stages this run has already passed. §8's optional completed list. */
export function completed(live: Live | null): Stage[] {
  if (!live) return [];
  if (live.completed?.length) return live.completed;
  const here = indexOf(live.stage);
  return here < 0 ? [] : SEQUENCE.slice(0, here);
}

/**
 * §9's escalation line, and the sentence under it.
 *
 * Returned as a pair so the component can render the transition in the
 * restrained two-line form the brief asks for — a heading and a reason — and
 * so an empty reason does not leave a dangling colon.
 */
export function escalation(
  live: Live | null,
): { line: string; reason: string } | null {
  const line = live?.escalation_line?.trim();
  if (!line) return null;
  return { line, reason: live?.selection_reason?.trim() ?? "" };
}

/**
 * How the indicator is described to a screen reader.
 *
 * §10 asks for an accessible live region. A pulse is nothing at all to a
 * screen reader, so what it means is stated in words — and the words are the
 * same ones on screen, not a separate description that can drift from them.
 */
export function announcement(live: Live | null): string {
  if (!live) return "";
  const parts = [statusLine(live), caption(live)];
  const specialists = specialistLine(live);
  if (specialists) parts.push(`Specialists: ${specialists}.`);
  return parts.filter(Boolean).join(". ");
}

/**
 * How often to poll while work is running.
 *
 * Fast at first, because the early stages are quick and a reader watching a
 * stale caption thinks nothing is happening; slower as a run gets long,
 * because a portfolio review takes minutes and a poll a second for three
 * minutes is 180 requests to watch a spinner.
 */
export function pollAfter(elapsedMs: number): number {
  if (elapsedMs < 5_000) return 700;
  if (elapsedMs < 30_000) return 1_500;
  return 4_000;
}
