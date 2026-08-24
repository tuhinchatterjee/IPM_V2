"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import {
  ArrowRight,
  Clock,
  GitBranch,
  Search,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";

import { ClarificationCard } from "@/components/ask/clarification";
import { Composer, useGreeting } from "@/components/ask/composer";
import {
  InvestigationProgress,
  InvestigationView,
} from "@/components/ask/investigation";
import { useCanRunAnalysis } from "@/components/system/role-switcher";
import { TrendChart } from "@/components/analytics/charts";
import { KpiTile } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  api,
  type InvestigationResponse,
  type Row,
  type Stage,
} from "@/lib/api";
import { byUnit, delta, money, percent } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

/**
 * The AI Cockpit — CreditProbe's hero screen.
 *
 * The order of the page is the order of a credit officer's morning: what would
 * you like to investigate, then where the book stands, then what is already
 * demanding attention, then what you were working on. The composer comes first
 * because asking is the product; everything beneath it exists so you know what
 * to ask, and is deliberately brief — a pulse, a short list, and your recent
 * work. It is not a dashboard competing with the question.
 *
 * Nothing on this page is a hard-coded portfolio figure. The pulse is three
 * registered analyses executed on request, and the answer below the composer is
 * a full investigation with its own Trace.
 */

const FALLBACK_STAGES: Stage[] = [
  { id: "understanding", label: "Understanding the question" },
  { id: "planning", label: "Selecting CreditProbe analyses" },
  { id: "retrieving", label: "Retrieving governed data" },
  { id: "running", label: "Running the CreditProbe Engine" },
  { id: "synthesising", label: "Synthesising findings" },
];

function numberOf(
  values: Record<string, unknown> | undefined,
  key: string,
): number | null {
  const v = values?.[key];
  return typeof v === "number" ? v : null;
}

export default function CockpitPage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Cockpit />
    </React.Suspense>
  );
}

