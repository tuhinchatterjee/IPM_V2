"use client";

import Link from "next/link";
import { notFound } from "next/navigation";
import * as React from "react";
import { ArrowLeft, ArrowRight, Sparkles, Target } from "lucide-react";

import { AnalyticalCard } from "@/components/analytics/analytical-card";
import { ResultView } from "@/components/analytics/result-view";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { findInvestigation, type InvestigationStep } from "@/lib/demo";
import { useAnalysis } from "@/lib/hooks";

/**
 * Investigation workspace.
 *
 * Each step executes its registered analysis for real. The interpreted objective
 * is written by the investigation's author; the *AI* interpretation and
 * narrative are explicitly marked as not yet built rather than being faked with
 * generated prose.
 */
export default function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = React.use(params);
  const investigation = findInvestigation(id);
  if (!investigation) notFound();

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/investigations">
          <ArrowLeft aria-hidden />
          Investigations
        </Link>
      </Button>

      <PageHeader
        title={investigation.title}
        description={investigation.objective}
        status="partial"
        phase="Real analyses · AI narrative next"
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="accent">{investigation.status.replace("_", " ")}</Badge>
            {investigation.project && (
              <Badge variant="outline">{investigation.project}</Badge>
            )}
          </div>
        }
      />

      {/* --------------------------------------------- question and objective */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
            <Sparkles className="size-3" aria-hidden />
            Original question
          </p>
          <p className="text-base italic text-text-primary">&ldquo;{investigation.question}&rdquo;</p>
        </Card>
        <Card className="p-5">
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
            <Target className="size-3" aria-hidden />
            Interpreted objective
          </p>
          <p className="text-sm text-text-secondary">{investigation.objective}</p>
          <p className="mt-2 text-[11px] text-text-muted">
            Written by the investigation&apos;s author. Automatic interpretation of the question
            arrives with AI orchestration.
          </p>
        </Card>
      </div>

      {/* -------------------------------------------------- AI interpretation */}
      <Card className="flex items-start gap-2.5 border-warning/30 bg-warning-muted p-4 text-sm text-warning">
        <Sparkles className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>
          <strong>AI orchestration coming next.</strong> The analytical steps below are real and
          run governed engine code. The interpretation, the narrative that links the steps, and
          the automatically generated key findings are not built yet and are deliberately absent
          rather than simulated.
        </span>
      </Card>

      {/* ------------------------------------------------------------- steps */}
      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-text-primary">
          Analysis steps
          <span className="ml-2 text-xs font-normal text-text-muted">
            {investigation.steps.length} certified analyses
          </span>
        </h2>
        <div className="space-y-4">
          {investigation.steps.map((step, i) => (
            <Step key={`${step.analysisId}-${i}`} index={i + 1} step={step} />
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------- follow-ups */}
      <Card className="p-5">
        <h3 className="mb-3 text-sm font-semibold text-text-primary">Suggested follow-ups</h3>
        <ul className="space-y-2">
          {investigation.followUps.map((q) => (
            <li key={q}>
              <Link
                href={`/?q=${encodeURIComponent(q)}`}
                className="group flex items-center justify-between gap-3 rounded-md border border-border px-4 py-2.5 transition-colors hover:bg-surface-hover"
              >
                <span className="text-sm text-text-secondary">{q}</span>
                <ArrowRight
                  className="size-3.5 shrink-0 text-text-muted opacity-0 transition-opacity group-hover:opacity-100"
                  aria-hidden
                />
              </Link>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-text-muted">
          These follow-ups were written by the author. Generated follow-ups arrive with
          orchestration.
        </p>
      </Card>
    </div>
  );
}

function Step({ index, step }: { index: number; step: InvestigationStep }) {
  const run = useAnalysis(step.analysisId, {
    params: step.params ?? {},
    filters: step.filters ?? {},
  });

  return (
    <div className="relative pl-9">
      <span className="absolute left-0 top-3 flex size-6 items-center justify-center rounded-full border border-border bg-surface text-xs font-semibold text-text-secondary tabular">
        {index}
      </span>
      <AnalyticalCard
        title={step.title}
        description={step.rationale}
        analysisId={step.analysisId}
        run={run.data}
        loading={run.loading}
        error={run.error}
        onRetry={run.reload}
        minHeight={220}
      >
        {run.data && <ResultView run={run.data} compact />}
      </AnalyticalCard>
    </div>
  );
}
