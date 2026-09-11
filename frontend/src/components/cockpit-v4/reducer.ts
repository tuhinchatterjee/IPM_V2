/**
 * Run-id and sequence fenced UI state.
 *
 * The fencing is the point. A late event from a run the user has moved on
 * from must not overwrite the active one, and a replayed event must not
 * duplicate a step already shown. Both are ordinary in practice: a reconnect
 * replays, and a user who asks a second question while the first is still
 * working has two streams alive for a moment.
 */

import type { FinalResponse, RunEvent, RunStatus } from "./client";

export type StepState = "prospective" | "running" | "done" | "failed";

export type Substep = {
  seq: number;
  operation: string;
  message: string;
  status: string;
  elapsedMs: number;
  attempt: number;
  errorId: string;
  detailRef: string;
  eventType: string;
};

export type Step = {
  stage: string;
  label: string;
  state: StepState;
  detail: string;
  startedAtMs: number;
  elapsedMs: number;
  errorId: string;
  /**
   * Failed attempts at this stage, which a later success does NOT erase.
   *
   * A run that finalized on its second attempt genuinely failed once, and a
   * panel that shows a clean tick over a hidden failure is an audit trace
   * that lies. `state` is the LATEST outcome; this is the count that keeps
   * the earlier one on screen.
   */
  failures: number;
  attempts: number;
  substeps: Substep[];
};

export type RunView = {
  runId: string;
  lastSeq: number;
  connection: "open" | "retrying" | "lost";
  steps: Step[];
  currentStage: string;
  /**
   * How long the run took, in milliseconds.
   *
   * While the run is live this is the highest `elapsed_ms` any event
   * reported. Once it settles, the authoritative run state replaces it:
   * the server's own clock is the fact, and an event stream that dropped
   * its last frame must not shorten the reported duration.
   */
  elapsedMs: number;
  elapsedIsAuthoritative: boolean;
  terminal: boolean;
  state: string;
  errorCode: string;
  errorId: string;
  response: FinalResponse | null;
};

export const STAGE_LABELS: Record<string, string> = {
  accepted: "Request accepted",
  understanding: "Understanding the request",
  product_knowledge: "Reading product knowledge",
  catalog: "Reading relevant data definitions",
  preparing: "Preparing query",
  validating: "Validating query",
  executing: "Executing query",
  reviewing: "Reviewing results",
  publishing: "Validating and publishing answer",
};

/**
 * The stages the panel LAYS OUT before anything has happened.
 *
 * Deliberately only the two that every run reaches. The actual path is
 * dynamic -- product help never reads the catalogue and never executes -- and
 * drawing an empty "Executing query" row for a question that will never run
 * one is a guess about the future dressed as progress.
 */
export const INITIAL_STAGES = ["accepted", "understanding"] as const;

export type Action =
  | { type: "start"; runId: string }
  | { type: "event"; event: RunEvent }
  | { type: "connection"; state: RunView["connection"] }
  | { type: "settled"; status: RunStatus };

export function initial(runId = ""): RunView {
  return {
    runId,
    lastSeq: 0,
    connection: "open",
    steps: INITIAL_STAGES.map((stage) => ({
      stage,
      label: STAGE_LABELS[stage],
      state: "prospective" as StepState,
      detail: "",
      startedAtMs: 0,
      elapsedMs: 0,
      errorId: "",
      failures: 0,
      attempts: 0,
      substeps: [],
    })),
    currentStage: "",
    elapsedMs: 0,
    elapsedIsAuthoritative: false,
    terminal: false,
    state: "ACCEPTED",
    errorCode: "",
    errorId: "",
    response: null,
  };
}

const TERMINAL_EVENTS = new Set([
  "answer.ready",
  "run.failed",
  "run.cancelled",
  "run.expired",
  "run.interrupted",
]);

