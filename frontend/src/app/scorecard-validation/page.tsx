"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Ask } from "@/components/scorecard-validation/ask";
import { ResultCard, StateChip }
  from "@/components/scorecard-validation/result-card";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  ScvCategory,
  ScvFinding,
  ScvModel,
  ScvOverview,
  ScvResult,
  ScvRun,
  ScvTest,
} from "@/lib/api";
import { count } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Scorecard Validation Intelligence. §21.
 *
 * A validation cockpit, not a dashboard. The difference is what the screen
 * does with an absence.
 *
 * A dashboard shows what it has. This shows what it has AND what it does not,
 * with equal weight, because the second is what a validation opinion has to
 * rest on. Forty-eight tests exist; a run reports how many produced a number
 * and how many refused, and the refusals carry the reason rather than an empty
 * cell. Eleven passes out of eleven and eleven passes out of forty-eight are
 * different claims about a model, and a screen that renders only the passes
 * makes the second one look like the first.
 *
 * The shape, top to bottom
 * --------------------------
 * 1. **Which scorecard** — three, and only three. The module is restricted to
 *    them at the data layer, not by this page offering fewer options.
 * 2. **Model health** — what data exists, and specifically how much of it has
 *    a realised outcome. Almost every wrong number in model validation comes
 *    from measuring an outcome over a window that has not closed.
 * 3. **Burning weaknesses** — the findings that would change a decision,
 *    ranked. Empty until something has been run, and it says so rather than
 *    showing an encouraging green tick.
 * 4. **Eleven category cards** — each carrying the question a validator is
 *    actually asking, not the name of a statistic.
 * 5. **The results workspace** — every result in the chosen category, with its
 *    chart, its table, its method and its limitations.
 *
 * What is deliberately absent
 * -----------------------------
 * There is no overall score, no traffic light for the model as a whole, and
 * no percentage complete. A single number for "is this scorecard sound" is
 * the thing a committee would quote and the thing no validator would sign,
 * and inventing one here would make every honest refusal below it decorative.
 */

const REPORT_IS_A_DRAFT =
  "The generated report is a draft for a validator to review, edit and sign. "
  + "CreditProbe does not issue validation opinions.";

// ------------------------------------------------------------ small pieces

function Figure({ label, value, hint }: {
  label: string; value: React.ReactNode; hint?: string;
}) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">
        {label}
      </p>
      <p className="text-lg font-semibold tabular-nums text-text">{value}</p>
      {hint && <p className="text-[11px] text-text-muted">{hint}</p>}
    </div>
  );
}

/**
 * What data this scorecard has, and how much of it has an outcome.
 *
 * The matured count is given its own figure rather than folded into a total,
 * because it is the number that decides which tests can run at all. A book
 * with thirty-six months of data and sixteen matured ones is not a
 * thirty-six-month validation.
 */
function HealthStrip({ model }: { model: ScvModel }) {
  const data = model.data;
  if (!data?.available) {
    return (
      <Card className="p-4">
        <p className="text-sm text-text-muted">
          No data is installed for this scorecard.
          {data?.why ? ` ${data.why}` : ""}
        </p>
      </Card>
    );
  }
  return (
    <Card className="p-4">
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Periods"
          value={count(data.periods ?? 0)}
          hint={data.latest_period ? `latest ${data.latest_period}` : undefined}
        />
        <Figure
          label="Outcome window closed"
          value={count(data.matured_periods ?? 0)}
          hint={data.latest_matured_period
            ? `latest ${data.latest_matured_period}` : undefined}
        />
        <Figure
          label="Not yet matured"
          value={count(data.immature_periods ?? 0)}
          hint={`${data.performance_window_months ?? 12}-month window`}
        />
        <Figure
          label="Cut-off"
          value={model.cut_off ?? "—"}
          hint={model.score_direction
            ? model.score_direction.toLowerCase().replace(/_/g, " ")
            : undefined}
        />
      </div>
      {data.why_immature && (
        <p className="mt-4 max-w-3xl border-t border-border pt-3 text-xs leading-relaxed text-text-muted">
          {data.why_immature}
        </p>
      )}
    </Card>
  );
}

