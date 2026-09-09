"use client";

import * as React from "react";

import { Empty, SectionCard, when } from "@/components/planner/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, ApiError, type PlannerAgentActivityItem } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * What the Agentic AI has actually done on this project. §21.
 *
 * Written the way a project manager would say it — "Reminded Priya Raman that
 * S-702 is due on Friday", "Escalated to the project manager because the data
 * extraction has been overdue for four days" — and not the way a scheduler
 * logs it. Nobody outside this codebase wants to read `due_3` or a
 * fingerprint, and a page that shows them is a page that gets ignored, which
 * is how an agent quietly stops being trusted.
 *
 * Every line comes from a record of something that was SENT. This is not a
 * projection of what the rules would do; it is the chase history.
 */
const KINDS = [
  { id: "", label: "Everything" },
  { id: "reminder", label: "Reminders" },
  { id: "escalation", label: "Escalations" },
  { id: "request", label: "Update requests" },
  { id: "response", label: "Replies" },
  { id: "health", label: "Health changes" },
];

export function AgentActivity({
  projectId,
  mayRun,
}: {
  projectId: number;
  mayRun: boolean;
}) {
  const [kind, setKind] = React.useState("");
  const [ran, setRan] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const activity = useAsync(
    () => api.planner.agentActivity(projectId, kind, 200),
    [projectId, kind],
  );

  const items = activity.data?.items ?? [];

  const run = async () => {
    setBusy(true);
    setRan("");
    try {
      const result = await api.planner.runAgent(projectId);
      setRan(
        result.sent === 0 && result.suppressed === 0
          ? "The agent found nothing that needed anybody."
          : `The agent sent ${result.sent} ` +
            `${result.sent === 1 ? "message" : "messages"} and suppressed ` +
            `${result.suppressed} it had already sent.`,
      );
      activity.reload();
    } catch (failure) {
      setRan(failure instanceof ApiError
        ? failure.message : "The agent could not run.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard
      title="Agent activity"
      action={
        <div className="flex items-center gap-2">
          <Badge variant="outline">{activity.data?.count ?? 0}</Badge>
          {mayRun && (
            <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => void run()}>
              Run the agent now
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-wrap gap-1.5 border-b border-border px-4 py-2.5">
        {KINDS.map((option) => (
          <button
            key={option.id || "all"}
            type="button"
            aria-pressed={kind === option.id}
            onClick={() => setKind(option.id)}
            className={cn(
              "rounded-md border px-2 py-1 text-xs transition",
              kind === option.id
                ? "border-accent bg-accent-muted text-text-primary"
                : "border-border text-text-secondary hover:border-accent",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      {ran && (
        <p role="status" className="border-b border-border px-4 py-2 text-sm text-text-secondary">
          {ran}
        </p>
      )}

      {activity.loading && <Empty>Reading what the agent has done…</Empty>}
      {activity.error && (
        <p className="px-4 py-4 text-sm text-negative">{activity.error}</p>
      )}
      {activity.data && items.length === 0 && (
        <Empty>
          The agent has not needed to say anything on this project yet.
        </Empty>
      )}
      {items.length > 0 && (
        <ul className="divide-y divide-border">
          {items.map((item, index) => (
            <ActivityLine key={index} item={item} />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function ActivityLine({ item }: { item: PlannerAgentActivityItem }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm text-text-primary">{item.headline}</span>
        {item.entity_code && (
          <span className="font-mono text-[11px] text-text-muted">
            {item.entity_code}
          </span>
        )}
        {item.state === "answered" && (
          <Badge variant="outline">answered</Badge>
        )}
      </div>
      {item.detail && (
        <p className="mt-0.5 text-xs text-text-secondary">{item.detail}</p>
      )}
      <p className="mt-0.5 text-xs text-text-muted">{when(item.at)}</p>
    </li>
  );
}
