"use client";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * What the portfolio figures mean, above the tables that state them.
 *
 * The screen already shows the score, the counts and the exposure. What it
 * did not say is which layer is carrying the movement, whether the risk sits
 * in a handful of names or across the book, and what follows from either —
 * which is the whole difference between a dashboard and a reading.
 */
export function PortfolioInsight({ period }: { period?: string }) {
  const insight = useAsync(() => api.earlyWarningV2Insight(period), [period]);

  if (insight.loading) return <Skeleton className="h-28 w-full" />;
  if (insight.error || !insight.data) return null;

  const { direct, interpretation, points } = insight.data;
  return (
    <Card className="space-y-2.5 border-accent/30 p-4">
      <p className="meta text-text-muted">What this says</p>
      <p className="text-[15px] font-medium leading-relaxed text-text-primary">
        {direct}
      </p>
      {interpretation && (
        <p className="text-sm leading-relaxed text-text-secondary">
          {interpretation}
        </p>
      )}
      {points.length > 0 && (
        <ul className="space-y-1 border-t border-border pt-2.5">
          {points.map((point, i) => (
            <li key={i} className="text-xs leading-relaxed text-text-muted">
              {point}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
