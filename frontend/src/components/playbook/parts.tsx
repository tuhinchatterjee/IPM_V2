"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import type {
  PlaybookAvailability,
  PlaybookFigure,
  PlaybookPackStatus,
  PlaybookReadiness,
  PlaybookSeverity,
} from "@/lib/api";
import {
  availabilityLabel,
  availabilityTone,
  figureReading,
  formatWhen,
  movementReading,
  packStatusTone,
  severityTone,
  stateTone,
} from "@/lib/playbook-format";
import { cn } from "@/lib/utils";

export { daysUntil, formatDay, formatWhen } from "@/lib/playbook-format";

/**
 * The pieces every Playbook screen shares.
 *
 * They live here rather than in each page because a figure with no value has
 * to read identically on the pack, in the readiness panel and in the findings
 * list. Three near-identical implementations is how a product ends up showing
 * "—" in one place, "0.0%" in another and "No data" in a third for the same
 * immature cohort.
 *
 * The rule the whole area rests on, enforced by `Figure` below:
 *
 *   A MISSING OR IMMATURE DENOMINATOR IS NEVER RENDERED AS A NUMBER.
 *
 * The backend already decided which of five different facts applies and put
 * the rounded string on the snapshot. This module renders that decision. It
 * does not re-round, re-derive or fall back to zero, because a screen that
 * computed its own display would eventually disagree with the PDF sent to the
 * same committee on the same morning.
 */

// ------------------------------------------------------------- availability

export function Availability({
  availability,
  reason,
  className,
}: {
  availability: PlaybookAvailability;
  reason?: string;
  className?: string;
}) {
  if (availability === "OK") return null;
  return (
    <Badge
      variant={availabilityTone(availability)}
      title={reason}
      className={className}
    >
      {availabilityLabel(availability)}
    </Badge>
  );
}

// ------------------------------------------------------------------ figures

/**
 * One governed figure, rendered from the snapshot the backend froze.
 *
 * Every decision here is in `figureReading`, which is a pure function with its
 * own tests. This component only paints what it returns — there is no branch
 * in here that could produce a dash or a zero for an absent figure.
 */
export function Figure({
  figure,
  size = "default",
  className,
}: {
  figure: PlaybookFigure | null;
  size?: "default" | "large";
  className?: string;
}) {
  const reading = figureReading(figure);

  if (reading.kind === "uncalculated") {
    return (
      <span className={cn("text-sm text-text-muted", className)}>
        {reading.text}
      </span>
    );
  }
  if (reading.kind === "unavailable") {
    return (
      <span className={cn("inline-flex flex-col gap-1", className)}>
        <Badge variant={reading.tone} title={reading.reason}>
          {reading.label}
        </Badge>
        {reading.reason && (
          <span className="text-xs text-text-muted">{reading.reason}</span>
        )}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "font-semibold tabular-nums text-text-primary",
        size === "large" ? "text-2xl" : "text-sm",
        className,
      )}
    >
      {reading.text}
    </span>
  );
}

/**
 * The movement since the comparison period, read in the metric's own
 * direction. The reading itself is `movementReading`; this paints it.
 */
export function Movement({
  figure,
  className,
}: {
  figure: PlaybookFigure | null;
  className?: string;
}) {
  const reading = movementReading(figure);
  if (reading.kind === "none" && !reading.text) return null;
  if (reading.kind !== "moved") {
    return (
      <span className={cn("text-xs text-text-muted", className)}>
        {reading.text}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "text-xs tabular-nums",
        reading.good ? "text-positive" : "text-negative",
        className,
      )}
    >
      {reading.text}
    </span>
  );
}

/**
 * The working behind a number, for the reader who asks "where is that from?".
 *
 * Every field here is what makes a committee figure defensible: which formula
 * (by hash, so two figures produced by the same arithmetic are visibly the
 * same), which dataset version, which run, and what the numerator and
 * denominator actually were.
 */
