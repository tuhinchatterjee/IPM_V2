"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowLeft,
  Check,
  FolderInput,
  Loader2,
  Pencil,
  Sparkles,
} from "lucide-react";

import { AnswerBlock, FollowUps } from "@/components/ask/answer";
import { ClarificationCard } from "@/components/ask/clarification";
import { Composer } from "@/components/ask/composer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type InvestigationResponse,
  type PlannerMode,
  type ProjectRow,
  type Thread,
  type ThreadMessage,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { useReturnTo, withReturnTo } from "@/lib/return-to";

/**
 * An Investigation: the conversation.
 *
 * The whole screen is one column of exchanges with a composer pinned under it.
 * That is the shape because the conversation IS the work — a question, an
 * answer, the thing you notice in the answer, the next question. A page that
 * made you go back to a search box to ask the next thing would break the only
 * motion that matters.
 *
 * Every answer is rendered by the same `AnswerBlock` used everywhere else, so a
 * follow-up answer looks exactly like a first answer: the sentence, the figures,
 * the analyses used, then CreditProbe's reading of them.
 *
 * Nothing is recomputed on load. Each stored answer is displayed as it was
 * given, with the run it came from — re-running quietly and showing today's
 * number under yesterday's question would be the worst thing this screen could
 * do.
 */
export default function InvestigationThreadPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = React.use(params);
  const threadId = Number(id);

  if (!Number.isFinite(threadId)) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        &ldquo;{id}&rdquo; is not an investigation.
      </Card>
    );
  }
  return <Thread threadId={threadId} />;
}

function Thread({ threadId }: { threadId: number }) {
  const back = useReturnTo({ href: "/investigations", label: "Investigations" });

  const loaded = useAsync(() => api.thread(threadId), [threadId]);
  const projects = useAsync(() => api.projects(), []);
  const mode = useAsync(() => api.askMode(), []);

  // Asking returns the whole updated thread, so the answer is shown from that
  // rather than by re-fetching. `local` holds it; until something is asked, the
  // fetched thread is what is displayed. Deriving it this way rather than
  // copying the fetch into state in an effect keeps one source of truth.
  const [local, setLocal] = React.useState<Thread | null>(null);
  const thread = local ?? loaded.data;

  const [draft, setDraft] = React.useState("");
  const [asking, setAsking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingQuestion, setPendingQuestion] = React.useState("");
  const [savedMessages, setSavedMessages] = React.useState<Set<number>>(
    () => new Set(),
  );

  const projectId = thread?.project_id ?? null;

  const endRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread?.message_count, asking]);

  const ask = React.useCallback(
    async (question: string, period?: { from: string; to: string }) => {
      if (!question.trim() || asking) return;
      setAsking(true);
      setError(null);
      setPendingQuestion(question);
      setDraft("");
      try {
        const turn = await api.askInThread(threadId, question, period);
        setLocal(turn.thread);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setAsking(false);
        setPendingQuestion("");
      }
    },
    [threadId, asking],
  );

  const saveAnswer = React.useCallback(
    async (sequence: number) => {
      try {
        await api.saveAnalysesFromAnswer({
          investigationId: threadId,
          sequence,
          projectId,
        });
        setSavedMessages((current) => new Set(current).add(sequence));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [threadId, projectId],
  );

  if (loaded.loading && !thread) return <Skeleton className="h-96 w-full" />;
  if (loaded.error && !thread) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {loaded.error}
      </Card>
    );
  }
  if (!thread) return null;

  const project =
    projects.data?.projects.find((p) => p.id === thread.project_id) ?? null;
  const settled = settledPeriod(thread);

  return (
    <div className="space-y-7">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href={back.href}>
          <ArrowLeft aria-hidden />
          {back.label}
        </Link>
      </Button>

      <ThreadHeader
        thread={thread}
        project={project}
        projects={projects.data?.projects ?? []}
        settled={settled}
        onChange={setLocal}
      />

      <div className="space-y-9">
        {thread.messages.map((message) => (
          <Exchange
            key={message.id}
            message={message}
            onAsk={ask}
            onSave={() => saveAnswer(message.sequence)}
            saved={savedMessages.has(message.sequence)}
            busy={asking}
            mode={mode.data ?? null}
            onAnswerClarification={(from, to) =>
              ask(previousQuestion(thread.messages, message.sequence), { from, to })
            }
          />
        ))}

        {asking && (
          <div className="space-y-3">
            <UserTurn content={pendingQuestion} />
            <p className="flex items-center gap-2 text-sm text-text-muted">
              <Loader2 className="size-3.5 animate-spin text-accent" aria-hidden />
              Choosing analyses and running them against published data…
            </p>
          </div>
        )}

        <div ref={endRef} />
      </div>

      {error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{error}</Card>
      )}

      {/* The composer is present after every answer, not only at the start. */}
      <div className="sticky bottom-0 -mx-10 bg-canvas px-10 pb-6 pt-4">
        <Composer
          value={draft}
          onChange={setDraft}
          onSubmit={(question) => ask(question)}
          busy={asking}
          suggestions={[]}
          placeholder="Ask a follow-up…"
          modeNote={mode.data?.description}
        />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- header */

