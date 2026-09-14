"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Composer } from "@/components/ask/composer";
import { type ProgressDocument } from "@/components/agentic/steps";
import { api, type EarlyWarningV2Answer } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { chartFor, showsChart, type EwsScope } from "./chart-rules";
import { TurnProgress } from "./ews-progress";
import { answerOf, useEwsTurn } from "./use-turn";
import { errorFor, isReconnecting, type Turn } from "./turn";
import * as store from "./thread-store";
import { TrendChart, CategoryBarChart } from "@/components/analytics/charts";

/**
 * The Early Warning chat: a conversation, not a form with answers under it.
 *
 * What changed, and why
 * ---------------------
 * It used to be a box at the top of the dashboard with answer cards piling
 * up beneath it, newest first, while the box stayed where it was. Two things
 * were wrong with that. The reader had to look UP to see the newest answer
 * and DOWN to ask the next question, which is the opposite of every chat
 * anybody uses. And nothing appeared at all until the turn finished — forty
 * to seventy-five seconds of a composer that had gone quiet.
 *
 * So: an empty state with a composer near the top and some suggestions, and
 * the moment a question is asked, a thread. The question appears at once,
 * the progress panel appears under it at once, the composer moves to the
 * bottom and stays there, and answers append above it in the order they were
 * asked.
 *
 * The turn's state comes from the backend — see `turn.ts` and `use-turn.ts`.
 * The browser no longer decides that an analysis has failed because a socket
 * took longer than a minute.
 */
/**
 * A remembered turn, read back as the settled Entry it was.
 *
 * `completed` because only a settled turn is ever remembered: a turn still
 * running was never written down, so there is no state to restore it into
 * other than the one it reached.
 */
function restored(
  remembered: store.RememberedTurn,
  threadId: string,
): Entry {
  return {
    turn: {
      id: remembered.id,
      threadId,
      question: remembered.question,
      state: "completed",
      answer: remembered.answer ?? null,
      failure: "",
      missedPolls: 0,
      elapsedMs: 0,
      progress: remembered.progress ?? null,
    },
    answer: (remembered.answer as EarlyWarningV2Answer | null) ?? null,
    progress: (remembered.progress as ProgressDocument | null) ?? null,
  };
}

type Entry = {
  /** The turn this entry is, while it runs and after it settles. */
  turn: Turn;
  answer: EarlyWarningV2Answer | null;
  progress: ProgressDocument | null;
};

