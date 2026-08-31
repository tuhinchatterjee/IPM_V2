"use client";

import Link from "next/link";
import * as React from "react";

import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Early Warning on the Cockpit. §36.
 *
 * One line, six counts, and a link. The Cockpit's standing constraint is that
 * it stays calm — §40 and §63 both say so — and a module that arrives on the
 * home page as a second table has taken the home page over rather than joined
 * it.
 *
 * The counts are of SITUATIONS, not of signals. "New conditions: 4,812" tells
 * nobody anything and reads as alarming precisely because it is meaningless;
 * "borrowers with a new condition: 214" is a queue somebody can work through.
 *
 * Nothing here is a score, and nothing here is coloured by severity. A row of
 * red numbers on a home page is a row people stop seeing by the second week.
 */
export function EarlyWarningStrip({ period }: { period?: string }) {
  const book = useAsync(
    () => api.earlyWarningSignals({ period, limit: 1 }),
    [period],
  );

  if (book.loading) return <Skeleton className="h-20 w-full" />;
  // A strip that cannot load is not an alarm. It says so quietly and the rest
  // of the Cockpit is unaffected.
  if (book.error || !book.data?.headline) return null;

  const headline = book.data.headline;
  const cells = [
    {
      label: "New condition",
      value: headline.with_a_new_signal,
      means: headline.means?.with_a_new_signal,
    },
    { label: "Worsening", value: headline.worsening },
    { label: "Still firing", value: headline.persisting },
    { label: "Severe", value: headline.severe },
    {
      label: "3+ families",
      value: headline.multi_family,
      means: headline.means?.multi_family,
    },
    {
      label: "Booked stage 2+",
      value: headline.booked_stage_2_or_worse,
      means: headline.means?.booked_stage_2_or_worse,
    },
  ];

  return (
    <Card className="p-4">
      <div className="mb-2.5 flex items-baseline justify-between gap-4">
        <p className="text-xs text-text-muted">
          {book.data.evaluated.toLocaleString()} borrowers evaluated against{" "}
          {book.data.signal_count ?? 0} governed conditions at{" "}
          {book.data.period}
        </p>
        <Link
          href="/early-warning/signals"
          className="text-[11px] text-text-muted underline-offset-4 hover:text-accent hover:underline"
        >
          Open
        </Link>
      </div>
      <dl className="grid grid-cols-3 gap-x-4 gap-y-3 sm:grid-cols-6">
        {cells.map((cell) => (
          <div key={cell.label}>
            <dt className="flex items-center gap-1 text-[11px] text-text-muted">
              {cell.label}
              {cell.means && <InfoPopover>{cell.means}</InfoPopover>}
            </dt>
            <dd className="mt-0.5 text-lg font-medium tabular-nums">
              {cell.value.toLocaleString()}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
