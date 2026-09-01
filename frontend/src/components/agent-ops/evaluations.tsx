"use client";

import * as React from "react";
import { CircleCheck, CircleX, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AgentEvaluation } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The EVALUATIONS tab. §33, §59, §61, §62.
 *
 * §33: "Do not use three random questions as certification."
 *
 * So the headline is not a percentage. It is a verdict — CERTIFIED or NOT
 * CERTIFIED with the reason — and under it the sixteen §59 areas scored
 * separately, because "87% accurate" does not answer "can it be trusted not to
 * close a case on its own".
 *
 * Safety is not averaged
 * -----------------------
 * A run that correctly refused nineteen material actions and performed the
 * twentieth has not scored 95%; it has failed. The safety areas are marked and
 * a single failure in one fails the run, whatever the accuracy — which is why
 * the failures list is above the score rather than below it.
 *
 * No model is called
 * ------------------
 * Every case is deterministic: a permission check, a plan validation, budget
 * arithmetic, an approval rule. The whole corpus runs in milliseconds and
 * costs nothing, which is what makes running it on demand reasonable.
 */
export function Evaluations() {
  const [tier, setTier] = React.useState("certification");
  const [loaded, setLoaded] = React.useState<{
    tier: string;
    data: AgentEvaluation | null;
    error: string;
  } | null>(null);
  const [showAll, setShowAll] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await api.agentEvaluations(tier);
        if (live) setLoaded({ tier, data: found, error: "" });
      } catch (error) {
        if (live)
          setLoaded({
            tier,
            data: null,
            error:
              error instanceof Error
                ? error.message
                : "The evaluation could not be run.",
          });
      }
    })();
    return () => {
      live = false;
    };
  }, [tier]);

  const settled = loaded && loaded.tier === tier ? loaded : null;
  if (settled === null) return <Skeleton className="h-64 w-full" />;
  if (settled.error)
    return <p className="text-sm text-negative">{settled.error}</p>;
  const found = settled.data;
  if (!found) return null;

  const failures = found.cases.filter((c) => !c.passed);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1">
        {found.tiers.map((one) => (
          <button
            key={one.id}
            type="button"
            onClick={() => setTier(one.id)}
            title={one.note}
            className={cn(
              "rounded px-2 py-1 text-xs transition-colors",
              tier === one.id
                ? "bg-accent text-accent-contrast"
                : "text-text-secondary hover:bg-surface-hover",
            )}
          >
            {one.label}
          </button>
        ))}
      </div>

      <Card className="p-4" data-testid="evaluation-verdict">
        <div className="flex items-start gap-3">
          {found.certified ? (
            <CircleCheck className="mt-0.5 size-5 shrink-0 text-positive" aria-hidden />
          ) : found.safety_failures.length ? (
            <ShieldAlert className="mt-0.5 size-5 shrink-0 text-negative" aria-hidden />
          ) : (
            <CircleX className="mt-0.5 size-5 shrink-0 text-text-muted" aria-hidden />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-text-primary">
              {found.verdict}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 text-[11px] text-text-muted">
              <span>
                {found.passed} of {found.total} cases
              </span>
              <span className="mono">{(found.accuracy * 100).toFixed(1)}%</span>
              <span>{found.duration_ms} ms</span>
              <span>corpus {found.version}</span>
              <span>no model calls</span>
            </p>
          </div>
        </div>
      </Card>

      <div>
        <h3 className="meta mb-1.5 text-text-muted">
          By evaluation area — §59
        </h3>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {found.areas.map((area) => (
            <div
              key={area.area}
              className="flex items-baseline justify-between gap-3 rounded border border-border px-2.5 py-1.5"
              data-testid={`evaluation-area-${area.area}`}
            >
              <span className="min-w-0 truncate text-xs text-text-secondary">
                {area.label}
                {area.safety && (
                  <span className="ml-1.5 rounded bg-surface-sunken px-1 py-0.5 text-[9px] uppercase tracking-[0.08em] text-text-muted">
                    safety
                  </span>
                )}
              </span>
              <span
                className={cn(
                  "mono shrink-0 text-xs tabular",
                  area.passed === area.total
                    ? "text-positive"
                    : area.safety
                      ? "text-negative"
                      : "text-warning",
                )}
              >
                {area.passed}/{area.total}
              </span>
            </div>
          ))}
        </div>
      </div>

      {failures.length > 0 && (
        <div>
          <h3 className="meta mb-1.5 text-text-muted">What did not pass</h3>
          <ul className="space-y-1.5">
            {failures.map((one) => (
              <li key={one.case_id} className="text-xs">
                <span className="mono text-text-muted">{one.case_id}</span>{" "}
                <span className="text-text-primary">{one.title}</span>
                {one.safety && (
                  <span className="ml-1.5 rounded bg-negative-muted px-1 py-0.5 text-[9px] uppercase tracking-[0.08em] text-negative">
                    safety
                  </span>
                )}
                <span className="block text-text-secondary">
                  {one.expectation}
                </span>
                <span className="block text-text-muted">
                  Observed: {one.observed || one.error}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <Button variant="ghost" size="sm" onClick={() => setShowAll((n) => !n)}>
          {showAll ? "Hide" : "Show"} all {found.total} cases
        </Button>
        {showAll && (
          <ul className="mt-2 space-y-0.5">
            {found.cases.map((one) => (
              <li
                key={one.case_id}
                className="flex items-start gap-2 text-[11px]"
              >
                {one.passed ? (
                  <CircleCheck
                    className="mt-0.5 size-3 shrink-0 text-positive"
                    aria-label="Passed"
                  />
                ) : (
                  <CircleX
                    className="mt-0.5 size-3 shrink-0 text-negative"
                    aria-label="Failed"
                  />
                )}
                <span className="mono shrink-0 text-text-muted">
                  {one.case_id}
                </span>
                <span className="min-w-0 flex-1 text-text-secondary">
                  {one.title}
                </span>
                <span className="shrink-0 text-text-muted">
                  {one.area_label}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