function ThreadHeader({
  thread,
  project,
  projects,
  settled,
  onChange,
}: {
  thread: Thread;
  project: ProjectRow | null;
  projects: ProjectRow[];
  settled: string | null;
  onChange: (thread: Thread) => void;
}) {
  const [renaming, setRenaming] = React.useState(false);
  const [title, setTitle] = React.useState(thread.title);
  const [moving, setMoving] = React.useState(false);

  async function rename() {
    setRenaming(false);
    if (title.trim() && title !== thread.title) {
      const updated = await api.renameThread(thread.id, title.trim());
      onChange({ ...thread, title: updated.title });
    }
  }

  async function move(projectId: number | null) {
    setMoving(false);
    const updated = await api.moveThread(thread.id, projectId);
    onChange({ ...thread, project_id: updated.project_id });
  }

  return (
    <header>
      <div className="flex flex-wrap items-start justify-between gap-3">
        {renaming ? (
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={rename}
            onKeyDown={(e) => {
              if (e.key === "Enter") rename();
              if (e.key === "Escape") {
                setTitle(thread.title);
                setRenaming(false);
              }
            }}
            className="min-w-0 flex-1 border-b border-accent bg-transparent text-[24px] font-semibold leading-tight tracking-tight text-text-primary focus:outline-none"
            aria-label="Investigation title"
          />
        ) : (
          <h1 className="min-w-0 text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
            {thread.title}
          </h1>
        )}

        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => setRenaming(true)}>
            <Pencil aria-hidden />
            Rename
          </Button>
          <div className="relative">
            <Button variant="ghost" size="sm" onClick={() => setMoving((m) => !m)}>
              <FolderInput aria-hidden />
              {project ? project.name : "Add to project"}
            </Button>
            {moving && (
              <div className="absolute right-0 top-full z-20 mt-1 w-64 rounded-lg border border-border bg-surface py-1 shadow-lg">
                {projects.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => move(p.id)}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-primary hover:bg-surface-hover"
                  >
                    {p.id === thread.project_id && (
                      <Check className="size-3.5 text-accent" aria-hidden />
                    )}
                    <span className="truncate">{p.name}</span>
                  </button>
                ))}
                {thread.project_id !== null && (
                  <button
                    type="button"
                    onClick={() => move(null)}
                    className="w-full border-t border-border px-3 py-2 text-left text-sm text-text-muted hover:bg-surface-hover"
                  >
                    Remove from project
                  </button>
                )}
                {projects.length === 0 && (
                  <p className="px-3 py-2 text-xs text-text-muted">
                    No projects yet.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
        {project && (
          <Link
            href={withReturnTo(
              `/projects/${project.id}`,
              `/investigations/${thread.id}`,
              thread.title,
            )}
            className="hover:text-accent"
          >
            {project.name}
          </Link>
        )}
        <span>
          {thread.message_count}{" "}
          {thread.message_count === 1 ? "message" : "messages"}
        </span>
        {settled && (
          <span title="Agreed once in this conversation and used for every question since">
            {settled}
          </span>
        )}
      </p>
    </header>
  );
}

/* ------------------------------------------------------------------ messages */

function Exchange({
  message,
  onAsk,
  onSave,
  saved,
  busy,
  mode,
  onAnswerClarification,
}: {
  message: ThreadMessage;
  onAsk: (question: string) => void;
  onSave: () => void;
  saved: boolean;
  busy: boolean;
  mode: PlannerMode | null;
  onAnswerClarification: (from: string, to: string) => void;
}) {
  if (message.role === "user") return <UserTurn content={message.content} />;

  const run = message.payload as InvestigationResponse | undefined;

  // A clarification is part of the conversation, so it is shown in place rather
  // than as an interruption: the thread reads as "I asked, it asked back".
  if (run?.status === "needs_clarification" && run.clarification) {
    return (
      <ClarificationCard
        clarification={run.clarification}
        mode={mode}
        onAnswer={onAnswerClarification}
        busy={busy}
      />
    );
  }

  if (!run || !run.narrative) {
    return (
      <p className="max-w-3xl text-sm leading-relaxed text-text-secondary">
        {message.content}
      </p>
    );
  }

  return (
    <div className="space-y-5">
      <AnswerBlock
        run={run}
        onAsk={onAsk}
        onSave={onSave}
        saved={saved}
        busy={busy}
        compact
      />
    </div>
  );
}

function UserTurn({ content }: { content: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <Sparkles className="mt-1 size-3.5 shrink-0 text-accent" aria-hidden />
      <p className="max-w-3xl text-[15px] font-medium leading-snug text-text-primary">
        {content}
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ helpers */

/** The question a clarification is asking about: the message just before it. */
function previousQuestion(messages: ThreadMessage[], sequence: number): string {
  for (let i = sequence - 1; i >= 0; i -= 1) {
    const message = messages.find((m) => m.sequence === i);
    if (message?.role === "user") return message.content;
  }
  return messages[0]?.content ?? "";
}

/** What this conversation has already agreed, in a phrase. */
function settledPeriod(thread: Thread): string | null {
  const from = thread.context.from_period;
  const to = thread.context.to_period;
  if (typeof from === "string" && typeof to === "string") {
    return `${from} to ${to}`;
  }
  return null;
}

/** Re-exported so the follow-up chips keep one implementation. */
export { FollowUps };
