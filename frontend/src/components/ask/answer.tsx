"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowRight,
  BookmarkPlus,
  Check,
  ChevronDown,
  GitBranch,
  TriangleAlert,
} from "lucide-react";

import { KpiTile } from "@/components/analytics/primitives";
import { ResultView } from "@/components/analytics/result-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CertificationBadge, CertifiedMark } from "@/components/ui/certified-mark";
import type {
  AnalysisRunResponse,
  ExecutedStep,
  InvestigationResponse,
} from "@/lib/api";
import { byUnit } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * ONE response architecture, used everywhere CreditProbe answers.
 *
 * Every answer — on the Cockpit, inside an Investigation, under a Lens — is laid
 * out in the same four movements, in this order:
 *
 *   1. ANSWER                   the sentence, the headline figures, the one chart
 *   2. ANALYSES USED            which certified functions produced those figures
 *   3. CREDITPROBE INTERPRETATION  what CreditProbe reads into them, labelled as reading
 *   4. FOLLOW-UPS               three short things to ask next
 *
 * (The composer sits between 3 and 4 and belongs to the page, not to this
 * component, because a thread has one composer at the bottom rather than one
 * under every answer.)
 *
 * The order is the argument. A reader gets the conclusion first, then the
 * evidence for it, and only then an opinion about it — clearly separated, so
 * nobody mistakes CreditProbe's reading for something the engine calculated.
 * Reversing any two of those would change what the product is claiming.
 */

/* ------------------------------------------------------------------ helpers */

/** An executed step, in the shape the shared result renderer expects. */
export function asRun(
  step: ExecutedStep,
  runId: number | null,
): AnalysisRunResponse {
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
    trace: step.trace ?? {
      nodes: [],
      edges: [],
      layers: [],
      stats: {
        node_count: 0,
        edge_count: 0,
        governed_nodes: 0,
        interpretive_nodes: 0,
      },
    },
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

/** Something the reader can open, but does not have to. */
export function Disclosure({
  summary,
  hint,
  children,
}: {
  summary: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-text-muted transition-colors hover:text-text-primary">
        <ChevronDown
          className="size-3.5 transition-transform group-open:rotate-180"
          aria-hidden
        />
        {summary}
        {hint && <span className="font-normal text-text-muted/70">— {hint}</span>}
      </summary>
      <div className="mt-3.5">{children}</div>
    </details>
  );
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
      {children}
    </h2>
  );
}

/* ------------------------------------------------------------- step results */

