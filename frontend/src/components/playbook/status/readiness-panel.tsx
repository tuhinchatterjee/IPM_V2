"use client";

import * as React from "react";
import { ChevronDown } from "lucide-react";

import { ScoreBar, ScoreChip, StatusChip } from "@/components/playbook/status/chips";
import type { PbDashboard } from "@/lib/api";
import {
  approvalBadge,
  componentViews,
  rag,
  ragLabel,
  shortDateTime,
} from "@/lib/intelligence";
import { cn } from "@/lib/utils";

/**
 * The right-hand readiness panel. §10.
 *
 * The question it exists to answer is not "what is the score" but **"why is
 * readiness 81%?"** — without asking Claude. So every component expands to
 * show its score, its explanation, what is blocking it and where to go and
 * deal with it, and the whole thing is keyboard-reachable.
 *
 * Nothing here is computed in the browser. The scores, the explanations and
 * the blockers all arrive from the backend, which derives them from governed
 * rows; a percentage this component invented would be exactly the thing §1
 * forbids.
 */
export function ReadinessPanel({
  dashboard,
  onOpenTab,
  className,
}: {
  dashboard: PbDashboard;
  onOpenTab: (tab: string) => void;
  className?: string;
}) {
  const readiness = dashboard.readiness;
  const badge = approvalBadge(dashboard);
  const components = componentViews(readiness.components,
    dashboard.committee_report);
  const tone = rag(readiness.readiness_pct);

  return (
    <section
      className={cn("space-y-4", className)}
      aria-label="Readiness"
      data-testid="playbook-readiness-panel"
    >
      <div className="rounded-lg border border-border bg-surface p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Readiness
        </h2>
        <p className="mt-2 text-3xl font-semibold tabular-nums text-text-primary">
          {readiness.readiness_pct}%
        </p>
        <div className="mt-1 flex items-center gap-2">
          <StatusChip tone={tone}>{ragLabel(tone)}</StatusChip>
          <StatusChip tone={badge.tone}>{badge.label}</StatusChip>
        </div>
        <ScoreBar score={readiness.readiness_pct} tone={tone} className="mt-3" />

        {readiness.blockers.length > 0 && (
          <ul className="mt-3 space-y-1.5" data-testid="playbook-blockers">
            {readiness.blockers.map((blocker, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => onOpenTab(blocker.link)}
                  className="w-full rounded-md border border-negative/40 bg-negative-muted px-2 py-1.5 text-left text-[11px] leading-relaxed text-negative hover:bg-negative/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-negative"
                >
                  {blocker.reason}
                </button>
              </li>
            ))}
          </ul>
        )}

        {readiness.computed_at && (
          <p className="mt-3 text-[10px] text-text-muted">
            Last evaluated {shortDateTime(readiness.computed_at)}
          </p>
        )}
      </div>

      <div className="rounded-lg border border-border bg-surface">
        <h3 className="border-b border-border px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          What it is made of
        </h3>
        <ul>
          {components.map((component) => (
            <ComponentRow
              key={component.name}
              component={component}
              onOpenTab={onOpenTab}
            />
          ))}
        </ul>
      </div>

      {readiness.missing.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Sections not yet written
          </h3>
          <ul className="mt-2 space-y-1">
            {readiness.missing.map((name) => (
              <li key={name} className="text-xs text-text-secondary">
                {name}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ComponentRow({
  component,
  onOpenTab,
}: {
  component: ReturnType<typeof componentViews>[number];
  onOpenTab: (tab: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const id = `readiness-${component.name.replace(/\W+/g, "-").toLowerCase()}`;

  return (
    <li className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={id}
        className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
        data-testid="playbook-readiness-component"
      >
        <ChevronDown
          className={cn("size-3.5 shrink-0 text-text-muted transition-transform",
            open && "rotate-180")}
          aria-hidden
        />
        <span className="min-w-0 flex-1 truncate text-xs text-text-primary">
          {component.name}
        </span>
        <ScoreChip
          score={component.score}
          tone={component.tone}
          display={component.display}
        />
      </button>
      {open && (
        <div id={id} className="space-y-2 bg-surface-sunken px-4 pb-3 pt-1">
          {component.applicable && component.score !== null && (
            <ScoreBar score={component.score} tone={component.tone} />
          )}
          <p className="text-[11px] leading-relaxed text-text-secondary">
            {component.explanation ||
              (component.applicable
                ? "No explanation was recorded."
                : "This component does not apply to this kind of document.")}
          </p>
          {component.blocking && (
            <p className="rounded border border-negative/40 bg-negative-muted px-2 py-1 text-[11px] text-negative">
              Blocking: {component.blocking}
            </p>
          )}
          <button
            type="button"
            onClick={() => onOpenTab(component.tab)}
            className="text-[11px] font-medium text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Go and deal with this →
          </button>
        </div>
      )}
    </li>
  );
}
