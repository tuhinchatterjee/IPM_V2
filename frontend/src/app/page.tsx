"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Boxes,
  ClipboardCheck,
  CornerDownLeft,
  Search,
  Sparkles,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";

import { AnalyticalCard, TraceButton } from "@/components/analytics/analytical-card";
import { TrendChart } from "@/components/analytics/charts";
import { KpiTile, ResultTable } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { BLUEPRINTS, INVESTIGATIONS, PROJECTS, SUGGESTED_QUESTIONS } from "@/lib/demo";
import { moneyCompact, percent } from "@/lib/format";
import { useAnalysis } from "@/lib/hooks";
import type { Row } from "@/lib/api";

/**
 * The AI Cockpit.
 *
 * The conversational workspace is the centre of the screen, not a widget bolted
 * to the side of a dashboard — that ordering is the product's whole claim.
 * Below it sit the things a credit officer needs before they know what to ask:
 * where the book stands, what moved, and what they were working on.
 *
 * Every figure here is produced by a registered engine analysis. Nothing on this
 * page is a hard-coded portfolio number.
 */

function numberOf(values: Record<string, unknown> | undefined, key: string): number | null {
  const v = values?.[key];
  return typeof v === "number" ? v : null;
}

export default function CockpitPage() {
  const router = useRouter();
  const [question, setQuestion] = React.useState("");
  const composerRef = React.useRef<HTMLTextAreaElement>(null);

  // Headline position and the movement against the prior period.
  const summary = useAnalysis("portfolio_summary", { params: { period: "latest" } });
  // What the book has done over every available period.
  const trend = useAnalysis("portfolio_trend", {});
  // Who got worse — the proactive signal, not a static watchlist.
  const deteriorating = useAnalysis("top_deteriorating_borrowers", {
    params: { from_period: "previous", to_period: "latest", top_n: 6 },
  });

  const values = summary.data?.result?.values;
  const movement = (values?.movement ?? {}) as Record<string, number>;
  const period = (values?.period as string) ?? "";

  function ask(text: string) {
    // Until the planner exists, a question resolves to the registered analysis
    // that answers it. The route is the same one the planner will use.
    const match = SUGGESTED_QUESTIONS.find(
      (s) => s.question.toLowerCase() === text.trim().toLowerCase(),
    );
    if (match) {
      const params = new URLSearchParams({ params: JSON.stringify(match.params ?? {}) });
      if (match.filters) params.set("filters", JSON.stringify(match.filters));
      params.set("q", match.question);
      router.push(`/analysis/${match.analysisId}?${params}`);
      return;
    }
    router.push(`/analysis/portfolio_summary?q=${encodeURIComponent(text)}&unmatched=1`);
  }

  return (
    <div className="space-y-8">
      {/* ---------------------------------------------------------- composer */}
      <section>
        <div className="mb-4 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-text-primary">
              Ask IPM
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Ask a question about the portfolio. IPM answers with governed analytics —
              every figure produced by a tested engine, every result traceable.
            </p>
          </div>
          {period && (
            <Badge variant="outline" className="shrink-0">
              Reporting period {period}
            </Badge>
          )}
        </div>

        <Card className="overflow-hidden border-border-strong">
          <div className="relative">
            <textarea
              ref={composerRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (question.trim()) ask(question);
                }
              }}
              rows={3}
              placeholder="What deteriorated this period?"
              aria-label="Ask IPM a question"
              className="w-full resize-none bg-transparent px-5 py-4 pr-32 text-base text-text-primary placeholder:text-text-muted focus:outline-none"
            />
            <div className="absolute bottom-3 right-4 flex items-center gap-2">
              <span className="hidden text-[11px] text-text-muted sm:inline">
                Enter to ask
              </span>
              <Button size="sm" disabled={!question.trim()} onClick={() => ask(question)}>
                <CornerDownLeft aria-hidden />
                Ask
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 border-t border-border bg-surface-sunken px-4 py-3">
            <span className="mr-1 text-[11px] font-medium uppercase tracking-wider text-text-muted">
              Try
            </span>
            {SUGGESTED_QUESTIONS.map((s) => (
              <button
                key={s.question}
                type="button"
                onClick={() => ask(s.question)}
                title={s.note}
                className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent"
              >
                {s.question}
              </button>
            ))}
          </div>
        </Card>

        <p className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
          <Sparkles className="size-3" aria-hidden />
          Suggested questions run the registered analysis that answers them. Free-text
          planning arrives with AI orchestration — the engine, contracts and Trace it will
          use are already in place.
        </p>
      </section>

      {/* ------------------------------------------------------ headline KPIs */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-tight text-text-primary">
            Portfolio position
          </h2>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/lenses/cro">
                CRO Lens
                <ArrowRight aria-hidden />
              </Link>
            </Button>
            <TraceButton runId={summary.data?.analysis_run_id} />
          </div>
        </div>

        {summary.error ? (
          <Card className="border-negative/40 p-4 text-sm text-negative">{summary.error}</Card>
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
              loading={summary.loading}
              emphasis
            />
            <KpiTile
              label="Total ECL"
              value={numberOf(values, "total_ecl")}
              unit="USD mn"
              change={movement.total_ecl ?? null}
              changeUnit="USD mn"
              hint="vs prior period"
              loading={summary.loading}
              emphasis
            />
            <KpiTile
              label="ECL coverage"
              value={numberOf(values, "ecl_coverage_pct")}
              unit="%"
              change={movement.ecl_coverage_pct ?? null}
              changeUnit="pp"
              hint="vs prior period"
              loading={summary.loading}
              emphasis
            />
            <KpiTile
              label="NPL ratio"
              value={numberOf(values, "npl_ratio_pct")}
              unit="%"
              change={movement.npl_ratio_pct ?? null}
              changeUnit="pp"
              hint="vs prior period"
              loading={summary.loading}
              emphasis
            />
          </div>
        )}
      </section>

      {/* ------------------------------------------- signals + trend, side by side */}
      <section className="grid gap-4 xl:grid-cols-[1.15fr_1fr]">
        <AnalyticalCard
          title="Deterioration signals"
          description="Borrowers whose position worsened against the prior period"
          analysisId="top_deteriorating_borrowers"
          run={deteriorating.data}
          loading={deteriorating.loading}
          error={deteriorating.error}
          onRetry={deteriorating.reload}
          minHeight={280}
          footer={
            <Link
              href="/investigations/stage-2-deterioration"
              className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
            >
              Open the Stage 2 Deterioration Review
              <ArrowUpRight className="size-3" aria-hidden />
            </Link>
          }
        >
          {deteriorating.data?.result && (
            <>
              <p className="mb-3 flex items-center gap-1.5 text-xs text-text-muted">
                <TriangleAlert className="size-3.5 text-warning" aria-hidden />
                {String(deteriorating.data.result.values.deteriorated_count ?? "—")} of{" "}
                {String(deteriorating.data.result.values.borrowers_compared ?? "—")} borrowers
                deteriorated
              </p>
              <ResultTable
                rows={deteriorating.data.result.rows as Row[]}
                units={{ ead: "USD mn", ecl_change: "USD mn" }}
                columns={["borrower_name", "sector", "ead", "ecl_change", "reasons"]}
                maxRows={6}
                renderCell={(column, value) =>
                  column === "reasons" ? (
                    <span className="block max-w-[22rem] truncate text-xs text-text-muted">
                      {String(value)}
                    </span>
                  ) : undefined
                }
              />
            </>
          )}
        </AnalyticalCard>

        <AnalyticalCard
          title="Coverage and staging trend"
          description="Every available reporting period"
          analysisId="portfolio_trend"
          run={trend.data}
          loading={trend.loading}
          error={trend.error}
          onRetry={trend.reload}
          minHeight={280}
        >
          {trend.data?.result && (
            <TrendChart
              data={trend.data.result.rows as Record<string, string | number | null>[]}
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
              height={230}
            />
          )}
        </AnalyticalCard>
      </section>

      {/* -------------------------------------------------------- your work */}
      <section className="grid gap-4 lg:grid-cols-3">
        <WorkCard
          icon={Search}
          title="Recent investigations"
          href="/investigations"
          items={INVESTIGATIONS.slice(0, 3).map((i) => ({
            href: `/investigations/${i.id}`,
            title: i.title,
            meta: `${i.steps.length} analyses · ${i.owner}`,
          }))}
        />
        <WorkCard
          icon={Boxes}
          title="Recent projects"
          href="/projects"
          items={PROJECTS.slice(0, 3).map((p) => ({
            href: `/projects/${p.id}`,
            title: p.name,
            meta: `${p.counts.investigations} investigations · ${p.team}`,
          }))}
        />
        <WorkCard
          icon={ClipboardCheck}
          title="Blueprints"
          href="/blueprints"
          items={BLUEPRINTS.slice(0, 3).map((b) => ({
            href: `/blueprints/${b.id}`,
            title: b.name,
            meta: `${b.steps.length} steps · ${b.cadence}`,
          }))}
        />
      </section>

      {/* ------------------------------------------------------- follow-ups */}
      <section>
        <h2 className="mb-3 text-sm font-semibold tracking-tight text-text-primary">
          Where to look next
        </h2>
        <div className="grid gap-3 md:grid-cols-3">
          <FollowUp
            title="Concentration"
            body={
              summary.data
                ? "Measure where the book is concentrated and what sits inside each sector."
                : "…"
            }
            href="/analysis/sector_concentration"
          />
          <FollowUp
            title="Rating migration"
            body="Empirical transition probabilities over the full history."
            href="/analysis/rating_transition_matrix?params=%7B%22from_period%22%3A%22earliest%22%2C%22to_period%22%3A%22latest%22%7D"
          />
          <FollowUp
            title="Downturn sensitivity"
            body="Size the incremental impairment under a management scenario."
            href="/stress"
          />
        </div>
      </section>

      {/* ------------------------------------------------------------ footer */}
      {trend.data?.result && (
        <p className="flex items-center gap-1.5 border-t border-border pt-4 text-xs text-text-muted">
          <TrendingUp className="size-3.5" aria-hidden />
          {trend.data.result.rows.length} reporting periods ·{" "}
          {moneyCompact(numberOf(values, "total_ead"))} exposure ·{" "}
          {percent(numberOf(values, "ecl_coverage_pct"))} coverage · figures are synthetic
          demonstration data
        </p>
      )}
    </div>
  );
}

