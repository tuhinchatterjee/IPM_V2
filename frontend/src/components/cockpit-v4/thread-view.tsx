"use client";

/**
 * The Cockpit thread: a conversation, not a page that answers once.
 *
 * The product problem this exists for
 * -----------------------------------
 * V4 could execute an analytical question and publish an evidence-bound
 * answer, and the experience was still a dashboard. You asked from a landing
 * page, one process panel appeared, one answer appeared, and to ask the
 * obvious next question you scrolled back up to the box you started in. There
 * was no transcript, so the second question felt like starting over, and the
 * answer read as the end of the interaction when the follow-up is the point.
 *
 * So: a thread. The question sits at the top, the process runs underneath it,
 * the answer appends below that, and the composer is waiting where your eye
 * already is. Ask again and the exchange appends -- it does not replace what
 * came before. Five questions render as five exchanges.
 *
 * What did NOT come back with the shape
 * --------------------------------------
 * None of the previous Cockpit's backend. No `/investigations`, no
 * `/agentic/officer`, no old Ask flow, no shim translating either. The run
 * lifecycle, the evidence model, the release binding and the numeric
 * rendering are V4's, unchanged by this file. This is the interaction the old
 * product got right, over the architecture the new one got right.
 *
 * Reloading is free
 * -----------------
 * The transcript is the server's. A refresh reads it back and re-follows only
 * a run that is genuinely still working -- it never re-asks, because asking
 * again spends the analysis twice and tells the reader nothing about the
 * first one.
 */

import * as React from "react";

import {
  acknowledge,
  cancelRun,
  forgetRun,
  readStatus,
  recallRun,
  rememberRun,
  readThread,
  renameThread,
  startRun,
  watch,
  type FinalResponse,
  type RunMode,
  type ThreadTranscript,
  type ThreadTurn,
} from "./client";
import { AnswerActions } from "./answer-actions";
import { ProcessPanel } from "./process-panel";
import { initial, reduce } from "./reducer";
import { ResponsePanel } from "./response-panel";
import { Visuals } from "./visuals";

/** A run in one of these states is finished; there is nothing to follow. */
const TERMINAL_RUN_STATES = new Set([
  "COMPLETED", "PARTIAL", "FAILED", "EXPIRED", "CANCELLED", "UNSUPPORTED",
  "REFERRED", "WAITING_FOR_USER", "INTERRUPTED",
]);

/** One exchange already on the server. */
type Settled = {
  key: string;
  runId: string;
  question: string;
  answer: FinalResponse;
};

function settled(turn: ThreadTurn): Settled {
  return {
    key: turn.turn_id,
    runId: turn.run_id,
    question: turn.question,
    answer: turn.answer as FinalResponse,
  };
}

// ---- the pieces ---------------------------------------------------------

function UserTurn({ question }: { question: string }) {
  return (
    <div data-testid="v4-turn-user" className="flex justify-end">
      <p
        dir="auto"
        className="max-w-[48rem] rounded-2xl rounded-br-sm bg-slate-800 px-4 py-2.5 text-sm text-white"
      >
        {question}
      </p>
    </div>
  );
}

function AssistantTurn({
  turn,
  onAsk,
}: {
  turn: Settled;
  onAsk: (question: string) => void;
}) {
  // The answer body is the SAME component the live run renders, driven by a
  // view reconstructed from the stored turn. A second renderer for answers
  // read back from the server would be a second set of rules about
  // dispositions, evidence links and suggested questions, and the two would
  // drift the first time either changed.
  const view = React.useMemo(
    () => ({
      ...initial(turn.runId),
      terminal: true,
      state: "COMPLETED",
      response: turn.answer,
    }),
    [turn.runId, turn.answer],
  );

  return (
    <div data-testid="v4-turn-assistant" className="space-y-4">
      <ResponsePanel
        view={view}
        question={turn.question}
        onAsk={onAsk}
      />
      <Visuals tables={turn.answer.tables ?? []}
               charts={turn.answer.charts ?? []} />
    </div>
  );
}


