"use client";

import Link from "next/link";
import * as React from "react";
import { Play, Sparkles } from "lucide-react";

import { AnalyticalCard, CertificationMark } from "@/components/analytics/analytical-card";
import { ResultView } from "@/components/analytics/result-view";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { BackLink } from "@/components/layout/back-link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAnalysis, useAsync } from "@/lib/hooks";

/**
 * Runs one registered analysis and shows the result.
 *
 * This is where a Cockpit question lands. Until the planner exists, a suggested
 * question resolves to the analysis that answers it and arrives here with its
 * parameters — the same route the planner will use once it is choosing the
 * analysis itself.
 */
export default function AnalysisRunPage({
  params,
  searchParams,
}: {
  params: Promise<{ analysisId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { analysisId } = React.use(params);
  const query = React.use(searchParams);

  const parsed = React.useMemo(() => {
    const read = (key: string) => {
      const raw = query[key];
      if (typeof raw !== "string") return undefined;
      try {
        return JSON.parse(raw) as Record<string, unknown>;
      } catch {
        return undefined;
      }
    };
    return { params: read("params") ?? {}, filters: read("filters") ?? {} };
  }, [query]);

  const question = typeof query.q === "string" ? query.q : undefined;
  const unmatched = query.unmatched === "1";

  const definition = useAsync(() => api.analysis(analysisId), [analysisId]);
  const run = useAnalysis(analysisId, {
    params: parsed.params,
    filters: parsed.filters,
  });

  return (
    <div className="space-y-6">
      <BackLink href="/" label="Cockpit" />

      {question && (
        <Card className="border-accent/30 bg-accent-muted/30 p-4">
          <p className="flex items-start gap-2 text-sm">
            <Sparkles className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
            <span>
              <span className="font-medium text-text-primary">“{question}”</span>
              <span className="mt-1 block text-xs text-text-secondary">
                {unmatched ? (
                  <>
                    Free-text planning is not connected yet, so CreditProbe has not interpreted this
                    question. It has run the portfolio summary instead. Choose a suggested
                    question on the Cockpit to run the analysis that answers it.
                  </>
                ) : (
                  <>
                    Answered by the <strong>{definition.data?.name ?? analysisId}</strong>{" "}
                    analysis. AI interpretation of free text arrives with orchestration; the
                    engine and Trace it will use are already in place.
                  </>
                )}
              </span>
            </span>
          </p>
        </Card>
      )}

      <PageHeader
        title={definition.data?.name ?? analysisId}
        description={definition.data?.description}
        actions={
          <div className="flex items-center gap-2">
            {definition.data && (
              <CertificationMark certification={definition.data.certification} />
            )}
            <Button variant="outline" size="sm" asChild>
              <Link href={`/engine-builder/${analysisId}`}>Definition</Link>
            </Button>
            <Button variant="outline" size="sm" onClick={run.reload}>
              <Play aria-hidden />
              Re-run
            </Button>
          </div>
        }
      />

      {Object.keys(parsed.params).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-text-muted">Parameters</span>
          {Object.entries(parsed.params).map(([k, v]) => (
            <Badge key={k} variant="outline">
              {k}: {String(v)}
            </Badge>
          ))}
          {Object.entries(parsed.filters).map(([k, v]) => (
            <Badge key={k} variant="accent">
              {k}: {String(v)}
            </Badge>
          ))}
        </div>
      )}

      <AnalyticalCard
        title="Result"
        description={run.data?.result?.meta?.grain}
        run={run.data}
        loading={run.loading}
        error={run.error}
        onRetry={run.reload}
        analysisId={analysisId}
        minHeight={320}
      >
        {run.data && <ResultView run={run.data} />}
      </AnalyticalCard>

      {definition.data && (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-semibold text-text-primary">Methodology</h3>
          <p className="whitespace-pre-line text-sm leading-relaxed text-text-secondary">
            {definition.data.calculation_description}
          </p>
        </Card>
      )}
    </div>
  );
}
