/**
 * How a Cockpit V3 request settles, and what the reader is shown.
 *
 * Defect 3 of the live UAT was that a real request took 20.517 seconds against
 * a 20-second transport timeout, the browser aborted it, and the only thing
 * that happened was `catch { setV3Steps([]) }` — the progress line vanished
 * and nothing replaced it. A request that fails in silence reads as a request
 * that succeeded and had nothing to say.
 *
 * So settlement is stated here, as data rather than as branches inside a
 * component, and it is exhaustive:
 *
 *   answer · referral · clarification · stop · error
 *
 * There is no sixth outcome and there is no blank.
 *
 * The distinction that matters is between the STOPS and the ERRORS. A stop is
 * something the server decided and wrote a sentence about: it reached its token
 * ceiling, its cost ceiling, its deadline, its submission or round limit; a
 * model was unavailable; the data release was; the answer is partial; it needs
 * the user to choose; it belongs to another module. All of those arrive as
 * envelopes and are rendered WITH THE SERVER'S OWN EXPLANATION. An error is
 * only the case where there is no envelope at all — the request never arrived,
 * never came back, or was refused before the Cockpit saw it.
 *
 * None of this touches the server's own limits. The transport timeout in
 * `api.cockpitV3Ask` is how long the browser waits; Standard still stops at 60
 * seconds and Deep at 120, and those are the server's to enforce.
 */

import type { CockpitV3Answer, CockpitV3Envelope } from "@/lib/api";

/** What the reader ends up looking at. Five, and no others. */
export type V3Settlement =
  | "answer"
  | "referral"
  | "clarification"
  | "stop"
  | "error";

export const V3_SETTLEMENTS: readonly V3Settlement[] = [
  "answer",
  "referral",
  "clarification",
  "stop",
  "error",
] as const;

/**
 * The terminal states the server can settle a request into, each of which
 * arrives as an envelope with its own explanation. Every one of these is a
 * SUPPORTED outcome: it is rendered as what the server said, never swallowed
 * as a transport failure and never shown as "something went wrong".
 */
export const V3_TERMINAL_STATUSES = [
  "COMPLETED",
  "PARTIAL",
  "REDIRECTED",
  "WAITING_FOR_USER",
  "UNSUPPORTED",
  "INSUFFICIENT_DATA",
  "EXECUTION_FAILED",
  "STOPPED_TOKEN_LIMIT",
  "STOPPED_COST_LIMIT",
  "STOPPED_TIME_LIMIT",
  "STOPPED_EXECUTION_LIMIT",
  "STOPPED_ANALYSIS_LIMIT",
  "STOPPED_SECURITY",
  "MODEL_CONFIGURATION_MISSING",
  "MODEL_UNAVAILABLE",
  "PROVIDER_CREDENTIAL_MISSING",
  "PROVIDER_ERROR",
  "DATA_UNAVAILABLE",
  "CONTEXT_TOO_LARGE",
  "CANCELLED",
  "INTERNAL_ERROR",
] as const;

export type V3TerminalStatus = (typeof V3_TERMINAL_STATUSES)[number];

/** Whether a status is one the server wrote an envelope for. */
export function isSupportedStop(status: string): boolean {
  return (V3_TERMINAL_STATUSES as readonly string[]).includes(status);
}

/**
 * Which of the five a returned payload is. Read from the envelope the server
 * wrote, not inferred from the status: a stop and a partial answer are
 * different things to show, and the server has already decided which.
 */
export function settlementOf(payload: CockpitV3Answer): V3Settlement {
  const envelope: CockpitV3Envelope | undefined = payload?.answer;
  switch (envelope?.kind) {
    case "referral":
      return "referral";
    case "clarification":
      return "clarification";
    case "stop":
      return "stop";
    case "answer":
      return "answer";
    default:
      // An envelope with no kind is not an answer with an empty narrative; it
      // is a response this client cannot render, and saying so is honest.
      return "error";
  }
}

/** Whether the running indicator should still be on. It should not: every
 *  settlement above is final, and so is a failure. */
export function stillRunning(): false {
  return false;
}

export type V3Failure = {
  message: string;
  status?: number;
  code?: string;
};

/**
 * What this module reads off a transport error, and the whole of it.
 *
 * Recognised structurally rather than with `instanceof ApiError`, for two
 * reasons that point the same way: this module then has no runtime dependency
 * on the API client, and the three fields below are stated as the only things
 * that may reach a reader. An exception that happens to carry a stack, a cause
 * or a response body contributes none of them.
 */
type TransportError = { name?: string; message?: unknown; status?: unknown;
                        code?: unknown };

function apiErrorFields(error: unknown): V3Failure | null {
  if (!error || typeof error !== "object") return null;
  const candidate = error as TransportError;
  if (candidate.name !== "ApiError") return null;
  if (typeof candidate.message !== "string") return null;
  return {
    message: candidate.message,
    status: typeof candidate.status === "number" ? candidate.status : undefined,
    code: typeof candidate.code === "string" ? candidate.code : undefined,
  };
}

/**
 * The governed message for the case where no envelope came back.
 *
 * Uses the sentence the server wrote when there was one — `request()` already
 * lifts `detail.message` out of an error body, which is how a 503
 * DATA_UNAVAILABLE keeps its own explanation instead of becoming "the backend
 * is unreachable". Where the server was never reached, this supplies a written
 * sentence of its own.
 *
 * What it never produces: a stack trace, an exception class name, a bare status
 * code standing in for a reason, or anything read from the environment. The
 * only inputs it takes from an error are `message`, `status` and `code`, and
 * anything that is not an `ApiError` contributes nothing at all -- it gets the
 * written sentence, not its own text.
 */
export function failureFrom(error: unknown): V3Failure {
  const fields = apiErrorFields(error);
  if (fields) {
    return {
      ...fields,
      message:
        fields.message.trim() ||
        "CreditProbe could not complete that request. Nothing was computed.",
    };
  }
  return {
    message:
      "CreditProbe could not complete that request, and did not say why. " +
      "Nothing was computed.",
    code: "unknown",
  };
}
