"use client";

import * as React from "react";
import { Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AgentSchedule } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The SCHEDULES tab. §31.
 *
 * What ships enabled, and why it matters
 * ---------------------------------------
 * Exactly one: the review that fires when a new portfolio period is published,
 * because that is the demonstration's own flow. Everything else arrives
 * disabled. A product whose first act is to start running daily jobs nobody
 * asked for is one whose operator learns to distrust it.
 *
 * Enabling is administrator-only (§32 is explicit that policy changes are
 * role-protected, and turning on a job that scans the whole book nightly is a
 * policy change). Running one NOW is a data steward's — it produces a draft,
 * costs a scan, and changes nothing.
 */
export function Schedules() {
  const [reload, setReload] = React.useState(0);
  const [loaded, setLoaded] = React.useState<{
    key: number;
    schedules: AgentSchedule[];
    error: string;
  } | null>(null);
  const [busy, setBusy] = React.useState<number | null>(null);
  const [note, setNote] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await api.agentSchedules();
        if (live)
          setLoaded({ key: reload, schedules: found.schedules, error: "" });
      } catch (error) {
        if (live)
          setLoaded({
            key: reload,
            schedules: [],
            error:
              error instanceof Error
                ? error.message
                : "Schedules could not be read.",
          });
      }
    })();
    return () => {
      live = false;
    };
  }, [reload]);

  const settled = loaded && loaded.key === reload ? loaded : null;
  if (settled === null) return <Skeleton className="h-64 w-full" />;
  if (settled.error)
    return <p className="text-sm text-negative">{settled.error}</p>;

  const act = async (id: number, run: () => Promise<{ message?: string }>) => {
    setBusy(id);
    try {
      const found = await run();
      setNote(found.message ?? "");
      setReload((n) => n + 1);
    } catch (error) {
      setNote(error instanceof Error ? error.message : "That did not work.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-3">
      {note && <p className="text-xs text-text-secondary">{note}</p>}

      {settled.schedules.map((schedule) => (
        <Card key={schedule.id} className="p-4" data-testid="agent-schedule">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-text-primary">
                  {schedule.name}
                </span>
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
                    schedule.enabled
                      ? "bg-positive-muted text-positive"
                      : "bg-surface-sunken text-text-muted",
                  )}
                >
                  {schedule.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-text-secondary">
                {schedule.description}
              </p>
              <p className="mt-1 flex flex-wrap items-center gap-x-3 text-[11px] text-text-muted">
                <span>{schedule.trigger_label}</span>
                <span>Scope: {schedule.scope}</span>
                <span>
                  {schedule.agents.map((a) => a.name).join(" · ") ||
                    "no agents named"}
                </span>
                <span>
                  {schedule.approval_policy === "draft_only"
                    ? "Produces drafts only"
                    : schedule.approval_policy}
                </span>
                {schedule.last_run_at && (
                  <span>Last run {schedule.last_run_at.slice(0, 10)}</span>
                )}
              </p>
            </div>

            <div className="flex shrink-0 items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                disabled={busy === schedule.id}
                onClick={() =>
                  void act(schedule.id, () => api.runSchedule(schedule.id))
                }
                title="Queue this review now"
              >
                <Play aria-hidden />
                Run now
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy === schedule.id}
                onClick={() =>
                  void act(schedule.id, async () => {
                    await api.setScheduleEnabled(schedule.id, !schedule.enabled);
                    return {
                      message: `${schedule.name} is now ${
                        schedule.enabled ? "disabled" : "enabled"
                      }.`,
                    };
                  })
                }
              >
                {schedule.enabled ? "Disable" : "Enable"}
              </Button>
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}