export function EarlyWarningChat({
  customerId,
  uiState,
  onOpenBorrower,
  /** What the dashboard was showing when this thread began, if anything. */
  scopeLabel,
  /** The same scope, as the governed FilterSpec the dashboard and the export
   *  use. Sent with the question so the answer is about the population the
   *  reader is looking at rather than the whole book. */
  dashboardScope,
}: {
  /** The obligor the screen is currently about, so "what should I do?"
   *  is answered about that obligor rather than about the book. */
  customerId?: string | null;
  /**
   * Where the reader is: the band filter, the level, the selected segment.
   * Navigation context, sent alongside the analytical summary rather than
   * folded into it — a screen rebuilt from a prose summary is sometimes
   * wrong, and this one already knows exactly where it is.
   */
  uiState?: Record<string, unknown>;
  onOpenBorrower?: (customerId: string) => void;
  scopeLabel?: string | null;
  dashboardScope?: Record<string, unknown>;
}) {
  const suggestions = useAsync(() => api.earlyWarningV2Suggestions(), []);
  const [question, setQuestion] = React.useState("");
  const { turn, progress, elapsedMs, start, clear } = useEwsTurn();

  /**
   * The thread this screen is showing, and everything it remembers.
   *
   * §4.7. The thread used to live in component state under an id React
   * generated on mount: open a borrower, press Back, and four questions and
   * their answers were gone — not archived, GONE, with no trace they had
   * existed. So the thread has an id in the address, and its turns are kept
   * against that id for as long as the tab is open.
   *
   * Restored on the first render, from the address, so a Back that returns
   * here returns to the conversation rather than to an empty box.
   */
  const [threadId, setThreadId] = React.useState(() => {
    if (typeof window === "undefined") return store.newThreadId(0);
    return store.threadFromQuery(window.location.search) || store.newThreadId();
  });
  const [entries, setEntries] = React.useState<Entry[]>(() => {
    if (typeof window === "undefined") return [];
    const held = store.recall(store.threadFromQuery(window.location.search));
    return (held?.turns ?? []).map((r) => restored(r, held?.id ?? ""));
  });

  /**
   * The thread's analytical context, as the server last wrote it, handed
   * straight back on the next turn. Stored rather than reconstructed: the
   * server is what decided it, and a client that rebuilt its own version
   * would be a second thread quietly disagreeing with the first.
   */
  const summary = React.useRef<Record<string, unknown> | undefined>(undefined);

  /**
   * The scope this thread is asked in, taken once and then held.
   *
   * §42: snapshotted at thread start. A thread whose scope followed the live
   * filter would make its own history unreadable — the answer three turns up
   * was about the population of three turns ago, and re-scoping it now would
   * silently restate what it said. So the snapshot is taken when the FIRST
   * question is asked, and only a new thread takes a new one.
   *
   * Held in state rather than a ref, and written in the ask handler rather
   * than during render: taking the snapshot is an event, and the moment it
   * happens is exactly the moment the reader presses Ask.
   */
  const [asked, setAsked] = React.useState<{
    spec: Record<string, unknown> | undefined;
    label: string;
  } | null>(() => {
    if (typeof window === "undefined") return null;
    const held = store.recall(store.threadFromQuery(window.location.search));
    return held?.scope ? { spec: held.scope.spec, label: held.scope.label } : null;
  });
  const scope = asked ?? { spec: dashboardScope, label: scopeLabel ?? "" };

  // Restore the server's rolling summary too, so a thread walked back to
  // carries on rather than starting over under the same heading.
  React.useEffect(() => {
    const held = store.recall(threadId);
    if (held?.summary && summary.current === undefined) {
      summary.current = held.summary;
    }
  }, [threadId]);

  const pane = React.useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = React.useState(true);

  // Follow the conversation while the reader is at the bottom of it, and
  // stop the moment they scroll up to read something. Yanking somebody back
  // down mid-sentence is worse than not scrolling at all.
  React.useEffect(() => {
    if (!pinned) return;
    pane.current?.scrollTo({ top: pane.current.scrollHeight });
  }, [entries, turn, progress, pinned]);

  const onScroll = React.useCallback(() => {
    const node = pane.current;
    if (!node) return;
    const slack = node.scrollHeight - node.scrollTop - node.clientHeight;
    setPinned(slack < 80);
  }, []);

  const ask = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || (turn && turn.state === "running")) return;
      setQuestion("");
      setPinned(true);
      // The thread's scope, fixed here and not moved again until a new
      // thread is started.
      const inScope = asked ?? { spec: dashboardScope, label: scopeLabel ?? "" };
      if (!asked) setAsked(inScope);
      const settled = await start(trimmed, {
        threadId,
        customerId,
        uiState: { ...(uiState ?? {}), customer_id: customerId ?? undefined },
        dashboardScope: inScope.spec,
        rollingSummary: summary.current,
      });
      if (!settled) return;
      const answer = answerOf(settled);
      if (answer?.rolling_summary) summary.current = answer.rolling_summary;
      const entry: Entry = {
        turn: settled,
        answer,
        progress:
          (answer?.progress as ProgressDocument | undefined) ??
          (settled.progress as ProgressDocument | null) ??
          null,
      };
      setEntries((prior) => {
        const next = [...prior, entry];
        // Remembered as it settles, so a Back from a borrower drilldown
        // returns to the conversation and not to an empty composer.
        store.remember({
          id: threadId,
          turns: next.map((e) => ({
            id: e.turn.id, question: e.turn.question,
            answer: e.answer, progress: e.progress,
          })),
          summary: summary.current,
          scope: inScope,
        });
        return next;
      });
      clear();
    },
    [turn, start, clear, threadId, customerId, uiState, asked,
     dashboardScope, scopeLabel],
  );

  const newThread = React.useCallback(() => {
    clear();
    setEntries([]);
    setQuestion("");
    setPinned(true);
    // A NEW id, not a cleared one. The thread just left stays where it is,
    // so Back reaches it — "New thread" starts a conversation, it does not
    // destroy the last one.
    const fresh = store.newThreadId();
    setThreadId(fresh);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.search = store.queryWithThread(url.search, fresh);
      window.history.pushState(window.history.state, "", url);
    }
    // A new thread carries no memory of the last one. The server is handed
    // no rolling summary and a different thread id, so "those names" in the
    // first question of a new thread resolves to nothing — which is correct.
    summary.current = undefined;
    // A new thread also takes a new scope: it is about whatever the reader
    // is looking at now, not about what they were looking at an hour ago.
    setAsked(null);
  }, [clear]);

  /**
   * The thread enters the address when it starts carrying something.
   *
   * Pushed, so Back leaves the thread and returns to the screen as it was —
   * and a Back INTO it (from a borrower, from another page) finds it again.
   * An empty thread is not pushed: a reader who opened the page and typed
   * nothing has taken no step to walk back from.
   */
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    if (entries.length === 0 && turn === null) return;
    if (store.threadFromQuery(window.location.search) === threadId) return;
    const url = new URL(window.location.href);
    url.search = store.queryWithThread(url.search, threadId);
    window.history.pushState(window.history.state, "", url);
  }, [entries.length, turn, threadId]);

  // The address is what Back and Forward move, so walking to another thread
  // is walking to another conversation.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const walked = () => {
      const walkedTo = store.threadFromQuery(window.location.search);
      if (!walkedTo || walkedTo === threadId) return;
      const held = store.recall(walkedTo);
      setThreadId(walkedTo);
      setAsked(held?.scope
        ? { spec: held.scope.spec, label: held.scope.label } : null);
      summary.current = held?.summary;
      setEntries((held?.turns ?? []).map((r) => restored(r, walkedTo)));
    };
    window.addEventListener("popstate", walked);
    return () => window.removeEventListener("popstate", walked);
  }, [threadId]);

  const inThread = entries.length > 0 || turn !== null;
  const running = turn?.state === "running";
  const liveError = errorFor(turn, turn?.id ?? "");

  const composer = (
    <Composer
      value={question}
      onChange={setQuestion}
      onSubmit={(q) => void ask(q)}
      busy={running}
      suggestions={
        inThread ? [] : (suggestions.data?.questions ?? []).slice(0, 3)
      }
      placeholder="Ask about this portfolio. Try: which layer moved most?"
    />
  );

  if (!inThread) {
    // The landing state: the composer where the reader is already looking,
    // and the questions this product can actually answer.
    return (
      <section className="space-y-3" data-testid="ews-chat-empty">
        {composer}
        {scope.label && <ScopeChip label={scope.label} />}
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3" data-testid="ews-chat-thread">
      <div className="flex items-center justify-between gap-2">
        {scope.label ? <ScopeChip label={scope.label} /> : <span />}
        <button
          type="button"
          onClick={newThread}
          className="rounded-md border border-border px-2.5 py-1 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent"
        >
          New thread
        </button>
      </div>

      <div
        ref={pane}
        onScroll={onScroll}
        className="relative max-h-[60vh] space-y-3 overflow-y-auto pr-1"
      >
        {entries.map((entry) => (
          <React.Fragment key={entry.turn.id || entry.turn.question}>
            <UserMessage text={entry.turn.question} />
            {entry.answer ? (
              <Answer
                question={entry.turn.question}
                answer={entry.answer}
                progress={entry.progress}
                onAsk={(q) => void ask(q)}
                onOpenBorrower={onOpenBorrower}
              />
            ) : (
              <TurnFailed turn={entry.turn} onRetry={(q) => void ask(q)} />
            )}
          </React.Fragment>
        ))}

        {turn && (
          <>
            <UserMessage text={turn.question} />
            {running ? (
              <div className="space-y-2">
                <TurnProgress turnKey={null} finished={progress} />
                {progress === null && (
                  <Card className="p-3 text-sm text-text-muted">
                    Starting the analysis…
                  </Card>
                )}
                {isReconnecting(turn) && (
                  <p className="text-xs text-text-muted">
                    Reconnecting… the analysis is still running.
                  </p>
                )}
                <p className="text-[11px] text-text-muted">
                  {(elapsedMs / 1000).toFixed(1)}s
                </p>
              </div>
            ) : (
              liveError && (
                <TurnFailed turn={turn} onRetry={(q) => void ask(q)} />
              )
            )}
          </>
        )}
      </div>

      {!pinned && (
        <button
          type="button"
          onClick={() => {
            setPinned(true);
            pane.current?.scrollTo({ top: pane.current.scrollHeight });
          }}
          className="self-center rounded-full border border-border bg-surface px-3 py-1 text-xs text-text-secondary shadow-sm hover:border-accent hover:text-accent"
        >
          Jump to latest
        </button>
      )}

      {/* The composer, at the bottom, where every chat anybody uses puts it. */}
      <div className="sticky bottom-0 border-t border-border bg-surface pt-3">
        {composer}
      </div>
    </section>
  );
}