function WorkCard({
  icon: Icon,
  title,
  href,
  items,
}: {
  icon: typeof Search;
  title: string;
  href: string;
  items: { href: string; title: string; meta: string }[];
}) {
  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-text-primary">
          <Icon className="size-4 text-text-muted" aria-hidden />
          {title}
        </h3>
        <Link href={href} className="text-xs font-medium text-accent hover:underline">
          All
        </Link>
      </div>
      <ul className="flex-1 divide-y divide-border">
        {items.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className="block px-4 py-2.5 transition-colors hover:bg-surface-hover"
            >
              <p className="truncate text-sm text-text-primary">{item.title}</p>
              <p className="mt-0.5 truncate text-xs text-text-muted">{item.meta}</p>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function FollowUp({ title, body, href }: { title: string; body: string; href: string }) {
  return (
    <Link
      href={href}
      className="group flex items-start gap-3 rounded-lg border border-border bg-surface p-4 transition-colors hover:bg-surface-hover"
    >
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-text-primary">{title}</p>
        <p className="mt-1 text-xs leading-relaxed text-text-muted">{body}</p>
      </div>
      <ArrowRight
        className="mt-0.5 size-4 shrink-0 text-text-muted opacity-0 transition-opacity group-hover:opacity-100"
        aria-hidden
      />
    </Link>
  );
}

export function CockpitSkeleton() {
  return <Skeleton className="h-64 w-full" />;
}
