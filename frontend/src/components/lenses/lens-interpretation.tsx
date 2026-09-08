"use client";

import * as React from "react";
import { Sparkles } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * "CreditProbe View" — what a Lens means, above what it shows.
 *
 * UAT: the CRO Lens "opens directly into metric cards... there is no AI
 * interpretation explaining what the user should conclude." This is that
 * reading, fetched from the SAME rendered figures already on the page below
 * it — never a second, independent look at the book — and refreshed
 * whenever the period or the Lens's own content changes, via `version` and
 * `period` in the caller's key: a metric added or removed, a chart recut, or
 * a rebuild all bump the Lens's version, and a period change is the period
 * itself changing, so neither needs its own tracking here.
 *
 * Degrading is the default, not the exception, in any deployment with no AI
 * provider configured: the note below says so in one sentence, and nothing
 * else on the page is affected — the metric tiles this panel sits above are
 * the deterministic product whether or not this ever has anything to say.
 */
export function LensInterpretationPanel({
  lensId,
  period,
  version,
}: {
  lensId: number;
  period: string | null;
  version: number;
}) {
  const interpretation = useAsync(
    () => api.lensInterpretation(lensId, period ?? undefined),
    [lensId, period, version],
  );

  if (interpretation.loading && !interpretation.data) {
    return <Skeleton className="h-24 w-full" />;
  }

  const data = interpretation.data;
  if (!data || !data.live) {
    return (
      <p
        className="text-[11px] text-text-muted"
        data-testid="ai-interpretation-unavailable"
      >
        {data?.unavailable ||
          interpretation.error ||
          "AI interpretation is temporarily unavailable."}
      </p>
    );
  }

  return (
    <Card className="border-accent/30 bg-accent/5 p-5" data-testid="ai-interpretation">
      <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-accent">
        <Sparkles className="size-3.5" aria-hidden />
        CreditProbe View
      </h2>
      {data.headline && (
        <p className="mt-2 text-sm font-medium text-text-primary">
          {data.headline}
        </p>
      )}
      {data.narrative && (
        <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-text-secondary">
          {data.narrative}
        </p>
      )}
      {data.observations.length > 0 && (
        <ul className="mt-3 space-y-1.5" data-testid="ai-interpretation-observations">
          {data.observations.map((o, i) => (
            <li key={i} className="text-xs text-text-secondary">
              <span>{o.text}</span>
              {o.metric_names.length > 0 && (
                <span className="ml-1.5 inline-flex flex-wrap gap-1">
                  {o.metric_names.map((name) => (
                    <span
                      key={name}
                      className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted"
                    >
                      {name}
                    </span>
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {data.unavailable_note && (
        <p className="mt-3 text-[11px] text-warning">{data.unavailable_note}</p>
      )}
    </Card>
  );
}
