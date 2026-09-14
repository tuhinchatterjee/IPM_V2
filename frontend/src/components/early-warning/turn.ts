/**
 * What a turn is, as the screen understands it.
 *
 * The defect this replaces
 * ------------------------
 * The chat sent one POST and held it open under a sixty-second fetch
 * timeout. A certified Early Warning turn takes forty to seventy-five
 * seconds, so the screen showed
 *
 *     The backend did not respond within 60 seconds.
 *
 * in red, and then the completed answer arrived underneath it. Both cannot be
 * true. The browser was deciding something it is in no position to know: a
 * fetch timeout is a fact about a socket, not about whether a credit analysis
 * succeeded.
 *
 * So the backend owns the state. It creates the turn, reports `running`,
 * `completed` or `failed`, and carries the answer when there is one. This
 * module is the reducer the UI renders from — pure, so the lifecycle can be
 * tested without a browser, a server or a clock.
 */

/** What the backend says about a turn. Nothing else may set these. */
export type TurnState = "running" | "completed" | "failed";

/** One poll, as `/ask/progress` returns it. */
export interface Poll {
  watching: boolean;
  /** "" when this worker has never seen the turn. Not a failure. */
  state?: TurnState | "";
  answer?: unknown;
  failure?: string;
  question?: string;
  elapsed_ms?: number;
  steps?: unknown;
}

export interface Turn {
  id: string;
  threadId: string;
  question: string;
  state: TurnState;
  /** Set only when the backend reports `completed`. */
  answer: unknown | null;
  /** Set only when the backend reports `failed`. Written for a reader. */
  failure: string;
  /** Consecutive polls that did not reach the backend. */
  missedPolls: number;
  /** The turn's own clock, from the backend's elapsed time where it has one. */
  elapsedMs: number;
  /** The latest progress document, for the panel. */
  progress: unknown | null;
}

/**
 * How many consecutive failed polls before the screen mentions it.
 *
 * Not before: one dropped request on a flaky connection is not news, and a
 * "Reconnecting…" that flashes on every hiccup is the same lie as the
 * timeout banner in a quieter voice.
 */
export const MISSES_BEFORE_RECONNECTING = 3;

/**
 * How many consecutive failed polls before the screen gives up.
 *
 * Deliberately large. At a two-second cadence this is four minutes of total
 * silence, which is a network that is gone rather than a turn that is slow.
 * A turn is NEVER failed for being slow — only for the backend saying so, or
 * for the browser being unable to reach it at all for this long.
 */
export const MISSES_BEFORE_UNREACHABLE = 120;

export function begin(id: string, threadId: string, question: string): Turn {
  return {
    id,
    threadId,
    question,
    state: "running",
    answer: null,
    failure: "",
    missedPolls: 0,
    elapsedMs: 0,
    progress: null,
  };
}

/**
 * The turn after one poll.
 *
 * Three rules, and they are the whole of it:
 *
 * 1. Only the backend moves a turn out of `running`.
 * 2. A poll that did not arrive is a missed poll, not a failed turn.
 * 3. A turn that reached a terminal state stays there.
 */
export function applyPoll(turn: Turn, poll: Poll): Turn {
  if (turn.state !== "running") return turn;

  const state = poll.state;
  if (state === "completed") {
    return {
      ...turn,
      state: "completed",
      answer: poll.answer ?? null,
      failure: "",
      missedPolls: 0,
      elapsedMs: poll.elapsed_ms ?? turn.elapsedMs,
      progress: poll.steps ? poll : turn.progress,
    };
  }
  if (state === "failed") {
    return {
      ...turn,
      state: "failed",
      answer: null,
      failure: poll.failure || "CreditProbe could not complete this analysis.",
      missedPolls: 0,
      elapsedMs: poll.elapsed_ms ?? turn.elapsedMs,
    };
  }
  // `running`, or a worker that has never seen this turn. Both mean carry on.
  return {
    ...turn,
    missedPolls: 0,
    elapsedMs: poll.elapsed_ms ?? turn.elapsedMs,
    progress: poll.watching ? poll : turn.progress,
  };
}

/** The turn after a poll that never arrived. */
export function applyPollFailure(turn: Turn): Turn {
  if (turn.state !== "running") return turn;
  const missed = turn.missedPolls + 1;
  if (missed >= MISSES_BEFORE_UNREACHABLE) {
    return {
      ...turn,
      state: "failed",
      missedPolls: missed,
      failure:
        "CreditProbe could not be reached while this analysis was running.",
    };
  }
  return { ...turn, missedPolls: missed };
}

/** Whether to tell the reader the connection is struggling. */
export function isReconnecting(turn: Turn): boolean {
  return (
    turn.state === "running" && turn.missedPolls >= MISSES_BEFORE_RECONNECTING
  );
}

/**
 * Whether this turn's error belongs on the screen right now.
 *
 * Scoped to the turn, which is the other half of the defect: a banner that
 * belonged to the screen outlived the turn that caused it, so a later
 * successful answer appeared under an earlier turn's red box.
 */
export function errorFor(turn: Turn | null, turnId: string): string {
  if (!turn || turn.id !== turnId) return "";
  return turn.state === "failed" ? turn.failure : "";
}

/** A turn is finished when the backend says so, and not before. */
export function isSettled(turn: Turn): boolean {
  return turn.state !== "running";
}
