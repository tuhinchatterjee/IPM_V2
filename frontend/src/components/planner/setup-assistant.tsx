"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import type { DraftGuidance, DraftProgress, DraftPointer } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Where you are in the setup, and what to do next.
 *
 * UAT's complaint about the panel beside the form was that it was a chat box
 * that did not help. This is the replacement, and it is deliberately not a
 * chat box: there is nothing to type into it. Everything it says is computed
 * on the server from the draft itself — what is complete, what is missing,
 * which dates contradict each other, and the single next thing worth doing —
 * so it cannot disagree with the fields beside it and it cannot be asked a
 * question it will answer badly.
 *
 * Every line it prints that names a field is a button. Telling somebody the
 * project has no sponsor and leaving them to find the sponsor field across
 * eight steps is most of the way to not telling them.
 */

/** The DOM id a completeness `field` addresses. One convention, one place. */
export function anchorId(field: string): string {
  return `f-${String(field || "").replace(/[^a-zA-Z0-9]+/g, "-")}`;
}

/**
 * Put the cursor on the thing the note was about.
 *
 * Called after the wizard has moved to the right step, so the element exists
 * — but not necessarily this tick, hence the frame. Silent when the field is
 * not on screen: a note about a plan-level fault has no field, and a jump
 * that scrolled the page to nowhere would be worse than no jump.
 */
export function focusField(field: string): void {
  if (!field || typeof document === "undefined") return;
  const go = () => {
    const found = document.getElementById(anchorId(field));
    if (!found) return;
    found.scrollIntoView({ block: "center", behavior: "smooth" });
    if (found instanceof HTMLInputElement
        || found instanceof HTMLSelectElement
        || found instanceof HTMLTextAreaElement
        || found instanceof HTMLButtonElement) {
      found.focus({ preventScroll: true });
    }
    found.classList.add("ring-2", "ring-accent");
    window.setTimeout(
      () => found.classList.remove("ring-2", "ring-accent"), 1600);
  };
  window.requestAnimationFrame(() => window.setTimeout(go, 60));
}

const STATE_STYLE: Record<string, string> = {
  complete: "border-positive/50 bg-positive/10 text-positive",
  in_progress: "border-accent/50 bg-accent-muted text-text-primary",
  needs_attention: "border-negative/50 bg-negative/10 text-negative",
  not_started: "border-border bg-surface text-text-muted",
};

/**
 * The eight sections, their state, and what the finished ones hold.
 *
 * This is the progress bar, the stepper and §12's collapsed summaries in one
 * control: a section you have finished shows the line it came to rather than
 * its fields, and the one you are on is the only one open.
 */