export function Working({ figure }: { figure: PlaybookFigure }) {
  const rows: [string, string][] = [
    ["Metric", `${figure.metric_name} (${figure.metric_id})`],
    ["Period", figure.period],
    ["Formula hash", figure.formula_hash || "—"],
    ["Metric version", figure.metric_version || "—"],
    ["Dataset", figure.dataset || "—"],
    ["Dataset version", figure.dataset_version || "—"],
    ["Run id", figure.run_id || "—"],
  ];
  if (figure.numerator !== null) {
    rows.push(["Numerator", String(figure.numerator)]);
  }
  if (figure.denominator !== null) {
    rows.push(["Denominator", String(figure.denominator)]);
  }
  if (figure.rows_considered !== null) {
    rows.push(["Rows considered", String(figure.rows_considered)]);
  }
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt className="text-text-muted">{label}</dt>
          <dd className="break-all font-mono text-text-secondary">{value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

// ------------------------------------------------------------------ statuses

export function PackStatus({
  status,
  label,
  className,
}: {
  status: PlaybookPackStatus;
  label?: string;
  className?: string;
}) {
  return (
    <Badge variant={packStatusTone(status)} className={className}>
      {label || status.replace(/_/g, " ").toLowerCase()}
    </Badge>
  );
}

/**
 * A colour with the word next to it, never the colour alone.
 *
 * A committee pack gets printed, photocopied and read by people who cannot
 * distinguish the reds — all three of which make a bare dot unreadable.
 */
export function Severity({
  severity,
  className,
}: {
  severity: PlaybookSeverity;
  className?: string;
}) {
  return (
    <Badge variant={severityTone(severity)} className={className}>
      {severity.toLowerCase()}
    </Badge>
  );
}

// ----------------------------------------------------------------- readiness

/**
 * How ready a pack is, and — always — when that was worked out.
 *
 * A percentage with no timestamp is a number nobody can defend in a meeting,
 * so `computed_at` is not optional here and is not tucked into a tooltip.
 */
export function ReadinessBar({
  readiness,
  className,
}: {
  readiness: PlaybookReadiness;
  className?: string;
}) {
  const tone = stateTone(readiness.state);
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold tabular-nums text-text-primary">
          {readiness.percent}% ready
        </span>
        <Badge variant={tone}>{readiness.state}</Badge>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
        <div
          className={cn(
            "h-full rounded-full",
            tone === "positive" && "bg-positive",
            tone === "warning" && "bg-warning",
            tone === "negative" && "bg-negative",
          )}
          style={{ width: `${Math.max(0, Math.min(100, readiness.percent))}%` }}
        />
      </div>
      <p className="text-[11px] text-text-muted">
        Worked out {formatWhen(readiness.computed_at)}
        {readiness.blocking_count > 0 && (
          <>
            {" · "}
            <span className="text-negative">
              {readiness.blocking_count} blocking
            </span>
          </>
        )}
      </p>
    </div>
  );
}

/**
 * The individual checks, each carrying what is left rather than only a score.
 *
 * A check that could not be RUN says so instead of scoring zero: "no data
 * steward has published this period yet" and "this check failed" are different
 * facts, and a bar at 0% for both makes the pack owner chase the wrong person.
 */
export function ReadinessChecks({
  readiness,
}: {
  readiness: PlaybookReadiness;
}) {
  return (
    <ul className="divide-y divide-border">
      {readiness.checks.map((check) => (
        <li key={check.key} className="px-4 py-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-medium text-text-primary">
              {check.label}
            </span>
            <span className="text-xs tabular-nums text-text-muted">
              {check.not_assessed
                ? "not assessed"
                : `${Math.round(check.progress * 100)}%`}
            </span>
          </div>
          {check.not_assessed && (
            <p className="mt-1 text-xs text-text-muted">{check.not_assessed}</p>
          )}
          {check.reasons.length > 0 && (
            <ul className="mt-1.5 space-y-1">
              {check.reasons.map((reason, index) => (
                <li
                  key={`${check.key}-${index}`}
                  className={cn(
                    "text-xs",
                    reason.blocking ? "text-negative" : "text-text-secondary",
                  )}
                >
                  {reason.blocking && (
                    <span className="mr-1 font-semibold">Blocking:</span>
                  )}
                  {reason.text}
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

// ------------------------------------------------------------------ chrome

export function SectionCard({
  title,
  action,
  description,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-2.5">
        <div>
          <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
          {description && (
            <p className="mt-0.5 text-xs text-text-muted">{description}</p>
          )}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: number | string;
  tone?: "negative" | "warning" | "positive";
  hint?: string;
}) {
  return (
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
      {hint && <p className="mt-0.5 text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-6 text-sm text-text-muted">{children}</p>;
}

/**
 * The outcome of something the reader just DID, when it failed.
 *
 * For a panel that could not load, use `<Unavailable>` instead — it tells a
 * refusal apart from a fault, and a Viewer correctly refused should not be
 * shown a red error saying the product is broken. This is for the other case:
 * a button was pressed and the API said no. The API's refusals name the access
 * needed, who moved the pack, or why a file was rejected, so the message is
 * shown as written rather than replaced with "Something went wrong".
 */
export function Problem({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : String(error ?? "Unknown error");
  return (
    <p className="rounded-lg border border-negative-muted bg-negative-muted/40 px-4 py-3 text-sm text-negative">
      {message}
    </p>
  );
}