/** What the reader asked, shown the moment they ask it. */
function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[80%] rounded-lg bg-surface-hover px-3 py-2 text-sm text-text-primary">
        {text}
      </p>
    </div>
  );
}

/**
 * The one red box, and only where the BACKEND said the turn failed.
 *
 * Scoped to its turn, which is the other half of the timeout defect: an
 * error that belonged to the screen outlived the turn that caused it, so a
 * later successful answer appeared under an earlier turn's warning.
 */
function TurnFailed({
  turn,
  onRetry,
}: {
  turn: Turn;
  onRetry: (question: string) => void;
}) {
  return (
    <Card className="space-y-2 border-negative/40 p-3">
      <p className="text-sm text-negative">
        {turn.failure || "CreditProbe could not complete this analysis."}
      </p>
      <button
        type="button"
        onClick={() => onRetry(turn.question)}
        className="rounded-md border border-border px-2.5 py-1 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent"
      >
        Retry
      </button>
    </Card>
  );
}

/**
 * What the dashboard was narrowed to when this thread began.
 *
 * Shown, not implied. A reader who filtered to High-and-above obligors in
 * Contracting and then asked "how many are deteriorating?" is owed a visible
 * statement that the answer is about those and not about the book -- and a
 * thread they come back to tomorrow is owed it more, not less.
 */