export function reduce(view: RunView, action: Action): RunView {
  switch (action.type) {
    case "start":
      return initial(action.runId);

    case "connection":
      return { ...view, connection: action.state };

    case "event": {
      const event = action.event;
      // Fencing: a different run, or an event already applied.
      if (event.run_id !== view.runId) return view;
      if (event.seq <= view.lastSeq) return view;

      const steps = view.steps.slice();
      let index = steps.findIndex((s) => s.stage === event.stage);
      if (index < 0) {
        steps.push({
          stage: event.stage,
          label: STAGE_LABELS[event.stage] ?? event.stage,
          state: "prospective",
          detail: "",
          startedAtMs: event.elapsed_ms,
          elapsedMs: 0,
          errorId: "",
          failures: 0,
          attempts: 0,
          substeps: [],
        });
        index = steps.length - 1;
      }

      const step = { ...steps[index] };
      step.substeps = [
        ...step.substeps,
        {
          seq: event.seq,
          operation: event.operation,
          message: event.public_message,
          status: event.status,
          elapsedMs: event.elapsed_ms,
          attempt: event.attempt,
          errorId: event.error_id,
          detailRef: event.detail_ref,
          eventType: event.event_type,
        },
      ];
      step.detail = event.public_message;
      if (!step.startedAtMs) step.startedAtMs = event.elapsed_ms;
      step.elapsedMs = Math.max(0, event.elapsed_ms - step.startedAtMs);
      if (event.attempt > step.attempts) step.attempts = event.attempt;

      if (event.status === "failed" || event.status === "rejected") {
        step.state = "failed";
        // Counted, not just displayed: a later success sets `state` back to
        // "done", and this is what keeps the failure on screen.
        step.failures += 1;
        step.errorId = event.error_id || step.errorId;
      } else if (event.status === "started") {
        step.state = "running";
      } else {
        // A success after a failure is a success. The failure survives in
        // `failures` and in the substep list, which is what the audit trace
        // is for.
        step.state = "done";
      }
      steps[index] = step;

      // Any earlier stage still marked running has been left behind.
      for (let i = 0; i < index; i += 1) {
        if (steps[i].state === "running") {
          steps[i] = { ...steps[i], state: "done" };
        }
      }

      return {
        ...view,
        lastSeq: event.seq,
        steps,
        currentStage: event.stage,
        elapsedMs: Math.max(view.elapsedMs, event.elapsed_ms),
        errorId: event.error_id || view.errorId,
        terminal: view.terminal || TERMINAL_EVENTS.has(event.event_type),
      };
    }

    case "settled": {
      if (action.status.run_id !== view.runId) return view;
      // A stage still marked running when the run settled did finish; the
      // event that said so may simply not have reached this browser.
      const steps = view.steps.map((step) =>
        step.state === "running" ? { ...step, state: "done" as StepState } : step,
      );
      const authoritative = authoritativeElapsedMs(action.status);
      return {
        ...view,
        steps,
        terminal: true,
        state: action.status.state,
        errorCode: action.status.error_code,
        errorId: action.status.error_id || view.errorId,
        response: action.status.final_response,
        elapsedMs: authoritative ?? view.elapsedMs,
        elapsedIsAuthoritative: authoritative !== null,
      };
    }

    default:
      return view;
  }
}

/**
 * The run's own elapsed time, from the server, in milliseconds.
 *
 * `budget.elapsed_seconds` is what the run ledger recorded. Preferring it
 * over the last event the browser happened to receive is the difference
 * between reporting 29.4s and reporting 0s.
 */
export function authoritativeElapsedMs(status: RunStatus): number | null {
  const budget = status.budget as { elapsed_seconds?: unknown } | undefined;
  const seconds = budget?.elapsed_seconds;
  if (typeof seconds === "number" && Number.isFinite(seconds) && seconds >= 0) {
    return Math.round(seconds * 1000);
  }
  return null;
}

/** The one-line collapsed summary. Says what is happening, or what stopped. */
export function collapsedSummary(view: RunView): string {
  const seconds = formatSeconds(view.elapsedMs);
  if (view.terminal) {
    if (view.state === "COMPLETED") return `Answered in ${seconds}`;
    if (view.state === "PARTIAL") return `Partly answered in ${seconds}`;
    if (view.state === "WAITING_FOR_USER") return "Waiting for your answer";
    if (view.state === "REFERRED") return "Referred to another area";
    if (view.state === "CANCELLED") return "Cancelled";
    return `Stopped: ${view.errorCode || view.state}`;
  }
  const running = view.steps.find((s) => s.state === "running");
  const label = running?.label ?? STAGE_LABELS[view.currentStage] ?? "Working";
  return `${label} · ${seconds} elapsed`;
}

/**
 * A duration a reader can act on.
 *
 * Sub-second runs keep one decimal, because "0s" for a run that took 400ms
 * reads as "nothing happened" — which is how a false trace hides.
 */
export function formatSeconds(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  return `${Math.round(seconds)}s`;
}

/** The step a failure should auto-expand to. */
export function failedStage(view: RunView): string {
  return (
    view.steps.find((s) => s.state === "failed")?.stage ??
    // A stage that failed and then succeeded still deserves the reader's
    // attention when the panel opens.
    view.steps.find((s) => s.failures > 0)?.stage ??
    ""
  );
}

/** Did any stage fail at any point, even if a later attempt succeeded? */
export function hadAnyFailure(view: RunView): boolean {
  return view.steps.some((step) => step.failures > 0);
}
