"use client";

import * as React from "react";
import {
  ChevronDown,
  CircleCheck,
  CircleHelp,
  CircleMinus,
  CircleX,
  TriangleAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Answer Assurance, and the Coordinated Review block. §53, §54.
 *
 * §54 opens with the instruction the whole component exists to honour:
 *
 *     "Do not show LLM self-confidence as the answer confidence."
 *
 * Nothing here is a model's opinion about itself. Every component is something
 * the run either observed or did not: whether the period was published, whether
 * the joins were governed, whether the invariants held, whether the totals
 * reconcile, whether every figure in the prose appears in the result. The
 * backend computes them; this renders them.
 *
 * The status is the weakest link, not an average — a result that fails its
 * invariants is not "mostly assured" because seven other checks passed — and
 * the component list makes that visible: a reader who clicks sees WHICH check
 * lowered it.
 */

export interface AssuranceComponent {
  key: string;
  label: string;
  state: string;
  detail: string;
  figures?: Record<string, unknown>;
}

export interface AssuranceView {
  status: string;
  meaning?: string;
  weakest?: string;
  components?: AssuranceComponent[];
  passed?: number;
  checked?: number;
}

/** §54's four statuses, with the register each one belongs in. */
const TONE: Record<string, string> = {
  "HIGH ASSURANCE": "bg-positive-muted text-positive",
  VALIDATED: "bg-positive-muted text-positive",
  "LIMITED EVIDENCE": "bg-warning-muted text-warning",
  "NEEDS REVIEW": "bg-negative-muted text-negative",
};

export function Assurance({
  assurance,
  className,
}: {
  assurance: AssuranceView | null | undefined;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  if (!assurance?.status) return null;

  const components = assurance.components ?? [];

  return (
    <div className={cn("min-w-0", className)} data-testid="assurance">
      <button
        type="button"
        onClick={() => setOpen((now) => !now)}
        aria-expanded={open}
        className="flex items-center gap-2 rounded text-left transition-colors hover:opacity-90"
      >
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.09em]",
            TONE[assurance.status] ?? "bg-surface-sunken text-text-muted",
          )}
          data-assurance={assurance.status}
        >
          {assurance.status}
        </span>
        {assurance.checked ? (
          <span className="text-[11px] text-text-muted">
            {assurance.passed ?? 0} of {assurance.checked} checks passed
          </span>
        ) : null}
        <ChevronDown
          className={cn(
            "size-3 shrink-0 text-text-muted transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        />
      </button>

      {open && (
        <div className="mt-2 space-y-1.5 rounded-md border border-border bg-surface-sunken p-2.5">
          {assurance.meaning && (
            <p className="text-xs leading-relaxed text-text-secondary">
              {assurance.meaning}
            </p>
          )}
          <ul className="space-y-1">
            {components.map((component) => (
              <li key={component.key} className="flex items-start gap-2">
                <StateIcon state={component.state} />
                <span className="min-w-0 flex-1 text-[11px]">
                  <span
                    className={cn(
                      "font-medium",
                      component.key === assurance.weakest
                        ? "text-text-primary"
                        : "text-text-secondary",
                    )}
                  >
                    {component.label}
                  </span>
                  <span className="text-text-muted"> — {component.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * §10's rule applied here too: text plus icon, never colour alone. A reader
 * who cannot distinguish the tick's green from the cross's red still sees two
 * different shapes and reads two different sentences.
 */
function StateIcon({ state }: { state: string }) {
  const size = "mt-0.5 size-3 shrink-0";
  if (state === "passed")
    return <CircleCheck className={cn(size, "text-positive")} aria-label="Passed" />;
  if (state === "failed")
    return <CircleX className={cn(size, "text-negative")} aria-label="Failed" />;
  if (state === "partial")
    return (
      <TriangleAlert className={cn(size, "text-warning")} aria-label="Partial" />
    );
  if (state === "not_applicable")
    return (
      <CircleMinus
        className={cn(size, "text-text-muted")}
        aria-label="Not applicable"
      />
    );
  return (
    <CircleHelp className={cn(size, "text-text-muted")} aria-label="Not checked" />
  );
}

/**
 * §53's COORDINATED REVIEW block.
 *
 * Shown only for a coordinated answer. On an ordinary question it would be a
 * heading, a list of one specialist and a count of one analysis — a box that
 * says "one person did one thing", which is what every answer in the product
 * already implies.
 *
 * §53: "Keep technical detail collapsed."
 */
export function CoordinatedReview({
  officer,
  specialists,
  summary,
  assurance,
  elapsed,
  findings,
  conflicts,
  limitations,
  className,
}: {
  officer: string;
  specialists: string[];
  summary?: string;
  assurance?: AssuranceView | null;
  elapsed?: string;
  findings?: { agent_name?: string; agent_id?: string; finding?: string }[];
  conflicts?: { sentence?: string; resolved?: boolean }[];
  limitations?: string[];
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  if (!specialists?.length) return null;

  return (
    <section
      className={cn(
        "rounded-md border border-border bg-surface-sunken p-3",
        className,
      )}
      data-testid="coordinated-review"
    >
      <h3 className="meta text-text-muted">Coordinated review</h3>
      <p className="mt-1 text-sm font-medium text-text-primary">
        Coordinated by {officer}
      </p>
      <p className="mt-0.5 text-xs text-text-secondary">
        {specialists.join(" · ")}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
        {summary && (
          <span className="text-[11px] text-text-muted">{summary}</span>
        )}
        {elapsed && (
          <span className="mono text-[11px] text-text-muted tabular">
            {elapsed}
          </span>
        )}
        <Assurance assurance={assurance} />
      </div>

      {(findings?.length || conflicts?.length || limitations?.length) ? (
        <>
          <button
            type="button"
            onClick={() => setOpen((now) => !now)}
            aria-expanded={open}
            className="mt-2 flex items-center gap-1 text-[11px] text-accent hover:underline"
          >
            {open ? "Hide" : "Show"} what each specialist found
            <ChevronDown
              className={cn("size-3 transition-transform", open && "rotate-180")}
              aria-hidden
            />
          </button>

          {open && (
            <div className="mt-2 space-y-2">
              {findings?.length ? (
                <ul className="space-y-1.5">
                  {findings.map((found, index) => (
                    <li key={`${found.agent_id}-${index}`} className="text-xs">
                      <span className="font-medium text-text-primary">
                        {found.agent_name || found.agent_id}
                      </span>
                      <span className="text-text-secondary">
                        {" "}
                        — {found.finding}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}

              {/* §25: a disagreement is preserved, not averaged away. */}
              {conflicts?.length ? (
                <ul className="space-y-1">
                  {conflicts.map((conflict, index) => (
                    <li
                      key={index}
                      className="flex items-start gap-1.5 text-[11px] text-text-secondary"
                    >
                      <TriangleAlert
                        className="mt-0.5 size-3 shrink-0 text-warning"
                        aria-hidden
                      />
                      <span>{conflict.sentence}</span>
                    </li>
                  ))}
                </ul>
              ) : null}

              {/* §55: what could not be done is said, not hidden. */}
              {limitations?.length ? (
                <p className="text-[11px] text-text-muted">
                  Not covered: {limitations.join("; ")}.
                </p>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
