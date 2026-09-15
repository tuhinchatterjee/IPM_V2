"use client";

import * as React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  XCircle,
} from "lucide-react";

import type { Rag } from "@/lib/intelligence";
import { ragLabel } from "@/lib/intelligence";
import { cn } from "@/lib/utils";

/**
 * A status, said three ways at once: colour, icon and word.
 *
 * §10 and §32 both forbid relying on colour alone, and an icon on its own is
 * no better for somebody using a screen reader or reading a black-and-white
 * printout of a committee pack. So every chip carries text, and the icon is
 * decorative.
 */

const TONE: Record<Rag, { className: string; Icon: typeof CheckCircle2 }> = {
  green: {
    className: "border-positive/40 bg-positive-muted text-positive",
    Icon: CheckCircle2,
  },
  amber: {
    className: "border-warning/40 bg-surface-warning text-warning",
    Icon: AlertTriangle,
  },
  red: {
    className: "border-negative/40 bg-negative-muted text-negative",
    Icon: XCircle,
  },
  unknown: {
    className: "border-border bg-surface-sunken text-text-secondary",
    Icon: CircleDashed,
  },
};

export function StatusChip({
  tone,
  children,
  className,
  title,
}: {
  tone: Rag;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  const { className: toneClass, Icon } = TONE[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5",
        "text-[11px] font-medium leading-none whitespace-nowrap",
        toneClass,
        className,
      )}
      title={title}
    >
      <Icon className="size-3 shrink-0" aria-hidden />
      {children}
    </span>
  );
}

/**
 * A percentage with its own meaning attached.
 *
 * The word is not decoration: 54% is not self-evidently a problem, and
 * "54% · Attention" is.
 */
export function ScoreChip({
  score,
  tone,
  display,
  className,
}: {
  score?: number | null;
  tone: Rag;
  display?: string;
  className?: string;
}) {
  const shown = display ?? (score === null || score === undefined
    ? "—" : `${score}%`);
  return (
    <StatusChip tone={tone} className={className} title={ragLabel(tone)}>
      <span className="tabular-nums">{shown}</span>
      <span className="sr-only"> — {ragLabel(tone)}</span>
    </StatusChip>
  );
}

/** A horizontal meter. Always beside a number, never instead of one. */
export function ScoreBar({
  score,
  tone,
  className,
}: {
  score: number | null;
  tone: Rag;
  className?: string;
}) {
  const width = score === null ? 0 : Math.max(0, Math.min(100, score));
  const fill = {
    green: "bg-positive",
    amber: "bg-warning",
    red: "bg-negative",
    unknown: "bg-border-strong",
  }[tone];
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken",
        className)}
      // The number beside it is the accessible value; this is presentation.
      aria-hidden
    >
      <div className={cn("h-full rounded-full transition-all", fill)}
        style={{ width: `${width}%` }} />
    </div>
  );
}

/** A small caption above a value. Used everywhere a field is labelled. */
export function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
      {children}
    </p>
  );
}

export function Field({
  label,
  children,
  className,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <FieldLabel>{label}</FieldLabel>
      <div className="mt-0.5 text-sm text-text-primary">{children}</div>
    </div>
  );
}

/**
 * Where a figure came from, shown as the address it actually has.
 *
 * `xlsx://Coverage!B12` is not pretty, and it is the thing that makes a
 * number checkable. Prettifying it would remove the only part a reviewer can
 * use.
 */
export function Locator({ value }: { value: string }) {
  if (!value) return null;
  return (
    <code className="rounded bg-surface-sunken px-1 py-0.5 text-[10px] text-text-muted">
      {value}
    </code>
  );
}

/** Who did it, or an honest blank. Never "system" dressed up as a person. */
export function Actor({ name }: { name: string }) {
  if (!name) return <span className="text-text-muted">—</span>;
  return <span className="text-text-secondary">{name}</span>;
}
