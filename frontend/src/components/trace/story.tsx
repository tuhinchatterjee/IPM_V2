"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { STATUS, statusOf } from "@/components/trace/status";
import { stagesOf, type Stage } from "@/components/trace/stages";
import { nodeTitle, nodeSubtitle } from "@/components/trace/node-presentation";
import { Card } from "@/components/ui/card";
import type { TraceGraph } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The Trace, read as a story before it is read as a graph.
 *
 * Why this is the default now
 * ---------------------------
 * The Trace opened on the lineage graph: forty rectangles of equal weight,
 * every one of them accurate, and none of them legible without a click. A CRO
 * asked to review an answer would open it, look at it, and close it — which is
 * the same as not having a Trace at all.
 *
 * Six stages, each one sentence, each with a status and a number. A reader
 * should be able to say what the analysis did, and whether anything went
 * wrong, without opening anything. The graph is still there, one click away,
 * for the reader who needs structure rather than narrative.
 *
 * Progressive disclosure, not less information
 * -------------------------------------------
 * Nothing is removed. Every node is inside the stage it belongs to, and every
 * stage opens. What changed is what a reader is asked to look at FIRST.
 */
export function TraceStory({
  graph,
  selected,
  onSelect,
  className,
}: {
  graph: TraceGraph;
  selected: string | null;
  onSelect: (id: string | null) => void;
  className?: string;
}) {
  const stages = React.useMemo(() => stagesOf(graph), [graph]);

  // A stage containing the selected node opens itself, so following an issue
  // from the strip above lands on the node rather than on a closed heading.
  const containing = React.useMemo(
    () => stages.find((s) => s.nodes.some((n) => n.id === selected))?.id ?? null,
    [stages, selected],
  );

  if (stages.length === 0) {
    return (
      <Card className={cn("p-5 text-sm text-text-muted", className)}>
        This run recorded no steps.
      </Card>
    );
  }

  return (
    <ol className={cn("space-y-2", className)}>
      {stages.map((stage, index) => (
        <StageRow
          key={stage.id}
          stage={stage}
          index={index + 1}
          open={containing === stage.id || stage.issues > 0}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
    </ol>
  );
}

/**
 * One stage: a number, a word, a sentence, a status and a count.
 *
 * Stages carrying an issue open themselves. A reader who has to expand six
 * headings to find the one thing that went wrong has been given a filing
 * cabinet rather than an answer.
 */
function StageRow({
  stage,
  index,
  open,
  selected,
  onSelect,
}: {
  stage: Stage;
  index: number;
  open: boolean;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const tone = STATUS[stage.status];

  return (
    <li>
      <details open={open} className="group">
        <summary
          className={cn(
            "flex cursor-pointer list-none items-start gap-3 rounded-lg border px-4 py-3 transition-colors",
            "border-border bg-surface hover:border-border-strong",
            stage.issues > 0 && tone.border,
          )}
        >
          <ChevronRight
            className="mt-1 size-3.5 shrink-0 text-text-muted transition-transform group-open:rotate-90"
            aria-hidden
          />
          <span
            aria-hidden
            className="mt-0.5 w-4 shrink-0 text-right font-mono text-[11px] text-text-muted"
          >
            {index}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-text-primary">
                {stage.title}
              </span>
              {/* Word, mark and colour together. Roughly one man in twelve
                  cannot separate the amber from the red, so the status is
                  never carried by colour alone. */}
              <span className={cn("flex items-center gap-1 text-[11px] font-medium", tone.text)}>
                <span aria-hidden>{tone.mark}</span>
                {tone.label}
              </span>
              <span className="font-mono text-[11px] text-text-muted">
                {stage.count.toLocaleString("en-US")} {stage.counts}
              </span>
              {stage.issues > 0 && (
                <span className={cn("font-mono text-[11px]", tone.text)}>
                  {stage.issues} to look at
                </span>
              )}
            </span>
            <span className="mt-1 block text-sm leading-relaxed text-text-secondary">
              {stage.summary}
            </span>
          </span>
        </summary>

        <ul className="mt-1 space-y-px border-l border-border pl-4 ml-[1.85rem]">
          {stage.nodes.map((node) => {
            const status = STATUS[statusOf(node)];
            const active = node.id === selected;
            return (
              <li key={node.id}>
                <button
                  type="button"
                  onClick={() => onSelect(active ? null : node.id)}
                  aria-pressed={active}
                  className={cn(
                    "flex w-full items-baseline gap-2.5 rounded px-2.5 py-1.5 text-left transition-colors",
                    active ? "bg-surface-raised" : "hover:bg-surface-sunken",
                  )}
                >
                  <span aria-hidden className={cn("text-[11px]", status.text)}>
                    {status.mark}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-text-primary">
                      {nodeTitle(node)}
                    </span>
                    {nodeSubtitle(node) && (
                      <span className="block truncate text-[11px] text-text-muted">
                        {nodeSubtitle(node)}
                      </span>
                    )}
                  </span>
                  {typeof node.rows_out === "number" && (
                    <span className="shrink-0 font-mono text-[11px] text-text-muted">
                      {node.rows_out.toLocaleString("en-US")}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </details>
    </li>
  );
}