const SEVERITY_TONE: Record<string, string> = {
  CRITICAL: "border-negative/40 bg-negative/10",
  HIGH: "border-negative/30 bg-negative/5",
  MEDIUM: "border-warning/30 bg-warning/5",
  LOW: "border-border",
  OBSERVATION: "border-border",
};

const SEVERITY_BADGE: Record<string,
  "negative" | "warning" | "default"> = {
  CRITICAL: "negative",
  HIGH: "negative",
  MEDIUM: "warning",
  LOW: "default",
  OBSERVATION: "default",
};

/**
 * One finding, with the route to check it.
 *
 * `verify_by` is rendered rather than hidden behind a disclosure, and that is
 * the point of the component: a finding a reader cannot independently check is
 * a finding they have to take on trust, which is the opposite of what an
 * independent validation is for.
 */
function FindingCard({ finding }: { finding: ScvFinding }) {
  return (
    <div className={cn("rounded-lg border p-4",
                       SEVERITY_TONE[finding.severity] ?? "border-border")}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={SEVERITY_BADGE[finding.severity] ?? "default"}>
          {finding.severity}
        </Badge>
        <h3 className="text-sm font-semibold text-text">{finding.title}</h3>
      </div>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-text">
        {finding.what}
      </p>
      {finding.why_it_matters && (
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-text-muted">
          {finding.why_it_matters}
        </p>
      )}
      {finding.remediation && (
        <p className="mt-2 max-w-3xl text-xs leading-relaxed text-text-muted">
          <span className="font-semibold uppercase tracking-wider">
            Remediation
          </span>{" "}
          — {finding.remediation}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {finding.evidence.map((test) => (
          <span key={test} className="font-mono text-[11px] text-text-muted">
            {test}
          </span>
        ))}
        {finding.cbuae.map((reference) => (
          <Badge key={reference} variant="outline">{reference}</Badge>
        ))}
      </div>
      {finding.verify_by && (
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          <span className="font-semibold uppercase tracking-wider">
            Check it yourself
          </span>{" "}
          — {finding.verify_by}
        </p>
      )}
    </div>
  );
}

/** One category card: the question, not the statistic. */
function CategoryCard({ category, coverage, chosen, onPick }: {
  category: ScvCategory;
  coverage?: { defined: number; run: number };
  chosen: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className={cn(
        "rounded-lg border p-4 text-left transition-colors",
        chosen
          ? "border-border-strong bg-surface-hover"
          : "border-border bg-surface hover:border-border-strong",
      )}
    >
      <h3 className="text-sm font-semibold text-text">{category.title}</h3>
      <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
        {category.question}
      </p>
      <div className="mt-3 flex items-center gap-2 text-[11px] text-text-muted">
        {coverage
          ? <span>{coverage.run} of {coverage.defined} measured</span>
          : <span>not run</span>}
        {!category.quantitative && (
          <Badge variant="outline">documentary</Badge>
        )}
      </div>
    </button>
  );
}

// -------------------------------------------------------------- the screen

export default function ScorecardValidationPage() {
  const [overview, setOverview] = React.useState<ScvOverview | null>(null);
  const [tests, setTests] = React.useState<Record<string, ScvTest>>({});
  const [modelId, setModelId] = React.useState("");
  const [category, setCategory] = React.useState("");
  const [run, setRun] = React.useState<ScvRun | null>(null);
  const [busy, setBusy] = React.useState("");
  const [failed, setFailed] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    Promise.all([api.scorecardValidation.overview(),
                 api.scorecardValidation.tests()])
      .then(([shape, registry]) => {
        if (!alive) return;
        setOverview(shape);
        const byId: Record<string, ScvTest> = {};
        for (const test of registry.tests) byId[test.test_id] = test;
        setTests(byId);
        if (shape.scorecards.length) {
          setModelId(shape.scorecards[0].model_id);
        }
      })
      .catch((error: Error) => alive && setFailed(error.message));
    return () => { alive = false; };
  }, []);

  const model = React.useMemo(
    () => overview?.scorecards.find((s) => s.model_id === modelId) ?? null,
    [overview, modelId]);

  /**
   * Switching scorecard clears the run rather than keeping it on screen.
   *
   * Results from one model sitting under the name of another is the kind of
   * mistake that survives all the way into a committee pack, so the clearing
   * happens in the same act as the switch — not in an effect that reacts to
   * it, which would leave one render showing the old results under the new
   * heading.
   */
  function chooseModel(next: string) {
    if (next === modelId) return;
    setModelId(next);
    setRun(null);
    setCategory("");
    setFailed("");
  }

  async function runCategory(key: string) {
    if (!modelId) return;
    setBusy(key);
    setFailed("");
    setCategory(key);
    try {
      setRun(await api.scorecardValidation.runCategory(modelId, key));
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function runEverything() {
    if (!modelId) return;
    setBusy("__all__");
    setFailed("");
    setCategory("");
    try {
      setRun(await api.scorecardValidation.runAll(modelId));
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (failed && !overview) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-8">
        <PageHeader title="Scorecard Validation" />
        <Card className="p-6">
          <p className="text-sm text-negative">{failed}</p>
        </Card>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="mx-auto max-w-7xl space-y-4 px-6 py-8">
        <PageHeader title="Scorecard Validation" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const categories = overview.registry.categories;
  const labels: Record<string, string> = {};
  for (const entry of overview.result_states) labels[entry.state] = entry.label;
  const burning = run?.burning_weaknesses ?? [];
  const results = run?.results ?? [];

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      <PageHeader
        title="Scorecard Validation"
        description={
          "Independent validation of three scorecards — the retail "
          + "application scorecard, the retail behaviour scorecard and the "
          + "Saudi SME scorecard — against forty-eight tests, each with a "
          + "governed limit that says where it came from."
        }
        actions={
          <Link
            href="/scorecard-validation/monitoring"
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text"
          >
            Ongoing monitoring
          </Link>
        }
      />

      {/* ---------------------------------------------- which scorecard */}
      <section className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {overview.scorecards.map((scorecard) => (
            <button
              key={scorecard.model_id}
              type="button"
              onClick={() => chooseModel(scorecard.model_id)}
              className={cn(
                "rounded-lg border px-4 py-2.5 text-left transition-colors",
                scorecard.model_id === modelId
                  ? "border-border-strong bg-surface-hover"
                  : "border-border bg-surface hover:border-border-strong",
              )}
            >
              <span className="block text-sm font-semibold text-text">
                {scorecard.name}
              </span>
              <span className="block text-[11px] text-text-muted">
                {scorecard.reference_number} v{scorecard.version}
                {scorecard.tier ? ` · ${scorecard.tier}` : ""}
              </span>
            </button>
          ))}
        </div>
        <p className="text-[11px] text-text-muted">
          Three, and only three. This module is restricted to the scorecard
          domains at the data layer — it cannot read the rest of the credit
          book, and the rest of the product cannot read these populations.
        </p>
      </section>

      {/* ------------------------------------------------------------ ask */}
      <section className="space-y-2">
        <Ask modelId={modelId} tests={tests} />
        <p className="max-w-3xl text-[11px] leading-relaxed text-text-muted">
          Questions are answered by running the governed tests, not by
          describing them. Every sentence beside a figure is the runner&apos;s
          own — a chat surface that paraphrased a validation statistic would
          produce the version that gets read aloud in a committee, with no way
          for the reader to tell it had been rewritten.
        </p>
      </section>

      {model && <HealthStrip model={model} />}

      {/* ------------------------------------------------------- actions */}
      <section className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={runEverything}
          disabled={Boolean(busy) || !modelId}
          className="rounded-md border border-border-strong bg-surface-hover px-4 py-2 text-sm font-medium text-text transition-colors hover:bg-surface disabled:opacity-50"
        >
          {busy === "__all__" ? "Running every test…" : "Run full validation"}
        </button>
        {model && (
          <a
            href={api.scorecardValidation.reportDocxUrl(model.model_id)}
            className="rounded-md border border-border px-4 py-2 text-sm text-text-muted transition-colors hover:border-border-strong hover:text-text"
          >
            Draft report (Word)
          </a>
        )}
        <p className="text-[11px] text-text-muted">{overview.full_run_cost}</p>
      </section>

      {failed && (
        <Card className="p-4">
          <p className="text-sm text-negative">{failed}</p>
        </Card>
      )}

      {/* ------------------------------------------- burning weaknesses */}
      {run && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold text-text">
              What would change a decision
            </h2>
            <p className="text-xs text-text-muted">
              {run.measured} of {run.returned} tests produced a number
            </p>
          </div>
          {burning.length > 0 ? (
            <div className="space-y-3">
              {burning.map((finding) => (
                <FindingCard key={finding.finding_id} finding={finding} />
              ))}
            </div>
          ) : (
            <Card className="p-4">
              <p className="text-sm text-text-muted">
                {run.findings.length > 0
                  ? `${run.findings.length} finding${run.findings.length === 1 ? "" : "s"} were raised, none of them severe enough to change a decision on their own. They are listed against their tests below.`
                  : "Nothing in this run breached a governed limit. That is a statement about the tests that ran, not about the model: read the coverage figure above before treating it as a clean bill of health."}
              </p>
            </Card>
          )}
          <p className="max-w-3xl text-[11px] leading-relaxed text-text-muted">
            {run.coverage_means}
          </p>
        </section>
      )}

      {/* --------------------------------------------- category cards */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-text">
          What a validation asks
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((entry) => (
            <CategoryCard
              key={entry.key}
              category={entry}
              coverage={run?.coverage?.[entry.key]}
              chosen={entry.key === category}
              onPick={() => runCategory(entry.key)}
            />
          ))}
        </div>
        {busy && busy !== "__all__" && (
          <p className="text-xs text-text-muted">Running {busy}…</p>
        )}
      </section>

      {/* ------------------------------------------ results workspace */}
      {results.length > 0 && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-semibold text-text">
              {category
                ? categories.find((c) => c.key === category)?.title ?? "Results"
                : "Every test"}
            </h2>
            <div className="flex flex-wrap items-center gap-1.5">
              {Object.entries(run?.tally ?? {})
                .filter(([, n]) => n > 0)
                .map(([state, n]) => (
                  <span key={state} className="flex items-center gap-1">
                    {/* The engine's own label, not the enum with its
                        underscores swapped for spaces. "NO LIMIT" and "No
                        approved limit" read as different states, and only one
                        of them is a state. */}
                    <StateChip
                      result={{ state: state as ScvResult["state"],
                                state_label: labels[state] ?? state }}
                    />
                    <span className="text-[11px] tabular-nums text-text-muted">
                      {n}
                    </span>
                  </span>
                ))}
            </div>
          </div>
          <div className="space-y-2">
            {results.map((result) => (
              <ResultCard
                key={`${result.test_id}-${result.segment}`}
                result={result}
                test={tests[result.test_id]}
              />
            ))}
          </div>
        </section>
      )}

      {!run && (
        <Card className="p-6">
          <p className="max-w-3xl text-sm leading-relaxed text-text-muted">
            Nothing has been run yet, and nothing is shown as passing.
            Choose a category above to run its tests, or run the full
            validation. Each result arrives with the population it was
            measured over, the limit it was compared against, where that limit
            came from, and — where a test could not run — the reason.
          </p>
        </Card>
      )}

      <p className="border-t border-border pt-4 text-[11px] leading-relaxed text-text-muted">
        {REPORT_IS_A_DRAFT}
      </p>
    </div>
  );
}
