"use client";

/**
 * The Cockpit landing page, as it exists in a V4 runtime.
 *
 * The LAYOUT is the earlier Cockpit's, restored deliberately: a greeting, one
 * wide question box across the workspace, business prompts beneath it, the
 * trace line, then what requires attention and what moved in ECL, then the
 * conversations you can pick back up. That page read like an executive
 * workspace and the narrow centred column did not.
 *
 * The BACKEND is entirely V4 and nothing of the old one came back with the
 * look. `/investigations`, `/agentic/officer`, `/ask/mode`, `/ask/briefing`,
 * `/ask/suggestions` and the V2/V3 diagnostics are not reached from this page
 * — not shimmed, not translated, not caught: never called. The attention
 * sections are the deterministic V4 engine, the drawer is the V4 drawer, and
 * Investigate Further seeds a real V4 thread.
 *
 * A separate component rather than a branch inside the legacy page, because
 * React runs every hook a component declares: guarding the JSX would not stop
 * the legacy Cockpit's requests, and not instantiating it does.
 */

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useWideContent } from "@/components/layout/content-width";

import { AttentionDrawer } from "./attention-drawer";
import { AttentionPanel } from "./attention-panel";
import {
  rememberInvestigation,
  type AttentionItem,
  type RecentThread,
} from "./client";
import { AskBox } from "./ask-box";
import { createThread, type RunMode } from "./client";
import {
  ContinueWhereYouLeftOff,
  useSession,
} from "./continue-where-you-left-off";
import { greeting } from "./greeting";
import { NotInThisRuntime } from "./not-in-this-runtime";

export function CockpitV4Home() {
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  // Operator detail is opt-in through the URL so a demonstration does not
  // show model ids and request sizes on a shared screen by default.
  const operatorView = searchParams.get("operator") === "1";

  const router = useRouter();
  const { name, threads, ready, refresh } = useSession();
  const [open, setOpen] = React.useState<AttentionItem | null>(null);
  const [question, setQuestion] = React.useState(initialQuestion);
  const [mode, setMode] = React.useState<RunMode>("standard");
  const [opening, setOpening] = React.useState(false);
  const [askError, setAskError] = React.useState("");
  const [showPrompts, setShowPrompts] = React.useState(true);

  /**
   * Asking from the home page opens a CONVERSATION.
   *
   * It does not answer here. A page that rendered the answer in place would
   * make the second question feel like starting over, which is exactly what
   * the old experience got right and this one had lost: the answer is never
   * the end, the follow-up is.
   *
   * The question travels in the URL rather than in component state, so a
   * refresh between opening the thread and the first answer does not lose
   * it -- and the thread asks it exactly once.
   */
  const openThread = React.useCallback(
    (threadId: string, ask = "") => {
      const suffix = ask ? `?q=${encodeURIComponent(ask)}` : "";
      router.push(`/cockpit/thread/${encodeURIComponent(threadId)}${suffix}`);
    },
    [router],
  );

  const askFromHome = React.useCallback(
    async (text: string) => {
      const asked = text.trim();
      if (!asked || opening) return;
      setOpening(true);
      setAskError("");
      try {
        const { thread_id } = await createThread();
        openThread(thread_id, asked);
      } catch (cause) {
        setOpening(false);
        setAskError(
          cause instanceof Error
            ? cause.message
            : "The conversation could not be opened.",
        );
      }
    },
    [opening, openThread],
  );
  /** Reopen a real persisted thread: its own page, with its own transcript. */
  const reopen = React.useCallback(
    (thread: RecentThread) => openThread(thread.thread_id),
    [openThread],
  );

  // Two dashboards, wide tables and a chat column: this page IS the
  // width. Every other page keeps the shell default.
  useWideContent();

  const hello = greeting(name);

  return (
    <div
      // A 1728px display was rendering a 1024px ribbon with two empty
      // thirds. The page now takes the workspace it is given up to
      // 1440px; answer PROSE still wraps at 68ch inside it, which is
      // where readability actually lives, while the dashboards and
      // tables get the width they were starved of.
      className="mx-auto w-full max-w-[90rem] px-4 py-10 sm:px-6 lg:px-10"
      data-testid="cockpit-v4-home"
    >
      <header className="space-y-1">
        <h1
          className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-4xl"
          data-testid="cockpit-v4-greeting"
        >
          {hello.salutation}
          {hello.name ? (
            <>
              ,{" "}
              <span className="font-normal italic" data-testid="cockpit-v4-greeting-name">
                {hello.name}
              </span>
            </>
          ) : null}
        </h1>
        <p className="text-base text-slate-500" data-testid="cockpit-v4-prompt-line">
          What&rsquo;s on your mind?
        </p>
      </header>

      <div className="mt-6">
        <AskBox
          question={question}
          onQuestionChange={setQuestion}
          mode={mode}
          onModeChange={setMode}
          onAsk={(text) => void askFromHome(text)}
          busy={opening}
          showPrompts={showPrompts}
          onDismissPrompts={() => setShowPrompts(false)}
        />
        {askError ? (
          <p
            data-testid="cockpit-v4-submit-error"
            className="mt-2 text-sm text-rose-700"
          >
            {askError}
          </p>
        ) : null}
      </div>

      <div className="mt-12">
        <AttentionPanel onOpen={(item) => setOpen(item)} />
      </div>

      <div className="mt-12">
        {ready ? (
          <ContinueWhereYouLeftOff
            threads={threads}
            onOpen={(thread) => void reopen(thread)}
          />
        ) : null}
      </div>

      <AttentionDrawer
        item={open}
        operatorView={operatorView}
        onClose={() => setOpen(null)}
        onInvestigate={(started) => {
          // §9: an investigation OPENS. The seed is already on the thread
          // server-side; what was missing was the reader ever arriving
          // somewhere that looked like an investigation had begun.
          rememberInvestigation({
            threadId: started.threadId,
            itemId: started.item.item_id,
            suggested: started.suggested,
          });
          setOpen(null);
          openThread(started.threadId);
        }}
      />

      <div className="mt-12 space-y-3">
        <NotInThisRuntime
          title="Early Warning"
          what="Live early-warning signals"
        />
        <NotInThisRuntime
          title="Daily briefing"
          what="The portfolio briefing"
        />
      </div>
    </div>
  );
}