function ScopeChip({ label }: { label: string }) {
  return (
    <p
      className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary"
      data-testid="ews-chat-scope"
    >
      <span className="text-text-muted">Asked about</span>
      {label}
    </p>
  );
}

function Answer({
  question,
  answer,
  progress,
  onAsk,
  onOpenBorrower,
}: {
  question: string;
  answer: EarlyWarningV2Answer;
  progress?: ProgressDocument | null;
  onAsk: (question: string) => void;
  onOpenBorrower?: (customerId: string) => void;
}) {
  const scope = (answer.scope ?? "") as EwsScope;
  const rows = answer.facts?.rows ?? [];
  const kind = answer.answered ? chartFor(scope) : null;

  if (answer.redirected) {
    return (
      <RedirectCard
        question={question}
        answer={answer}
        progress={progress}
        onAsk={onAsk}
      />
    );
  }

  return (
    <Card className="space-y-3 p-4">
      <p className="text-xs text-text-muted">{question}</p>
      {/* What CreditProbe did, collapsed to one line and reopenable. §17. */}
      <TurnProgress turnKey={null} finished={progress ?? null} />
      <p className="text-[15px] font-medium leading-relaxed text-text-primary">
        {answer.direct}
      </p>
      {answer.complete === false && (
        <p className="rounded-md border border-warning/40 bg-warning-muted/30 px-2.5 py-1.5 text-xs text-text-secondary">
          This answer is partial. The parts it could not cover are named in the
          limits below, rather than left for you to notice.
        </p>
      )}
      {answer.interpretation && (
        <div className="border-l-2 border-accent/50 pl-3">
          <p className="meta mb-1 text-text-muted">CreditProbe interpretation</p>
          <p className="text-sm leading-relaxed text-text-secondary">
            {answer.interpretation}
          </p>
        </div>
      )}
      {answer.points && answer.points.length > 0 && (
        <ul className="space-y-1.5">
          {answer.points.map((point, i) => (
            <li key={i} className="text-sm leading-relaxed text-text-secondary">
              {point}
            </li>
          ))}
        </ul>
      )}

      {showsChart(scope) && kind && <AnswerChart kind={kind} rows={rows} />}

      {answer.drivers && answer.drivers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {answer.drivers.slice(0, 5).map((d) => (
            <Badge key={d.code} variant="outline">
              {d.code} {d.name} {d.score.toFixed(0)}
            </Badge>
          ))}
        </div>
      )}

      {rows.length > 0 && onOpenBorrower && (
        <div className="flex flex-wrap gap-1.5">
          {rows
            .filter((r) => typeof r.customer_id === "string")
            .slice(0, 5)
            .map((r) => (
              <button
                key={String(r.customer_id)}
                type="button"
                onClick={() => onOpenBorrower(String(r.customer_id))}
                className="rounded-md border border-border px-2 py-1 text-xs text-accent hover:bg-surface-hover"
              >
                {String(r.customer_name ?? r.customer_id)}
              </button>
            ))}
        </div>
      )}

      {answer.follow_ups && answer.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-t border-border pt-2.5">
          {answer.follow_ups.slice(0, 4).map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onAsk(q)}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {answer.facts?.caveats && answer.facts.caveats.length > 0 && (
        <p className="text-[11px] leading-relaxed text-text-muted">
          {answer.facts.caveats.join(" ")}
        </p>
      )}
    </Card>
  );
}

