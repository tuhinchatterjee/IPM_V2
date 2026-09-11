"use client";

/**
 * The Cockpit V4 Ask surface.
 *
 * This is the whole interaction, and it speaks only the V4 run API. There is
 * no call to `/investigations`, no call to `/agentic/officer`, and no shim
 * translating either into V4 behind the scenes — the page uses the V4
 * architecture explicitly or it does not run at all.
 *
 * The lifecycle rule that shapes this component: a run is FOLLOWED, not
 * awaited. Submitting returns a run id and nothing else; everything after that
 * is the persisted event stream and the authoritative status. Nothing here
 * re-submits on an error, and nothing renders a stage the backend did not
 * report.
 *
 * A run outlives this page. Reloading the browser reconnects to the SAME run
 * from the last sequence actually rendered, because the alternative — asking
 * again — spends the analysis twice and tells the reader nothing about the
 * first one.
 */

import * as React from "react";

import {
  acknowledge,
  cancelRun,
  createThread,
  forgetRun,
  readStatus,
  recallRun,
  rememberRun,
  startRun,
  watch,
  type RunMode,
} from "./client";
import { ProcessPanel } from "./process-panel";
import { initial, reduce } from "./reducer";
import { ResponsePanel } from "./response-panel";

const MODES: { id: RunMode; label: string; hint: string }[] = [
  {
    id: "standard",
    label: "Standard",
    hint: "60-second deadline. Enough for most questions.",
  },
  {
    id: "deep",
    label: "Deep",
    hint: "120 seconds and a longer response allowance, for work that needs it.",
  },
];

export function CockpitV4({
  operatorView = false,
  initialQuestion = "",
}: {
  operatorView?: boolean;
  initialQuestion?: string;
}) {
  const [view, dispatch] = React.useReducer(reduce, initial());
  const [question, setQuestion] = React.useState(initialQuestion);
  const [mode, setMode] = React.useState<RunMode>("standard");
  const [threadId, setThreadId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  // A ref, not state. Flipping state inside the replay effect would re-run
  // the effect, and its cleanup would set `cancelled` on the invocation still
  // awaiting `readStatus` — cancelling the replay it had just started.
  const resumeAttempted = React.useRef(false);
  const stopRef = React.useRef<(() => void) | null>(null);
  //: The thread the active run belongs to, readable from callbacks that must
  //: not be rebuilt every time it changes.
  const threadRef = React.useRef("");
  const acknowledged = React.useRef("");

  /** Follow a run that already exists. Used by submit AND by replay. */
  const follow = React.useCallback((runId: string, cursor = 0) => {
    stopRef.current?.();
    stopRef.current = watch(
      runId,
      {
        onEvent: (event) => {
          dispatch({ type: "event", event });
          // The cursor is the last sequence actually RENDERED, so a refresh
          // resumes from what the reader saw rather than from the start.
          rememberRun({
            runId,
            threadId: threadRef.current,
            cursor: event.seq,
          });
        },
        onSettled: (status) => {
          dispatch({ type: "settled", status });
          setBusy(false);
          forgetRun();
        },
        onConnectionState: (state) => dispatch({ type: "connection", state }),
      },
      cursor,
    );
  }, []);

  // Replay after a refresh. The run id came from this tab's own session, and
  // the authoritative status decides whether to reconnect or simply render
  // the answer that arrived while the page was reloading.
  React.useEffect(() => {
    if (resumeAttempted.current) return;
    resumeAttempted.current = true;
    const active = recallRun();
    if (!active) return;

    // No `cancelled` flag, deliberately. Next runs effects twice on mount in
    // development (StrictMode): the first invocation starts this work, the
    // cleanup that follows would set the flag, and the replay would abort
    // itself. The ref above already prevents a second FOLLOW, which is the
    // only thing that must not happen twice.
    void (async () => {
      try {
        const status = await readStatus(active.runId);
        setThreadId(status.thread_id);
        dispatch({ type: "start", runId: active.runId });
        if (status.terminal) {
          dispatch({ type: "settled", status });
          forgetRun();
          return;
        }
        setBusy(true);
        follow(active.runId, active.cursor);
      } catch {
        // The run is gone, or belongs to someone else. Forget it rather than
        // showing a reader a run they cannot see.
        forgetRun();
      }
    })();
    // Deliberately mount-only: the replay happens once, from this tab's own
    // session, and re-running it would reconnect to a run already followed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => () => stopRef.current?.(), []);

  // Acknowledgement happens AFTER the answer is on screen, which is what makes
  // "the user saw it" a different fact from "we generated it".
  React.useEffect(() => {
    if (view.terminal && view.response && acknowledged.current !== view.runId) {
      acknowledged.current = view.runId;
      void acknowledge(view.runId);
    }
  }, [view.terminal, view.response, view.runId]);

  const ask = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;
      setBusy(true);
      setError("");
      stopRef.current?.();
      try {
        let thread = threadId;
        if (!thread) {
          thread = (await createThread()).thread_id;
          setThreadId(thread);
          threadRef.current = thread;
        }
        const started = await startRun({
          question: trimmed,
          threadId: thread,
          mode,
          // A stable key for THIS submission, so a retried POST cannot buy a
          // second paid run.
          idempotencyKey:
            typeof crypto !== "undefined" && "randomUUID" in crypto
              ? crypto.randomUUID()
              : `${thread}-${Date.now()}`,
        });
        dispatch({ type: "start", runId: started.run_id });
        rememberRun({ runId: started.run_id, threadId: thread, cursor: 0 });
        setQuestion("");
        follow(started.run_id);
      } catch (caught) {
        setBusy(false);
        setError(
          caught instanceof Error
            ? caught.message
            : "The request could not be submitted.",
        );
      }
    },
    [busy, follow, mode, threadId],
  );

  return (
    <div className="space-y-4" data-testid="cockpit-v4">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
        className="space-y-2"
      >
        <div className="flex gap-2">
          <label className="sr-only" htmlFor="cockpit-v4-question">
            Ask the Cockpit
          </label>
          <input
            id="cockpit-v4-question"
            data-testid="cockpit-v4-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about the corporate book, or about CreditProbe itself"
            className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            data-testid="cockpit-v4-ask"
            disabled={busy || !question.trim()}
            className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            Ask
          </button>
        </div>

        <fieldset className="flex items-center gap-3" disabled={busy}>
          <legend className="sr-only">Analysis depth</legend>
          {MODES.map((option) => (
            <label
              key={option.id}
              title={option.hint}
              className="inline-flex items-center gap-1.5 text-xs text-slate-600"
            >
              <input
                type="radio"
                name="cockpit-v4-mode"
                data-testid={`cockpit-v4-mode-${option.id}`}
                value={option.id}
                checked={mode === option.id}
                onChange={() => setMode(option.id)}
              />
              {option.label}
            </label>
          ))}
          <span className="text-xs text-slate-400">
            {MODES.find((m) => m.id === mode)?.hint}
          </span>
        </fieldset>
      </form>

      {error ? (
        <p
          data-testid="cockpit-v4-submit-error"
          className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800"
        >
          {error}
        </p>
      ) : null}

      {view.runId ? (
        <>
          <ProcessPanel
            view={view}
            operatorView={operatorView}
            onCancel={() => void cancelRun(view.runId)}
            onRetryStatus={() =>
              void readStatus(view.runId).then((status) =>
                dispatch({ type: "settled", status }),
              )
            }
          />
          <ResponsePanel view={view} onAsk={(text) => void ask(text)} />
        </>
      ) : null}
    </div>
  );
}
