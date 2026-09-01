"use client";

import Link from "next/link";
import * as React from "react";
import { GitBranch, RotateCcw, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AgentRunSummary, type AgentWorker } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The RUNS tab. §30, and the worker health §18 asks for.
 *
 * Every run: what triggered it, which officer, which specialists, its scope,
 * its status, when it started, how long it took, how many tasks, what it cost,
 * and links to the result and the Trace.
 *
 * Cancel and retry
 * ----------------
 * §30 asks for both, and both are narrower than they look. Cancel sets a flag
 * the worker notices at its next checkpoint — it does not kill a process, so a
 * cancelled run still shows what it completed. Retry re-enqueues a PROACTIVE
 * review only: re-running somebody's question on their behalf would put an
 * answer they did not ask for into a thread they are reading.
 */
export function Runs() {
  const [reload, setReload] = React.useState(0);
  const [loaded, setLoaded] = React.useState<{
    key: number;
    runs: AgentRunSummary[];
    workers: { workers: AgentWorker[]; queue: Record<string, number>; alive: number } | null;
    error: string;
  } | null>(null);
  const [busy, setBusy] = React.useState<number | null>(null);
  const [note, setNote] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const [runs, workers] = await Promise.all([
          api.agenticRuns({ limit: 40 }),
          api.agentWorkers(),
        ]);
        if (live)
          setLoaded({ key: reload, runs: runs.runs, workers, error: "" });
      } catch (error) {
        if (live)
          setLoaded({
            key: reload,
            runs: [],
            workers: null,
            error:
              error instanceof Error ? error.message : "Runs could not be read.",
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
    <div className="space-y-4">
      <WorkerHealth found={settled.workers} />

      {note && <p className="text-xs text-text-secondary">{note}</p>}

      {settled.runs.length === 0 ? (
        <Card className="p-6 text-center text-sm text-text-secondary">
          No agentic run has been recorded yet.
          <span className="mt-1 block text-xs text-text-muted">
            A run appears here for every question asked and every proactive
            review, whether it succeeded or not.
          </span>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full border-collapse text-[11px]">
              <thead>
                <tr className="border-b border-border">
                  <Th>Run</Th>
                  <Th>Trigger</Th>
                  <Th>Officer</Th>
                  <Th>Specialists</Th>
                  <Th>Scope</Th>
                  <Th>Status</Th>
                  <Th className="text-right">Tasks</Th>
                  <Th className="text-right">Duration</Th>
                  <Th>Usage</Th>
                  <Th>Result</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {settled.runs.map((run) => (
                  <tr key={run.id} className="border-b border-border/60" data-testid="agent-run">
                    <Td className="mono">{run.id}</Td>
                    <Td>{run.trigger_label}</Td>
                    <Td>{run.officer_title || "—"}</Td>
                    <Td className="text-text-muted">
                      {run.specialists.length || "—"}
                    </Td>
                    <Td className="max-w-[16rem] truncate">
                      {run.question || run.period || "—"}
                    </Td>
                    <Td>
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 font-medium uppercase tracking-[0.08em]",
                          run.status === "complete" && "bg-positive-muted text-positive",
                          run.status === "failed" && "bg-negative-muted text-negative",
                          run.status === "cancelled" && "bg-surface-sunken text-text-muted",
                          !["complete", "failed", "cancelled"].includes(run.status) &&
                            "bg-warning-muted text-warning",
                        )}
                        title={run.failure || run.stage_label}
                      >
                        {run.stage_label || run.status}
                      </span>
                    </Td>
                    <Td className="mono text-right">{run.task_count || "—"}</Td>
                    <Td className="mono text-right">
                      {run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : "—"}
                    </Td>
                    <Td className="text-text-muted">{run.usage || "—"}</Td>
                    <Td>
                      {run.analysis_run_id ? (
                        <Link
                          href={`/trace/${run.analysis_run_id}`}
                          className="inline-flex items-center gap-1 text-accent hover:underline"
                        >
                          <GitBranch className="size-3" aria-hidden />
                          Trace
                        </Link>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </Td>
                    <Td>
                      <span className="flex gap-1">
                        {["queued", "running", "calculating", "validating",
                          "coordinating", "scoping", "understanding",
                          "selecting_data", "interpreting"].includes(run.status) && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy === run.id}
                            onClick={() =>
                              void act(run.id, () => api.cancelAgenticRun(run.id))
                            }
                            title="Stop this run at its next checkpoint"
                          >
                            <Square aria-hidden />
                          </Button>
                        )}
                        {run.status === "failed" && run.trigger !== "user_question" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={busy === run.id}
                            onClick={() =>
                              void act(run.id, () => api.retryAgenticRun(run.id))
                            }
                            title="Queue this review again"
                          >
                            <RotateCcw aria-hidden />
                          </Button>
                        )}
                      </span>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

/**
 * §18 asks the worker to expose health. An operator's first question when a
 * review has not appeared is "is anything actually running", and a queue depth
 * with no worker beside it cannot answer it.
 */
function WorkerHealth({
  found,
}: {
  found: { workers: AgentWorker[]; queue: Record<string, number>; alive: number } | null;
}) {
  if (!found) return null;
  const queued = found.queue.queued ?? 0;
  const running = found.queue.running ?? 0;
  const dead = found.queue.dead_letter ?? 0;

  return (
    <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-3">
      <Fact
        label="Workers alive"
        value={String(found.alive)}
        tone={found.alive === 0 && (queued || running) ? "negative" : "normal"}
      />
      <Fact label="Queued" value={String(queued)} />
      <Fact label="Running" value={String(running)} />
      <Fact
        label="Dead letter"
        value={String(dead)}
        tone={dead > 0 ? "warning" : "normal"}
      />
      {found.alive === 0 && (queued > 0 || running > 0) && (
        <p className="text-[11px] text-negative">
          Work is queued and no worker is answering. Start the agent-worker
          service; the jobs are durable and will be picked up.
        </p>
      )}
    </Card>
  );
}

function Fact({
  label,
  value,
  tone = "normal",
}: {
  label: string;
  value: string;
  tone?: "normal" | "warning" | "negative";
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
        {label}
      </p>
      <p
        className={cn(
          "mono text-sm tabular",
          tone === "negative" && "text-negative",
          tone === "warning" && "text-warning",
          tone === "normal" && "text-text-primary",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Th({
  children,
  className,
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap px-2 py-1.5 text-left font-medium uppercase tracking-[0.08em] text-text-muted",
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
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <td className={cn("px-2 py-1.5 align-top text-text-secondary", className)}>
      {children}
    </td>
  );
}
