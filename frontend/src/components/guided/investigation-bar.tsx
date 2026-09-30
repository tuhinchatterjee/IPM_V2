"use client";

/**
 * The investigation path and next-best questions, inside an ordinary Cockpit
 * thread that started from a Requires Attention card.
 *
 * Shows where the banker is -- Issue → Evidence → Driver → Cohort → Finding →
 * Scenario/Decision -- and 2-5 grounded next questions. A chip is submitted
 * through the thread's OWN `ask` (the same path as typing), after its click is
 * recorded with the suggestion's rationale for the trace. The composer below
 * stays free-form: nobody is trapped in a wizard.
 */

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, ChevronRight, Circle, FlaskConical, Info } from "lucide-react";

import {
  guidedEnabled,
  readInvestigationByThread,
  recordStep,
  type InvestigationState,
  type Suggestion,
} from "@/lib/workspace/guided";
import { cn } from "@/lib/utils";

export function InvestigationBar({
  threadId,
  busy,
  turnCount,
  onAsk,
}: {
  threadId: string;
  busy: boolean;
  turnCount: number;
  onAsk: (question: string) => void;
}) {
  const [state, setState] = React.useState<InvestigationState | null>(null);
  const [showWhy, setShowWhy] = React.useState<string>("");
  const params = useSearchParams();
  const router = useRouter();
  const autoAsked = React.useRef(false);
  const enabled = guidedEnabled();

  React.useEffect(() => {
    if (!enabled) return;
    readInvestigationByThread(threadId)
      .then(setState)
      .catch(() => setState(null));
  }, [threadId, turnCount, busy, enabled]);

  // A chip clicked on the Cockpit home arrives as `?ask=`: submit it once,
  // through the thread's own ask, then drop the parameter.
  React.useEffect(() => {
    if (!enabled || autoAsked.current) return;
    const pending = params.get("ask");
    if (!pending) return;
    autoAsked.current = true;
    router.replace(`/cockpit/thread/${threadId}`);
    onAsk(pending);
  }, [params, onAsk, router, threadId, enabled]);

  if (!enabled || !state || !state.investigation_id) return null;

  async function choose(s: Suggestion) {
    if (!state?.investigation_id) return;
    await recordStep(state.investigation_id, {
      suggestion_id: s.suggestion_id,
      kind: s.type,
      question: s.exact_request,
    }).catch(() => undefined);
    if (s.type === "run_whatif") {
      router.push(`/what-if?cohort=${encodeURIComponent(state.cohort_id ?? "")}&from=${encodeURIComponent(threadId)}&suggest=${encodeURIComponent(s.exact_request)}`);
      return;
    }
    if (s.type === "freeze_cohort") {
      // Already frozen when the investigation opened; show where it lives.
      router.push(`/what-if?cohort=${encodeURIComponent(state.cohort_id ?? "")}`);
      return;
    }
    if (s.type === "save_share_monitor") {
      router.push(`/lenses?from_investigation=${encodeURIComponent(state.investigation_id)}`);
      return;
    }
    onAsk(s.exact_request);
  }

  const suggestions = state.suggestions?.primary ?? [];
  return (
    <section className="rounded-xl border border-border bg-surface p-3" data-testid="investigation-bar" aria-label="Investigation path">
      <ol className="flex flex-wrap items-center gap-1 text-xs" data-testid="investigation-path">
        {(state.path ?? []).map((step, i) => (
          <li key={step.step} className="flex items-center gap-1" data-step={step.step} data-status={step.status}>
            {i > 0 && <ChevronRight className="h-3 w-3 text-text-muted" />}
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
                step.status === "done" ? "bg-positive-muted text-positive" : step.status === "in_progress" ? "bg-warning-muted text-warning" : "bg-surface-sunken text-text-muted",
              )}
              title={step.detail}
            >
              {step.status === "done" ? <Check className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
              {step.step}
            </span>
          </li>
        ))}
      </ol>
      <div className="mt-2 flex flex-wrap gap-1.5" data-testid="investigation-suggestions">
        {suggestions.map((s) => (
          <span key={s.suggestion_id} className="inline-flex items-center">
            <button
              type="button"
              disabled={busy}
              onClick={() => void choose(s)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs disabled:opacity-50",
                s.is_stress_test ? "border-warning text-warning" : "border-accent text-accent hover:bg-accent-muted",
              )}
              data-testid="nbq-chip"
              data-suggestion-type={s.type}
            >
              {s.is_stress_test && <FlaskConical className="mr-1 inline h-3 w-3" />}
              {s.text}
            </button>
            <button
              type="button"
              aria-label="Why is this suggested?"
              onClick={() => setShowWhy(showWhy === s.suggestion_id ? "" : s.suggestion_id)}
              className="ml-0.5 text-text-muted hover:text-text-primary"
            >
              <Info className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      {showWhy && (
        <p className="mt-2 rounded bg-surface-sunken p-2 text-[11px] text-text-secondary" data-testid="nbq-rationale">
          {suggestions.find((s) => s.suggestion_id === showWhy)?.rationale} Source:{" "}
          {suggestions.find((s) => s.suggestion_id === showWhy)?.source.metric_id} on{" "}
          {suggestions.find((s) => s.suggestion_id === showWhy)?.source.issue_id}.
        </p>
      )}
      <p className="mt-2 text-[11px] text-text-muted">
        Suggestions are grounded in the issue&apos;s measured evidence; answered ones are hidden. Type anything in the box
        below to go your own way.
      </p>
    </section>
  );
}
