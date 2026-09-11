"use client";

import * as React from "react";

import { StepProgress } from "@/components/agentic/step-progress";
import {
  type ProgressDocument,
  pollAfter,
  understands,
} from "@/components/agentic/steps";
import { api } from "@/lib/api";

/**
 * Early Warning's half of the shared progress experience.
 *
 * Everything about how the panel LOOKS is in `components/agentic` and is
 * shared with the Cockpit. What is here is the part only Early Warning can
 * supply: which endpoint to poll, and the key that names this turn.
 *
 * That split is the whole point of the brief's §35. An `EwsProgressWidget`
 * and a `CockpitProgressWidget` with the same marks, the same timing rules
 * and the same accessibility handling drawn twice is two places for those
 * rules to drift apart, and drift in a progress indicator shows up as one
 * product looking subtly broken.
 *
 * A turn key, not a run id
 * ------------------------
 * The Cockpit polls a run that exists in the database before the indicator
 * does. An Early Warning turn is one synchronous request with no row of its
 * own, so the client names the turn before it sends it and the server writes
 * that turn's events under the same name. Same shape, one less round trip,
 * and no schema.
 */
export function useTurnKey(): () => string {
  const counter = React.useRef(0);
  const prefix = React.useId().replace(/[^A-Za-z0-9]/g, "");
  return React.useCallback(() => {
    counter.current += 1;
    return `ews-${prefix}-${counter.current}`;
  }, [prefix]);
}

/**
 * Watch one turn while it runs.
 *
 * Polling starts when a key is handed in and stops the moment the turn
 * reports that it is no longer active — §10's "stop completely when work is
 * done", which matters more here than it looks: a panel that keeps polling a
 * finished turn keeps its clock ticking under an answer that has arrived.
 *
 * The document is keyed by the turn it belongs to, so a second question asked
 * before the first settled cannot paint the first one's steps under the
 * second one's answer.
 */
export function useTurnProgress(turnKey: string | null): {
  document: ProgressDocument | null;
  liveMs: number;
} {
  const [state, setState] = React.useState<{
    key: string;
    document: ProgressDocument | null;
  } | null>(null);
  // Keyed by the turn it belongs to, so the figure under a new question is
  // never the previous question's clock still running.
  const [clock, setClock] = React.useState<{ key: string; ms: number }>({
    key: "",
    ms: 0,
  });

  React.useEffect(() => {
    if (!turnKey) return;
    const since = Date.now();
    let watching = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // The clock that makes the running step's figure move between polls.
    // Four times a second: fast enough that a tenth-of-a-second figure does
    // not visibly stutter, slow enough to cost nothing.
    const ticking = setInterval(
      () => setClock({ key: turnKey, ms: Date.now() - since }),
      250,
    );

    const tick = async () => {
      try {
        const reply = await api.earlyWarningV2Progress(turnKey);
        if (!watching) return;
        if (reply.watching && understands(reply)) {
          const document = reply as unknown as ProgressDocument;
          setState({ key: turnKey, document });
          if (!document.active) return;
        }
      } catch {
        // A poll that fails is not worth an error state: the answer is
        // unaffected and the next poll usually succeeds. The panel simply
        // does not advance, which is honest — nothing new is known.
      }
      if (watching) timer = setTimeout(tick, pollAfter(Date.now() - since));
    };

    void tick();
    return () => {
      watching = false;
      clearInterval(ticking);
      if (timer) clearTimeout(timer);
    };
  }, [turnKey]);

  const document =
    state && turnKey && state.key === turnKey ? state.document : null;
  const liveMs = turnKey && clock.key === turnKey ? clock.ms : 0;
  return { document, liveMs };
}

/**
 * The panel, while a question is in flight.
 *
 * Renders nothing until the server has reported at least one stage. That is
 * deliberate: the alternative is a skeleton of eleven grey rows, which is a
 * claim about what is going to happen rather than a report of what has, and
 * on a redirect most of those rows never run. The first stage arrives within
 * a few hundred milliseconds, and until then the composer's own busy state is
 * what the reader sees.
 */
export function TurnProgress({
  turnKey,
  finished,
  className,
}: {
  turnKey: string | null;
  /** The completed document from the answer, once it has arrived. */
  finished?: ProgressDocument | null;
  className?: string;
}) {
  const { document, liveMs } = useTurnProgress(turnKey);
  const shown = finished ?? document;
  if (!shown || shown.steps.length === 0) return null;
  return (
    <StepProgress
      document={shown}
      liveMs={liveMs}
      className={className}
      collapsible={!shown.active}
    />
  );
}
