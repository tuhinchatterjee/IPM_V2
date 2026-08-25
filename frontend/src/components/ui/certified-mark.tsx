import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The CreditProbe certification mark.
 *
 * Two ticks, drawn as one stroke pair: the first for "the method is validated",
 * the second for "the run is recorded". Certification in CreditProbe is exactly those
 * two claims, so the mark carries two ticks rather than one.
 *
 * It is drawn here rather than taken from an icon set on purpose. A tick inside
 * a coloured badge is another product's mark and would read as borrowed
 * credibility; this is a quiet pair of strokes in CreditProbe's own blue, sized to sit
 * inside a line of text without shouting.
 */

export function CertifiedMark({
  className,
  title = "CreditProbe Certified — a validated method, and a recorded run",
}: {
  className?: string;
  title?: string;
}) {
  return (
    <svg
      viewBox="0 0 22 14"
      className={cn("size-[1.1em] w-auto shrink-0", className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={title}
    >
      <title>{title}</title>
      <path d="M1.6 7.6 5.2 11.2 12.4 3.2" />
      <path d="M9.6 7.6 13.2 11.2 20.4 3.2" />
    </svg>
  );
}

/**
 * The certification state of one analysis, as a line of text.
 *
 * Three states, and they are not decorative. "Certified" means the bank has
 * validated the method and CreditProbe recorded the run. "Custom" means someone in the
 * bank defined it and it has not been through validation. "Unvalidated" is a
 * draft. A reader must be able to tell which figure they are allowed to put in
 * front of a regulator.
 */
export function CertificationBadge({
  certification,
  className,
}: {
  certification: string;
  className?: string;
}) {
  if (certification === "certified") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 text-[11px] font-medium text-info",
          className,
        )}
      >
        <CertifiedMark />
        Certified
      </span>
    );
  }

  if (certification === "dynamic") {
    // Composed for one question and never reviewed. Named rather than left
    // blank: a figure with no label reads as certified to somebody scanning.
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 text-[11px] font-medium text-accent",
          className,
        )}
        title="Composed for this question and run through the governed runtime. Not a certified method, and not reviewed by anybody."
      >
        <span aria-hidden className="inline-block size-1.5 rounded-full bg-accent" />
        Dynamic analysis
      </span>
    );
  }

  const custom = certification === "user_defined";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-[11px] font-medium",
        custom ? "text-text-muted" : "text-warning",
        className,
      )}
      title={
        custom
          ? "Defined in Analysis Studio by the bank. Not validated."
          : "A draft definition. Not validated, and not to be relied on."
      }
    >
      <span
        aria-hidden
        className={cn(
          "inline-block size-1.5 rounded-full",
          custom ? "bg-border-strong" : "bg-warning",
        )}
      />
      {custom ? "Custom" : "Unvalidated"}
    </span>
  );
}
