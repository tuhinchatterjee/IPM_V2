"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowRight,
  BadgeCheck,
  Check,
  CircleDashed,
  GitBranch,
  Loader2,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { ResultView } from "@/components/analytics/result-view";
import { KpiTile } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type {
  AnalysisRunResponse,
  ExecutedStep,
  InvestigationResponse,
  Stage,
} from "@/lib/api";
import { byUnit } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The investigation experience.
 *
 * Two things it deliberately does NOT do.
 *
 * It does not stream a model's thinking. The stages below are the real phases of
 * the request — reading the question, choosing analyses, reading governed data,
 * running the engine, writing the findings — shown so the wait is legible. They
 * are not chain-of-thought, and there is none to show: the planner selects from
 * a fixed library and the figures come from tested code.
 *
 * It does not present the narrative as the answer. The executive summary sits
 * above the evidence, and every result block below it carries its own Trace
 * button, so a reader can go from a sentence to the exact rows behind it.
 */

/* ------------------------------------------------------------------ stages */

export function InvestigationProgress({
  stages,
  question,
}: {
  stages: Stage[];
  question: string;
}) {
  // The stages advance on a timer because the request is a single round trip:
  // the backend does all five phases before it replies. The timing is honest
  // about that — it is a progress indication, not a claim to be watching the
  // server. The final stage stays lit until the answer arrives.
  const [reached, setReached] = React.useState(0);

  React.useEffect(() => {
    // Only timers here — no synchronous setState. The component is mounted fresh
    // for each question, so `reached` already starts at zero and needs no reset.
    const timers = stages.slice(1).map((_, index) =>
      setTimeout(() => setReached(index + 1), 550 * (index + 1)),
    );
    return () => timers.forEach(clearTimeout);
  }, [stages]);

  return (
    <Card className="p-6">
      <p className="flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-text-muted">
        <Sparkles className="size-3.5 text-accent" aria-hidden />
        Investigating
      </p>
      <p className="mt-2 max-w-2xl text-lg font-medium leading-snug tracking-tight text-text-primary">
        {question}
      </p>
      <ol className="mt-5 space-y-2.5">
        {stages.map((stage, index) => {
          const done = index < reached;
          const active = index === reached;
          return (
            <li key={stage.id} className="flex items-center gap-2.5 text-sm">
              {done ? (
                <Check className="size-4 shrink-0 text-positive" aria-hidden />
              ) : active ? (
                <Loader2 className="size-4 shrink-0 animate-spin text-accent" aria-hidden />
              ) : (
                <CircleDashed className="size-4 shrink-0 text-text-muted" aria-hidden />
              )}
              <span
                className={cn(
                  done && "text-text-secondary",
                  active && "text-text-primary",
                  !done && !active && "text-text-muted",
                )}
              >
                {stage.label}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-5 border-t border-border pt-3 text-xs text-text-muted">
        Every figure in the answer is produced by a registered IPM Engine analysis running
        against the published data.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ answer */

/** An executed step, in the shape the shared result renderer expects. */
function asRun(step: ExecutedStep, runId: number | null): AnalysisRunResponse {
  return {
    analysis_id: step.analysis_id,
    analysis_version: step.analysis_version,
    certification: step.certification,
    status: step.status,
    params: step.params,
    context: { period: step.period, filters: step.filters },
    result: step.result,
    duration_ms: step.duration_ms,
    error: step.error,
    trace: step.trace ?? { nodes: [], edges: [], layers: [], stats: {
      node_count: 0, edge_count: 0, governed_nodes: 0, interpretive_nodes: 0 } },
    node_hashes: step.node_hashes,
    analysis_run_id: runId,
  };
}

const TONE_CLASS: Record<string, string> = {
  negative: "border-l-negative",
  warning: "border-l-warning",
  positive: "border-l-positive",
  neutral: "border-l-border-strong",
};

export function InvestigationView({
  investigation,
  onAsk,
  onReset,
}: {
  investigation: InvestigationResponse;
  onAsk: (question: string) => void;
  onReset: () => void;
}) {
  const runId = investigation.analysis_run_id;
  const { narrative } = investigation;
  const traceHref = runId ? `/trace/${runId}` : null;

  return (
    <div className="space-y-7">
      {/* ------------------------------------------------------------ header */}
      <header className="border-b border-border pb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
              Investigation
            </p>
            <h1 className="mt-2 max-w-3xl text-2xl font-semibold leading-tight tracking-tight text-text-primary">
              {investigation.question}
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-text-secondary">{investigation.intent}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {traceHref && (
              <Button variant="outline" size="sm" asChild>
                <Link href={traceHref} title="See exactly how this answer was produced">
                  <GitBranch aria-hidden />
                  Trace
                </Link>
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onReset}>
              New question
            </Button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-muted">
          <span>
            {investigation.steps.length}{" "}
            {investigation.steps.length === 1 ? "analysis" : "analyses"} ·{" "}
            {investigation.trace.stats.node_count} recorded steps
          </span>
          <span>{investigation.duration_ms}ms</span>
          <span className="flex items-center gap-1">
            <BadgeCheck className="size-3.5 text-info" aria-hidden />
            {investigation.steps.filter((s) => s.certification === "certified").length} certified
          </span>
        </div>
      </header>

      {investigation.rejected.length > 0 && (
        <Card className="border-negative/40 p-5">
          <p className="text-sm font-medium text-negative">IPM refused to run this plan</p>
          <ul className="mt-2 space-y-1">
            {investigation.rejected.map((reason) => (
              <li key={reason} className="text-xs text-negative">
                {reason}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {investigation.unmatched && investigation.notes.length > 0 && (
        <Card className="flex items-start gap-2.5 border-warning/30 bg-warning-muted p-4">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <p className="text-xs leading-relaxed text-warning">{investigation.notes[0]}</p>
        </Card>
      )}

      {/* -------------------------------------------------- executive summary */}
      {narrative.summary && (
        <section>
          <SectionLabel>Executive summary</SectionLabel>
          <p className="max-w-3xl text-[17px] leading-relaxed text-text-primary">
            {narrative.summary}
          </p>
        </section>
      )}

      {/* ---------------------------------------------------- headline metrics */}
      {narrative.metrics.length > 0 && (
        <section>
          <SectionLabel>Headline metrics</SectionLabel>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {narrative.metrics.map((metric) => (
              <KpiTile
                key={metric.label}
                label={metric.label}
                value={metric.value}
                unit={metric.unit}
                change={metric.change}
                changeUnit={metric.change_unit}
                direction={metric.direction}
                hint={metric.hint}
              />
            ))}
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------- findings */}
      {narrative.findings.length > 0 && (
        <section>
          <SectionLabel>Key findings</SectionLabel>
          <ul className="space-y-2.5">
            {narrative.findings.map((finding, i) => (
              <li
                key={i}
                className={cn(
                  "border-l-2 py-0.5 pl-3.5",
                  TONE_CLASS[finding.tone] ?? TONE_CLASS.neutral,
                )}
              >
                <p className="text-sm leading-relaxed text-text-primary">{finding.text}</p>
                {finding.evidence.length > 0 && (
                  <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
                    {finding.evidence.map((e) => (
                      <span key={e.label} className="tabular">
                        {e.label} {byUnit(e.value, e.unit)}
                      </span>
                    ))}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ----------------------------------------------------------- drivers */}
      {narrative.drivers.length > 0 && (
        <section>
          <SectionLabel>What is driving it</SectionLabel>
          <Card className="divide-y divide-border">
            {narrative.drivers.map((driver) => (
              <div key={driver.name} className="flex items-baseline gap-3 px-4 py-2.5">
                <span className="min-w-0 flex-1 truncate text-sm text-text-primary">
                  {driver.name}
                </span>
                {driver.detail && (
                  <span className="hidden max-w-[26rem] truncate text-xs text-text-muted lg:block">
                    {driver.detail}
                  </span>
                )}
                <span
                  className={cn(
                    "shrink-0 text-sm font-medium tabular",
                    (driver.value ?? 0) > 0 ? "text-negative" : "text-positive",
                  )}
                >
                  {byUnit(driver.value, driver.unit)}
                </span>
              </div>
            ))}
            <p className="px-4 py-2 text-[11px] text-text-muted">
              {narrative.drivers[0]?.measure} — ranked by the engine, not re-ordered here.
            </p>
          </Card>
        </section>
      )}

      {/* ------------------------------------------------------------ results */}
      <section>
        <SectionLabel>Evidence</SectionLabel>
        <div className="space-y-4">
          {investigation.steps.map((step) => (
            <StepResult key={step.index} step={step} runId={runId} />
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ caveats */}
      {narrative.caveats.length > 0 && (
        <section>
          <SectionLabel>Caveats</SectionLabel>
          <ul className="space-y-1">
            {narrative.caveats.map((caveat) => (
              <li key={caveat} className="flex gap-2 text-xs text-text-muted">
                <TriangleAlert className="mt-0.5 size-3 shrink-0 text-warning" aria-hidden />
                {caveat}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* --------------------------------------------------------- follow-ups */}
      {investigation.follow_ups.length > 0 && (
        <section>
          <SectionLabel>Recommended next questions</SectionLabel>
          <div className="grid gap-2 md:grid-cols-3">
            {investigation.follow_ups.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onAsk(question)}
                className="group flex items-start gap-2.5 rounded-lg border border-border bg-surface p-3.5 text-left transition-colors hover:border-accent hover:bg-surface-hover"
              >
                <span className="min-w-0 flex-1 text-sm leading-snug text-text-primary">
                  {question}
                </span>
                <ArrowRight
                  className="mt-0.5 size-3.5 shrink-0 text-text-muted transition-colors group-hover:text-accent"
                  aria-hidden
                />
              </button>
            ))}
          </div>
        </section>
      )}

      <p className="border-t border-border pt-4 text-xs leading-relaxed text-text-muted">
        {investigation.mode.description}
      </p>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
      {children}
    </h2>
  );
}

function StepResult({ step, runId }: { step: ExecutedStep; runId: number | null }) {
  const run = React.useMemo(() => asRun(step, runId), [step, runId]);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold tracking-tight text-text-primary">
              {step.title || step.analysis_id}
            </h3>
            {step.certification === "certified" ? (
              <span
                className="inline-flex items-center gap-1 text-[11px] font-medium text-info"
                title="IPM Certified — validated and tested by the bank"
              >
                <BadgeCheck className="size-3.5" aria-hidden />
              </span>
            ) : (
              <Badge variant="warning">User defined</Badge>
            )}
            {step.reused && (
              <Badge variant="outline" title="Nothing about this step changed, so it was not re-run">
                Reused
              </Badge>
            )}
          </div>
          {step.rationale && (
            <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-text-muted">
              {step.rationale}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/engine-builder/${step.analysis_id}`} title="Open the analysis definition">
              Method
            </Link>
          </Button>
          {runId ? (
            <Button variant="ghost" size="sm" asChild>
              <Link href={`/trace/${runId}`} title="See exactly how this result was produced">
                <GitBranch aria-hidden />
                Trace
              </Link>
            </Button>
          ) : (
            <Button variant="ghost" size="sm" disabled>
              <GitBranch aria-hidden />
              Trace
            </Button>
          )}
        </div>
      </div>

      <div className="px-5 py-4">
        {step.status === "succeeded" && step.result ? (
          <ResultView run={run} />
        ) : (
          <p className="text-sm text-negative">{step.error ?? "This analysis returned nothing."}</p>
        )}
      </div>

      {(step.result?.warnings.length ?? 0) > 0 && (
        <div className="border-t border-border bg-surface-sunken px-5 py-2.5">
          {step.result?.warnings.map((warning) => (
            <p key={warning} className="flex items-start gap-1.5 text-xs text-warning">
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {warning}
            </p>
          ))}
        </div>
      )}
    </Card>
  );
}
