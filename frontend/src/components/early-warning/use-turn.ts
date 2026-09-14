"use client";

import * as React from "react";

import { type ProgressDocument, pollAfter } from "@/components/agentic/steps";
import { api, type EarlyWarningV2Answer } from "@/lib/api";
import {
  applyPoll,
  applyPollFailure,
  begin,
  isSettled,
  type Turn,
} from "./turn";

export interface StartOptions {
  threadId: string;
  customerId?: string | null;
  uiState?: Record<string, unknown>;
  /**
   * The dashboard's filter as the governed spec, snapshotted when the thread
   * began. Structured rather than described: a scope reconstructed from prose
   * is a scope that can be read back wrong, and this one is already exact.
   */
  dashboardScope?: Record<string, unknown>;
  rollingSummary?: Record<string, unknown>;
  mode?: "standard" | "deep";
}

/**
 * Run one Early Warning turn, and report what the backend says about it.
 *
 * The lifecycle, in full:
 *
 *     start  ->  turn_id, at once
 *            ->  poll   running / running / running ...
 *            ->  poll   completed (with the answer)  or  failed (with a
 *                       sentence written for a credit officer)
 *
 * Nothing here decides a turn has failed. A poll that does not arrive is a
 * missed poll; forty, seventy-five or three hundred seconds of `running` is
 * a turn that is running. That is the entire difference between this and the
 * single sixty-second POST it replaces, which told the reader an analysis
 * had timed out and then showed them its answer.
 *
 * `turn.ts` holds the reducer, so the rules above are tested without a
 * browser, a server or a clock.
 */
export function useEwsTurn(): {
  turn: Turn | null;
  /** The live progress document, for the panel. */
  progress: ProgressDocument | null;
  /** The turn's elapsed time, from the backend's clock where it has one. */
  elapsedMs: number;
  start: (question: string, options: StartOptions) => Promise<Turn | null>;
  /** Forget the current turn. Used when a new one begins. */
  clear: () => void;
} {
  const [turn, setTurn] = React.useState<Turn | null>(null);
  const [tickMs, setTickMs] = React.useState(0);
  // The turn the polling loop belongs to. A second question asked before the
  // first settled must not have the first one's loop writing into it.
  const watching = React.useRef<string>("");

  React.useEffect(
    () => () => {
      watching.current = "";
    },
    [],
  );

  const start = React.useCallback(
    async (question: string, options: StartOptions): Promise<Turn | null> => {
      const trimmed = question.trim();
      if (!trimmed) return null;

      let started;
      try {
        started = await api.earlyWarningV2AskStart({
          question: trimmed,
          threadId: options.threadId,
          customerId: options.customerId ?? undefined,
          uiState: options.uiState,
          dashboardScope: options.dashboardScope,
          rollingSummary: options.rollingSummary,
          mode: options.mode ?? "standard",
        });
      } catch {
        // The turn never began, so there is nothing to poll and nothing to
        // be ambiguous about. This is the one failure the client does own.
        const stillborn: Turn = {
          ...begin("", options.threadId, trimmed),
          state: "failed",
          failure: "CreditProbe could not start this analysis.",
        };
        setTurn(stillborn);
        return stillborn;
      }

      const fresh = begin(started.turn_id, options.threadId, trimmed);
      watching.current = started.turn_id;
      setTurn(fresh);
      setTickMs(0);

      const since = Date.now();
      let current = fresh;
      // A local clock only for the figure between polls. The backend's
      // elapsed time is authoritative and overwrites it on every poll.
      const ticking = setInterval(() => {
        if (watching.current === started.turn_id) {
          setTickMs(Date.now() - since);
        }
      }, 250);

      try {
        for (;;) {
          if (watching.current !== started.turn_id) return null;
          try {
            const reply = await api.earlyWarningV2Progress(started.turn_id);
            current = applyPoll(current, reply);
          } catch {
            current = applyPollFailure(current);
          }
          if (watching.current !== started.turn_id) return null;
          setTurn(current);
          if (isSettled(current)) return current;
          await new Promise((resolve) =>
            setTimeout(resolve, pollAfter(Date.now() - since)),
          );
        }
      } finally {
        clearInterval(ticking);
      }
    },
    [],
  );

  const clear = React.useCallback(() => {
    watching.current = "";
    setTurn(null);
    setTickMs(0);
  }, []);

  const progress =
    turn && turn.progress ? (turn.progress as ProgressDocument) : null;
  return {
    turn,
    progress,
    elapsedMs: turn ? Math.max(turn.elapsedMs, tickMs) : 0,
    start,
    clear,
  };
}

/** The answer a completed turn carries, typed. */
export function answerOf(turn: Turn | null): EarlyWarningV2Answer | null {
  if (!turn || turn.state !== "completed" || !turn.answer) return null;
  return turn.answer as EarlyWarningV2Answer;
}