function Cockpit() {
  const searchParams = useSearchParams();
  const focusAsk = searchParams.get("focus") === "ask";
  // A question can arrive in the URL — from a follow-up on a stored
  // investigation, or from a link in a lens. It is offered in the composer
  // rather than run automatically: the user still presses Ask.
  const prefilled = searchParams.get("q") ?? "";

  const [question, setQuestion] = React.useState(prefilled);
  const [asking, setAsking] = React.useState<string | null>(null);
  const [answer, setAnswer] = React.useState<InvestigationResponse | null>(
    null,
  );
  const [askError, setAskError] = React.useState<string | null>(null);
  // When CreditProbe asks a period question back, the question that prompted it is held
  // here so answering can re-run the same question with the chosen periods.
  const [pending, setPending] = React.useState<string | null>(null);
  const [savedId, setSavedId] = React.useState<number | null>(null);

  const greeting = useGreeting();
  // A Viewer may read what others have produced but may not execute an analysis.
  // The backend refuses it either way; disabling the composer says so before the
  // question is typed rather than after it is submitted.
  const canRun = useCanRunAnalysis();
  const mode = useAsync(() => api.askMode(), []);
  const suggestions = useAsync(() => api.askSuggestions(), []);
  const briefing = useAsync(() => api.briefing(), []);
  const recent = useAsync(
    () => api.recentInvestigations(5),
    [answer?.analysis_run_id],
  );

  const stages = mode.data?.stages ?? FALLBACK_STAGES;

  const ask = React.useCallback(
    async (text: string, period?: { from: string; to: string }) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setAsking(trimmed);
      setAnswer(null);
      setAskError(null);
      window.scrollTo({ top: 0, behavior: "smooth" });
      try {
        const result = await api.ask(trimmed, {
          fromPeriod: period?.from,
          toPeriod: period?.to,
        });
        // A clarification is not an answer. The question is held so answering it
        // re-runs the same question rather than making the user retype it.
        setPending(result.clarification ? trimmed : null);
        setAnswer(result);
      } catch (e) {
        setAskError(
          e instanceof ApiError
            ? e.message
            : "CreditProbe could not complete that investigation.",
        );
      } finally {
        setAsking(null);
      }
    },
    [],
  );

  const reset = React.useCallback(() => {
    setAnswer(null);
    setPending(null);
    setSavedId(null);
    setQuestion("");
  }, []);

  /**
   * Keep this answer.
   *
   * The question is re-executed server-side rather than the displayed result
   * being posted: what gets saved has to be something CreditProbe produced, not
   * something a browser sent. The period already settled is carried over so the
   * saved answer is the one on screen.
   */
  const save = React.useCallback(async () => {
    if (!answer) return;
    const scope = answer.plan.scope;
    try {
      const stored = await api.saveInvestigation({
        question: answer.question,
        fromPeriod: scope?.from_period ?? undefined,
        toPeriod: scope?.to_period ?? undefined,
      });
      setSavedId(stored.id);
    } catch (e) {
      setAskError(
        e instanceof ApiError ? e.message : "CreditProbe could not save this investigation.",
      );
    }
  }, [answer]);

  if (asking) {
    return <InvestigationProgress stages={stages} question={asking} />;
  }

  if (answer?.clarification && pending) {
    return (
      <div className="space-y-5">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
            You asked
          </p>
          <h1 className="mt-1.5 max-w-3xl text-[22px] font-semibold leading-tight tracking-tight text-text-primary">
            {pending}
          </h1>
        </div>
        <ClarificationCard
          clarification={answer.clarification}
          mode={mode.data ?? null}
          onAnswer={(from, to) => void ask(pending, { from, to })}
        />
        <button
          type="button"
          onClick={reset}
          className="text-xs text-text-muted underline-offset-4 transition-colors hover:text-accent hover:underline"
        >
          Ask something else
        </button>
      </div>
    );
  }

  if (answer) {
    return (
      <InvestigationView
        investigation={answer}
        onAsk={(q) => void ask(q)}
        onReset={reset}
        onSave={canRun ? () => void save() : undefined}
        saved={savedId !== null}
        savedHref={savedId !== null ? `/investigations/saved/${savedId}` : undefined}
      />
    );
  }

  const values = briefing.data?.summary?.result?.values;
  const movement = (values?.movement ?? {}) as Record<string, number>;
  const period = briefing.data?.period ?? "";
  const attention = briefing.data?.attention;
  const trend = briefing.data?.trend;

  return (
    <div className="space-y-10">
      {/* ------------------------------------------------------------- hero */}
      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-text-muted">
            Credit Portfolio Intelligence
          </p>
          {period && (
            <Badge variant="outline" className="shrink-0">
              Reporting period {period}
            </Badge>
          )}
        </div>

        <h1 className="mt-3 max-w-3xl text-[28px] font-semibold leading-[1.15] tracking-tight text-text-primary sm:text-[34px]">
          {greeting}. What would you like to investigate?
        </h1>

        <div className="mt-6">
          <Composer
            value={question}
            onChange={setQuestion}
            onSubmit={(q) => void ask(q)}
            busy={!canRun}
            readOnlyNote={
              canRun
                ? undefined
                : "You are acting as a Viewer. Running an analysis needs the Analyst role or above."
            }
            suggestions={suggestions.data?.questions ?? []}
            autoFocus={focusAsk}
            modeNote={
              mode.data?.mode === "demo"
                ? "No model key is configured, so questions are read by CreditProbe's built-in planner."
                : undefined
            }
          />
        </div>

        {askError && (
          <Card className="mt-4 border-negative/40 p-4 text-sm text-negative">
            {askError}
          </Card>
        )}
      </section>

      {/* ----------------------------------------------------- portfolio pulse */}
      <section>
        <SectionHeading
          title="Portfolio pulse"
          info={
            <>
              <p>
                Four figures from the certified portfolio summary, run against
                the latest published period and compared with the one before it.
              </p>
              <p>
                It is here so you know what to ask, not as a dashboard. The CRO
                Lens has the full position.
              </p>
            </>
          }
          action={
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/lenses/cro">
                  CRO Lens
                  <ArrowRight aria-hidden />
                </Link>
              </Button>
              {briefing.data?.summary?.analysis_run_id && (
                <Button variant="ghost" size="sm" asChild>
                  <Link
                    href={`/trace/${briefing.data.summary.analysis_run_id}`}
                  >
                    <GitBranch aria-hidden />
                    Trace
                  </Link>
                </Button>
              )}
            </div>
          }
        />

        {briefing.error ? (
          <Card className="border-negative/40 p-4 text-sm text-negative">
            {briefing.error}
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              label="Total EAD"
              value={numberOf(values, "total_ead")}
              unit="USD mn"
              change={movement.total_ead ?? null}
              changeUnit="USD mn"
              direction="neutral"
              hint={period ? `vs prior period` : undefined}
              loading={briefing.loading}
            />
            <KpiTile
              label="NPL ratio"
              value={numberOf(values, "npl_ratio_pct")}
              unit="%"
              change={movement.npl_ratio_pct ?? null}
              changeUnit="pp"
              hint="vs prior period"
              loading={briefing.loading}
            />
            <KpiTile
              label="Stage 2 share"
              value={numberOf(values, "stage2_pct")}
              unit="%"
              change={movement.stage2_pct ?? null}
              changeUnit="pp"
              hint="vs prior period"
              loading={briefing.loading}
            />
            <KpiTile
              label="Total ECL"
              value={numberOf(values, "total_ecl")}
              unit="USD mn"
              change={movement.total_ecl ?? null}
              changeUnit="USD mn"
              hint="vs prior period"
              loading={briefing.loading}
            />
          </div>
        )}
      </section>

      {/* ---------------------------------------------------- requires attention */}
      <section className="grid gap-5 xl:grid-cols-[1.15fr_1fr]">
        <div>
          <SectionHeading
            title="Requires attention"
            info={
              <p>
                Borrowers whose expected credit loss rose most against the prior
                period, ranked by the engine. Selecting one asks CreditProbe the full
                question.
              </p>
            }
            action={
              attention?.analysis_run_id ? (
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/trace/${attention.analysis_run_id}`}>
                    <GitBranch aria-hidden />
                    Trace
                  </Link>
                </Button>
              ) : undefined
            }
          />
          <Card className="overflow-hidden">
            {briefing.loading && <Skeleton className="h-40 w-full" />}
            {!briefing.loading && attention?.result && (
              <>
                <ul className="divide-y divide-border">
                  {(attention.result.rows as Row[])
                    .slice(0, 4)
                    .map((row, i) => (
                      <li key={i}>
                        <button
                          type="button"
                          onClick={() =>
                            void ask(
                              "Show me the top ten deteriorating borrowers.",
                            )
                          }
                          className="flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-hover"
                        >
                          <TriangleAlert
                            className="mt-0.5 size-3.5 shrink-0 text-warning"
                            aria-hidden
                          />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-baseline justify-between gap-3">
                              <span className="truncate text-sm font-medium text-text-primary">
                                {String(row.borrower_name ?? "—")}
                              </span>
                              <span className="shrink-0 text-sm font-medium text-negative tabular">
                                {delta(Number(row.ecl_change), 1, " USD mn")}
                              </span>
                            </span>
                            <span className="mt-0.5 block truncate text-xs text-text-muted">
                              {String(row.sector ?? "")} ·{" "}
                              {money(Number(row.ead ?? 0), 0)}mn exposure
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                </ul>
                <p className="border-t border-border bg-surface-sunken px-4 py-2 text-xs text-text-muted">
                  {String(attention.result.values.deteriorated_count ?? "—")} of{" "}
                  {String(attention.result.values.borrowers_compared ?? "—")}{" "}
                  borrowers deteriorated, adding{" "}
                  {byUnit(
                    attention.result.values.total_ecl_increase as number,
                    "USD mn",
                  )}{" "}
                  USD mn of expected credit loss.
                </p>
              </>
            )}
          </Card>
        </div>

        <div>
          <SectionHeading
            title="Coverage and staging"
            info={
              <p>
                ECL coverage and the Stage 2 and Stage 3 shares across every
                published reporting period, from the certified portfolio trend
                analysis.
              </p>
            }
            action={
              trend?.analysis_run_id ? (
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/trace/${trend.analysis_run_id}`}>
                    <GitBranch aria-hidden />
                    Trace
                  </Link>
                </Button>
              ) : undefined
            }
          />
          <Card className="p-5">
            {briefing.loading && <Skeleton className="h-40 w-full" />}
            {!briefing.loading && trend?.result && (
              <>
                <TrendChart
                  data={
                    trend.result.rows as Record<
                      string,
                      string | number | null
                    >[]
                  }
                  xKey="period"
                  series={[
                    { key: "ecl_coverage_pct", label: "ECL coverage", slot: 0 },
                    { key: "stage2_pct", label: "Stage 2 share", slot: 1 },
                    { key: "stage3_pct", label: "Stage 3 share", slot: 2 },
                  ]}
                  units={{
                    ecl_coverage_pct: "%",
                    stage2_pct: "%",
                    stage3_pct: "%",
                  }}
                  height={190}
                />
                <p className="mt-3 flex items-start gap-1.5 border-t border-border pt-3 text-xs text-text-muted">
                  <TrendingUp className="mt-0.5 size-3 shrink-0" aria-hidden />
                  {trend.result.rows.length} periods · coverage{" "}
                  {percent(
                    (trend.result.values.change as Record<string, number>)
                      ?.ecl_coverage_pct,
                  )}{" "}
                  and Stage 2 share{" "}
                  {percent(
                    (trend.result.values.change as Record<string, number>)
                      ?.stage2_pct,
                  )}{" "}
                  since {String(trend.result.values.first_period ?? "")}
                </p>
              </>
            )}
          </Card>
        </div>
      </section>

      {/* --------------------------------------------------------- recent work */}
      <section>
        <SectionHeading
          title="Recent work"
          info={
            <p>
              Investigations you have run. Each one keeps the Trace it was
              produced with, so reopening it shows the same figures and the same
              lineage.
            </p>
          }
          action={
            <Button variant="ghost" size="sm" asChild>
              <Link href="/investigations">
                All
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        />
        {recent.data && recent.data.investigations.length > 0 ? (
          <Card className="divide-y divide-border">
            {recent.data.investigations.map((item) => (
              <div
                key={item.analysis_run_id}
                className="flex items-start gap-3 px-4 py-3"
              >
                <Search
                  className="mt-0.5 size-3.5 shrink-0 text-text-muted"
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text-primary">
                    {item.question}
                  </p>
                  <p className="mt-0.5 line-clamp-1 text-xs text-text-muted">
                    {item.summary || item.intent}
                  </p>
                </div>
                <span className="hidden shrink-0 items-center gap-1 text-[11px] text-text-muted sm:flex">
                  <Clock className="size-3" aria-hidden />
                  {item.duration_ms ?? "—"}ms
                </span>
                <Link
                  href={`/trace/${item.analysis_run_id}`}
                  className="shrink-0 text-xs font-medium text-accent hover:underline"
                >
                  Trace
                </Link>
              </div>
            ))}
          </Card>
        ) : (
          <Card className="px-5 py-8 text-center">
            <p className="text-sm text-text-secondary">
              No investigations yet.
            </p>
            <p className="mt-1 text-xs text-text-muted">
              Ask a question above and it will appear here, with its Trace,
              ready to reopen.
            </p>
          </Card>
        )}
      </section>

      <p className="flex items-center gap-2 border-t border-border pt-4 text-xs text-text-muted">
        <InfoPopover title="About these figures">
          <p>
            Every number on this page was produced by a registered CreditProbe Engine
            analysis executed against the published data, and carries a Trace.
          </p>
          <p>
            The book itself is CreditProbe&rsquo;s synthetic demonstration data until
            client data is onboarded and marked authoritative in Data Builder.
          </p>
        </InfoPopover>
        Demonstration data. Every figure carries a Trace.
      </p>
    </div>
  );
}

/**
 * A section heading.
 *
 * The explanation of what a section is lives behind the "i", not underneath the
 * title. Five sections with a line of standfirst each is five paragraphs of
 * furniture between the reader and the figures.
 */
function SectionHeading({
  title,
  info,
  action,
}: {
  title: string;
  info?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">
          {title}
        </h2>
        {info && <InfoPopover title={title}>{info}</InfoPopover>}
      </div>
      {action}
    </div>
  );
}
