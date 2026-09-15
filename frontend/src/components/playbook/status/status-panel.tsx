"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronRight, Gauge } from "lucide-react";

import { Card } from "@/components/ui/card";
import { StatusChip } from "@/components/playbook/status/chips";
import type { PbDashboard } from "@/lib/api";
import { approvalBadge, compactRows, hasStatus } from "@/lib/intelligence";

/**
 * The compact Document Status panel that sits beside the conversation. §5.
 *
 * Its job is to orient somebody without taking them out of the chat, so it is
 * deliberately short: the two percentages, the counts that would change what
 * you do next, and one button. Everything else is a click away.
 *
 * A workspace with nothing to say about itself gets no panel at all. A column
 * of noughts beside an empty conversation is worse than no column — it
 * describes a document that does not exist yet as though it were failing.
 */
export function DocumentStatusPanel({
  workspaceId,
  dashboard,
  onOpen,
}: {
  workspaceId: number;
  dashboard: PbDashboard | null;
  /** Called before navigating, so the thread can save what it is holding. */
  onOpen?: () => void;
}) {
  if (!hasStatus(dashboard) || !dashboard) return null;

  const rows = compactRows(dashboard);
  const badge = approvalBadge(dashboard);

  return (
    <Card className="p-3" data-testid="playbook-status-panel">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
            Document status
          </h2>
          <p className="mt-1 truncate text-sm font-medium text-text-primary"
            title={dashboard.title}>
            {dashboard.title}
          </p>
          <p className="mt-0.5 text-[11px] text-text-muted">
            {[
              dashboard.document_type_label,
              dashboard.committee_report && dashboard.committee_name,
              dashboard.reporting_period,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <StatusChip tone={badge.tone}>{badge.label}</StatusChip>
      </div>

      <dl className="mt-3 space-y-1.5">
        {rows.map((row) => (
          <div key={row.label}
            className="flex items-baseline justify-between gap-3">
            <dt className="text-[11px] text-text-muted">{row.label}</dt>
            <dd
              className={
                "text-xs font-medium tabular-nums " +
                (row.tone === "red"
                  ? "text-negative"
                  : row.tone === "amber"
                    ? "text-warning"
                    : row.tone === "green"
                      ? "text-positive"
                      : "text-text-primary")
              }
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>

      {badge.detail && (
        <p className="mt-2 text-[11px] text-text-muted">{badge.detail}</p>
      )}

      <Link
        href={`/playbook/${workspaceId}/status`}
        onClick={onOpen}
        data-testid="playbook-know-the-status"
        className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-accent/40 bg-accent-muted px-3 py-2 text-xs font-semibold text-accent hover:bg-accent/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <Gauge className="size-3.5" aria-hidden />
        Know the status
        <span className="tabular-nums">
          · {dashboard.readiness.readiness_pct}% ready
        </span>
        <ChevronRight className="size-3.5" aria-hidden />
      </Link>
    </Card>
  );
}
