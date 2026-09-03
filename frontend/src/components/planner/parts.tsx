"use client";

import Link from "next/link";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import type {
  PlannerFinding,
  PlannerHealth,
  PlannerStatement,
  PlannerTaskRow,
} from "@/lib/api";
import {
  claimLabel,
  dueLabel,
  healthTone,
  progressWidth,
  when,
} from "@/lib/planner-format";
import { cn } from "@/lib/utils";

export { when };

/**
 * The pieces every planner screen shares.
 *
 * They live here rather than in each page because a project's health has to
 * look and read identically in the portfolio table, the project header and
 * the attention panel. Three near-identical implementations is how a product
 * ends up calling the same project AMBER in one place and "At risk" in
 * another.
 */

// ---------------------------------------------------------------- health

/**
 * A colour with the word next to it, never the colour alone.
 *
 * A dot on its own is unreadable in greyscale, unreadable to a reader who
 * cannot distinguish the greens, and unreadable in a photocopied committee
 * pack — all three of which happen to a project status report.
 */
export function HealthPill({
  health,
  reason,
  overridden,
  className,
}: {
  health: PlannerHealth;
  reason?: string;
  overridden?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <Badge variant={healthTone(health)} title={reason}>
        {health}
      </Badge>
      {overridden && (
        <span
          className="text-[10px] uppercase tracking-wide text-text-muted"
          title="Reported by hand. The calculated value is on the project's Overview."
        >
          reported
        </span>
      )}
    </span>
  );
}

// -------------------------------------------------------------- progress

export function Progress({
  percent,
  className,
}: {
  percent: number;
  className?: string;
}) {
  const value = progressWidth(percent);
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-sunken"
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span
          className="block h-full rounded-full bg-accent"
          style={{ width: `${value}%` }}
        />
      </span>
      <span className="tabular-nums text-xs text-text-secondary">{value}%</span>
    </span>
  );
}

// ------------------------------------------------------------------ dates

/**
 * A date said the way a person would say it.
 *
 * "6 days overdue" is what somebody needs; "2026-08-28" makes them do
 * arithmetic. Both are shown — the relative phrase is what carries, the date
 * is what they will quote in a meeting.
 */
export function Due({
  date,
  daysOverdue,
  daysUntil,
}: {
  date: string | null;
  daysOverdue?: number | null;
  daysUntil?: number | null;
}) {
  const { text, tone } = dueLabel(date, daysOverdue, daysUntil);
  const shown = text !== date && date ? date : "";
  return (
    <span
      className={cn(
        tone === "negative" && "text-negative",
        tone === "warning" && "text-warning",
        tone === "muted" && "text-text-muted",
        tone === "normal" && "text-text-secondary",
      )}
    >
      {text}
      {shown && <span className="ml-1 text-text-muted">({shown})</span>}
    </span>
  );
}

// ------------------------------------------------------------------ tasks

export function TaskLine({
  task,
  onOpen,
  showProject,
}: {
  task: PlannerTaskRow;
  onOpen?: (task: PlannerTaskRow) => void;
  showProject?: boolean;
}) {
  const body = (
    <>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] text-text-muted">
            {task.code}
          </span>
          <span className="truncate text-sm text-text-primary">
            {task.title}
          </span>
          {task.critical && (
            <Badge variant="outline" className="shrink-0">
              critical path
            </Badge>
          )}
          {task.blocked && (
            <Badge variant="negative" className="shrink-0">
              blocked
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-muted">
          {showProject && <span>{task.project_code}</span>}
          <span>{task.owner?.name ?? "Unassigned"}</span>
          <Due
            date={task.due_date}
            daysOverdue={task.days_overdue}
            daysUntil={task.days_until_due}
          />
          {task.blocked && task.blocker_reason && (
            <span className="truncate text-negative">
              {task.blocker_reason}
            </span>
          )}
        </div>
      </div>
      <Progress percent={task.percent_complete} className="shrink-0" />
    </>
  );

  if (!onOpen) {
    return (
      <div className="flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-0">
        {body}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onOpen(task)}
      className="flex w-full items-center gap-3 border-b border-border px-4 py-2.5 text-left last:border-0 hover:bg-surface-hover"
    >
      {body}
    </button>
  );
}

// --------------------------------------------------------------- findings

const SEVERITY_VARIANT = {
  critical: "negative",
  warn: "warning",
  info: "default",
} as const;

export function FindingList({ findings }: { findings: PlannerFinding[] }) {
  if (!findings.length) {
    return (
      <p className="px-4 py-3 text-sm text-text-muted">
        Nothing the schedule rules flag on this project.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border">
      {findings.map((f, i) => (
        <li key={`${f.rule}-${f.entity_id}-${i}`}
            className="flex items-start gap-3 px-4 py-2.5">
          <Badge variant={SEVERITY_VARIANT[f.severity] ?? "default"}
                 className="mt-0.5 shrink-0">
            {f.severity}
          </Badge>
          <span className="text-sm text-text-secondary">{f.detail}</span>
        </li>
      ))}
    </ul>
  );
}

// -------------------------------------------------------------- grounding

const KIND_VARIANT: Record<string, "default" | "info" | "accent" | "warning"> = {
  FACT: "info",
  INFERENCE: "accent",
  RECOMMENDATION: "default",
  "NOT RECORDED": "warning",
};

/**
 * One line of a brief, with what kind of claim it is.
 *
 * The label is the point. A reader deciding whether to act on "the vendor is
 * the problem" needs to know instantly whether that is in the project record
 * or a reading of it, and a paragraph of undifferentiated prose cannot tell
 * them.
 */
export function StatementLine({ statement }: { statement: PlannerStatement }) {
  const variant = KIND_VARIANT[statement.kind] ?? "default";
  return (
    <li className="flex items-start gap-3 py-2">
      <Badge variant={variant} className="mt-0.5 shrink-0">
        {claimLabel(statement.kind)}
      </Badge>
      <div className="min-w-0">
        <p className="text-sm text-text-primary">{statement.text}</p>
        {statement.evidence.length > 0 && (
          <p className="mt-0.5 font-mono text-[11px] text-text-muted">
            {statement.evidence.slice(0, 8).join(" · ")}
          </p>
        )}
      </div>
    </li>
  );
}

// ------------------------------------------------------------------ misc

export function Stat({
  label,
  value,
  tone,
  href,
}: {
  label: string;
  value: number | string;
  tone?: "negative" | "warning" | "positive";
  href?: string;
}) {
  const inner = (
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "negative" && "text-negative",
          tone === "warning" && "text-warning",
          tone === "positive" && "text-positive",
        )}
      >
        {value}
      </p>
    </div>
  );
  return href ? (
    <Link href={href} className="block hover:opacity-90">
      {inner}
    </Link>
  ) : (
    inner
  );
}

export function SectionCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-6 text-sm text-text-muted">{children}</p>;
}
