"use client";

import * as React from "react";

import { Card } from "@/components/ui/card";
import type { StudioExplanation, StudioValidation } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The pieces every Studio tab is built from. §117, §118.
 *
 * Why these are shared components rather than per-tab markup
 * -----------------------------------------------------------
 * §117 says every object must answer the same seven questions, and the surest
 * way for that to stop being true is fifteen tabs each rendering its own
 * version of "about this object". One component means one place where the
 * seven questions live, and a tab that forgets to pass an explanation renders
 * a visible gap rather than a tidy card with nothing behind it.
 *
 * §117 also says: avoid an admin card wall. So the default state of every
 * explanation is COLLAPSED, showing only the first answer — what the thing is.
 * A reader scanning fifteen blueprints reads fifteen sentences, not a hundred
 * and five.
 */

/** §117's seven questions, progressively disclosed. */
export function Explain({
  explanation,
  className,
}: {
  explanation: StudioExplanation;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const first = explanation.answers[0];
  const rest = explanation.answers.slice(1);

  return (
    <div className={cn("space-y-2", className)}>
      <p className="text-sm leading-relaxed text-text-secondary">
        {first?.answer ?? "No description recorded."}
      </p>

      {!explanation.complete ? (
        <p className="text-xs text-status-warning">
          This object does not answer{" "}
          {explanation.missing.length === 1 ? "one question" : `${explanation.missing.length} questions`} it
          should: {explanation.missing.join(", ")}.
        </p>
      ) : null}

      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="text-xs font-medium text-text-link hover:underline"
      >
        {open ? "Less" : "Why, when, how it was validated, and what release uses it"}
      </button>

      {open ? (
        <dl className="mt-1 space-y-2 border-l-2 border-border pl-3">
          {rest.map((answer) => (
            <div key={answer.id}>
              <dt className="text-xs font-medium text-text-primary">
                {answer.question}
              </dt>
              <dd className="text-xs leading-relaxed text-text-secondary">
                {answer.answer}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

/**
 * §118's validation drill-down.
 *
 * The sentence is the headline because it is the only part that is always
 * meaningful: a pass rate over four cases is a number, and "not evaluated —
 * nothing has run against this" is the truth.
 */
export function Validation({ validation }: { validation: StudioValidation }) {
  const [open, setOpen] = React.useState(false);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Dot ok={validation.trustworthy} />
        <span className="text-xs text-text-secondary">{validation.sentence}</span>
      </div>
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="text-xs font-medium text-text-link hover:underline"
      >
        {open ? "Hide validation detail" : "Validation detail"}
      </button>
      {open ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 border-l-2 border-border pl-3 text-xs sm:grid-cols-3">
          <Field label="Status" value={validation.validation_status} />
          <Field label="Test set" value={validation.test_set} />
          <Field label="Cases" value={String(validation.case_count)} />
          <Field label="Last run" value={validation.last_run} />
          <Field label="Version" value={validation.version || "—"} />
          <Field label="Owner" value={validation.owner} />
          {validation.critical_failures.length ? (
            <Field
              label="Critical failures"
              value={validation.critical_failures.join("; ")}
              wide
            />
          ) : null}
          {validation.staleness.length ? (
            <Field label="Stale" value={validation.staleness.join(", ")} wide />
          ) : null}
          {validation.known_limitations.length ? (
            <Field
              label="Known limitations"
              value={validation.known_limitations.join("; ")}
              wide
            />
          ) : null}
        </dl>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  wide,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "col-span-2 sm:col-span-3" : undefined}>
      <dt className="text-text-tertiary">{label}</dt>
      <dd className="text-text-primary">{value}</dd>
    </div>
  );
}

/**
 * A status dot.
 *
 * Never the only carrier of the information — every dot here sits beside a
 * sentence saying the same thing, because a reader who cannot distinguish the
 * colours still has to be able to read the screen.
 */
export function Dot({ ok }: { ok: boolean | null }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        ok === null
          ? "bg-text-tertiary"
          : ok
            ? "bg-status-positive"
            : "bg-status-negative",
      )}
    />
  );
}

/** A section of a tab, with its own heading and explanation. */
export function Panel({
  title,
  count,
  editIn,
  explanation,
  children,
}: {
  title: string;
  count?: number;
  editIn?: string;
  explanation?: StudioExplanation;
  children?: React.ReactNode;
}) {
  return (
    <Card className="space-y-3 p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-text-primary">
          {title}
          {typeof count === "number" ? (
            <span className="ml-2 text-xs font-normal text-text-tertiary">
              {count}
            </span>
          ) : null}
        </h3>
        {editIn ? (
          <a
            href={editIn}
            className="text-xs font-medium text-text-link hover:underline"
          >
            Open where it is edited
          </a>
        ) : null}
      </div>
      {explanation ? <Explain explanation={explanation} /> : null}
      {children}
    </Card>
  );
}

/** A calm key/value list. Used everywhere a policy shows its actual rules. */
export function Rules({ rules }: { rules: Record<string, unknown> }) {
  return (
    <dl className="space-y-2">
      {Object.entries(rules).map(([key, value]) => (
        <div key={key}>
          <dt className="text-xs font-medium text-text-primary">
            {key.replaceAll("_", " ")}
          </dt>
          <dd className="text-xs leading-relaxed text-text-secondary">
            {render(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function render(value: unknown): React.ReactNode {
  if (Array.isArray(value)) {
    if (!value.length) return "—";
    if (typeof value[0] === "object" && value[0] !== null) {
      return (
        <ul className="mt-1 space-y-1">
          {(value as Record<string, unknown>[]).map((row, index) => (
            <li key={index} className="text-text-secondary">
              {Object.entries(row)
                .map(([k, v]) => `${k}: ${String(v)}`)
                .join(" · ")}
            </li>
          ))}
        </ul>
      );
    }
    return value.join(", ");
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k} ${String(v)}`)
      .join(" · ");
  }
  return String(value);
}
