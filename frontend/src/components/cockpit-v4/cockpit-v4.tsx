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
import type { AttentionItem } from "./client";
import { AskBox } from "./ask-box";
import { ProcessPanel } from "./process-panel";
import { initial, reduce } from "./reducer";
import { ResponsePanel } from "./response-panel";

export type ActiveInvestigation = {
  threadId: string;
  item: AttentionItem;
  suggested: string[];
};


export function CockpitV4({
  operatorView = false,
  initialQuestion = "",
  investigation = null,
  onClearInvestigation,
  onSettled,
}: {
  operatorView?: boolean;
  initialQuestion?: string;
  /**
   * A conversation opened from an attention card. The thread already holds
   * the segment, the quarter and the movement server-side; this component
   * only has to ask into it and say, on screen, what it is asking about.
   */
  investigation?: ActiveInvestigation | null;
  onClearInvestigation?: () => void;
  /** Called when a run settles, so the page can refresh what it can reopen. */
  onSettled?: () => void;
}) {
  const [view, dispatch] = React.useReducer(reduce, initial());
  const [question, setQuestion] = React.useState(initialQuestion);
  const [mode, setMode] = React.useState<RunMode>("standard");
  const [threadId, setThreadId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [showPrompts, setShowPrompts] = React.useState(true);
  const [traceHelp, setTraceHelp] = React.useState(false);
  // A ref, not state. Flipping state inside the replay effect would re-run
  // the effect, and its cleanup would set `cancelled` on the invocation still
  // awaiting `readStatus` — cancelling the replay it had just started.
  const resumeAttempted = React.useRef(false);
  const stopRef = React.useRef<(() => void) | null>(null);
  //: The thread the active run belongs to, readable from callbacks that must
  //: not be rebuilt every time it changes.
  const threadRef = React.useRef("");
  const acknowledged = React.useRef("");
  //: Read from the watcher callback, which must not be rebuilt on every
  //: render just because the page handed down a new closure.
  const settledRef = React.useRef<(() => void) | undefined>(undefined);
  settledRef.current = onSettled;

  // Adopt the seeded thread. The seed itself lives on the server; what the
  // component needs is the id to ask into.
  React.useEffect(() => {
    if (!investigation?.threadId) return;
    setThreadId(investigation.threadId);
    threadRef.current = investigation.threadId;
  }, [investigation?.threadId]);

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
          settledRef.current?.();
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
        // The seeded thread wins, and it is read here rather than from state:
        // a reader who clicks Investigate Further and types immediately must
        // land in that conversation, not in a new one an effect had not yet
        // adopted.
        let thread = investigation?.threadId || threadId;
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
    [busy, follow, investigation?.threadId, mode, threadId],
  );

  return (
    <div className="space-y-4" data-testid="cockpit-v4">
      {investigation ? (
        <div
          data-testid="investigation-context"
          data-segment={investigation.item.segment}
          data-thread-id={investigation.threadId}
          className="rounded border border-sky-200 bg-sky-50 px-4 py-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-sky-800">
                Investigating
              </p>
              <p className="mt-0.5 text-sm text-sky-900">
                {investigation.item.headline}
              </p>
              <p className="mt-0.5 text-xs text-sky-700">
                {investigation.item.segment} ·{" "}
                {investigation.item.reporting_quarter}
                {investigation.item.comparison_quarter
                  ? ` vs ${investigation.item.comparison_quarter}`
                  : ""}{" "}
                · {investigation.item.movement}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setThreadId("");
                threadRef.current = "";
                onClearInvestigation?.();
              }}
              data-testid="investigation-clear"
              className="rounded px-2 py-1 text-xs text-sky-700 hover:bg-sky-100"
            >
              Clear
            </button>
          </div>
          {investigation.suggested.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {investigation.suggested.map((text) => (
                <button
                  key={text}
                  type="button"
                  data-testid="investigation-suggestion"
                  onClick={() => void ask(text)}
                  disabled={busy}
                  className="rounded-full border border-sky-300 bg-white px-3 py-1 text-xs text-sky-800 hover:bg-sky-100 disabled:opacity-40"
                >
                  {text}
                </button>
              ))}
            </div>
          ) : null}
          <p className="mt-2 text-[11px] text-sky-700">
            Follow-up questions are read against this segment and quarter. You
            do not need to repeat them.
          </p>
        </div>
      ) : null}

      <AskBox
        question={question}
        onQuestionChange={setQuestion}
        mode={mode}
        onModeChange={setMode}
        onAsk={(text) => void ask(text)}
        busy={busy}
        showPrompts={showPrompts && !view.runId}
        onDismissPrompts={() => setShowPrompts(false)}
      />

      <p className="text-xs text-slate-500" data-testid="cockpit-v4-trace-note">
        <span aria-hidden="true">ⓘ </span>
        Every answer carries a Trace.{" "}
        <button
          type="button"
          data-testid="cockpit-v4-trace-explain"
          onClick={() => setTraceHelp((open) => !open)}
          className="underline underline-offset-2 hover:text-slate-700"
        >
          What is a Trace?
        </button>
      </p>
      {traceHelp ? (
        <p
          data-testid="cockpit-v4-trace-help"
          className="rounded border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600"
        >
          Every figure in an answer is bound to a query that actually ran. The
          process panel below shows each stage as it happens — the metadata
          read, the query validated and bound, the rows returned, any attempt
          that failed — and each stored result can be opened from the answer.
          Nothing is asserted that has no evidence behind it.
        </p>
      ) : null}

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
          <ResponsePanel
            view={view}
            onAsk={(text) => void ask(text)}
            question={question}
            threadId={threadId}
          />
        </>
      ) : null}
    </div>
  );
}
