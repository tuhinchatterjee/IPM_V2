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

export type Step = {
  stage: string;
  label: string;
  state: StepState;
  detail: string;
  startedAtMs: number;
  elapsedMs: number;
  errorId: string;
  substeps: {
    operation: string;
    message: string;
    status: string;
    elapsedMs: number;
    errorId: string;
    detailRef: string;
  }[];
};

export type RunView = {
  runId: string;
  lastSeq: number;
  connection: "open" | "retrying" | "lost";
  steps: Step[];
  currentStage: string;
  elapsedMs: number;
  terminal: boolean;
  state: string;
  errorCode: string;
  errorId: string;
  response: FinalResponse | null;
};

export const STAGE_LABELS: Record<string, string> = {
  accepted: "Request accepted",
  understanding: "Understanding the request",
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
      substeps: [],
    })),
    currentStage: "",
    elapsedMs: 0,
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
          substeps: [],
        });
        index = steps.length - 1;
      }

      const step = { ...steps[index] };
      step.substeps = [
        ...step.substeps,
        {
          operation: event.operation,
          message: event.public_message,
          status: event.status,
          elapsedMs: event.elapsed_ms,
          errorId: event.error_id,
          detailRef: event.detail_ref,
        },
      ];
      step.detail = event.public_message;
      step.elapsedMs = event.elapsed_ms - step.startedAtMs;
      if (event.status === "failed" || event.status === "rejected") {
        step.state = "failed";
        step.errorId = event.error_id || step.errorId;
      } else if (event.status === "started") {
        step.state = "running";
        if (!step.startedAtMs) step.startedAtMs = event.elapsed_ms;
      } else if (step.state !== "failed") {
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
      const steps = view.steps.map((step) =>
        step.state === "running" ? { ...step, state: "done" as StepState } : step,
      );
      return {
        ...view,
        steps,
        terminal: true,
        state: action.status.state,
        errorCode: action.status.error_code,
        errorId: action.status.error_id || view.errorId,
        response: action.status.final_response,
      };
    }

    default:
      return view;
  }
}

/** The one-line collapsed summary. Says what is happening, or what stopped. */
export function collapsedSummary(view: RunView): string {
  const seconds = Math.round(view.elapsedMs / 1000);
  if (view.terminal) {
    if (view.state === "COMPLETED") return `Answered in ${seconds}s`;
    if (view.state === "PARTIAL") return `Partly answered in ${seconds}s`;
    if (view.state === "WAITING_FOR_USER") return "Waiting for your answer";
    if (view.state === "REFERRED") return "Referred to another area";
    if (view.state === "CANCELLED") return "Cancelled";
    return `Stopped: ${view.errorCode || view.state}`;
  }
  const running = view.steps.find((s) => s.state === "running");
  const label = running?.label ?? STAGE_LABELS[view.currentStage] ?? "Working";
  return `${label} · ${seconds}s elapsed`;
}

/** The step a failure should auto-expand to. */
export function failedStage(view: RunView): string {
  return view.steps.find((s) => s.state === "failed")?.stage ?? "";
}