export function StepResult({
  step,
  runId,
  compact,
}: {
  step: ExecutedStep;
  runId: number | null;
  /** Inside a thread, a result sits closer to the text around it. */
  compact?: boolean;
}) {
  const run = React.useMemo(() => asRun(step, runId), [step, runId]);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold tracking-tight text-text-primary">
              {step.title || step.analysis_id}
            </h3>
            <CertificationBadge certification={step.certification} />
            {step.reused && (
              <Badge
                variant="outline"
                title="Nothing about this step changed, so it was not re-run"
              >
                Reused
              </Badge>
            )}
          </div>
          {step.rationale && !compact && (
            <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-text-muted">
              {step.rationale}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Button variant="ghost" size="sm" asChild>
            <Link
              href={`/engine-builder/${step.analysis_id}`}
              title="Open the analysis definition"
            >
              Method
            </Link>
          </Button>
          {runId ? (
            <Button variant="ghost" size="sm" asChild>
              <Link
                href={`/trace/${runId}`}
                title="See exactly how this result was produced"
              >
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
          <p className="text-sm text-negative">
            {step.error ?? "This analysis returned nothing."}
          </p>
        )}
      </div>

      {(step.result?.warnings.length ?? 0) > 0 && (
        <div className="border-t border-border bg-surface-sunken px-5 py-2.5">
          {step.result?.warnings.map((warning) => (
            <p
              key={warning}
              className="flex items-start gap-1.5 text-xs text-warning"
            >
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
              {warning}
            </p>
          ))}
        </div>
      )}
    </Card>
  );
}

/* --------------------------------------------------------- analyses used */

/**
 * Which certified functions produced the figures above.
 *
 * Named as its own section rather than left implicit. "Where did this number
 * come from" is the first question a credit committee asks, and an answer that
 * makes them hunt for it has failed before the figure is even discussed.
 */
export function AnalysesUsed({
  steps,
  runId,
}: {
  steps: ExecutedStep[];
  runId: number | null;
}) {
  if (steps.length === 0) return null;

  return (
    <section>
      <SectionLabel>Analyses used</SectionLabel>
      <Card className="divide-y divide-border">
        {steps.map((step) => (
          <div
            key={step.index}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5"
          >
            <Link
              href={`/engine-builder/${step.analysis_id}`}
              className="text-sm font-medium text-text-primary hover:text-accent"
            >
              {step.title || step.analysis_id}
            </Link>
            <CertificationBadge certification={step.certification} />
            <span className="text-[11px] text-text-muted">
              {step.analysis_version && `v${step.analysis_version}`}
              {step.period && ` · ${step.period}`}
              {step.role === "supporting" && " · supporting"}
            </span>
            <span className="ml-auto text-[11px] text-text-muted">
              {step.status === "succeeded" ? `${step.duration_ms}ms` : step.status}
            </span>
          </div>
        ))}
        {runId && (
          <div className="px-4 py-2">
            <Link
              href={`/trace/${runId}`}
              className="inline-flex items-center gap-1.5 text-[11px] text-text-muted hover:text-accent"
            >
              <GitBranch className="size-3" aria-hidden />
              Follow every figure back to the rows behind it
            </Link>
          </div>
        )}
      </Card>
    </section>
  );
}

/* --------------------------------------------------------- interpretation */

/**
 * CreditProbe's reading — and nothing else on the page is.
 *
 * Kept visually distinct (its own rule, its own label, its own footnote) because
 * the separation between what was calculated and what was inferred is the single
 * most important boundary in the product.
 */
export function Interpretation({ points }: { points: string[] }) {
  if (points.length === 0) return null;

  return (
    <section className="max-w-3xl border-l-2 border-accent/40 pl-4">
      <SectionLabel>CreditProbe interpretation</SectionLabel>
      <ul className="space-y-2">
        {points.map((point) => (
          <li key={point} className="text-sm leading-relaxed text-text-secondary">
            {point}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
        Interpretation, not calculation. Every figure above came from a registered
        analysis; this describes what those figures show and does not claim a
        cause the engine did not establish.
      </p>
    </section>
  );
}

/* ---------------------------------------------------------------- follow-ups */

export function FollowUps({
  questions,
  onAsk,
  busy,
}: {
  questions: string[];
  onAsk: (question: string) => void;
  busy?: boolean;
}) {
  if (questions.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5">
      {questions.slice(0, 3).map((question) => (
        <button
          key={question}
          type="button"
          disabled={busy}
          onClick={() => onAsk(question)}
          className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {question}
          <ArrowRight
            className="size-3 text-text-muted transition-colors group-hover:text-accent"
            aria-hidden
          />
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- the answer */

/**
 * One answer, in the standard four movements.
 *
 * `onSave` is offered wherever an answer can become evidence. Saving keeps the
 * analyses behind the answer — the certified functions and their results — not
 * a screenshot of the text.
 */
export function AnswerBlock({
  run,
  onAsk,
  onSave,
  saved,
  busy,
  compact,
}: {
  run: InvestigationResponse;
  onAsk?: (question: string) => void;
  onSave?: () => void;
  saved?: boolean;
  busy?: boolean;
  /** Inside a thread the answer sits tighter and drops the run statistics. */
  compact?: boolean;
}) {
  const runId = run.analysis_run_id;
  const { narrative } = run;
  const answer = narrative.direct_answer || narrative.summary;
  const reading = narrative.interpretation_points ?? [];

  // One step answers the question. The planner marked it, and the layout follows
  // that marking rather than the order things happened to run in.
  const primary =
    run.steps.find((s) => s.role === "primary") ?? run.steps[0] ?? null;
  const supporting = run.steps.filter((s) => s !== primary);
  const certified =
    run.steps.length > 0 && run.steps.every((s) => s.certification === "certified");

  return (
    <div className={cn(compact ? "space-y-5" : "space-y-8")}>
      {run.rejected.length > 0 && (
        <Card className="border-negative/40 p-5">
          <p className="text-sm font-medium text-negative">
            CreditProbe refused to run this plan
          </p>
          <ul className="mt-2 space-y-1">
            {run.rejected.map((reason) => (
              <li key={reason} className="text-xs text-negative">
                {reason}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {run.unmatched && run.notes.length > 0 && (
        <Card className="flex items-start gap-2.5 border-warning/30 bg-warning-muted p-4">
          <TriangleAlert
            className="mt-0.5 size-4 shrink-0 text-warning"
            aria-hidden
          />
          <p className="text-xs leading-relaxed text-warning">{run.notes[0]}</p>
        </Card>
      )}

      {/* ------------------------------------------------------- 1. ANSWER */}
      {answer && (
        <p className="max-w-3xl text-[18px] font-medium leading-relaxed tracking-tight text-text-primary">
          {answer}
        </p>
      )}

      {narrative.metrics.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
      )}

      {primary && <StepResult step={primary} runId={runId} compact={compact} />}

      {narrative.findings.length > 1 && (
        <Disclosure summary={`Findings in full (${narrative.findings.length})`}>
          <ul className="space-y-2.5">
            {narrative.findings.map((finding, i) => (
              <li
                key={i}
                className={cn(
                  "border-l-2 py-0.5 pl-3.5",
                  TONE_CLASS[finding.tone] ?? TONE_CLASS.neutral,
                )}
              >
                <p className="text-sm leading-relaxed text-text-primary">
                  {finding.text}
                </p>
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
        </Disclosure>
      )}

      {narrative.drivers.length > 0 && (
        <Disclosure summary={`${narrative.drivers[0]?.measure} by contributor`}>
          <Card className="divide-y divide-border">
            {narrative.drivers.map((driver) => (
              <div
                key={driver.name}
                className="flex items-baseline gap-3 px-4 py-2.5"
              >
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
              Ranked by the engine, not re-ordered here.
            </p>
          </Card>
        </Disclosure>
      )}

      {/* ------------------------------------------------ 2. ANALYSES USED */}
      <AnalysesUsed steps={run.steps} runId={runId} />

      {supporting.length > 0 && (
        <Disclosure
          summary={`Supporting results (${supporting.length})`}
          hint="Run to help explain the answer, not to answer the question."
        >
          <div className="space-y-4">
            {supporting.map((step) => (
              <StepResult key={step.index} step={step} runId={runId} compact />
            ))}
          </div>
        </Disclosure>
      )}

      {/* --------------------------------------- 3. CREDITPROBE INTERPRETATION */}
      <Interpretation points={reading} />

      {narrative.caveats.length > 0 && (
        <ul className="space-y-1">
          {narrative.caveats.map((caveat) => (
            <li key={caveat} className="flex gap-2 text-xs text-text-muted">
              <TriangleAlert
                className="mt-0.5 size-3 shrink-0 text-warning"
                aria-hidden
              />
              {caveat}
            </li>
          ))}
        </ul>
      )}

      {/* ------------------------------------------------- provenance and save */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-text-muted">
        {certified && (
          <span className="flex items-center gap-1.5 text-info">
            <CertifiedMark />
            Certified analysis
          </span>
        )}
        {run.plan.scope?.from_period && run.plan.scope?.to_period && (
          <span>
            {run.plan.scope.from_period} to {run.plan.scope.to_period}
          </span>
        )}
        {!compact && (
          <span>
            {run.steps.length} {run.steps.length === 1 ? "analysis" : "analyses"} ·{" "}
            {run.trace.stats.node_count} recorded steps · {run.duration_ms}ms
          </span>
        )}
        {onSave && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            onClick={onSave}
            disabled={saved || busy}
          >
            {saved ? <Check aria-hidden /> : <BookmarkPlus aria-hidden />}
            {saved ? "Saved" : "Save analysis"}
          </Button>
        )}
      </div>

      {/* ---------------------------------------------------- 4. FOLLOW-UPS */}
      {onAsk && <FollowUps questions={run.follow_ups} onAsk={onAsk} busy={busy} />}
    </div>
  );
}
