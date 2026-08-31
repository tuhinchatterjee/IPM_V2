"use client";

import * as React from "react";
import { ArrowRight, CalendarRange, HelpCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Clarification, PlannerMode } from "@/lib/api";

/**
 * The question CreditProbe asks back instead of guessing.
 *
 * Two situations reach this card, and they need different answers:
 *
 *   PERIOD   "Which sectors deteriorated?" has no answer until somebody says
 *            since when. The options are two published periods, and answering
 *            re-runs the same question with them.
 *
 *   INTENT   CreditProbe did not follow the question at all, or it named a
 *            borrower without saying what to look at. The options are
 *            registered analyses, and answering asks a DIFFERENT question —
 *            the one the option names.
 *
 * Getting that distinction wrong is not cosmetic: clicking "Arrears Position"
 * on an intent clarification and having it re-ask the original question with
 * two empty periods would be a confident answer to a question nobody asked,
 * which is the exact failure this whole card exists to prevent.
 */

export function ClarificationCard({
  clarification,
  mode,
  onAnswer,
  onAsk,
  busy,
}: {
  clarification: Clarification;
  mode: PlannerMode | null;
  /** Answer a PERIOD clarification: re-run the question between two periods. */
  onAnswer: (from: string, to: string) => void;
  /** Answer an INTENT or ENTITY clarification: ask the question offered. */
  onAsk?: (question: string) => void;
  busy?: boolean;
}) {
  const periods = mode?.periods ?? [];
  const [custom, setCustom] = React.useState(false);
  const [from, setFrom] = React.useState(periods[0] ?? "");
  const [to, setTo] = React.useState(periods[periods.length - 1] ?? "");

  const isPeriod = clarification.kind === "period";
  const Icon = isPeriod ? CalendarRange : HelpCircle;

  return (
    <Card className="max-w-2xl p-6">
      <p className="meta flex items-center gap-2 text-text-muted">
        <Icon className="size-3.5 text-accent" aria-hidden />
        {/* §14: not "Not understood". A competent risk officer asking which
            of two things you meant has not failed to understand you - and a
            card that opens by announcing its own failure reads as a fault in
            the product rather than a normal turn in a conversation. The
            question itself, immediately below, does the work. */}
        {isPeriod ? "One thing first" : "One question back"}
      </p>

      <h2 className="mt-3 text-xl font-semibold leading-snug tracking-tight text-text-primary">
        {clarification.question}
      </h2>
      {clarification.detail && (
        <p className="prose-ai mt-1.5 text-sm text-text-secondary">
          {clarification.detail}
        </p>
      )}

      {clarification.options.length > 0 && (
        <div className="mt-5 space-y-1.5">
          {clarification.options.map((option) => {
            // A period option answers this question; anything else asks a new
            // one. An option carrying neither is not clickable, because there
            // is nothing honest for a click to do.
            const answersPeriod = Boolean(option.from_period && option.to_period);
            const asks = !answersPeriod && Boolean(option.question);
            const disabled = busy || (!answersPeriod && !(asks && onAsk));

            return (
              <button
                key={option.id}
                type="button"
                disabled={disabled}
                onClick={() => {
                  if (answersPeriod) {
                    onAnswer(option.from_period!, option.to_period!);
                  } else if (asks && onAsk) {
                    onAsk(option.question!);
                  }
                }}
                className="group flex w-full items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-accent hover:bg-surface-hover disabled:opacity-50"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-text-primary">
                    {option.label}
                  </span>
                  <span className="mt-0.5 block text-xs text-text-muted">
                    {option.detail || option.question}
                  </span>
                </span>
                <ArrowRight
                  className="size-3.5 shrink-0 text-text-muted transition-colors group-hover:text-accent"
                  aria-hidden
                />
              </button>
            );
          })}
        </div>
      )}

      {/* The custom row only exists for periods. On an intent clarification the
          way to say something else is the follow-up composer below, which is
          already on screen — a second box would be two ways to do one thing. */}
      {isPeriod && clarification.allow_custom && periods.length > 1 && (
        <div className="mt-4 border-t border-border pt-4">
          {custom ? (
            <div className="flex flex-wrap items-end gap-3">
              <PeriodSelect label="From" value={from} periods={periods} onChange={setFrom} />
              <PeriodSelect label="To" value={to} periods={periods} onChange={setTo} />
              <Button
                size="sm"
                disabled={busy || !from || !to || from === to}
                onClick={() => onAnswer(from, to)}
              >
                Compare
              </Button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setCustom(true)}
              className="text-xs text-text-muted underline-offset-4 transition-colors hover:text-accent hover:underline"
            >
              Choose the periods myself
            </button>
          )}
        </div>
      )}

      {!isPeriod && (
        <p className="mt-4 border-t border-border pt-4 text-xs text-text-muted">
          Or ask something else in the box below.
        </p>
      )}

      {clarification.because && (
        <p className="mt-5 border-l-2 border-border pl-3 text-xs leading-relaxed text-text-muted">
          {clarification.because}
        </p>
      )}
    </Card>
  );
}

function PeriodSelect({
  label,
  value,
  periods,
  onChange,
}: {
  label: string;
  value: string;
  periods: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="meta text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text-primary focus:border-accent focus:outline-none"
      >
        {periods.map((period) => (
          <option key={period} value={period}>
            {period}
          </option>
        ))}
      </select>
    </label>
  );
}
