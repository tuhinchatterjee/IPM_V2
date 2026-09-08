"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { ExternalLink, Sparkles, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EarlyWarningV2BorrowerDetail } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { borrower360Href } from "@/lib/borrower-link";
import { fromEwsBorrower, linkBack } from "@/lib/return-context";
import { SignalTree } from "@/components/early-warning/signal-tree";

/** Mirrors backend.orchestration.domain_lock.EARLY_WARNING. */
const EARLY_WARNING_DOMAIN = "early_warning";

/**
 * The dedicated Early Warning borrower journey (EWS Screens slide 8).
 *
 * Clicking a high-risk borrower opens THIS panel, on the same page, rather
 * than abandoning the Early Warning investigation into the generic,
 * EWS-unaware Borrower 360 screen. "Open full Borrower 360" stays one click
 * away for anyone who wants the wider account view — it is available, not
 * the default.
 */
export function BorrowerDrilldown({
  customerId,
  onClose,
}: {
  customerId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [investigating, setInvestigating] = React.useState(false);
  const detail = useAsync<EarlyWarningV2BorrowerDetail>(
    () => api.earlyWarningV2Borrower(customerId),
    [customerId],
  );
  const tree = useAsync(() => api.earlyWarningV2BorrowerTree(customerId), [customerId]);

  const latest = detail.data?.latest as
    | { customer_name?: string; ews_score?: number; ews_band?: string; segment?: string }
    | undefined;
  const name = latest?.customer_name ?? customerId;

  // A dedicated Investigation, locked to the Early Warning domain from its
  // very first turn (backend.orchestration.domain_lock) — not the generic
  // Cockpit ask box, which carries no domain at all. "Investigate" is how a
  // reader leaves this screen for a chat thread; it does not abandon the
  // Early Warning journey, it opens the next stage of it.
  const investigate = async () => {
    setInvestigating(true);
    try {
      const started = await api.startThread({
        question: `Investigate ${name}'s Early Warning position.`,
        context: { domain: EARLY_WARNING_DOMAIN },
      });
      router.push(linkBack(`/investigations/${started.thread.id}`, fromEwsBorrower(customerId, name)));
    } finally {
      setInvestigating(false);
    }
  };

  return (
    <Card className="space-y-4 border-accent/40 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-text-primary">
            {latest?.customer_name ?? customerId}
          </p>
          <p className="text-xs text-text-muted">{customerId}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href={borrower360Href(customerId)}>
              <ExternalLink aria-hidden />
              Open full Borrower 360
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={investigate}
            disabled={investigating}
          >
            <Sparkles aria-hidden />
            {investigating ? "Opening…" : "Investigate"}
          </Button>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X aria-hidden />
          </Button>
        </div>
      </div>

      {(detail.loading || tree.loading) && <Skeleton className="h-48 w-full" />}
      {(detail.error || tree.error) && (
        <p className="text-sm text-negative">{detail.error ?? tree.error}</p>
      )}

      {detail.data && (
        <div className="flex flex-wrap gap-4 text-xs text-text-secondary">
          <span>
            EWS <span className="font-medium text-text-primary">{latest?.ews_score?.toFixed(1)}</span>{" "}
            <Badge variant="outline">{latest?.ews_band}</Badge>
          </span>
          {latest?.segment && <span>Segment {latest.segment}</span>}
          <span>{detail.data.history.length}-month history</span>
          <span>{detail.data.fired_signals.length} signals fired this period</span>
        </div>
      )}

      {tree.data ? (
        <SignalTree tree={tree.data} />
      ) : (
        !tree.loading &&
        !tree.error && (
          <EmptyState title="No layer detail available for this borrower this period." />
        )
      )}
    </Card>
  );
}
