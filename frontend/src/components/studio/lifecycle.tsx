"use client";

import { BadgeCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";

/**
 * How far a method has got, said in one place.
 *
 * The distinction the whole Studio rests on is between a method that has been
 * *written down* and one that has been *proven*, and a label composed at the
 * call site is a label that eventually drifts. Only `certified` gets the mark;
 * everything else says plainly what it is, including "definition only".
 */
export function LifecycleMark({
  lifecycle,
  label,
  compact = false,
}: {
  lifecycle: string;
  label?: string;
  compact?: boolean;
}) {
  if (lifecycle === "certified") {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs font-medium text-info"
        title="CreditProbe Certified — a written methodology, a runnable implementation, and test cases that have been run and passed"
      >
        <BadgeCheck className="size-3.5 shrink-0" aria-hidden />
        {!compact && "CreditProbe Certified"}
      </span>
    );
  }

  const variant =
    lifecycle === "validated"
      ? "positive"
      : lifecycle === "preconfigured" || lifecycle === "preview"
        ? "outline"
        : lifecycle === "deprecated"
          ? "negative"
          : "default";

  return (
    <Badge variant={variant} className="whitespace-nowrap">
      {label ?? lifecycle}
    </Badge>
  );
}

/** Passed / failed / not run, in the same words everywhere. */
export function CaseVerdict({ passed }: { passed: boolean | null }) {
  if (passed === true) return <span className="text-xs text-positive">Passed</span>;
  if (passed === false) return <span className="text-xs text-negative">Failed</span>;
  return <span className="text-xs text-text-muted">Not run</span>;
}
