"use client";

import * as React from "react";

import { STATUS, statusOf, worst, type TraceStatus } from "@/components/trace/status";
import { LAYER_LABELS, LAYER_LANE } from "@/components/trace/graph";
import { TechnicalLabel } from "@/components/typography";
import type { TraceGraph, TraceNode } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Where the problems are, in one line.
 *
 * The question a Trace is opened with is almost never "show me all forty
 * steps". It is **"did anything go wrong, and where"** — and a graph, however
 * well drawn, makes a reader hunt for the answer. This answers it before they
 * look at the graph at all:
 *
 *   Request ✓  Understanding ✓  Data ✓  Join !  Calculation ✓  Invariant ✕  …
 *
 * Clicking a stage selects its first troubled node, so the map is a way in
 * rather than only a summary. A stage with nothing in it is drawn faintly and
 * is not clickable: an empty Conversation band on a first question is a fact,
 * not a gap.
 */
export function HealthMap({
  graph,
  onFocus,
  selected,
  className,
}: {
  graph: TraceGraph;
  /** Called with a node id when a stage is chosen. */
  onFocus?: (nodeId: string) => void;
  selected?: string | null;
  className?: string;
}) {
  const stages = React.useMemo(() => summarise(graph), [graph]);
  const troubled = stages.filter((s) => s.nodes.length && STATUS[s.status].attention);

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {stages.map((stage) => {
          const presentation = STATUS[stage.status];
          const empty = stage.nodes.length === 0;
          const holdsSelection =
            selected != null && stage.nodes.some((n) => n.id === selected);
          return (
            <button
              key={stage.lane}
              type="button"
              disabled={empty || !onFocus}
              onClick={() => onFocus?.(firstOfInterest(stage.nodes).id)}
              title={
                empty
                  ? `${stage.label}: nothing in this stage`
                  : `${stage.label}: ${presentation.label} — ${stage.nodes.length} ${
                      stage.nodes.length === 1 ? "step" : "steps"
                    }`
              }
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md border px-2 py-1",
                "transition-colors duration-[--duration-instant]",
                empty
                  ? "cursor-default border-transparent opacity-40"
                  : cn(
                      presentation.border,
                      holdsSelection ? "bg-surface-selected" : "bg-surface",
                      "hover:bg-surface-hover",
                    ),
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "grid size-4 shrink-0 place-items-center rounded-sm text-[0.625rem] font-bold",
                  empty ? "text-text-muted" : cn(presentation.surface, presentation.text),
                )}
              >
                {empty ? "·" : presentation.mark}
              </span>
              <TechnicalLabel className="whitespace-nowrap">
                {stage.label}
              </TechnicalLabel>
              {/* The word, not only the mark. Screen readers and monochrome
                  printouts both need it, and it costs one small span. */}
              <span className="sr-only">
                {empty ? "nothing in this stage" : presentation.label}
              </span>
            </button>
          );
        })}
      </div>

      {troubled.length > 0 && (
        <p className="mt-1.5 text-[0.6875rem] text-text-secondary">
          {troubled.length === 1
            ? `One stage needs attention: ${troubled[0].label.toLowerCase()}.`
            : `${troubled.length} stages need attention: ${troubled
                .map((s) => s.label.toLowerCase())
                .join(", ")}.`}
        </p>
      )}
    </div>
  );
}

interface Stage {
  lane: number;
  label: string;
  status: TraceStatus;
  nodes: TraceNode[];
}

function summarise(graph: TraceGraph): Stage[] {
  const byLane = new Map<number, TraceNode[]>();
  for (const node of graph.nodes) {
    const lane = LAYER_LANE[node.type] ?? LAYER_LABELS.length - 1;
    const list = byLane.get(lane) ?? [];
    list.push(node);
    byLane.set(lane, list);
  }
  return LAYER_LABELS.map((label, lane) => {
    const nodes = byLane.get(lane) ?? [];
    return { lane, label, nodes, status: worst(nodes.map(statusOf)) };
  });
}

/** The node a reader should be taken to: the worst one, else the first. */
function firstOfInterest(nodes: TraceNode[]): TraceNode {
  return (
    nodes.find((n) => STATUS[statusOf(n)].attention) ?? nodes[0]
  );
}
