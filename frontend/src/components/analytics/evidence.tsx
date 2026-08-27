"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import {
  describeMeaning,
  meaningOf,
  MEANING_CLASS,
  MEANING_LABEL,
  type Direction,
  type Meaning,
} from "@/lib/credit-semantics";
import { byUnit } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useHighlight } from "./highlight";

/**
 * A figure, inside a sentence, that says what it means.
 *
 *     Contracting ECL rose by [ +12.4% ↑ adverse ]
 *
 * Three rules hold this together, and the first is the one that matters:
 *
 * COLOUR IS CREDIT-RISK MEANING, NOT ARITHMETIC SIGN. A rising ECL and a rising
 * cure rate are both increases and only one of them is bad news. The direction
 * comes from the semantic ontology, never from the number, and where the
 * ontology has nothing to say the token is not coloured at all. `meaningOf` in
 * `lib/credit-semantics.ts` is the whole rule and it is tested there.
 *
 * NEVER COLOUR ALONE. Every token carries an arrow, a word and a full
 * `aria-label`, so the meaning survives a monochrome print-out, a colour-blind
 * reader and a screen reader.
 *
 * NOT CONFETTI. §10: two to five facts in an answer, not every number in every
 * sentence. Nothing here enforces that — a component cannot — but the callers
 * take at most a handful, and a rendered answer that looks like a highlighter
 * accident is a bug in the caller.
 */
export function EvidenceToken({
  label,
  value,
  unit,
  period,
  direction,
  /** The change this figure represents, when it is a movement rather than a level. */
  change,
  source,
  className,
}: {
  label: string;
  value: number | string | null;
  unit: string;
  period?: string;
  direction?: Direction;
  change?: number | null;
  /** Where the figure came from: an analysis name, a dataset. */
  source?: string;
  className?: string;
}) {
  const { active, point } = useHighlight();
  // A movement is judged by its change; a level has no direction of travel and
  // so no meaning to colour, however risky the measure it belongs to.
  const moving = change ?? (typeof value === "number" && unit === "pp" ? value : null);
  const meaning: Meaning = meaningOf(moving, direction);
  const display = byUnit(value, unit);
  const pointed = active !== null && active === label;

  const detail = [period, source].filter(Boolean).join(" · ");

  return (
    <button
      type="button"
      onClick={() => point(label)}
      aria-pressed={pointed}
      aria-label={describeMeaning(label, display, meaning)}
      title={detail || undefined}
      className={cn(
        "mx-0.5 inline-flex items-baseline gap-1 rounded-sm border px-1.5 py-px align-baseline",
        "text-[0.8125rem] leading-snug transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        MEANING_CLASS[meaning],
        pointed && "ring-2 ring-accent/50",
        className,
      )}
    >
      <span className="font-mono tabular-nums font-medium">{display}</span>
      <Arrow meaning={meaning} rising={(moving ?? 0) > 0} />
      {MEANING_LABEL[meaning] && (
        <span className="text-[0.6875rem] font-normal opacity-80">
          {MEANING_LABEL[meaning]}
        </span>
      )}
    </button>
  );
}

/**
 * The arrow shows which way the figure MOVED; the colour shows what that
 * means. Both, because either alone is ambiguous: an arrow with no colour does
 * not say whether up is good, and a colour with no arrow does not survive a
 * greyscale print.
 */
function Arrow({ meaning, rising }: { meaning: Meaning; rising: boolean }) {
  if (meaning === "neutral") {
    return <Minus className="size-3 shrink-0 self-center opacity-50" aria-hidden />;
  }
  const Icon = rising ? ArrowUp : ArrowDown;
  return <Icon className="size-3 shrink-0 self-center" aria-hidden />;
}

/**
 * A row of the evidence behind one finding.
 *
 * Used where a sentence is followed by its figures rather than containing
 * them — which is most of the time, because the backend composes prose and
 * attaches evidence beside it rather than marking figures up inside it.
 */
export function EvidenceRow({
  items,
  className,
}: {
  items: {
    label: string;
    value: number | string | null;
    unit: string;
    direction?: Direction;
    period?: string;
  }[];
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <p className={cn("flex flex-wrap items-baseline gap-x-1.5 gap-y-1", className)}>
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-baseline gap-1">
          <span className="text-[0.6875rem] text-text-muted">{item.label}</span>
          <EvidenceToken
            label={item.label}
            value={item.value}
            unit={item.unit}
            direction={item.direction}
            period={item.period}
          />
        </span>
      ))}
    </p>
  );
}
