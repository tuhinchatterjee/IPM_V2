"use client";

import * as React from "react";

import { Empty, SectionCard } from "@/components/planner/parts";
import { Badge } from "@/components/ui/badge";
import { api, type PlannerUpdateRequest } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Who has been asked for an update, and whether they came back.
 *
 * The project manager's actual question is not "what did we send" — it is
 * "who is not replying". So the list is ordered oldest first, the state is a
 * column rather than a filter somebody has to discover, and the reply is
 * shown beside the request rather than left in the timeline for them to hunt
 * through.
 *
 * Nothing here sends anything. The requests were raised by the monitor from
 * the deterministic rules; this is the record of them.
 */

const STATE_LABEL: Record<string, string> = {
  sent: "waiting",
  answered: "answered",
  cancelled: "no longer needed",
};

function since(iso: string | null): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function UpdateRequests({
  projectId,
  title = "Update requests",
}: {
  projectId?: number;
  title?: string;
}) {
  const [state, setState] = React.useState("all");
  const rows = useAsync(
    () => (projectId
      ? api.planner.projectRequests(projectId, state)
      : api.planner.requests(state)),
    [projectId, state],
  );

  const requests: PlannerUpdateRequest[] = rows.data?.requests ?? [];
  const waiting = requests.filter((r) => r.state === "sent").length;

  return (
    <SectionCard
      title={title}
      action={
        <div className="flex items-center gap-2">
          {waiting > 0 && (
            <Badge variant="warning">{waiting} waiting</Badge>
          )}
          <select
            value={state}
            onChange={(e) => setState(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs"
            aria-label="Filter requests"
          >
            <option value="all">Everything</option>
            <option value="sent">Waiting</option>
            <option value="answered">Answered</option>
          </select>
        </div>
      }
    >
      {rows.loading ? (
        <p className="px-4 py-3 text-sm text-text-muted">Reading…</p>
      ) : requests.length === 0 ? (
        <Empty>
          Nobody has been asked for an update. CreditProbe asks when somebody
          has gone quiet on something that is late, blocked or nearly due —
          not merely because a date is coming.
        </Empty>
      ) : (
        <ul className="divide-y divide-border">
          {requests.map((row) => (
            <li key={row.id} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-[11px] text-text-muted">
                  {row.task_code}
                </span>
                <span className="text-sm text-text-primary">
                  {row.task_title}
                </span>
                {!projectId && (
                  <span className="text-xs text-text-muted">
                    {row.project_code}
                  </span>
                )}
                <Badge
                  variant={row.state === "sent"
                    ? "warning"
                    : row.state === "answered" ? "positive" : "default"}
                  className="ml-auto"
                >
                  {STATE_LABEL[row.state] ?? row.state}
                </Badge>
              </div>
              <p className="mt-1 text-sm text-text-secondary">{row.reason}</p>
              <p className="mt-1 text-xs text-text-muted">
                {row.person?.name ?? "somebody"} · asked {since(row.sent_at)}
                {row.responded_at && ` · replied ${since(row.responded_at)}`}
              </p>
              {row.response && (
                <div className="mt-2 rounded-md border border-border bg-surface-sunken px-3 py-2">
                  <p className="text-sm text-text-primary">
                    {row.response.narrative || "No narrative."}
                  </p>
                  <p className="mt-1 text-xs text-text-muted">
                    {row.response.new_percent !== null &&
                      `now ${row.response.new_percent}%`}
                    {row.response.blocker && ` · blocked: ${row.response.blocker}`}
                    {row.response.next_step && ` · next: ${row.response.next_step}`}
                  </p>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
