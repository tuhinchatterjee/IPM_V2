"use client";

import * as React from "react";
import Link from "next/link";
import { ArrowLeft, Download, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/playbook/status/chips";
import type { PbDashboard } from "@/lib/api";
import { approvalBadge, shortDate } from "@/lib/intelligence";

/**
 * The dashboard header. §7.
 *
 * Title, then the facts that decide how this document is read — what it is,
 * whose committee, which period, which meeting, whose it is, which version —
 * and on the right the one thing a reader came to find out: whether it can be
 * approved, and how much is in the way.
 *
 * Committee fields appear only on committee documents. §21 is explicit that
 * they must not be put on generic ones, and a "Meeting date: —" on a working
 * methodology paper invents an obligation that does not exist.
 */
export function DashboardHeader({
  dashboard,
  workspaceId,
  onBack,
  onCheckForUpdates,
  checking,
  latestDownload,
}: {
  dashboard: PbDashboard;
  workspaceId: number;
  onBack: () => void;
  onCheckForUpdates: () => void;
  checking: boolean;
  latestDownload: { href: string; format: string } | null;
}) {
  const badge = approvalBadge(dashboard);

  const facts = [
    dashboard.document_type_label,
    dashboard.committee_report ? dashboard.committee_name : "",
    dashboard.reporting_period,
    dashboard.version ? `Version ${dashboard.version}` : "",
  ].filter(Boolean);

  return (
    <header className="space-y-3" data-testid="playbook-dashboard-header">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold leading-tight text-text-primary">
            {dashboard.title}
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            {facts.join(" · ")}
          </p>
          <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-text-muted">
            {dashboard.committee_report && dashboard.meeting_date && (
              <div className="flex gap-1.5">
                <dt>Meeting</dt>
                <dd className="text-text-secondary">
                  {shortDate(dashboard.meeting_date)}
                </dd>
              </div>
            )}
            {dashboard.owner && (
              <div className="flex gap-1.5">
                <dt>Owner</dt>
                <dd className="text-text-secondary">{dashboard.owner}</dd>
              </div>
            )}
            {dashboard.readiness.computed_at && (
              <div className="flex gap-1.5">
                <dt>Last updated</dt>
                <dd className="text-text-secondary">
                  {shortDate(dashboard.readiness.computed_at)}
                </dd>
              </div>
            )}
          </dl>
        </div>

        <div className="flex flex-col items-end gap-2">
          <StatusChip tone={badge.tone} className="px-3 py-1 text-xs">
            {badge.label}
          </StatusChip>
          {badge.detail && (
            <p className="text-[11px] text-text-muted">{badge.detail}</p>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBack}
          data-testid="playbook-back-to-chat">
          <ArrowLeft className="size-3.5" aria-hidden />
          Back to chat
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onCheckForUpdates}
          disabled={checking}
          data-testid="playbook-check-for-updates"
        >
          <RefreshCw className={"size-3.5" + (checking ? " animate-spin" : "")}
            aria-hidden />
          {checking ? "Checking…" : "Check for updates"}
        </Button>
        {latestDownload ? (
          <a
            href={latestDownload.href}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            data-testid="playbook-download-latest"
          >
            <Download className="size-3.5" aria-hidden />
            Download latest ({latestDownload.format.toUpperCase()})
          </a>
        ) : (
          <span className="text-[11px] text-text-muted">
            No file has been generated yet
          </span>
        )}
        <Link
          href={`/playbook/${workspaceId}`}
          className="ml-auto text-xs text-text-muted hover:text-text-secondary hover:underline"
        >
          Open the conversation
        </Link>
      </div>
    </header>
  );
}
