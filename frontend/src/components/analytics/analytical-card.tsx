"use client";

import Link from "next/link";
import * as React from "react";
import {
  AlertTriangle,
  BadgeCheck,
  GitBranch,
  RotateCcw,
  Search,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { AnalysisRunResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The standard container for an analytical result.
 *
 * Two things about it are product rules rather than styling choices:
 *
 *  1. **The Trace button sits in the top-right of every analytical output**, in
 *     the same place on every card, so "how was this produced?" is one
 *     predictable click from any number on the screen.
 *
 *  2. **Certification is shown next to the result, not buried in a settings
 *     page.** The blue tick tells a reader whether the bank has validated the
 *     calculation that produced the figure they are looking at.
 */

export function CertificationMark({
  certification,
  compact = false,
}: {
  certification: string;
  compact?: boolean;
}) {
  if (certification === "certified") {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs font-medium text-info"
        title="CreditProbe Certified — validated and tested by the bank"
      >
        <BadgeCheck className="size-3.5 shrink-0" aria-hidden />
        {!compact && "CreditProbe Certified"}
      </span>
    );
  }
  if (certification === "user_defined") {
    return (
      <Badge variant="warning" title="Built by a user and not yet certified by the bank">
        User Defined
      </Badge>
    );
  }
  return <Badge variant="outline">{certification}</Badge>;
}

/** The Trace affordance. Consistent everywhere an analytical figure appears. */
export function TraceButton({
  runId,
  disabled,
  label = "Trace",
}: {
  runId: number | null | undefined;
  disabled?: boolean;
  label?: string;
}) {
  if (!runId || disabled) {
    return (
      <Button
        variant="ghost"
        size="sm"
        disabled
        title="Trace becomes available once the analysis has run"
      >
        <GitBranch aria-hidden />
        {label}
      </Button>
    );
  }
  return (
    <Button variant="ghost" size="sm" asChild>
      <Link href={`/trace/${runId}`} title="See exactly how this result was produced">
        <GitBranch aria-hidden />
        {label}
      </Link>
    </Button>
  );
}

interface AnalyticalCardProps {
  title: string;
  description?: string;
  /** The run this card is displaying. Drives Trace, certification and errors. */
  run?: AnalysisRunResponse | null;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Analysis id, used by the "View analysis" and "Investigate" links. */
  analysisId?: string;
  /** Show View analysis / Investigate alongside Trace. */
  actions?: boolean;
  footer?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
  /** Height reserved while loading, so the page does not jump. */
  minHeight?: number;
}

export function AnalyticalCard({
  title,
  description,
  run,
  loading,
  error,
  onRetry,
  analysisId,
  actions = true,
  footer,
  className,
  children,
  minHeight = 180,
}: AnalyticalCardProps) {
  const warnings = run?.result?.warnings ?? [];
  const period = (run?.context?.period as string | undefined) ?? undefined;

  return (
    <Card className={cn("flex flex-col overflow-hidden", className)}>
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold tracking-tight text-text-primary">{title}</h3>
            {run && <CertificationMark certification={run.certification} compact />}
          </div>
          {description && (
            <p className="mt-0.5 truncate text-xs text-text-muted">{description}</p>
          )}
        </div>

        {/* Top-right action cluster. Trace is always last and always present. */}
        <div className="flex shrink-0 items-center gap-0.5">
          {actions && analysisId && (
            <>
              <Button variant="ghost" size="sm" asChild>
                <Link href={`/engine-builder/${analysisId}`} title="Open the analysis definition">
                  View
                </Link>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link
                  href={`/investigations/new?analysis=${analysisId}`}
                  title="Start an investigation from this result"
                >
                  <Search aria-hidden />
                  Investigate
                </Link>
              </Button>
            </>
          )}
          <TraceButton runId={run?.analysis_run_id} />
        </div>
      </div>

      <div className="flex-1 px-5 py-4" style={{ minHeight }}>
        {loading && (
          <div className="space-y-3" aria-busy>
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        )}

        {!loading && error && (
          <div className="flex h-full flex-col items-start justify-center gap-3">
            <p className="flex items-start gap-2 text-sm text-negative">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>{error}</span>
            </p>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry}>
                <RotateCcw aria-hidden />
                Try again
              </Button>
            )}
          </div>
        )}

        {!loading && !error && children}
      </div>

      {(warnings.length > 0 || footer || period) && (
        <div className="space-y-2 border-t border-border bg-surface-sunken px-5 py-2.5">
          {warnings.map((warning) => (
            <p key={warning} className="flex items-start gap-1.5 text-xs text-warning">
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {warning}
            </p>
          ))}
          {footer}
          {period && !footer && (
            <p className="text-xs text-text-muted">
              Reporting period {period}
              {run?.duration_ms ? ` · computed in ${run.duration_ms}ms` : ""}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
