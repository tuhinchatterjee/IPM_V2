"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowRight,
  BookmarkPlus,
  Check,
  ChevronDown,
  FolderPlus,
  GitBranch,
  TriangleAlert,
} from "lucide-react";

import { DataAndMethod } from "@/components/ask/data-and-method";
import { DynamicAnalysisPanel } from "@/components/ask/dynamic-analysis";
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
import { isRegisteredMethod, stepHref } from "@/lib/analysis-links";
import { withReturnTo } from "@/lib/return-to";
import { cn } from "@/lib/utils";

/**
 * ONE response architecture, used everywhere CreditProbe answers.
 *
 * The order is the argument:
 *
 *   1. DIRECT ANSWER          the sentence that answers the question asked
 *   2. ANALYST INTERPRETATION what it means, written rather than computed
 *   3. PRIMARY VISUAL / TABLE the figures and the one chart behind them
 *   4. EXCEPTIONS AND LIMITS  only when there is something material
 *   5. SUPPORTING ANALYSES    collapsed; open them if you want them
 *   6. DATA AND METHOD        collapsed; plan, SQL, joins, validations
 *   7. ACTION STRIP           certified · trace · save · project
 *   8. SUGGESTED QUESTIONS    three or four things worth asking next
 *
 * (The composer sits between 7 and 8 and belongs to the page, because a thread
 * has one composer at the bottom rather than one under every answer.)
 *
 * The direct answer comes FIRST and ALONE, and that is the change that matters
 * most. An answer that opens with total exposure at default when the question
 * was about sector deterioration is a portfolio review wearing the costume of
 * an answer. A reader who stops at the first sentence must already have what
 * they asked for.
 *
 * The interpretation is separate from it, and visibly so. The boundary between
 * what was CALCULATED and what CreditProbe made of it is the most important
 * line in the product. It was also, until now, the line that never reached the
 * screen: the paragraph was composed, grounded figure by figure against the
 * result, withheld when one number could not be traced — and then dropped by
 * the layout, which rendered only the headline.
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
  defaultOpen,
}: {
  summary: string;
  hint?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="group" open={defaultOpen}>
      <summary className="meta flex cursor-pointer list-none items-center gap-1.5 text-text-muted transition-colors hover:text-text-primary">
        <ChevronDown
          className="size-3.5 transition-transform group-open:rotate-180"
          aria-hidden
        />
        {summary}
        {hint && (
          <span className="font-normal normal-case tracking-normal text-text-muted/70">
            — {hint}
          </span>
        )}
      </summary>
      <div className="mt-3.5">{children}</div>
    </details>
  );
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="meta mb-2.5 text-text-muted">{children}</h2>;
}

/* ------------------------------------------------------------- step results */

