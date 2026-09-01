"use client";

import * as React from "react";
import { ChevronDown, ShieldCheck } from "lucide-react";

import { Card } from "@/components/ui/card";
import { api, type AgentRunDetail } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Assurance } from "./assurance";

/**
 * The agentic layers of a Trace. §26, §27.
 *
 * §26 asks Trace to carry the coordination as well as the calculation:
 * trigger, officer selection, orchestration plan, delegation, task, tool call,
 * data and method, result, handoff, challenge, validation, approval,
 * synthesis, action, final answer.
 *
 * §27 asks Story mode to summarise it without requiring node clicks — six
 * stages, each a paragraph. Both are here: the story reads first, and the task
 * table under it is the same information at node granularity.
 *
 * Absent by default, and that is correct
 * ---------------------------------------
 * Most analyses are one person's question, answered by one specialist. There
 * is no coordination to show, and this component renders nothing rather than
 * an empty section headed "Agentic" — which would imply the product does this
 * to every analysis and merely has nothing to say about this one.
 *
 * §26's last line: "Do not expose hidden chain-of-thought." Every string here
 * is a structured field the run recorded — a purpose, a finding, a validation
 * state, a tool id. There is no path from a prompt to this component.
 */
export function AgenticTrace({
  analysisRunId,
  className,
}: {
  analysisRunId: number;
  className?: string;
}) {
  const [loaded, setLoaded] = React.useState<{
    runId: number;
    found: (AgentRunDetail & { found: boolean; story: Stage[] }) | null;
  } | null>(null);
  const [openTasks, setOpenTasks] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = (await api.agenticForAnalysis(analysisRunId)) as
          AgentRunDetail & { found: boolean; story: Stage[] };
        if (live)
          setLoaded({ runId: analysisRunId, found: found.found ? found : null });
      } catch {
        // No coordination behind this analysis, or not ours to read. Either
        // way the Trace is unaffected and the section simply does not appear.
        if (live) setLoaded({ runId: analysisRunId, found: null });
      }
    })();
    return () => {
      live = false;
    };
  }, [analysisRunId]);

  const settled = loaded && loaded.runId === analysisRunId ? loaded : null;
  const run = settled?.found;
  if (!run) return null;

  return (
    <Card className={cn("space-y-3 p-4", className)} data-testid="agentic-trace">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="meta text-text-muted">Coordination</h2>
        <span className="text-[11px] text-text-muted">
          {run.officer_title} · run{" "}
          <span className="mono">{run.id}</span>
          {run.duration_ms ? ` · ${(run.duration_ms / 1000).toFixed(1)}s` : ""}
        </span>
      </div>

      {/* §27 — the story, readable without clicking a node. */}
      <ol className="space-y-2.5">
        {(run.story ?? []).map((stage) => (
          <li key={stage.stage} className="flex gap-3">
            <span className="mono w-[5.5rem] shrink-0 pt-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
              {stage.stage}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs font-medium text-text-primary">
                {stage.title}
              </span>
              {stage.body && (
                <span className="mt-0.5 block whitespace-pre-line text-xs leading-relaxed text-text-secondary">
                  {stage.body}
                </span>
              )}
              {stage.detail && (
                <span className="mt-0.5 block text-[11px] text-text-muted">
                  {stage.detail}
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-3">
        <Assurance
          assurance={
            run.assurance_detail as unknown as Parameters<
              typeof Assurance
            >[0]["assurance"]
          }
        />
        {run.approvals?.length ? (
          <span className="inline-flex items-center gap-1 text-[11px] text-text-muted">
            <ShieldCheck className="size-3" aria-hidden />
            {run.approvals.length} approval gate
            {run.approvals.length === 1 ? "" : "s"} —{" "}
            {run.approvals.filter((a) => a.status === "approved").length}{" "}
            approved
          </span>
        ) : null}
      </div>

      {/* §26 at node granularity: every delegated task, its tool, its result,
          its validation and its approval state. */}
      {run.tasks?.length ? (
        <div>
          <button
            type="button"
            onClick={() => setOpenTasks((now) => !now)}
            aria-expanded={openTasks}
            className="flex items-center gap-1 text-[11px] text-accent hover:underline"
          >
            {openTasks ? "Hide" : "Show"} the {run.tasks.length} delegated task
            {run.tasks.length === 1 ? "" : "s"}
            <ChevronDown
              className={cn(
                "size-3 transition-transform",
                openTasks && "rotate-180",
              )}
              aria-hidden
            />
          </button>

          {openTasks && (
            <div className="mt-2 min-w-0 overflow-x-auto">
              <table className="w-full border-collapse text-[11px]">
                <thead>
                  <tr className="border-b border-border">
                    <Th>Layer</Th>
                    <Th>Agent</Th>
                    <Th>Purpose</Th>
                    <Th>Tool</Th>
                    <Th>Status</Th>
                    <Th>Validation</Th>
                    <Th>Approval</Th>
                    <Th className="text-right">ms</Th>
                    <Th>Analysis</Th>
                  </tr>
                </thead>
                <tbody>
                  {run.tasks.map((task) => (
                    <tr
                      key={task.task_key}
                      className="border-b border-border/60"
                      data-testid="agentic-task"
                    >
                      <Td className="mono">{task.layer}</Td>
                      <Td>{task.agent_name}</Td>
                      <Td className="max-w-[18rem]">{task.purpose}</Td>
                      <Td className="mono text-text-muted">{task.tool || "—"}</Td>
                      <Td
                        className={cn(
                          task.status === "complete" && "text-positive",
                          task.status === "failed" && "text-negative",
                          task.status === "blocked" && "text-warning",
                        )}
                        title={task.error || ""}
                      >
                        {task.status}
                      </Td>
                      <Td>{task.validation_state.replace(/_/g, " ")}</Td>
                      <Td>{task.approval_state.replace(/_/g, " ")}</Td>
                      <Td className="mono text-right">
                        {task.duration_ms ?? "—"}
                      </Td>
                      <Td className="mono">{task.analysis_run_id ?? "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}

      <p className="text-[10px] text-text-muted">
        Registry {run.config_fingerprint} · build {run.build_sha.slice(0, 8)} ·{" "}
        {run.usage || "no usage recorded"}
      </p>
    </Card>
  );
}

interface Stage {
  stage: string;
  title: string;
  body: string;
  detail: string;
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
  title,
}: {
  children?: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <td
      title={title}
      className={cn("px-2 py-1.5 align-top text-text-secondary", className)}
    >
      {children}
    </td>
  );
}
