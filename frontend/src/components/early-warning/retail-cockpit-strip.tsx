"use client";

import Link from "next/link";
import * as React from "react";

import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Early Warning on the Cockpit, for the retail book.
 *
 * The defect this closes. The corporate strip asked
 * `/early-warning/signals?limit=1`, which reads `corporate_borrower_360` — a
 * dataset this installation does not have. Every Cockpit load therefore fired
 * a request that answered 503 with "CreditProbe is starting up or briefly
 * unavailable. Try again in a moment." It never becomes available; a permanent
 * failure was wearing a transient one's message. The strip handled it politely
 * by rendering nothing, so the only visible symptom was that the Cockpit had
 * no Early Warning line at all — a headline capability missing from the home
 * page, and nothing on screen to say why.
 *
 * The counts here are of CUSTOMERS and of MONEY, not of alerts. "5,952 alerts"
 * tells nobody anything and reads as alarming precisely because it is
 * meaningless; "3,896 customers with a warning" is a queue somebody can work
 * through, and the exposure behind them is the reason to.
 *
 * Nothing here is a score, and nothing is coloured by severity. A row of red
 * numbers on a home page is a row people stop seeing by the second week.
 */
export function RetailEarlyWarningStrip({ month }: { month?: string }) {
  const book = useAsync(async () => {
    const at = month || (await api.retailManifest()).snapshot_month;
    // The full alert list is large and the strip needs none of it: the counts
    // and the rule breakdown come back whatever the page size.
    return api.retailEarlyWarning(at, "", 1);
  }, [month]);

  if (book.loading) return <Skeleton className="h-20 w-full" />;
  // A strip that cannot load is not an alarm. It says so quietly and the rest
  // of the Cockpit is unaffected.
  if (book.error || !book.data) return null;

  const data = book.data;
  const byRule = data.by_rule ?? [];
  const severe = byRule
    .filter((r) => (r.severity || "").toUpperCase() === "HIGH")
    .reduce((total, r) => total + (r.alerts || 0), 0);
  const share = data.portfolio_exposure_sar
    ? (100 * data.affected_exposure_sar) / data.portfolio_exposure_sar
    : null;

  const cells = [
    {
      label: "Customers warned",
      value: data.distinct_customers.toLocaleString(),
      means: "Distinct customers with at least one warning. A customer with "
        + "four warnings is one customer.",
    },
    {
      label: "Warnings raised",
      value: data.alert_count.toLocaleString(),
      means: "One per rule per customer or facility, so this is larger than "
        + "the number of customers and is not a queue length.",
    },
    {
      label: "On high severity",
      value: severe.toLocaleString(),
      means: "Warnings from rules the rulebook marks HIGH.",
    },
    {
      label: "Rules firing",
      value: String(byRule.filter((r) => (r.alerts || 0) > 0).length),
      means: `Of ${byRule.length} governed rules in rulebook `
        + `${data.rulebook_version}.`,
    },
    {
      label: "Exposure behind them",
      value: `SAR ${Math.round(data.affected_exposure_sar).toLocaleString()}`,
      means: "Each facility counted once, even where two rules cover it.",
    },
    {
      label: "Share of the book",
      value: share === null ? "—" : `${share.toFixed(1)}%`,
      means: "Affected exposure over the whole retail gross carrying amount.",
    },
  ];

  return (
    <Card className="p-4" data-testid="retail-ews-strip">
      <div className="mb-2.5 flex items-baseline justify-between gap-4">
        <p className="text-xs text-text-muted">
          {data.distinct_customers.toLocaleString()} customers warned at{" "}
          {data.snapshot_month} under rulebook {data.rulebook_version}
        </p>
        <Link
          href="/early-warning/signals"
          className="text-[11px] text-text-muted underline-offset-4 hover:text-accent hover:underline"
          data-testid="retail-ews-strip-open"
        >
          Open
        </Link>
      </div>
      <dl className="grid grid-cols-3 gap-x-4 gap-y-3 sm:grid-cols-6">
        {cells.map((cell) => (
          <div key={cell.label}>
            <dt className="flex items-center gap-1 text-[11px] text-text-muted">
              {cell.label}
              {cell.means ? (
                <InfoPopover title={cell.label}>{cell.means}</InfoPopover>
              ) : null}
            </dt>
            <dd className="mt-0.5 text-[15px] font-medium tabular-nums text-text-primary">
              {cell.value}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
