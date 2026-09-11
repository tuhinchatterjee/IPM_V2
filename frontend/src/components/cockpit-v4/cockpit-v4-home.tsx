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
 */

import * as React from "react";
import { useSearchParams } from "next/navigation";

import { CockpitV4 } from "./cockpit-v4";
import { NotInThisRuntime } from "./not-in-this-runtime";

export function CockpitV4Home() {
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q") ?? "";
  // Operator detail is opt-in through the URL so a demonstration does not
  // show model ids and request sizes on a shared screen by default.
  const operatorView = searchParams.get("operator") === "1";

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 py-8" data-testid="cockpit-v4-home">
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

      <CockpitV4 operatorView={operatorView} initialQuestion={initialQuestion} />

      <div className="space-y-3 pt-4">
        <NotInThisRuntime
          title="Needs attention"
          what="The risk-case and early-warning queue"
        />
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