export function SetupProgress({
  progress,
  at,
  onJump,
}: {
  progress: DraftProgress;
  /** The step key currently open. */
  at: string;
  onJump: (step: string) => void;
}) {
  const done = progress.complete;
  const share = Math.round((done / Math.max(1, progress.total)) * 100);
  return (
    <section className="rounded-lg border border-border bg-surface px-4 py-3"
             aria-label="Project setup progress">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-text-primary">
          {progress.sentence}
        </p>
        <p className="text-xs text-text-muted">{progress.publish_message}</p>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div className="h-full rounded-full bg-accent transition-all"
             style={{ width: `${share}%` }}
             role="progressbar"
             aria-valuenow={done}
             aria-valuemin={0}
             aria-valuemax={progress.total}
             aria-label={progress.sentence} />
      </div>
      <ol className="mt-3 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
        {progress.sections.map((section) => {
          const here = section.step === at;
          return (
            <li key={section.key}>
              <button
                type="button"
                aria-current={here ? "step" : undefined}
                onClick={() => onJump(section.step)}
                className={cn(
                  "w-full rounded-md border px-2.5 py-2 text-left transition",
                  STATE_STYLE[section.state] ?? STATE_STYLE.not_started,
                  here && "ring-2 ring-accent",
                )}
              >
                <span className="flex items-baseline gap-1.5">
                  <span className="font-mono text-[11px] opacity-70">
                    {section.number}
                  </span>
                  <span className="truncate text-xs font-medium">
                    {section.title}
                  </span>
                </span>
                <span className="mt-0.5 block truncate text-[11px] opacity-80">
                  {section.summary || section.label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Pointer({
  pointer,
  onGo,
  tone,
}: {
  pointer: DraftPointer;
  onGo: (step: string, field: string) => void;
  tone: "blocker" | "warning" | "conflict";
}) {
  const label = `${pointer.message}${pointer.code ? ` (${pointer.code})` : ""}`;
  return (
    <li>
      <button
        type="button"
        onClick={() => onGo(pointer.step, pointer.field)}
        aria-label={`Fix: ${label}`}
        className={cn(
          "w-full rounded-md border px-2.5 py-1.5 text-left text-xs transition hover:border-accent",
          tone === "blocker" && "border-negative/40 bg-negative/5",
          tone === "warning" && "border-border bg-surface-raised",
          tone === "conflict" && "border-warning/50 bg-warning/10",
        )}
      >
        {pointer.code && (
          <span className="mr-1.5 font-mono text-[11px] text-text-muted">
            {pointer.code}
          </span>
        )}
        <span className="text-text-primary">{pointer.message}</span>
        {pointer.fix && (
          <span className="mt-0.5 block text-text-muted">{pointer.fix}</span>
        )}
      </button>
    </li>
  );
}

export function SetupAssistant({
  guidance,
  onGo,
}: {
  guidance: DraftGuidance;
  /** Move the form to this step, then put the cursor on this field. */
  onGo: (step: string, field: string) => void;
}) {
  const { next, readiness } = guidance;
  return (
    <aside className="space-y-3" aria-label="Project setup assistant">
      <section className="rounded-lg border border-border bg-surface px-4 py-3">
        <p className="text-[11px] uppercase tracking-wide text-text-muted">
          Project setup assistant
        </p>
        <p className="mt-1 text-sm text-text-primary">{guidance.headline}</p>
        <p className="mt-2 text-[11px] uppercase tracking-wide text-text-muted">
          Next recommended step
        </p>
        <button
          type="button"
          onClick={() => onGo(next.step, next.field)}
          className="mt-1 w-full rounded-md border border-accent bg-accent-muted px-2.5 py-2 text-left transition hover:border-accent"
        >
          <span className="block text-sm font-medium text-text-primary">
            {next.title}
          </span>
          <span className="mt-0.5 block text-xs text-text-secondary">
            {next.why}
          </span>
        </button>
        <p className="mt-2 text-xs text-text-muted">{readiness.message}</p>
      </section>

      {guidance.actions.length > 0 && (
        <section className="rounded-lg border border-border bg-surface px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">
            On this step
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {guidance.actions.map((action) => (
              <Button
                key={action.label}
                size="sm"
                variant="outline"
                onClick={() => onGo(action.step, action.field)}
              >
                {action.label}
              </Button>
            ))}
          </div>
        </section>
      )}

      {guidance.conflicts.length > 0 && (
        <section className="rounded-lg border border-warning/50 bg-surface px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-warning">
            Dates that contradict each other
          </p>
          <ul className="mt-1.5 space-y-1">
            {guidance.conflicts.map((row, index) => (
              <Pointer key={`c${index}`} pointer={row} onGo={onGo}
                       tone="conflict" />
            ))}
          </ul>
        </section>
      )}

      <section className="rounded-lg border border-border bg-surface px-4 py-3">
        <p className="text-[11px] uppercase tracking-wide text-negative">
          Required before publish
        </p>
        {guidance.missing.length === 0 ? (
          <p className="mt-1 text-sm text-positive">
            Nothing outstanding. This plan can be published.
          </p>
        ) : (
          <ul className="mt-1.5 space-y-1">
            {guidance.missing.map((row, index) => (
              <Pointer key={`m${index}`} pointer={row} onGo={onGo}
                       tone="blocker" />
            ))}
          </ul>
        )}
      </section>

      {guidance.recommended.length > 0 && (
        <section className="rounded-lg border border-border bg-surface px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-warning">
            Recommended improvements
          </p>
          <ul className="mt-1.5 space-y-1">
            {guidance.recommended.map((row, index) => (
              <Pointer key={`r${index}`} pointer={row} onGo={onGo}
                       tone="warning" />
            ))}
          </ul>
        </section>
      )}

      {guidance.complete.length > 0 && (
        <section className="rounded-lg border border-border bg-surface px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-positive">
            Settled
          </p>
          <ul className="mt-1.5 space-y-1">
            {guidance.complete.map((row) => (
              <li key={row.section} className="text-xs">
                <span className="text-text-muted">{row.section}: </span>
                <span className="text-text-primary">{row.summary}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
