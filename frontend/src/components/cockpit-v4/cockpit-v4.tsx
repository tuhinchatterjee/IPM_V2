"use client";

/**
 * The V4 ask surface: one question, a live trace, one published answer.
 *
 * The lifecycle rule that shapes this component: a run is followed, not
 * awaited. Submitting returns a run id; everything after that is the event
 * stream and the authoritative status. Nothing here re-submits on an error,
 * and the answer is acknowledged only after it has actually been rendered.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  acknowledge,
  cancelRun,
  createThread,
  readStatus,
  startRun,
  watch,
} from "./client";
import { ProcessPanel } from "./process-panel";
import { initial, reduce } from "./reducer";
import { ResponsePanel } from "./response-panel";

export function CockpitV4({ operatorView = false }: { operatorView?: boolean }) {
  const [view, dispatch] = useReducer(reduce, initial());
  const [question, setQuestion] = useState("");
  const [threadId, setThreadId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const stopRef = useRef<(() => void) | null>(null);
  const acknowledged = useRef("");

  useEffect(() => () => stopRef.current?.(), []);

  // Acknowledgement happens AFTER the answer is on screen, which is what
  // makes "the user saw it" a different fact from "we generated it".
  useEffect(() => {
    if (view.terminal && view.response && acknowledged.current !== view.runId) {
      acknowledged.current = view.runId;
      void acknowledge(view.runId);
    }
  }, [view.terminal, view.response, view.runId]);

  const ask = useCallback(
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
        }
        const started = await startRun({
          question: trimmed,
          threadId: thread,
          // A stable key for THIS submission, so a retried POST cannot buy
          // a second paid run.
          idempotencyKey:
            typeof crypto !== "undefined" && "randomUUID" in crypto
              ? crypto.randomUUID()
              : `${thread}-${Date.now()}`,
        });
        dispatch({ type: "start", runId: started.run_id });
        setQuestion("");
        stopRef.current = watch(started.run_id, {
          onEvent: (event) => dispatch({ type: "event", event }),
          onSettled: (status) => {
            dispatch({ type: "settled", status });
            setBusy(false);
          },
          onConnectionState: (state) =>
            dispatch({ type: "connection", state }),
        });
      } catch (caught) {
        setBusy(false);
        setError(
          caught instanceof Error
            ? caught.message
            : "The request could not be submitted.",
        );
      }
    },
    [busy, threadId],
  );

  return (
    <div className="space-y-3">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
        className="flex gap-2"
      >
        <label className="sr-only" htmlFor="cockpit-v4-question">
          Ask the Cockpit
        </label>
        <input
          id="cockpit-v4-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about the corporate book, or about CreditProbe itself"
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !question.trim()}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          Ask
        </button>
      </form>

      {error ? (
        <p className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
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