/** The chart, when the answer is genuinely about shape. */
function AnswerChart({
  kind,
  rows,
}: {
  kind: NonNullable<ReturnType<typeof chartFor>>;
  rows: Record<string, unknown>[];
}) {
  if (kind === "movement" && rows.length >= 2) {
    return (
      <CategoryBarChart
        data={rows.map((r) => ({
          label: String(r.name ?? r.layer ?? ""),
          points: Number(r.points_contributed ?? 0),
        }))}
        xKey="label"
        series={[{ key: "points", label: "Points contributed", slot: 0 }]}
        height={180}
      />
    );
  }
  if (kind === "trend" && rows.length >= 3) {
    return (
      <TrendChart
        data={rows.map((r) => ({
          period: String(r.snapshot_month ?? r.period ?? ""),
          ews: Number(r.ews_score ?? 0),
        }))}
        xKey="period"
        series={[{ key: "ews", label: "EWS", slot: 0 }]}
        height={180}
        area
      />
    );
  }
  if (rows.length >= 2) {
    return (
      <CategoryBarChart
        data={rows.slice(0, 10).map((r) => ({
          label: String(r.customer_name ?? r.label ?? r.segment ?? ""),
          score: Number(r.ews_score ?? r.mean_ews ?? r.portfolio_ews ?? 0),
        }))}
        xKey="label"
        series={[{ key: "score", label: "EWS", slot: 0 }]}
        height={200}
      />
    );
  }
  return null;
}

/**
 * Another functionality owns this question.
 *
 * Rendered as its own kind of answer rather than as a thin one, because it
 * IS a different thing: nothing was analysed, and the reader needs to see
 * that rather than wonder whether the numbers are missing or absent. The
 * alternatives are the useful half — each one is a question this domain can
 * answer, checked against the live field dictionary before it was offered,
 * so clicking one always lands somewhere.
 */
function RedirectCard({
  question,
  answer,
  progress,
  onAsk,
}: {
  question: string;
  answer: EarlyWarningV2Answer;
  progress?: ProgressDocument | null;
  onAsk: (question: string) => void;
}) {
  return (
    <Card className="space-y-3 border-accent/30 p-4">
      <p className="text-xs text-text-muted">{question}</p>
      {/* The routing decision, visible: four stages ran and none of them
          touched the Early Warning data. §10. */}
      <TurnProgress turnKey={null} finished={progress ?? null} />
      <div className="flex items-baseline gap-2">
        <Badge variant="info">{answer.selected_name ?? "Another product"}</Badge>
        <p className="text-[15px] font-medium leading-relaxed text-text-primary">
          {answer.direct}
        </p>
      </div>
      {answer.interpretation && (
        <p className="text-sm leading-relaxed text-text-secondary">
          {answer.interpretation}
        </p>
      )}
      {answer.alternatives && answer.alternatives.length > 0 && (
        <div className="space-y-1.5 border-t border-border pt-2.5">
          <p className="meta text-text-muted">What I can answer instead</p>
          {answer.alternatives.map((option) => (
            <button
              key={option.question}
              type="button"
              onClick={() => onAsk(option.question)}
              className="block w-full rounded-md border border-border px-2.5 py-1.5 text-left text-xs transition-colors hover:border-accent hover:bg-surface-hover"
            >
              <span className="text-accent">{option.question}</span>
              <span className="mt-0.5 block text-text-muted">
                {option.because}
              </span>
            </button>
          ))}
        </div>
      )}
      {answer.caveats && answer.caveats.length > 0 && (
        <p className="text-[11px] leading-relaxed text-text-muted">
          {answer.caveats.join(" ")}
        </p>
      )}
    </Card>
  );
}
