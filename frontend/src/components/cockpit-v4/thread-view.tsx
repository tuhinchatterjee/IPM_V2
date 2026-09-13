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
  readStatus,
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
import { Markdown } from "./markdown.tsx";
import { Visuals } from "./visuals";

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

function Suggestions({
  questions,
  onAsk,
}: {
  questions: string[];
  onAsk: (question: string) => void;
}) {
  if (!questions.length) return null;
  return (
    <div data-testid="v4-suggestions" className="flex flex-wrap gap-2">
      {questions.map((question) => (
        <button
          key={question}
          type="button"
          dir="auto"
          data-testid="v4-suggestion"
          onClick={() => onAsk(question)}
          className="rounded-full border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
        >
          {question}
        </button>
      ))}
    </div>
  );
}

/**
 * A completed exchange.
 *
 * Executive first: the narrative leads, the visual evidence follows, the
 * suggestions close. Prose wraps at a readable measure; the chart and the
 * table get the workspace, because a twelve-row sector table squeezed into a
 * prose column is the reason people export to Excel.
 */
function AssistantTurn({
  turn,
  onAsk,
}: {
  turn: Settled;
  onAsk: (question: string) => void;
}) {
  const answer = turn.answer;
  const suggestions = (answer.suggested_questions ?? [])
    .map((s) => (typeof s === "string" ? s : s?.question))
    .filter((q): q is string => Boolean(q));

  return (
    <div data-testid="v4-turn-assistant" className="space-y-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        CreditProbe
      </p>
      <div className="max-w-[68ch] text-sm leading-relaxed text-slate-800">
        <Markdown source={answer.narrative ?? ""} />
      </div>

      <Visuals tables={answer.tables ?? []} charts={answer.charts ?? []} />

      {(answer.limitations ?? []).length ? (
        <ul
          data-testid="v4-limitations"
          className="max-w-[68ch] list-disc space-y-1 pl-5 text-xs text-amber-900"
        >
          {answer.limitations.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
      ) : null}

      <AnswerActions runId={turn.runId} question={turn.question} />
      <Suggestions questions={suggestions} onAsk={onAsk} />
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
  const [live, setLive] = React.useState<{ question: string } | null>(null);
  const [view, dispatch] = React.useReducer(reduce, initial());
  const [mode, setMode] = React.useState<RunMode>("standard");
  const [error, setError] = React.useState("");
  const asked = React.useRef(false);
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

  const ask = React.useCallback(
    async (question: string) => {
      if (!question.trim()) return;
      setError("");
      setLive({ question });
      dispatch({ type: "start", runId: "" });
      try {
        const started = await startRun({ question, mode, threadId });
        dispatch({ type: "start", runId: started.run_id });
        const stop = watch(started.run_id, {
          onEvent: (event) => dispatch({ type: "event", event }),
          onConnectionState: (state) =>
            dispatch({ type: "connection", state }),
          onSettled: async () => {
            try {
              const status = await readStatus(started.run_id);
              dispatch({ type: "settled", status });
              await acknowledge(started.run_id).catch(() => undefined);
            } catch {
              /* the transcript reload below is the authority anyway */
            }
            await load();
            setLive(null);
          },
        });
        return stop;
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

  const turns = (transcript?.turns ?? []).map(settled);
  const busy = Boolean(live);

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
            {view.terminal && view.state !== "COMPLETED" ? (
              <ResponsePanel view={view} />
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