/** What a seeded investigation already knows, before anything is asked. */
function SeedCard({ context }: { context: ThreadTranscript["context"] }) {
  const body = (context?.body ?? {}) as Record<string, unknown>;
  if (context?.kind !== "attention_item") return null;
  const rows: [string, string][] = [
    ["Segment", String(body.segment ?? "")],
    ["Period", [body.reporting_quarter, body.comparison_quarter]
      .filter(Boolean).join(" vs ")],
    ["Measure", String(body.metric_label ?? body.metric ?? "")],
  ].filter(([, value]) => Boolean(value)) as [string, string][];

  return (
    <section
      data-testid="v4-investigation-context"
      className="rounded-lg border border-sky-200 bg-sky-50/60 px-4 py-3"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-sky-800">
        Investigating
      </p>
      <p dir="auto" className="mt-1 text-sm font-medium text-slate-900">
        {String(body.headline ?? "")}
      </p>
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-600">
        {rows.map(([label, value]) => (
          <div key={label} className="flex gap-1.5">
            <dt className="text-slate-500">{label}</dt>
            <dd className="font-medium text-slate-800" dir="auto">{value}</dd>
          </div>
        ))}
      </dl>
      {body.issue ? (
        <p dir="auto" className="mt-2 max-w-[68ch] text-xs text-slate-700">
          {String(body.issue)}
        </p>
      ) : null}
    </section>
  );
}