export function StepResult({
  step,
  runId,
  compact,
  returnTo,
  question,
}: {
  step: ExecutedStep;
  runId: number | null;
  /** Inside a thread, a result sits closer to the text around it. */
  compact?: boolean;
  /** Where Method and Trace should come back to. */
  returnTo?: { href: string; label: string };
  /** The question this answered. Carried so a composed analysis can be saved
   *  with the sentence it came from rather than with a generated title. */
  question?: string;
}) {
  const run = React.useMemo(() => asRun(step, runId), [step, runId]);
  // A composed analysis has no definition in the library to open — it did not
  // exist until the question was asked. It carries its own working instead.
  const dynamic = step.certification === "dynamic";
  const definition = isRegisteredMethod(step.analysis_id, step.certification)
    ? `/engine-builder/${step.analysis_id}`
    : null;
  const method =
    definition && returnTo
      ? withReturnTo(definition, returnTo.href, returnTo.label)
      : definition;
  const trace =
    runId && returnTo
      ? withReturnTo(`/trace/${runId}`, returnTo.href, returnTo.label)
      : runId
        ? `/trace/${runId}`
        : null;

  return (
    <Card className="overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="display text-sm font-semibold text-text-primary">
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
            <p className="prose-ai mt-0.5 max-w-2xl text-xs text-text-muted">
              {step.rationale}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {method && (
            <Button variant="ghost" size="sm" asChild>
              <Link href={method} title="Open the analysis definition">
                Method
              </Link>
            </Button>
          )}
          {trace ? (
            <Button variant="ghost" size="sm" asChild>
              <Link href={trace} title="See exactly how this result was produced">
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

      {/* Before the composed-analysis disclosure, because "which data, joined
          how" is the question a reader has first — and it applies to a
          certified multi-dataset answer too, which has no composition panel. */}
      {step.result && <DataAndMethod result={step.result} />}

      {dynamic && step.result && (
        <DynamicAnalysisPanel result={step.result} question={question ?? ""} />
      )}

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

/* --------------------------------------------------------- the answer text */

/**
 * The sentence that answers the question, and nothing else.
 *
 * First and alone. Everything below it is evidence for it, and a reader who
 * stops here has the answer — which is the test the whole response architecture
 * is built to pass.
 */
export function DirectAnswer({
  answer,
  scope,
}: {
  answer: string;
  /**
   * What these figures cover: the population, the window, the measures.
   *
   * Above the answer rather than below it. A figure computed over five carried
   * names and read as a portfolio total is wrong by three orders of magnitude
   * and looks exactly like the right answer; the only thing that prevents it is
   * seeing the scope before reading the number.
   */
  scope?: string;
}) {
  if (!answer) return null;

  return (
    <section className="max-w-[68ch]">
      {scope && (
        <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.08em] text-text-muted">
          {scope}
        </p>
      )}
      <p className="prose-ai text-[17px] leading-[1.5] text-text-primary">
        {answer}
      </p>
    </section>
  );
}

/**
 * What it means, written by CreditProbe rather than computed.
 *
 * This paragraph was being thrown away. The backend composed it, grounded every
 * figure in it against the result, withheld it when a single number could not
 * be traced — and the answer surface rendered only the headline, so the reading
 * a credit officer was meant to get never reached the screen. An interpretation
 * that is computed, checked and then discarded by the layout is worse than none:
 * it costs a model call and the product looks incapable of analysis.
 *
 * Kept visually distinct from the direct answer above it. The boundary between
 * what was CALCULATED and what CreditProbe made of it is the most important
 * line in the product, and a reader has to be able to see it without being
 * told.
 */
export function AnalystReading({
  interpretation,
  points,
  whyMultiple,
}: {
  interpretation?: string;
  points: string[];
  whyMultiple?: string;
}) {
  const notes = points.filter(Boolean);
  if (!interpretation && notes.length === 0 && !whyMultiple) return null;

  return (
    <section className="max-w-[68ch] border-l-2 border-accent/40 pl-4">
      <SectionLabel>CreditProbe interpretation</SectionLabel>
      {interpretation && (
        <p className="prose-ai text-[15px] leading-relaxed text-text-secondary">
          {interpretation}
        </p>
      )}
      {notes.length > 0 && (
        <ul className={cn("space-y-1.5", interpretation && "mt-2.5")}>
          {notes.slice(0, 3).map((note) => (
            <li
              key={note}
              className="prose-ai flex gap-2 text-sm text-text-secondary"
            >
              <span aria-hidden className="mt-[0.55em] size-1 shrink-0 rounded-full bg-accent/60" />
              {note}
            </li>
          ))}
        </ul>
      )}
      {whyMultiple && (
        <p className="prose-ai mt-2.5 text-xs text-text-muted">{whyMultiple}</p>
      )}
    </section>
  );
}

/**
 * What limits what may be concluded. Shown only when there is something.
 *
 * Between the figures and the supporting detail, which is where a reader is
 * deciding whether to act. A limitation disclosed after the follow-up buttons
 * is a limitation disclosed to nobody.
 */
export function Limitations({ caveats }: { caveats: string[] }) {
  const material = caveats.filter(Boolean);
  if (material.length === 0) return null;

  return (
    <ul className="max-w-[68ch] space-y-1">
      {material.map((caveat) => (
        <li key={caveat} className="flex gap-2 text-xs text-text-muted">
          <TriangleAlert
            className="mt-0.5 size-3 shrink-0 text-warning"
            aria-hidden
          />
          {caveat}
        </li>
      ))}
    </ul>
  );
}

/* --------------------------------------------------------- analyses used */

/**
 * Which certified functions produced the figures.
 *
 * Behind a disclosure rather than always open: "where did this come from" is
 * the first question a committee asks, but it is not the first thing every
 * reader needs on screen. One click, and it is complete.
 *
 * Nothing at all for a catalogue lookup. "Which analyses produced this?" is a
 * question about a portfolio figure; asked of "what fields does the ratings
 * data have?" it invites a reader to look for an engine run that never
 * happened and does not need to have happened. Provenance for a metadata
 * answer is the catalogue, and it is on the Trace.
 */
/**
 * A step's name, linked to whichever of the three things it actually is.
 *
 * A composed analysis has no library entry — clicking one used to land on
 * "'dynamic_analysis' is not a registered CreditProbe analysis", which reads
 * as a broken product rather than as an absent page. It links to its run
 * instead, which is what a reader wanted anyway: how was THIS produced.
 */
function StepLink({
  step,
  runId,
  returnTo,
}: {
  step: ExecutedStep;
  runId: number | null;
  returnTo?: { href: string; label: string };
}) {
  const label = step.title || step.analysis_id;
  const target = stepHref(step.analysis_id, step.certification, runId);
  if (!target) {
    return <span className="text-sm font-medium text-text-primary">{label}</span>;
  }
  const href = returnTo
    ? withReturnTo(target, returnTo.href, returnTo.label)
    : target;
  return (
    <Link href={href} className="text-sm font-medium text-text-primary hover:text-accent">
      {label}
    </Link>
  );
}

export function AnalysesUsed({
  steps,
  runId,
  returnTo,
}: {
  steps: ExecutedStep[];
  runId?: number | null;
  returnTo?: { href: string; label: string };
}) {
  const computed = steps.filter((step) => step.certification !== "metadata");
  if (computed.length === 0) return null;

  return (
    <Disclosure
      summary={`Analyses used (${computed.length})`}
      hint="what produced these figures"
    >
      <Card className="divide-y divide-border">
        {computed.map((step) => (
          <div
            key={step.index}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2"
          >
            <StepLink step={step} runId={runId ?? null} returnTo={returnTo} />
            <CertificationBadge certification={step.certification} />
            <span className="mono text-[11px] text-text-muted">
              {step.analysis_version && `v${step.analysis_version}`}
              {step.period && ` · ${step.period}`}
              {step.role === "supporting" && " · supporting"}
            </span>
            <span className="mono ml-auto text-[11px] text-text-muted">
              {step.status === "succeeded" ? `${step.duration_ms}ms` : step.status}
            </span>
          </div>
        ))}
      </Card>
    </Disclosure>
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
          className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {question}
          <ArrowRight
            className="size-2.5 opacity-60 transition-opacity group-hover:opacity-100"
            aria-hidden
          />
        </button>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------- action strip */

/**
 * The same five actions under every answer, in the same order.
 *
 * Consistency is the feature: somebody who learns where Trace is once should
 * never have to look for it again.
 */
export function ActionStrip({
  run,
  onSave,
  saved,
  onAddToProject,
  busy,
  returnTo,
}: {
  run: InvestigationResponse;
  onSave?: () => void;
  saved?: boolean;
  onAddToProject?: () => void;
  busy?: boolean;
  returnTo?: { href: string; label: string };
}) {
  const runId = run.analysis_run_id;
  const certified =
    run.steps.length > 0 && run.steps.every((s) => s.certification === "certified");
  const scope = run.plan.scope;
  const trace =
    runId && returnTo
      ? withReturnTo(`/trace/${runId}`, returnTo.href, returnTo.label)
      : runId
        ? `/trace/${runId}`
        : null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border pt-3">
      {certified && (
        <span
          className="flex items-center gap-1.5 text-[11px] text-info"
          title="CreditProbe Certified — deterministic governed analysis"
        >
          <CertifiedMark />
          Certified
        </span>
      )}
      {scope?.from_period && scope?.to_period && (
        <span className="mono text-[11px] text-text-muted">
          {scope.from_period} → {scope.to_period}
        </span>
      )}

      <div className="ml-auto flex items-center gap-0.5">
        {trace && (
          <Button variant="ghost" size="sm" asChild>
            <Link href={trace}>
              <GitBranch aria-hidden />
              Trace
            </Link>
          </Button>
        )}
        {onAddToProject && (
          <Button variant="ghost" size="sm" onClick={onAddToProject} disabled={busy}>
            <FolderPlus aria-hidden />
            Project
          </Button>
        )}
        {onSave && (
          <Button variant="ghost" size="sm" onClick={onSave} disabled={saved || busy}>
            {saved ? <Check aria-hidden /> : <BookmarkPlus aria-hidden />}
            {saved ? "Saved" : "Save analysis"}
          </Button>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- the answer */

export function AnswerBlock({
  run,
  onAsk,
  onSave,
  saved,
  onAddToProject,
  busy,
  compact,
  returnTo,
}: {
  run: InvestigationResponse;
  onAsk?: (question: string) => void;
  onSave?: () => void;
  saved?: boolean;
  onAddToProject?: () => void;
  busy?: boolean;
  /** Inside a thread the answer sits tighter and drops the run statistics. */
  compact?: boolean;
  /** Where Method and Trace links should return to. */
  returnTo?: { href: string; label: string };
}) {
  const runId = run.analysis_run_id;
  const { narrative } = run;
  const answer = narrative.direct_answer || narrative.summary;
  const reading = narrative.interpretation_points ?? [];
  // The direct answer and the interpretation are sometimes the same sentence —
  // the deterministic path summarises what it computed. Showing it twice reads
  // as a stutter, so the reading is dropped when it adds nothing.
  const interpretation =
    narrative.interpretation && narrative.interpretation.trim() !== answer.trim()
      ? narrative.interpretation
      : "";

  // One step answers the question. The planner marked it, and the layout follows
  // that marking rather than the order things happened to run in.
  const primary =
    run.steps.find((s) => s.role === "primary") ?? run.steps[0] ?? null;
  const supporting = run.steps.filter((s) => s !== primary);

  return (
    <div className={cn(compact ? "space-y-5" : "space-y-6")}>
      {run.rejected.length > 0 && (
        <Card className="border-negative/40 p-4">
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
        <Card className="flex items-start gap-2.5 border-warning/30 bg-warning-muted p-3.5">
          <TriangleAlert
            className="mt-0.5 size-4 shrink-0 text-warning"
            aria-hidden
          />
          <p className="prose-ai text-xs text-warning">{run.notes[0]}</p>
        </Card>
      )}

      {/* ------------------------------------------------- 1. DIRECT ANSWER */}
      <DirectAnswer answer={answer} scope={narrative.scope} />

      {/* ------------------------------------------- 2. ANALYST INTERPRETATION */}
      <AnalystReading
        interpretation={interpretation}
        points={reading}
        whyMultiple={narrative.why_multiple}
      />

      {/* --------------------------------------- 3. THE PRIMARY VISUAL/TABLE */}
      {narrative.metrics.length > 0 && (
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
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

      {primary && (
        <StepResult
          step={primary}
          runId={runId}
          compact={compact}
          returnTo={returnTo}
          question={run.question}
        />
      )}

      {/* ----------------------------- 4. EXCEPTIONS AND LIMITATIONS, IF ANY */}
      <Limitations caveats={narrative.caveats} />

      {/* --------------------------------------- 5. SUPPORTING, COLLAPSED */}
      {supporting.length > 0 && (
        <Disclosure
          summary={`Supporting analysis (${supporting.length})`}
          hint="run to help explain the answer, not to answer the question"
        >
          <div className="space-y-4">
            {supporting.map((step) => (
              <StepResult
                key={step.index}
                step={step}
                runId={runId}
                compact
                returnTo={returnTo}
              />
            ))}
          </div>
        </Disclosure>
      )}

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
                <p className="prose-ai text-sm text-text-primary">{finding.text}</p>
                {finding.evidence.length > 0 && (
                  <p className="mono mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
                    {finding.evidence.map((e) => (
                      <span key={e.label}>
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
                className="flex items-baseline gap-3 px-4 py-2"
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
                    "display-num shrink-0 text-sm font-medium",
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

      {/* ---------------------------------- 6. DATA AND METHOD, COLLAPSED */}
      <AnalysesUsed steps={run.steps} runId={runId} returnTo={returnTo} />

      {/* -------------------------------------------------- 7. ACTION STRIP */}
      <ActionStrip
        run={run}
        onSave={onSave}
        saved={saved}
        onAddToProject={onAddToProject}
        busy={busy}
        returnTo={returnTo}
      />

      {/* ------------------------------------ 8. CONTEXTUAL SUGGESTIONS */}
      {onAsk && <FollowUps questions={run.follow_ups} onAsk={onAsk} busy={busy} />}
    </div>
  );
}
