"use client";

import * as React from "react";
import { ArrowRight, CalendarRange } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { Clarification, PlannerMode } from "@/lib/api";

/**
 * The one question CreditProbe asks back.
 *
 * "Which sectors deteriorated?" has no answer until someone says since when.
 * Choosing a comparison silently would produce a confident number answering a
 * question nobody asked — and it would carry a certification mark while doing
 * it. So CreditProbe asks, once, and says why it is asking.
 *
 * Every option here resolves to two real published periods, so answering is a
 * click. The custom row exists for the case the quick options do not cover, and
 * offers only periods that exist.
 */

export function ClarificationCard({
  clarification,
  mode,
  onAnswer,
  busy,
}: {
  clarification: Clarification;
  mode: PlannerMode | null;
  onAnswer: (from: string, to: string) => void;
  busy?: boolean;
}) {
  const periods = mode?.periods ?? [];
  const [custom, setCustom] = React.useState(false);
  const [from, setFrom] = React.useState(periods[0] ?? "");
  const [to, setTo] = React.useState(periods[periods.length - 1] ?? "");

  return (
    <Card className="max-w-2xl p-6">
      <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
        <CalendarRange className="size-3.5 text-accent" aria-hidden />
        One thing first
      </p>

      <h2 className="mt-3 text-xl font-semibold leading-snug tracking-tight text-text-primary">
        {clarification.question}
      </h2>
      {clarification.detail && (
        <p className="mt-1.5 text-sm text-text-secondary">{clarification.detail}</p>
      )}

      <div className="mt-5 space-y-1.5">
        {clarification.options.map((option) => (
          <button
            key={option.id}
            type="button"
            disabled={busy}
            onClick={() => onAnswer(option.from_period, option.to_period)}
            className="group flex w-full items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-accent hover:bg-surface-hover disabled:opacity-50"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-text-primary">{option.label}</span>
              <span className="mt-0.5 block text-xs text-text-muted">{option.detail}</span>
            </span>
            <ArrowRight
              className="size-3.5 shrink-0 text-text-muted transition-colors group-hover:text-accent"
              aria-hidden
            />
          </button>
        ))}
      </div>

      {clarification.allow_custom && periods.length > 1 && (
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
    <label className="text-xs text-text-muted">
      <span className="mb-1 block">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-text-primary outline-none focus-visible:border-accent"
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
