"use client";

import * as React from "react";
import { CircleAlert, CircleCheck, CircleDashed, CircleHelp, CircleX } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { CompoundAnswer, ObjectiveCoverageEntry } from "@/lib/api";

/**
 * What the reader asked for, against what they got. §11, §36, §37, §39.
 *
 * The strip at the top of a multi-question answer, and the one thing on the
 * page that can contradict the rest of it. Everything else on an answer says
 * what CreditProbe found; this says whether that is what was asked.
 *
 * Two decisions worth stating.
 *
 * **It renders when everything was answered too.** "1 of 1" is what teaches a
 * reader to read the counter, so that "1 of 2 answered" three turns later
 * registers instead of being skimmed past. A warning that only ever appears
 * when something is wrong is a warning people learn not to look for.
 *
 * **PARTIAL is not styled as a failure.** It means the clause was folded into
 * a combined analysis rather than run as its own step - the figure is there
 * and it was not separately checked. Colouring that like a failure would
 * teach readers to ignore the colour; hiding it would be the silent omission
 * the coverage report exists to prevent.
 */

const STATUS_META: Record<
  string,
  { label: string; icon: React.ElementType; tone: string }
> = {
  COMPLETE: {
    label: "Answered",
    icon: CircleCheck,
    tone: "text-emerald-600 dark:text-emerald-400",
  },
  PARTIAL: {
    label: "Folded into the combined analysis",
    icon: CircleDashed,
    tone: "text-amber-600 dark:text-amber-400",
  },
  NEEDS_CLARIFICATION: {
    label: "Needs one more detail",
    icon: CircleHelp,
    tone: "text-sky-600 dark:text-sky-400",
  },
  UNAVAILABLE: {
    label: "Not supported",
    icon: CircleAlert,
    tone: "text-muted-foreground",
  },
  FAILED: {
    label: "Could not be completed",
    icon: CircleX,
    tone: "text-rose-600 dark:text-rose-400",
  },
  PLANNED: {
    label: "Not answered",
    icon: CircleX,
    tone: "text-rose-600 dark:text-rose-400",
  },
};

function meta(status: string) {
  return STATUS_META[status] ?? STATUS_META.PLANNED;
}

export function ObjectiveLine({ objective }: { objective: ObjectiveCoverageEntry }) {
  const { label, icon: Icon, tone } = meta(objective.status);
  return (
    <li className="flex items-start gap-2 py-1 text-sm">
      <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", tone)} />
      <span className="min-w-0">
        <span className="text-foreground">
          {objective.description.replace(/^and\s+/i, "")}
        </span>
        <span className={cn("ml-2 text-xs", tone)}>{label}</span>
        {objective.note ? (
          <span className="block text-xs text-muted-foreground">{objective.note}</span>
        ) : null}
      </span>
    </li>
  );
}

export function QuestionsAnswered({ compound }: { compound?: CompoundAnswer }) {
  if (!compound) return null;

  if (!compound.available) {
    // Never render nothing here. An absent coverage strip reads as "all
    // fine", and the one thing established is that we do not know.
    return (
      <p className="text-xs text-muted-foreground" data-testid="coverage-unavailable">
        {compound.why ?? "The coverage of this request could not be established."}
      </p>
    );
  }

  const coverage = compound.coverage;
  if (!coverage || coverage.total === 0) return null;

  const everything = coverage.complete === coverage.total;
  const analyses = compound.analyses_performed ?? 0;

  return (
    <div className="space-y-2" data-testid="questions-answered">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.6875rem] font-medium uppercase tracking-[0.08em] text-muted-foreground">
          Questions answered
        </span>
        <Badge variant={everything ? "outline" : "warning"}>
          {compound.questions_answered ?? `${coverage.complete} of ${coverage.total}`}
        </Badge>
        {analyses > 0 ? (
          <span className="text-xs text-muted-foreground">
            {analyses} {analyses === 1 ? "analysis" : "analyses"} performed
          </span>
        ) : null}
      </div>
      {coverage.total > 1 ? (
        <ul className="space-y-0.5">
          {coverage.objectives.map((objective) => (
            <ObjectiveLine key={objective.objective_id} objective={objective} />
          ))}
        </ul>
      ) : null}
      {compound.shared_scope &&
      !compound.shared_scope.shared &&
      compound.shared_scope.divergent.length > 1 ? (
        <p className="text-xs text-muted-foreground">
          These parts are about different populations, so their figures are not
          directly comparable.
        </p>
      ) : null}
    </div>
  );
}

/**
 * §12: what was weighed, and what was set aside.
 *
 * A disclosure rather than inline content. The reader who wants to know why
 * an analysis they expected is missing needs this; the reader who does not is
 * answering a different question, and putting seven rejected analyses above
 * the answer would bury it.
 */
export function AnalysesConsidered({ compound }: { compound?: CompoundAnswer }) {
  const portfolio = compound?.portfolio;
  if (!portfolio || portfolio.candidate_analyses.length < 2) return null;

  return (
    <details className="group rounded-lg border border-border/60 bg-muted/20 px-3 py-2">
      <summary className="cursor-pointer list-none text-xs text-muted-foreground">
        {portfolio.selection_reason ||
          `${portfolio.selected_analyses.length} of ${portfolio.candidate_analyses.length} analyses selected`}
      </summary>
      <div className="mt-2 space-y-2 text-xs">
        {portfolio.selected_analyses.length ? (
          <div>
            <p className="font-medium text-foreground">Run</p>
            <ul className="mt-0.5 space-y-0.5">
              {portfolio.selected_analyses.map((decision) => (
                <li key={decision.analysis_id} className="text-muted-foreground">
                  <span className="text-foreground">{decision.title}</span>
                  {decision.primary ? (
                    <Badge variant="outline" className="ml-1.5 px-1 py-0 text-[0.625rem]">
                      primary
                    </Badge>
                  ) : null}
                  {decision.reason ? <> &mdash; {decision.reason}</> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {portfolio.rejected_analyses.length ? (
          <div>
            <p className="font-medium text-foreground">Considered and not run</p>
            <ul className="mt-0.5 space-y-0.5">
              {portfolio.rejected_analyses.map((decision) => (
                <li key={decision.analysis_id} className="text-muted-foreground">
                  <span className="text-foreground">{decision.title}</span>
                  {decision.reason ? <> &mdash; {decision.reason}</> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </details>
  );
}
