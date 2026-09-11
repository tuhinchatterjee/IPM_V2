"use client";

/**
 * The Cockpit page, as it exists in a V4 runtime.
 *
 * A separate component rather than a branch inside the legacy page, and that
 * is the whole point: React runs every hook a component declares, so a
 * `useAsync(() => api.askSuggestions())` inside the legacy Cockpit fires the
 * moment that component is instantiated. Guarding the JSX would not stop the
 * request; not instantiating the component does.
 *
 * The result is that a V4 runtime issues exactly the calls the V4 API serves
 * and no others. `/investigations`, `/agentic/officer`, `/ask/mode`,
 * `/ask/briefing`, `/ask/suggestions` and the V2/V3 diagnostics are not
 * reached from this page — not shimmed, not translated, not caught: never
 * called.
 *
 * Below the question box are two analytical sections computed from the pinned
 * release. They are Cockpit's own question — what deteriorated in the
 * recorded book — and not Early Warning's. Clicking one opens the detail
 * drawer; Investigate Further turns it into a seeded conversation.
 */

import * as React from "react";
import { useSearchParams } from "next/navigation";

import { AttentionDrawer } from "./attention-drawer";
import { AttentionPanel } from "./attention-panel";
import {
  forgetInvestigation,
  readAttentionItem,
  rememberInvestigation,
  recallInvestigation,
  type AttentionItem,
} from "./client";
import { CockpitV4, type ActiveInvestigation } from "./cockpit-v4";
import { NotInThisRuntime } from "./not-in-this-runtime";

export function CockpitV4Home() {
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  // Operator detail is opt-in through the URL so a demonstration does not
  // show model ids and request sizes on a shared screen by default.
  const operatorView = searchParams.get("operator") === "1";

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

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 py-8" data-testid="cockpit-v4-home">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-slate-900">
          Cockpit
        </h1>
        <p className="text-sm text-slate-600">
          Ask about the recorded corporate book, or about CreditProbe itself.
          Every figure in an answer is bound to a query that actually ran, and
          you can watch it run.
        </p>
      </header>

      <CockpitV4
        operatorView={operatorView}
        initialQuestion={initialQuestion}
        investigation={investigation}
        onClearInvestigation={() => {
          setInvestigation(null);
          forgetInvestigation();
        }}
      />

      <AttentionPanel onOpen={(item) => setOpen(item)} />

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

      <div className="space-y-3 pt-2">
        <NotInThisRuntime
          title="Recent investigations"
          what="The investigations workspace"
        />
        <NotInThisRuntime
          title="Daily briefing"
          what="The portfolio briefing"
        />
      </div>
    </div>
  );
}
