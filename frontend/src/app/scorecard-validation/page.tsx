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
  ScvJob,
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
 * rest on. The registry's tests exist; a run reports how many produced a number
 * and how many refused, and the refusals carry the reason rather than an empty
 * cell. Eleven passes out of eleven and eleven passes out of fifty-two are
 * different claims about a model, and a screen that renders only the passes
 * makes the second one look like the first.
 *
 * The shape, top to bottom
 * --------------------------
 * 1. **Which scorecard** — whichever the registry holds. The module is
 *    restricted to them at the data layer, not by this page offering fewer
 *    options, and the count is read from the registry rather than written
 *    into a caption that goes stale the first time a model is registered.
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
      {(finding.also_in ?? []).length > 0 && (
        <p className="mt-2 max-w-3xl text-[11px] leading-relaxed text-text-muted">
          <span className="font-semibold uppercase tracking-wider">
            Also read under
          </span>{" "}
          — {(finding.category_titles ?? []).slice(1).join(", ")}. This is one
          finding seen from several categories, with one id
          ({finding.finding_id}) and one set of values, not several findings
          that agree.
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        {finding.evidence.map((test) => (
          <span key={test} className="font-mono text-[11px] text-text-muted">
            {test}
          </span>
        ))}
        {(finding.references ?? finding.cbuae).map((reference) => (
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
  // Read inside the polling loop, which closes over the model it started
  // with. Comparing against the state variable would compare against the
  // value captured when the loop was created.
  const modelIdRef = React.useRef("");
  React.useEffect(() => { modelIdRef.current = modelId; }, [modelId]);
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
    // Takes the ticket, so a run started against the previous model can no
    // longer paint its results under this one's name.
    ticket.current += 1;
    setModelId(next);
    modelIdRef.current = next;
    setRun(null);
    setJob(null);
    setBusy("");
    setCategory("");
    setFailed("");
  }

  /**
   * Only the latest request may write to the screen.
   *
   * The defect this closes, reproduced by timing: Data & Representativeness
   * took 79 seconds and Champion vs Challenger took 0.15. Clicking the first
   * and then the second painted the challenger results, and 79 seconds later
   * the data results overwrote them — under the heading the reader had
   * chosen last. That is §2.6's screenshot: a category's card showing
   * another category's results.
   *
   * Every run takes a ticket. A response whose ticket is not the current one
   * is discarded, and so is one whose model or category no longer matches
   * what is on screen.
   */
  const ticket = React.useRef(0);
  const [job, setJob] = React.useState<ScvJob | null>(null);

  async function runCategory(key: string) {
    if (!modelId) return;
    await launch(key);
  }

  async function runEverything() {
    if (!modelId) return;
    await launch("");
  }

  async function launch(key: string) {
    const mine = ++ticket.current;
    const forModel = modelId;
    setBusy(key || "__all__");
    setFailed("");
    setCategory(key);
    setRun(null);
    setJob(null);
    try {
      const started = await api.scorecardValidation.startJob(
        forModel, key ? { category: key } : {});
      if (mine !== ticket.current) return;
      setJob(started);
      await follow(started.job_id, mine, forModel);
    } catch (error) {
      if (mine !== ticket.current) return;
      setFailed((error as Error).message);
      setBusy("");
    }
  }

  /**
   * Poll until the job finishes, showing what it has done so far.
   *
   * §14.2 asks for progress, partial results and an explicit finished state.
   * The loop stops the moment a newer run takes the ticket, so a reader who
   * changes their mind is not waiting on the run they abandoned.
   */
  async function follow(jobId: string, mine: number, forModel: string) {
    for (;;) {
      await new Promise((wake) => setTimeout(wake, 900));
      if (mine !== ticket.current) return;
      let state: ScvJob;
      try {
        state = await api.scorecardValidation.job(jobId);
      } catch (error) {
        if (mine !== ticket.current) return;
        setFailed((error as Error).message);
        setBusy("");
        return;
      }
      if (mine !== ticket.current || forModel !== modelIdRef.current) return;
      setJob(state);
      if (state.finished) {
        setBusy("");
        if (state.state === "FAILED") {
          setFailed(state.error || "The validation run failed.");
        } else if (state.run) {
          // Complete or stopped, this is a whole run object: tally, coverage,
          // findings and all. A stopped one arrives with recorded false and
          // no run key, and the progress card above says how far it got.
          //
          // The earlier version built one here instead, by spreading the
          // previous run and swapping in the partial results. That object had
          // no `findings`, so the first render after Stop threw on
          // `run.findings.length` and took the whole page down with it —
          // which is why pressing Stop made the progress card vanish rather
          // than say "Stopped after 7 of 48 tests".
          setRun(state.run as unknown as ScvRun);
        }
        return;
      }
    }
  }

  async function stopRun() {
    if (!job || job.finished) return;
    try {
      await api.scorecardValidation.cancelJob(job.job_id);
    } catch {
      // The job may have finished between the click and the call; the poll
      // above will report whatever actually happened.
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
  // Findings that belong to the category on screen — including the shared
  // ones, which name this category on `categories` without owning it. §14.5
  // asks for the same finding, with the same id and the same values, under
  // every category it bears on; a list that showed only the owned ones would
  // put an under-prediction finding in Calibration and nowhere else, and the
  // reader looking at Data & Representativeness would conclude it was clean.
  const inCategory = category
    ? (run?.findings ?? []).filter(
        (finding) => (finding.categories ?? [finding.category])
          .includes(category))
    : [];

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-8">
      <PageHeader
        title="Scorecard Validation"
        description={
          // Counted from the registry rather than written down. §14 is
          // explicit: audit the scorecards the registry holds and do not
          // hard-code an assumed number. This said "three scorecards …
          // against forty-eight tests" over a registry that holds eight and
          // fifty-two, which is a caption that goes stale the first time
          // somebody registers a model.
          `Independent validation of ${overview.scorecards.length} `
          + `scorecards against ${overview.registry.tests} tests, each with `
          + "a governed limit that says where it came from."
        }
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/scorecard-validation/history"
              className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text"
            >
              Validation History
            </Link>
            <Link
              href="/scorecard-validation/monitoring"
              className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text"
            >
              Ongoing monitoring
            </Link>
          </div>
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
        {job && !job.finished && (
          <button
            type="button"
            onClick={stopRun}
            data-testid="scv-stop"
            className="rounded-md border border-negative/40 px-4 py-2 text-sm text-negative transition-colors hover:bg-negative/10"
          >
            Stop
          </button>
        )}
        <p className="text-[11px] text-text-muted">{overview.full_run_cost}</p>
      </section>

      {/* ------------------------------------------------------- progress */}
      {job && (
        <Card className="p-4" data-testid="scv-progress">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-text">
              {job.state === "RUNNING" ? "Running" : job.state[0]
                + job.state.slice(1).toLowerCase()}
              {job.categories.length === 1
                ? ` — ${job.categories[0].replace(/_/g, " ")}`
                : " — every category"}
            </p>
            <p className="text-[12px] tabular-nums text-text-muted"
               data-testid="scv-progress-count">
              {job.done} of {job.total} tests
              {job.current ? ` · ${job.current}` : ""}
            </p>
          </div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-hover">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500"
              style={{ width: `${Math.round(job.progress * 100)}%` }}
            />
          </div>
          {job.partial && (
            <p className="mt-2 text-[11px] text-text-muted">
              These are partial results. The tally below covers the{" "}
              {job.done} tests finished so far, not the whole run.
            </p>
          )}
          {job.state === "CANCELLED" && (
            <p className="mt-2 text-[11px] text-warning">
              Stopped after {job.done} of {job.total} tests. What had already
              been measured is kept; the rest was not run and is not reported
              as anything.
            </p>
          )}
          {job.state === "FAILED" && (
            <p className="mt-2 text-[11px] text-negative">{job.error}</p>
          )}
        </Card>
      )}

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
          {inCategory.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                What this category concludes
              </h3>
              {inCategory.map((finding) => (
                <FindingCard key={finding.finding_id} finding={finding} />
              ))}
            </div>
          )}
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

      {!run && !job && (
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
