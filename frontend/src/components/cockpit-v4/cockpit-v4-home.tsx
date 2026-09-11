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
import { useSearchParams } from "next/navigation";

import { AttentionDrawer } from "./attention-drawer";
import { AttentionPanel } from "./attention-panel";
import {
  forgetInvestigation,
  readAttentionItem,
  readThread,
  rememberInvestigation,
  recallInvestigation,
  type AttentionItem,
  type RecentThread,
} from "./client";
import { CockpitV4, type ActiveInvestigation } from "./cockpit-v4";
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

  const { name, threads, ready, refresh } = useSession();
  const [open, setOpen] = React.useState<AttentionItem | null>(null);
  const [investigation, setInvestigation] =
    React.useState<ActiveInvestigation | null>(null);
  // A ref, for the same reason the run replay uses one: flipping state inside
  // the effect would re-run it, and StrictMode's double mount would then fetch
  // the item twice.
  const restored = React.useRef(false);

  // Come back to the same investigation after a reload. The thread and its
  // seed are on the server; only the pointer was in this tab.
  React.useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const remembered = recallInvestigation();
    if (!remembered) return;
    void (async () => {
      try {
        const { item } = await readAttentionItem(remembered.itemId);
        setInvestigation({
          threadId: remembered.threadId,
          item,
          suggested: remembered.suggested,
        });
      } catch {
        forgetInvestigation();
      }
    })();
  }, []);

  /** Reopen a real persisted thread, with its seed when it had one. */
  const reopen = React.useCallback(async (thread: RecentThread) => {
    try {
      const loaded = await readThread(thread.thread_id);
      const body = loaded.context?.body as
        | { item_id?: string }
        | undefined;
      if (loaded.context?.kind === "attention_item" && body?.item_id) {
        const { item } = await readAttentionItem(body.item_id);
        const resumed = {
          threadId: thread.thread_id,
          item,
          suggested:
            (item.drilldown?.suggested_questions as string[] | undefined) ?? [],
        };
        setInvestigation(resumed);
        rememberInvestigation({
          threadId: resumed.threadId,
          itemId: item.item_id,
          suggested: resumed.suggested,
        });
      }
    } catch {
      /* a thread that cannot be read is not reopened, and nothing is faked */
    }
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, []);

  const hello = greeting(name);

  return (
    <div
      className="mx-auto w-full max-w-5xl px-4 py-10 sm:px-6 lg:px-8"
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
        <CockpitV4
          operatorView={operatorView}
          initialQuestion={initialQuestion}
          investigation={investigation}
          onClearInvestigation={() => {
            setInvestigation(null);
            forgetInvestigation();
          }}
          onSettled={() => void refresh()}
        />
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
          setInvestigation(started);
          rememberInvestigation({
            threadId: started.threadId,
            itemId: started.item.item_id,
            suggested: started.suggested,
          });
          setOpen(null);
          if (typeof window !== "undefined") {
            window.scrollTo({ top: 0, behavior: "smooth" });
          }
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
