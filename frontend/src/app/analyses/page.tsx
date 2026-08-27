"use client";

import Link from "next/link";
import * as React from "react";
import { BarChart3, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CertificationBadge } from "@/components/ui/certified-mark";
import { stepHref } from "@/lib/analysis-links";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type SavedAnalysis } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import {
  analysisAnchor,
  fromSavedAnalysis,
  linkBack,
  useAnchorScroll,
} from "@/lib/return-to";

/**
 * Analyses: the evidence.
 *
 * An Analysis is the smallest unit of the hierarchy —
 * Analysis &lt; Investigation &lt; Project — one certified function, run with stated
 * parameters over a stated period, producing one result somebody chose to keep.
 *
 * What is on this screen is what was calculated at the time it was saved. It is
 * not re-run when you open it, and it never will be: an answer that quietly
 * refreshed itself would stop being evidence of anything. Each row carries its
 * certification, its period, and a link to the Trace that shows how it was
 * produced.
 */
export default function AnalysesPage() {
  const saved = useAsync(() => api.savedAnalyses(), []);
  // A Trace opened from a row returns here; land on the row rather than the
  // top of a list that may run to a hundred entries.
  useAnchorScroll(Boolean(saved.data));
  const projects = useAsync(() => api.projects(), []);
  const [removed, setRemoved] = React.useState<Set<number>>(() => new Set());

  const projectName = React.useCallback(
    (id: number | null) =>
      id === null
        ? null
        : (projects.data?.projects.find((p) => p.id === id)?.name ?? null),
    [projects.data],
  );

  const rows = (saved.data?.analyses ?? []).filter((a) => !removed.has(a.id));

  async function remove(id: number) {
    await api.deleteAnalysis(id);
    setRemoved((current) => new Set(current).add(id));
  }

  return (
    <div className="space-y-7">
      <PageHeader
        title="Analyses"
        description="One certified calculation, kept. Each analysis records the run that produced it — the function, its version, the parameters and the period — so a figure can be put in front of a committee and followed back to the rows behind it."
        status="live"
      />

      {saved.loading && <Skeleton className="h-52 w-full" />}
      {saved.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {saved.error}
        </Card>
      )}

      {saved.data &&
        (rows.length > 0 ? (
          <Card className="divide-y divide-border">
            {rows.map((analysis) => (
              <Row
                key={analysis.id}
                analysis={analysis}
                projectName={projectName(analysis.project_id)}
                onDelete={() => remove(analysis.id)}
              />
            ))}
          </Card>
        ) : (
          <EmptyState
            icon={BarChart3}
            title="No saved analyses yet"
            description="Under any answer, Save analysis keeps the certified calculations behind it. They collect here and can be filed under a project."
            action={
              <Button size="sm" asChild>
                <Link href="/?focus=ask">Ask a question</Link>
              </Button>
            }
          />
        ))}
    </div>
  );
}

function Row({
  analysis,
  projectName,
  onDelete,
}: {
  analysis: SavedAnalysis;
  projectName: string | null;
  onDelete: () => void;
}) {
  const target = stepHref(
    analysis.analysis_id,
    analysis.certification,
    analysis.analysis_run_id ?? null,
  );
  const period = periodLabel(analysis.period);

  return (
    <div
      id={analysisAnchor(analysis.id)}
      className="flex scroll-mt-24 items-start gap-3 px-5 py-4"
    >
      <BarChart3 className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {target ? (
            <Link
              href={linkBack(
                target,
                fromSavedAnalysis(analysis.id, analysis.title),
              )}
              className="truncate text-sm font-medium text-text-primary hover:text-accent"
            >
              {analysis.title}
            </Link>
          ) : (
            <span className="truncate text-sm font-medium text-text-primary">
              {analysis.title}
            </span>
          )}
          <CertificationBadge certification={analysis.certification} />
        </div>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
          <span>{analysis.analysis_id}</span>
          {analysis.analysis_version && <span>v{analysis.analysis_version}</span>}
          {period && <span>{period}</span>}
          {projectName && analysis.project_id !== null && (
            <Link
              href={linkBack(
                `/projects/${analysis.project_id}`,
                fromSavedAnalysis(analysis.id, analysis.title),
              )}
              className="hover:text-accent"
            >
              {projectName}
            </Link>
          )}
          {analysis.investigation_id !== null && (
            <Link
              href={linkBack(
                `/investigations/${analysis.investigation_id}`,
                fromSavedAnalysis(analysis.id, analysis.title),
              )}
              className="hover:text-accent"
            >
              From this investigation
            </Link>
          )}
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-0.5">
        {analysis.analysis_run_id !== null && (
          <Button variant="ghost" size="sm" asChild>
            <Link
              href={linkBack(
                `/trace/${analysis.analysis_run_id}`,
                fromSavedAnalysis(analysis.id, analysis.title),
              )}
            >
              Trace
            </Link>
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={onDelete}
          title="Stop keeping this analysis. The run and its Trace are untouched."
        >
          <Trash2 aria-hidden />
          <span className="sr-only">Delete</span>
        </Button>
      </div>
    </div>
  );
}

/** The period a saved analysis covered, however it was recorded. */
function periodLabel(period: Record<string, unknown>): string {
  const from = period.from_period;
  const to = period.to_period;
  if (typeof from === "string" && typeof to === "string") return `${from} to ${to}`;
  if (typeof period.period === "string") return period.period;
  return "";
}
