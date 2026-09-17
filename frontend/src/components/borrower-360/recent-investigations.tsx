"use client";

import * as React from "react";
import { Pin } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { api, type SavedInvestigationView } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The cards below the chatbox. U07.
 *
 * DRAFTS ARE SHOWN, ON PURPOSE
 *
 * Every import writes one of these before the reader presses anything, because
 * the failure it prevents is losing a list by closing a tab. Hiding the
 * unnamed ones would recreate exactly that: the list would exist and the
 * reader would have no way back to it.
 *
 * THE RATE ON A CARD
 *
 * An observed default rate is shown with its numerator, its denominator and
 * its window, or it is not shown at all. Where the outcome window has not
 * completed the card reads "Not yet observed" — a fabricated rate on a card
 * somebody glances at is worse than no figure, because it will be quoted.
 *
 * Everything shown is SYNTHETIC demonstration data.
 */
export function RecentInvestigations({
  onOpen,
  limit = 8,
}: {
  onOpen: (snapshotId: string, savedId: string) => void;
  limit?: number;
}) {
  const [rows, setRows] = React.useState<SavedInvestigationView[] | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .retailRecentInvestigations(limit)
      .then((found) => live && setRows(found.rows))
      .catch(() => live && setRows([]));
    return () => {
      live = false;
    };
  }, [limit]);

  if (!rows?.length) return null;

  return (
    <div className="space-y-2" data-testid="recent-investigations">
      <h4 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
        Recent investigations
      </h4>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => (
          <Card
            key={`${row.saved_id}-${row.version}`}
            className={cn(
              "cursor-pointer transition hover:border-accent/50",
              row.pinned && "border-accent/40",
            )}
            onClick={() => onOpen(row.snapshot_id, row.saved_id)}
          >
            <CardContent className="space-y-1 pt-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs font-medium text-text-primary">
                  {row.title || row.issue || row.case_id}
                </p>
                {row.pinned ? (
                  <Pin className="size-3 shrink-0 text-accent" aria-hidden />
                ) : null}
              </div>
              <p className="text-[11px] text-text-muted">{row.segment}</p>
              <dl className="space-y-0.5 text-[11px]">
                <Line label="Customers" value={row.customer_count.toLocaleString("en-GB")} />
                <Line
                  label="Observed default rate"
                  value={
                    row.odr?.state === "observed"
                      ? `${row.odr.label} (${row.odr.numerator}/${row.odr.denominator}, ${row.odr.window})`
                      : "Not yet observed"
                  }
                />
                <Line label="Noticed" value={short(row.noticed_at)} />
                <Line
                  label="Saved"
                  value={
                    row.state === "saved" ? short(row.saved_at) : "draft, not named"
                  }
                />
                <Line label="Source step" value={row.source_step} />
              </dl>
              {row.notes_preview ? (
                <p className="line-clamp-2 text-[11px] italic text-text-secondary">
                  {row.notes_preview}
                </p>
              ) : null}
              {row.version > 1 ? (
                <p className="text-[10px] text-text-muted">
                  version {row.version} — earlier versions are still readable
                </p>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-text-muted">{label}</dt>
      <dd className="text-right text-text-primary">{value}</dd>
    </div>
  );
}

function short(value: string | null) {
  if (!value) return "—";
  return value.slice(0, 16).replace("T", " ");
}
