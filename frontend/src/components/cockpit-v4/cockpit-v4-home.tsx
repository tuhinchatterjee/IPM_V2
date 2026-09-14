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
import { EclPanel } from "./ecl-panel";
import { DomainSwitch, recallDomain, rememberDomain } from "./domain-switch";
import {
  rememberInvestigation,
  type AttentionItem,
  type RecentThread,
} from "./client";
import { AskBox } from "./ask-box";
import {
  rememberRun,
  startRun,
  readDomains,
  type DomainAvailability,
  type DomainId,
  type RunMode,
} from "./client";
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
  const [traceHelp, setTraceHelp] = React.useState(false);
  // Which book Home is showing. Read once from the server, so a runtime with
  // one domain unpublished disables that control and says why rather than
  // offering a switch that cannot work.
  const [domains, setDomains] =
    React.useState<DomainAvailability | null>(null);
  const [domain, setDomain] = React.useState<DomainId>("corporate");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const available = await readDomains();
        if (!live) return;
        setDomains(available);
        const remembered = recallDomain();
        const usable = remembered && available.ready.includes(remembered)
          ? remembered
          : available.default_domain;
        setDomain(usable);
      } catch {
        // A runtime that cannot answer which books it has still answers
        // questions about the default one.
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const chooseDomain = React.useCallback((next: DomainId) => {
    setDomain(next);
    rememberDomain(next);
  }, []);

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
    (threadId: string) => {
      router.push(`/cockpit/thread/${encodeURIComponent(threadId)}`);
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
        // The run creates its own thread, pinned to the selected book.
        //
        // It used to create the thread first and then start a run in it,
        // which quietly discarded the domain: `startRun` reads it only when
        // OPENING a conversation, so a retail question would have opened a
        // corporate thread and read corporate relations. Asking the run to
        // make the thread is what keeps the selection and the evidence the
        // same decision.
        //
        // The run also STARTS here, before the navigation, so the question
        // never reaches the URL and a reload cannot ask it a second time --
        // the thread finds a run already going and follows it.
        const started = await startRun({
          question: asked, mode, domain,
        });
        rememberRun({
          runId: started.run_id, threadId: started.thread_id, cursor: 0,
          question: asked,
        });
        openThread(started.thread_id);
      } catch (cause) {
        setOpening(false);
        setAskError(
          cause instanceof Error
            ? cause.message
            : "The conversation could not be opened.",
        );
      }
    },
    [opening, openThread, domain, mode],
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
        {/*
          §24: beside the Ask box, because choosing a book is part of asking
          the question rather than a setting somewhere else. It changes which
          release the server opens, not which rows a shared answer shows.
        */}
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <DomainSwitch
            availability={domains}
            value={domain}
            onChange={chooseDomain}
          />
          <span className="text-xs text-slate-500">
            Saudi Arabia · SAR million · monthly
          </span>
        </div>
        <AskBox
          question={question}
          onQuestionChange={setQuestion}
          mode={mode}
          onModeChange={setMode}
          onAsk={(text) => void askFromHome(text)}
          busy={opening}
          showPrompts={showPrompts}
          onDismissPrompts={() => setShowPrompts(false)}
          domain={domain}
        />
        {/*
          §2A: the landing page says what an answer will carry, before one
          exists. It belonged to the in-page Ask component, which the thread
          replaced -- and it is a promise about every answer, not about one
          run, so it lives with the box that makes the promise.
        */}
        <p className="mt-3 text-xs text-slate-500"
           data-testid="cockpit-v4-trace-note">
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
            className="mt-2 rounded border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600"
          >
            Every figure in an answer is bound to a query that actually ran.
            The process panel in the conversation shows each stage as it
            happens — the metadata read, the query validated and bound, the
            rows returned, any attempt that failed — and each stored result
            can be opened from the answer. Nothing is asserted that has no
            evidence behind it.
          </p>
        ) : null}
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
        <AttentionPanel onOpen={(item) => setOpen(item)} domain={domain} />
      </div>

      <div className="mt-12">
        <EclPanel domain={domain} />
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
