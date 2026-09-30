"use client";

/**
 * What-If state inside an ordinary Cockpit conversation.
 *
 * When the conversation's scenario is confirmed but no method was chosen it
 * says so -- "confirmed, NOT executed" -- and offers the four methods as
 * ordinary turns through the thread's own `ask` (a click is the same as
 * typing "Run it with Delta"). Once executed, the result opens as a governed
 * Scenario Result with the universal dual-scope Plotly decomposition.
 */

import * as React from "react";
import { useRouter } from "next/navigation";

import { guidedEnabled } from "@/lib/workspace/guided";
import { adoptThreadResult, readThreadCohort, type ThreadCohort } from "@/lib/workspace/whatif";

const METHOD_TURNS: { id: string; label: string; ask: string }[] = [
  { id: "delta", label: "Delta", ask: "Run the confirmed scenario with the Delta method." },
  { id: "ml", label: "ML emulator", ask: "Run the confirmed scenario with the ML emulator." },
  { id: "user_defined", label: "User-defined", ask: "Run the confirmed scenario with a user-defined impact." },
  { id: "compare", label: "Compare methods", ask: "Run the confirmed scenario with Delta and the ML emulator and compare them." },
];

export function ThreadWhatIf({ threadId, busy, turnCount, onAsk }: { threadId: string; busy: boolean; turnCount: number; onAsk: (q: string) => void }) {
  const [state, setState] = React.useState<ThreadCohort | null>(null);
  const [error, setError] = React.useState("");
  const [opening, setOpening] = React.useState(false);
  const router = useRouter();
  const enabled = guidedEnabled();

  React.useEffect(() => {
    if (!enabled || busy) return;
    readThreadCohort(threadId)
      .then(setState)
      .catch(() => setState(null));
  }, [threadId, turnCount, busy, enabled]);

  if (!enabled || !state?.has_cohort) return null;
  const awaitingMethod = state.method_state === "METHOD_SELECTION_REQUIRED" || state.method_state === "METHOD_INPUT_REQUIRED" || state.method_state === "METHOD_UNAVAILABLE";

  async function open() {
    setOpening(true);
    setError("");
    try {
      const r = await adoptThreadResult(threadId);
      router.push(`/what-if/result/${r.object_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setOpening(false);
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-3 text-xs" data-testid="thread-whatif" data-method-state={state.method_state ?? ""} data-has-result={String(Boolean(state.has_result))}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">What-If in this conversation</span>
        <span className="text-text-muted">
          {state.entities} exposures · scenario {state.scenario_id} · {state.state}
        </span>
        {state.has_result && (
          <button type="button" disabled={opening} onClick={() => void open()} className="ml-auto rounded-md bg-accent px-2 py-1 text-accent-contrast disabled:opacity-40" data-testid="thread-whatif-open-result">
            Open the decomposition ({(state.methods_ran ?? []).join(" + ")})
          </button>
        )}
      </div>
      {awaitingMethod && (
        <div className="mt-2 space-y-1" data-testid="thread-whatif-methods">
          <p className="font-semibold text-warning">Scenario confirmed — NOT executed. Choose the method; nothing runs until you do.</p>
          <div className="flex flex-wrap gap-1.5">
            {METHOD_TURNS.map((m) => (
              <button key={m.id} type="button" disabled={busy} onClick={() => onAsk(m.ask)} className="rounded-full border border-accent px-2.5 py-1 text-accent hover:bg-accent-muted disabled:opacity-50" data-testid={`thread-whatif-method-${m.id}`}>
                {m.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-1 text-negative">
          {error}
        </p>
      )}
    </section>
  );
}
