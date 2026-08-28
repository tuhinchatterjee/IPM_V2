"use client";

import * as React from "react";
import { Download } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type ExportRecord } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Who has downloaded this analysis, and what they got.
 *
 * §41 asks for the export activity to appear in the Analysis audit history,
 * and the reason is not tidiness. A workbook leaves the product — it lands on
 * a laptop and gets forwarded — so "who has a copy of this, and which version
 * of it" is a question somebody eventually has to answer, and answering it
 * from a database console is not answering it.
 *
 * Refusals are shown alongside downloads. A log of successes cannot answer
 * "who tried", which is the question an access review actually asks.
 *
 * Visible to whoever may download the full pack: knowing who else holds a copy
 * of an analysis sits inside the same trust boundary as holding one. The
 * endpoint enforces that; a reader without it sees nothing rather than an
 * error, because a permissions message where a panel would be is noise.
 */
export function ExportHistory({
  runId,
  className,
}: {
  runId: number;
  className?: string;
}) {
  const [loaded, setLoaded] = React.useState<{
    runId: number;
    rows: ExportRecord[] | null;
  } | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .exportHistory(runId)
      .then((found) => {
        if (live) setLoaded({ runId, rows: found.exports });
      })
      // A refusal is the ordinary case for an Analyst looking at somebody
      // else's run, and it is not an error worth a panel.
      .catch(() => {
        if (live) setLoaded({ runId, rows: null });
      });
    return () => {
      live = false;
    };
  }, [runId]);

  const settled = loaded && loaded.runId === runId ? loaded : null;
  if (settled === null) return <Skeleton className={cn("h-20 w-full", className)} />;
  if (settled.rows === null) return null;

  return (
    <Card className={cn("p-4", className)}>
      <div className="mb-2.5 flex items-center gap-2">
        <Download className="size-3.5 shrink-0 text-text-muted" aria-hidden />
        <h2 className="text-[11px] font-medium uppercase tracking-[0.11em] text-text-muted">
          Downloads
        </h2>
        <span className="text-[11px] text-text-muted">
          {settled.rows.length === 0
            ? "none yet"
            : `${settled.rows.length} recorded`}
        </span>
      </div>

      {settled.rows.length === 0 ? (
        <p className="text-xs text-text-muted">
          Nobody has exported this analysis. Every download and every refusal is
          recorded here, with the Trace version it carried.
        </p>
      ) : (
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full border-collapse text-[11px]">
            <caption className="sr-only">
              Every attempt to download this analysis, most recent first.
            </caption>
            <thead>
              <tr className="border-b border-border">
                <Th>When</Th>
                <Th>Who</Th>
                <Th>Role</Th>
                <Th>Workbook</Th>
                <Th className="text-right">Trace</Th>
                <Th className="text-right">Rows</Th>
                <Th>Outcome</Th>
              </tr>
            </thead>
            <tbody>
              {settled.rows.map((row) => (
                <tr key={row.id} className="border-b border-border/60">
                  <Td className="mono whitespace-nowrap">
                    {row.at ? row.at.slice(0, 16).replace("T", " ") : "—"}
                  </Td>
                  <Td>{row.user_name || "not signed in"}</Td>
                  <Td className="text-text-muted">{row.role || "—"}</Td>
                  <Td>{row.kind_label}</Td>
                  <Td className="mono text-right">{row.trace_version ?? "—"}</Td>
                  <Td className="mono text-right">
                    {row.row_count === null ? "—" : row.row_count.toLocaleString()}
                  </Td>
                  <Td>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 font-medium uppercase tracking-[0.08em]",
                        row.status === "allowed" && "bg-positive-muted text-positive",
                        row.status === "denied" && "bg-warning-muted text-warning",
                        row.status === "failed" && "bg-negative-muted text-negative",
                      )}
                      title={row.reason || undefined}
                    >
                      {row.status}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function Th({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={cn(
        "px-2 py-1.5 text-left font-medium uppercase tracking-[0.08em] text-text-muted",
        className,
      )}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <td className={cn("px-2 py-1.5 align-top text-text-secondary", className)}>
      {children}
    </td>
  );
}