function Composer({
  onAsk,
  busy,
  mode,
  onMode,
}: {
  onAsk: (question: string) => void;
  busy: boolean;
  mode: RunMode;
  onMode: (mode: RunMode) => void;
}) {
  const [text, setText] = React.useState("");
  const submit = () => {
    const question = text.trim();
    if (!question || busy) return;
    setText("");
    onAsk(question);
  };

  return (
    <div
      data-testid="v4-composer"
      className="sticky bottom-0 z-10 -mx-1 bg-gradient-to-t from-white via-white to-white/0 px-1 pb-4 pt-6"
    >
      <div className="rounded-xl border border-slate-300 bg-white shadow-sm focus-within:border-slate-400">
        <textarea
          data-testid="v4-composer-input"
          dir="auto"
          rows={2}
          value={text}
          disabled={busy}
          placeholder="Ask a follow-up…"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter asks; Shift+Enter is a new line. The same contract every
            // chat surface has trained every reader to expect.
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
          className="w-full resize-none rounded-xl px-4 py-3 text-sm text-slate-900 outline-none disabled:bg-slate-50"
        />
        <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-3 py-2">
          <label className="flex items-center gap-2 text-xs text-slate-500">
            <span>Depth</span>
            <select
              data-testid="v4-composer-mode"
              value={mode}
              onChange={(event) => onMode(event.target.value as RunMode)}
              className="rounded border border-slate-200 px-2 py-1 text-xs"
            >
              <option value="standard">Standard</option>
              <option value="deep">Deep</option>
            </select>
          </label>
          <button
            type="button"
            data-testid="v4-composer-send"
            onClick={submit}
            disabled={busy || !text.trim()}
            className="rounded-lg bg-slate-900 px-4 py-1.5 text-sm font-medium text-white disabled:bg-slate-300"
          >
            {busy ? "Working…" : "Ask"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ThreadHeader({
  title,
  turnCount,
  onRename,
  onHome,
}: {
  title: string;
  turnCount: number;
  onRename: (title: string) => void;
  onHome: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(title);
  React.useEffect(() => setDraft(title), [title]);

  return (
    <header
      data-testid="v4-thread-header"
      className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4"
    >
      <div className="min-w-0">
        {editing ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const next = draft.trim();
              if (next) onRename(next);
              setEditing(false);
            }}
          >
            <input
              data-testid="v4-thread-title-input"
              autoFocus
              dir="auto"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="w-[28rem] max-w-full rounded border border-slate-300 px-2 py-1 text-lg"
            />
            <button
              type="submit"
              data-testid="v4-thread-rename-save"
              className="rounded bg-slate-900 px-3 py-1 text-xs text-white"
            >
              Save
            </button>
          </form>
        ) : (
          <h1
            data-testid="v4-thread-title"
            dir="auto"
            className="truncate text-xl font-semibold text-slate-900"
          >
            {title || "New conversation"}
          </h1>
        )}
        <p className="mt-1 text-xs text-slate-500" data-testid="v4-thread-turns">
          {turnCount} message{turnCount === 1 ? "" : "s"}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          data-testid="v4-thread-rename"
          onClick={() => setEditing((prev) => !prev)}
          className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
        >
          Rename
        </button>
        <button
          type="button"
          data-testid="v4-thread-home"
          onClick={onHome}
          className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
        >
          Cockpit home
        </button>
      </div>
    </header>
  );
}

// ---- the thread ---------------------------------------------------------

export function CockpitV4Thread({
  threadId,
  initialQuestion = "",
  onHome,
}: {
  threadId: string;
  /** Asked once, on open, when the home page handed one over. */
  initialQuestion?: string;
  onHome: () => void;
}) {
  const [transcript, setTranscript] = React.useState<ThreadTranscript | null>(
    null,
  );
  const [loadError, setLoadError] = React.useState("");
  const [live, setLive] = React.useState<
    { question: string; runId: string } | null
  >(null);
  const [view, dispatch] = React.useReducer(reduce, initial());
  const [mode, setMode] = React.useState<RunMode>("standard");
  const [error, setError] = React.useState("");
  const asked = React.useRef(false);
  const resumed = React.useRef(false);
  const bottom = React.useRef<HTMLDivElement | null>(null);

  const load = React.useCallback(async () => {
    try {
      setTranscript(await readThread(threadId));
    } catch (cause) {
      setLoadError(
        cause instanceof Error ? cause.message : "This conversation could not be opened.",
      );
    }
  }, [threadId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  /**
   * Follow a run that is already going: attach the stream, settle, reload.
   *
   * Shared by asking and by RESUMING after a refresh, because the two are the
   * same thing from the moment the run id exists -- and a resumed run that
   * followed a different code path would be a second set of rules about
   * cursors, settlement and acknowledgement.
   */
  const follow = React.useCallback(
    (runId: string) =>
      watch(runId, {
        onEvent: (event) => dispatch({ type: "event", event }),
        onConnectionState: (state) =>
          dispatch({ type: "connection", state }),
        onSettled: async () => {
          try {
            const status = await readStatus(runId);
            dispatch({ type: "settled", status });
            await acknowledge(runId).catch(() => undefined);
          } catch {
            /* the transcript reload below is the authority anyway */
          }
          forgetRun();
          await load();
        },
      }),
    [load],
  );

  const ask = React.useCallback(
    async (question: string) => {
      if (!question.trim()) return;
      setError("");
      // The previous run's panel gives way to this one. Its exchange is
      // already in the transcript by now, so the conversation keeps it.
      await load();
      setLive({ question, runId: "" });
      dispatch({ type: "start", runId: "" });
      try {
        const started = await startRun({ question, mode, threadId });
        setLive({ question, runId: started.run_id });
        dispatch({ type: "start", runId: started.run_id });
        // The pointer a refresh picks the run back up from. The transcript
        // itself is the server's; this is only "which run is still working".
        rememberRun({ runId: started.run_id, threadId, cursor: 0 });
        // The live turn STAYS once the answer arrives. Its process panel is
        // where the stages, their timings and any failed attempt live, and
        // clearing it the moment the answer landed took the trace off the
        // screen at exactly the point a reader wants to check it (§56). The
        // turn it belongs to is filtered out of the reloaded transcript, so
        // the exchange is drawn once.
        return follow(started.run_id);
      } catch (cause) {
        setLive(null);
        setError(
          cause instanceof Error ? cause.message : "The request was not accepted.",
        );
      }
      return undefined;
    },
    [load, mode, threadId],
  );

  // The question the home page handed over, asked exactly once. A ref rather
  // than state: flipping state here would re-run the effect and ask twice,
  // and StrictMode's double mount would do it again.
  React.useEffect(() => {
    if (!initialQuestion || asked.current) return;
    asked.current = true;
    void ask(initialQuestion);
  }, [ask, initialQuestion]);

  /**
   * Pick a run back up after a refresh.
   *
   * A run outlives this page. Reloading while one is working must reconnect
   * to THAT run rather than ask again -- asking again spends the analysis
   * twice and tells the reader nothing about the first one. The status is
   * read first, so a run that settled while the browser was away is settled
   * here rather than followed into a stream that has already ended.
   */
  React.useEffect(() => {
    if (initialQuestion || resumed.current) return;
    resumed.current = true;
    const active = recallRun();
    if (!active || active.threadId !== threadId) return;
    let stop: (() => void) | undefined;
    void (async () => {
      try {
        const status = await readStatus(active.runId);
        if (TERMINAL_RUN_STATES.has(status.state)) {
          forgetRun();
          return;
        }
        setLive({ question: "", runId: active.runId });
        dispatch({ type: "start", runId: active.runId });
        stop = follow(active.runId);
      } catch {
        forgetRun();
      }
    })();
    return () => stop?.();
  }, [follow, initialQuestion, threadId]);

  React.useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcript?.turn_count, live?.question, view.terminal]);

  const rename = React.useCallback(
    async (title: string) => {
      try {
        const renamed = await renameThread(threadId, title);
        setTranscript((prev) =>
          prev ? { ...prev, title: renamed.title } : prev,
        );
      } catch {
        /* a rename that did not take is not shown as if it had */
      }
    },
    [threadId],
  );

  // The exchange that is still on screen as a live run is not drawn a second
  // time from the transcript. Both are the same question and the same answer;
  // the live one additionally carries its process panel.
  const turns = (transcript?.turns ?? [])
    .filter((turn) => !live || turn.run_id !== live.runId)
    .map(settled);
  // "Busy" is about whether a NEW question can be asked, which a finished run
  // does not prevent -- the panel simply stays on screen.
  const busy = Boolean(live) && !view.terminal;

  if (loadError) {
    return (
      <div data-testid="v4-thread-error" className="mx-auto max-w-2xl py-16">
        <p className="text-sm text-rose-700">{loadError}</p>
        <button
          type="button"
          onClick={onHome}
          className="mt-3 text-sm text-sky-700 hover:underline"
        >
          Back to Cockpit home
        </button>
      </div>
    );
  }

  return (
    <div
      data-testid="cockpit-v4-thread"
      data-thread-id={threadId}
      className="mx-auto flex w-full max-w-[90rem] flex-col px-4 py-8 sm:px-6 lg:px-10"
    >
      <ThreadHeader
        title={transcript?.title ?? ""}
        turnCount={turns.length + (live ? 1 : 0)}
        onRename={(title) => void rename(title)}
        onHome={onHome}
      />

      <div className="mt-6 space-y-10">
        <SeedCard context={transcript?.context ?? {}} />

        {turns.map((turn) => (
          <article key={turn.key} className="space-y-4">
            <UserTurn question={turn.question} />
            <AssistantTurn turn={turn} onAsk={(q) => void ask(q)} />
          </article>
        ))}

        {live ? (
          <article className="space-y-4" data-testid="v4-turn-live">
            <UserTurn question={live.question} />
            <ProcessPanel
              view={view}
              onCancel={
                view.runId && !view.terminal
                  ? () => void cancelRun(view.runId).catch(() => undefined)
                  : undefined
              }
              onRetryStatus={
                view.runId
                  ? () =>
                      void readStatus(view.runId)
                        .then((status) =>
                          dispatch({ type: "settled", status }),
                        )
                        .catch(() => undefined)
                  : undefined
              }
            />
            {/*
              The answer lands HERE, under the process panel that produced
              it, and a run that stopped shows the stop in the same place.
              §55: one failed exchange does not wipe the conversation it
              happened in -- the turns before it are untouched, and the
              composer below is still available.
            */}
            {view.terminal ? (
              // The same turn marker a settled exchange carries. This IS
              // the assistant's turn -- it simply still has the process
              // panel that produced it attached above.
              <div data-testid="v4-turn-assistant" className="space-y-4">
                <ResponsePanel
                  view={view}
                  question={live.question}
                  threadId={threadId}
                  onAsk={(q) => void ask(q)}
                />
                {view.response ? (
                  <Visuals
                    tables={view.response.tables ?? []}
                    charts={view.response.charts ?? []}
                  />
                ) : null}
              </div>
            ) : null}
          </article>
        ) : null}

        {error ? (
          <p data-testid="v4-thread-ask-error" className="text-sm text-rose-700">
            {error}
          </p>
        ) : null}
      </div>

      <div ref={bottom} />
      <Composer
        onAsk={(question) => void ask(question)}
        busy={busy}
        mode={mode}
        onMode={setMode}
      />
    </div>
  );
}
