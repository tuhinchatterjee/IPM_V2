"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Clock,
  GitBranch,
  Search,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";

import { Composer, useGreeting } from "@/components/ask/composer";
import { InvestigationProgress, InvestigationView } from "@/components/ask/investigation";
import { TrendChart } from "@/components/analytics/charts";
import { KpiTile } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
 * The AI Cockpit — IPM's hero screen.
 *
 * The order of the page is the order of a credit officer's morning: what would
 * you like to investigate, then where the book stands, then what is already
 * demanding attention, then what you were working on. The composer comes first
 * because asking is the product; the briefing beneath it exists so you know what
 * to ask.
 *
 * Nothing on this page is a hard-coded portfolio figure. The briefing is three
 * registered analyses executed on request, and the answer below the composer is
 * a full investigation with its own Trace.
 */

const FALLBACK_STAGES: Stage[] = [
  { id: "understanding", label: "Understanding the question" },
  { id: "planning", label: "Selecting IPM analyses" },
  { id: "retrieving", label: "Retrieving governed data" },
  { id: "running", label: "Running the IPM Engine" },
  { id: "synthesising", label: "Synthesising findings" },
];

function numberOf(values: Record<string, unknown> | undefined, key: string): number | null {
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
  const [answer, setAnswer] = React.useState<InvestigationResponse | null>(null);
  const [askError, setAskError] = React.useState<string | null>(null);

  const greeting = useGreeting();
  const mode = useAsync(() => api.askMode(), []);
  const suggestions = useAsync(() => api.askSuggestions(), []);
  const briefing = useAsync(() => api.briefing(), []);
  const recent = useAsync(() => api.recentInvestigations(5), [answer?.analysis_run_id]);

  const stages = mode.data?.stages ?? FALLBACK_STAGES;

  const ask = React.useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setAsking(trimmed);
    setAnswer(null);
    setAskError(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
    try {
      setAnswer(await api.ask(trimmed));
    } catch (e) {
      setAskError(
        e instanceof ApiError ? e.message : "IPM could not complete that investigation.",
      );
    } finally {
      setAsking(null);
    }
  }, []);

  if (asking) {
    return <InvestigationProgress stages={stages} question={asking} />;
  }

  if (answer) {
    return (
      <InvestigationView
        investigation={answer}
        onAsk={(q) => void ask(q)}
        onReset={() => {
          setAnswer(null);
          setQuestion("");
        }}
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
            suggestions={suggestions.data?.questions ?? []}
            autoFocus={focusAsk}
            modeNote={mode.data?.mode === "demo"
              ? "No model key is configured, so questions are read by IPM's built-in planner."
              : undefined}
          />
        </div>

        {askError && (
          <Card className="mt-4 border-negative/40 p-4 text-sm text-negative">{askError}</Card>
        )}
      </section>

      {/* -------------------------------------------------- portfolio briefing */}
      <section>
        <SectionHeading
          title="Portfolio briefing"
          hint={period ? `As at ${period}, against the prior period` : undefined}
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
                  <Link href={`/trace/${briefing.data.summary.analysis_run_id}`}>
                    <GitBranch aria-hidden />
                    Trace
                  </Link>
                </Button>
              )}
            </div>
          }
        />

        {briefing.error ? (
          <Card className="border-negative/40 p-4 text-sm text-negative">{briefing.error}</Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              label="Total EAD"
              value={numberOf(values, "total_ead")}
              unit="USD mn"
              change={movement.total_ead ?? null}
              changeUnit="USD mn"
              direction="neutral"
              hint="vs prior period"
              loading={briefing.loading}
              emphasis
            />
            <KpiTile
              label="NPL ratio"
              value={numberOf(values, "npl_ratio_pct")}
              unit="%"
              change={movement.npl_ratio_pct ?? null}
              changeUnit="pp"
              hint="vs prior period"
              loading={briefing.loading}
              emphasis
            />
            <KpiTile
              label="Stage 2 share"
              value={numberOf(values, "stage2_pct")}
              unit="%"
              change={movement.stage2_pct ?? null}
              changeUnit="pp"
              hint="vs prior period"
              loading={briefing.loading}
              emphasis
            />
            <KpiTile
              label="Total ECL"
              value={numberOf(values, "total_ecl")}
              unit="USD mn"
              change={movement.total_ecl ?? null}
              changeUnit="USD mn"
              hint="vs prior period"
              loading={briefing.loading}
              emphasis
            />
          </div>
        )}
      </section>

      {/* ---------------------------------------------------- requires attention */}
      <section className="grid gap-5 xl:grid-cols-[1.15fr_1fr]">
        <div>
          <SectionHeading
            title="Requires attention"
            hint="Borrowers whose position worsened against the prior period"
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
            {briefing.loading && <Skeleton className="h-56 w-full" />}
            {!briefing.loading && attention?.result && (
              <>
                <ul className="divide-y divide-border">
                  {(attention.result.rows as Row[]).slice(0, 5).map((row, i) => (
                    <li key={i}>
                      <button
                        type="button"
                        onClick={() =>
                          void ask(
                            `Show me the top ten deteriorating borrowers.`,
                          )
                        }
                        className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-hover"
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
                            {String(row.sector ?? "")} · {money(Number(row.ead ?? 0), 0)}mn
                            exposure · {String(row.reasons ?? "")}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
                <p className="border-t border-border bg-surface-sunken px-4 py-2.5 text-xs text-text-muted">
                  {String(attention.result.values.deteriorated_count ?? "—")} of{" "}
                  {String(attention.result.values.borrowers_compared ?? "—")} borrowers
                  deteriorated, adding{" "}
                  {byUnit(attention.result.values.total_ecl_increase as number, "USD mn")} of
                  expected credit loss.
                </p>
              </>
            )}
          </Card>
        </div>

        <div>
          <SectionHeading
            title="Portfolio intelligence"
            hint="Coverage and staging across every reporting period"
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
            {briefing.loading && <Skeleton className="h-56 w-full" />}
            {!briefing.loading && trend?.result && (
              <>
                <TrendChart
                  data={trend.result.rows as Record<string, string | number | null>[]}
                  xKey="period"
                  series={[
                    { key: "ecl_coverage_pct", label: "ECL coverage", slot: 0 },
                    { key: "stage2_pct", label: "Stage 2 share", slot: 1 },
                    { key: "stage3_pct", label: "Stage 3 share", slot: 2 },
                  ]}
                  units={{ ecl_coverage_pct: "%", stage2_pct: "%", stage3_pct: "%" }}
                  height={210}
                />
                <p className="mt-3 flex items-start gap-1.5 border-t border-border pt-3 text-xs text-text-muted">
                  <TrendingUp className="mt-0.5 size-3 shrink-0" aria-hidden />
                  {trend.result.rows.length} periods · coverage{" "}
                  {percent(
                    (trend.result.values.change as Record<string, number>)?.ecl_coverage_pct,
                  )}{" "}
                  and Stage 2 share{" "}
                  {percent((trend.result.values.change as Record<string, number>)?.stage2_pct)}{" "}
                  since {String(trend.result.values.first_period ?? "")}
                </p>
              </>
            )}
          </Card>
        </div>
      </section>

      {/* ------------------------------------------------- recent investigations */}
      <section>
        <SectionHeading
          title="Recent investigations"
          hint="Every one keeps its Trace"
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
              <div key={item.analysis_run_id} className="flex items-start gap-3 px-4 py-3">
                <Search className="mt-0.5 size-3.5 shrink-0 text-text-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text-primary">{item.question}</p>
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
            <p className="text-sm text-text-secondary">No investigations yet.</p>
            <p className="mt-1 text-xs text-text-muted">
              Ask a question above and it will appear here, with its Trace, ready to reopen.
            </p>
          </Card>
        )}
      </section>

      {/* ------------------------------------------------------------- footer */}
      <section>
        <SectionHeading title="Where to look next" />
        <div className="grid gap-3 md:grid-cols-3">
          <NextStep
            title="Concentration"
            body="Where the book is concentrated, and the quality of what sits inside each group."
            onClick={() => void ask("Where is the book most concentrated?")}
          />
          <NextStep
            title="Rating migration"
            body="Empirical transition probabilities between the two reporting periods."
            onClick={() => void ask("Show me the rating transition matrix.")}
          />
          <NextStep
            title="Downturn sensitivity"
            body="Size the incremental impairment under a management scenario."
            onClick={() => void ask("Stress the portfolio under a severe scenario.")}
          />
        </div>
      </section>

      <p className="border-t border-border pt-4 text-xs leading-relaxed text-text-muted">
        Figures are synthetic demonstration data. Every number on this page was produced by a
        registered IPM Engine analysis and carries a Trace.
      </p>
    </div>
  );
}

function SectionHeading({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-text-muted">{hint}</p>}
      </div>
      {action}
    </div>
  );
}

function NextStep({
  title,
  body,
  onClick,
}: {
  title: string;
  body: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex items-start gap-3 rounded-lg border border-border bg-surface p-4 text-left transition-colors hover:border-accent hover:bg-surface-hover"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-text-primary">{title}</span>
        <span className="mt-1 block text-xs leading-relaxed text-text-muted">{body}</span>
      </span>
      <ArrowUpRight
        className="mt-0.5 size-3.5 shrink-0 text-text-muted opacity-0 transition-opacity group-hover:opacity-100"
        aria-hidden
      />
    </button>
  );
}
