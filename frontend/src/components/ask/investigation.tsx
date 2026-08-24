"use client";

import Link from "next/link";
import * as React from "react";
import {
  BookmarkPlus,
  Check,
  CircleDashed,
  GitBranch,
  Loader2,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { InvestigationResponse, Stage } from "@/lib/api";
import { cn } from "@/lib/utils";

import { AnswerBlock } from "./answer";

/**
 * A single answer, on its own page.
 *
 * The answer itself is rendered by `AnswerBlock`, which is the one response
 * architecture used everywhere CreditProbe answers. This file adds only what a
 * standalone view needs on top of it: the question as a heading, the actions
 * that apply to the whole run, and the progress indication while it is working.
 *
 * One thing it deliberately does NOT do: stream a model's thinking. The stages
 * below are the real phases of the request — reading the question, choosing
 * analyses, reading governed data, running the engine, writing the findings —
 * shown so the wait is legible. They are not chain-of-thought, and there is none
 * to show: the planner selects from a fixed library and the figures come from
 * tested code.
 */

/* ------------------------------------------------------------------ stages */

export function InvestigationProgress({
  stages,
  question,
}: {
  stages: Stage[];
  question: string;
}) {
  // The stages advance on a timer because the request is a single round trip:
  // the backend does all five phases before it replies. The timing is honest
  // about that — it is a progress indication, not a claim to be watching the
  // server. The final stage stays lit until the answer arrives.
  const [reached, setReached] = React.useState(0);

  React.useEffect(() => {
    // Only timers here — no synchronous setState. The component is mounted fresh
    // for each question, so `reached` already starts at zero and needs no reset.
    const timers = stages
      .slice(1)
      .map((_, index) =>
        setTimeout(() => setReached(index + 1), 550 * (index + 1)),
      );
    return () => timers.forEach(clearTimeout);
  }, [stages]);

  return (
    <Card className="p-6">
      <p className="flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-text-muted">
        <Sparkles className="size-3.5 text-accent" aria-hidden />
        Investigating
      </p>
      <p className="mt-2 max-w-2xl text-lg font-medium leading-snug tracking-tight text-text-primary">
        {question}
      </p>
      <ol className="mt-5 space-y-2.5">
        {stages.map((stage, index) => {
          const done = index < reached;
          const active = index === reached;
          return (
            <li key={stage.id} className="flex items-center gap-2.5 text-sm">
              {done ? (
                <Check className="size-4 shrink-0 text-positive" aria-hidden />
              ) : active ? (
                <Loader2
                  className="size-4 shrink-0 animate-spin text-accent"
                  aria-hidden
                />
              ) : (
                <CircleDashed
                  className="size-4 shrink-0 text-text-muted"
                  aria-hidden
                />
              )}
              <span
                className={cn(
                  done && "text-text-secondary",
                  active && "text-text-primary",
                  !done && !active && "text-text-muted",
                )}
              >
                {stage.label}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-5 border-t border-border pt-3 text-xs text-text-muted">
        Every figure in the answer is produced by a registered CreditProbe Engine
        analysis running against the published data.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ answer */

export function InvestigationView({
  investigation,
  onAsk,
  onReset,
  onSave,
  saved,
  savedHref,
}: {
  investigation: InvestigationResponse;
  onAsk: (question: string) => void;
  onReset: () => void;
  onSave?: () => void;
  saved?: boolean;
  savedHref?: string;
}) {
  const runId = investigation.analysis_run_id;

  return (
    <div className="space-y-8">
      <header>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="max-w-3xl text-[22px] font-semibold leading-tight tracking-tight text-text-primary">
              {investigation.question}
            </h1>
            <p className="mt-1.5 max-w-3xl text-sm text-text-muted">
              {investigation.intent}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {onSave && saved && savedHref && (
              <Button variant="ghost" size="sm" asChild>
                <Link href={savedHref} title="Open the saved investigation">
                  <BookmarkPlus aria-hidden />
                  Saved
                </Link>
              </Button>
            )}
            {runId && (
              <Button variant="outline" size="sm" asChild>
                <Link
                  href={`/trace/${runId}`}
                  title="See exactly how this answer was produced"
                >
                  <GitBranch aria-hidden />
                  Trace
                </Link>
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onReset}>
              New question
            </Button>
          </div>
        </div>
      </header>

      <AnswerBlock
        run={investigation}
        onAsk={onAsk}
        onSave={saved && savedHref ? undefined : onSave}
        saved={saved}
      />

      <p className="border-t border-border pt-4 text-xs leading-relaxed text-text-muted">
        {investigation.mode.description}
      </p>
    </div>
  );
}
