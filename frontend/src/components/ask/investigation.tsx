"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowRight,
  BookmarkPlus,
  Check,
  ChevronDown,
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
import {
  CertificationBadge,
  CertifiedMark,
} from "@/components/ui/certified-mark";
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
 * It does not present a briefing. One analysis answers the question and leads
 * the page; anything else that ran is supporting evidence, folded away until it
 * is wanted. A reader gets the answer, the chart that fits it, IPM's reading of
 * it, and a route to the Trace — in that order.
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
    const timers = stages
      .slice(1)
      .map((_, index) =>
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
                <Loader2
                  className="size-4 shrink-0 animate-spin text-accent"
                  aria-hidden
                />
              ) : (
                <CircleDashed
                  className="size-4 shrink-0 text-text-muted"
                  aria-hidden
                />
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
        Every figure in the answer is produced by a registered IPM Engine
        analysis running against the published data.
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

export function InvestigationView({
  investigation,
  onAsk,
  onReset,
  onSave,
  saved,
  savedHref,
}: {
  investigation: InvestigationResponse;
  onAsk: (question: string) => void;
  onReset: () => void;
  onSave?: () => void;
  saved?: boolean;
  savedHref?: string;
}) {
  const runId = investigation.analysis_run_id;
  const { narrative } = investigation;
  const traceHref = runId ? `/trace/${runId}` : null;

  // One step answers the question. The planner marked it, and the layout
  // follows that marking rather than the order things happened to run in.
  const primary =
    investigation.steps.find((s) => s.role === "primary") ??
    investigation.steps[0] ??
    null;
  const supporting = investigation.steps.filter((s) => s !== primary);
  const answer = narrative.direct_answer || narrative.summary;
  const reading = narrative.interpretation_points ?? [];
  const certified = investigation.steps.every(
    (s) => s.certification === "certified",
  );

  return (
    <div className="space-y-8">
      {/* ------------------------------------------------------------ header */}
      <header>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="max-w-3xl text-[22px] font-semibold leading-tight tracking-tight text-text-primary">
              {investigation.question}
            </h1>
            <p className="mt-1.5 max-w-3xl text-sm text-text-muted">
              {investigation.intent}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {onSave &&
              (saved && savedHref ? (
                <Button variant="ghost" size="sm" asChild>
                  <Link href={savedHref} title="Open the saved investigation">
                    <BookmarkPlus aria-hidden />
                    Saved
                  </Link>
                </Button>
              ) : (
                <Button variant="ghost" size="sm" onClick={onSave} disabled={saved}>
                  <BookmarkPlus aria-hidden />
                  Save
                </Button>
              ))}
            {traceHref && (
              <Button variant="outline" size="sm" asChild>
                <Link
                  href={traceHref}
                  title="See exactly how this answer was produced"
                >
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

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-text-muted">
          {certified && (
            <span className="flex items-center gap-1.5 text-info">
              <CertifiedMark />
              Certified analysis
            </span>
          )}
          {investigation.plan.scope?.from_period &&
            investigation.plan.scope?.to_period && (
              <span>
                {investigation.plan.scope.from_period} to{" "}
                {investigation.plan.scope.to_period}
              </span>
            )}
          <span>
            {investigation.steps.length}{" "}
            {investigation.steps.length === 1 ? "analysis" : "analyses"} ·{" "}
            {investigation.trace.stats.node_count} recorded steps ·{" "}
            {investigation.duration_ms}ms
          </span>
        </div>
      </header>

      {investigation.rejected.length > 0 && (
        <Card className="border-negative/40 p-5">
          <p className="text-sm font-medium text-negative">
            IPM refused to run this plan
          </p>
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
          <TriangleAlert
            className="mt-0.5 size-4 shrink-0 text-warning"
            aria-hidden
          />
          <p className="text-xs leading-relaxed text-warning">
            {investigation.notes[0]}
          </p>
        </Card>
      )}

      {/* ------------------------------------------------------- the answer */}
      {answer && (
        <p className="max-w-3xl text-[19px] font-medium leading-relaxed tracking-tight text-text-primary">
          {answer}
        </p>
      )}

      {/* --------------------------------------------------- headline figures */}
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

      {/* ------------------------------------------------------ primary visual */}
      {primary && <StepResult step={primary} runId={runId} />}

      {/* --------------------------------------------------- IPM's reading */}
      {reading.length > 0 && (
        <section className="max-w-3xl border-l-2 border-accent/40 pl-4">
          <SectionLabel>IPM&rsquo;s reading</SectionLabel>
          <ul className="space-y-2">
            {reading.map((point) => (
              <li
                key={point}
                className="text-sm leading-relaxed text-text-secondary"
              >
                {point}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
            Interpretation, not calculation. Every figure above it came from a
            registered analysis; the reading describes what those figures show
            and does not claim a cause the engine did not establish.
          </p>
        </section>
      )}

      {/* --------------------------------------------------------- findings */}
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

      {/* ----------------------------------------------------------- drivers */}
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

      {/* ------------------------------------------------- supporting evidence */}
      {supporting.length > 0 && (
        <Disclosure
          summary={`Supporting analysis (${supporting.length})`}
          hint="Run to help explain the answer, not to answer the question."
        >
          <div className="space-y-4">
            {supporting.map((step) => (
              <StepResult key={step.index} step={step} runId={runId} />
            ))}
          </div>
        </Disclosure>
      )}

      {/* ------------------------------------------------------------ caveats */}
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

      {/* --------------------------------------------------------- follow-ups */}
      {investigation.follow_ups.length > 0 && (
        <section>
          <SectionLabel>Ask next</SectionLabel>
          <div className="grid gap-2 md:grid-cols-3">
            {investigation.follow_ups.slice(0, 3).map((question) => (
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

/**
 * Something the reader can open, but does not have to.
 *
 * The answer is above; this is what is underneath it. Using the native
 * `<details>` element keeps it keyboard-accessible and printable without any
 * state of its own.
 */
function Disclosure({
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
        {hint && (
          <span className="font-normal text-text-muted/70">— {hint}</span>
        )}
      </summary>
      <div className="mt-3.5">{children}</div>
    </details>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-text-muted">
      {children}
    </h2>
  );
}

function StepResult({
  step,
  runId,
}: {
  step: ExecutedStep;
  runId: number | null;
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
          {step.rationale && (
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
