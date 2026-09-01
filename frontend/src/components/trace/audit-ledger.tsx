"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { STATUS, statusOf } from "@/components/trace/status";
import { LAYER_LABELS, LAYER_LANE } from "@/components/trace/graph";
import { MetadataLabel, TechnicalLabel } from "@/components/typography";
import type { TraceGraph, TraceNode } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Trace as a ledger: every step, in order, as rows.
 *
 * Why this mode exists
 * --------------------
 * Two reasons, and the second is the important one.
 *
 * An auditor does not want a picture. They want a list they can read top to
 * bottom, check off, and quote a line from in a memo. A graph is the right
 * shape for understanding how something was produced and the wrong shape for
 * recording that you checked it.
 *
 * And a spatial view is not usable by everyone. A map that can only be read by
 * seeing it excludes anybody using a screen reader, and "there is also a
 * diagram" is not an answer. This mode carries the **complete** lineage — every
 * node, its stage, its status, what it did, what it read and what it produced —
 * in a plain table with real headers, real row semantics and full keyboard
 * navigation. Nothing is available in the other modes that is missing here.
 *
 * That is why it is a first-class mode with its own button rather than an
 * accessibility fallback hidden behind a preference.
 */
export function AuditLedger({
  graph,
  selected,
  onSelect,
  className,
}: {
  graph: TraceGraph;
  selected?: string | null;
  onSelect?: (nodeId: string) => void;
  className?: string;
}) {
  const rows = React.useMemo(() => order(graph), [graph]);

  return (
    <div className={cn("min-w-0 overflow-x-auto", className)}>
      <table className="w-full border-collapse text-body">
        <caption className="sr-only">
          Every step of this analysis in execution order, with its stage, status
          and what it produced.
        </caption>
        <thead>
          <tr className="border-b border-border-strong">
            <Th className="w-10 text-right">#</Th>
            <Th className="w-32">Stage</Th>
            <Th>Step</Th>
            <Th className="w-28">Status</Th>
            <Th className="w-20 text-right">Rows in</Th>
            <Th className="w-20 text-right">Rows out</Th>
            <Th className="w-20 text-right">Time</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((node, index) => {
            const status = statusOf(node);
            const presentation = STATUS[status];
            const isSelected = selected === node.id;
            return (
              <tr
                key={node.id}
                onClick={() => onSelect?.(node.id)}
                tabIndex={onSelect ? 0 : undefined}
                onKeyDown={(e) => {
                  if (onSelect && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    onSelect(node.id);
                  }
                }}
                aria-current={isSelected ? "true" : undefined}
                className={cn(
                  "border-b border-border/60 last:border-0",
                  "transition-colors duration-[--duration-instant]",
                  onSelect && "cursor-pointer outline-none",
                  isSelected ? "bg-surface-selected" : "hover:bg-surface-interactive",
                  "focus-visible:ring-2 focus-visible:ring-accent/40",
                )}
              >
                <Td className="text-right font-mono text-text-muted tabular-nums">
                  {index + 1}
                </Td>
                <Td>
                  <TechnicalLabel>
                    {LAYER_LABELS[LAYER_LANE[node.type] ?? LAYER_LABELS.length - 1]}
                  </TechnicalLabel>
                </Td>
                <Td>
                  <div className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate font-medium text-text-primary">
                      {node.label}
                    </span>
                    {node.dataset && (
                      <MetadataLabel className="shrink-0">{node.dataset}</MetadataLabel>
                    )}
                  </div>
                  {/* The reason a status is not "passed" belongs on the row,
                      not one click away. An auditor scanning for problems
                      should not have to open each one to learn what it says. */}
                  {(node.error || node.warnings?.length > 0) && (
                    <p className={cn("mt-0.5 text-[0.6875rem]", presentation.text)}>
                      {node.error ?? node.warnings[0]}
                    </p>
                  )}
                </Td>
                <Td>
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded px-1.5 py-0.5",
                      presentation.surface,
                      presentation.text,
                    )}
                  >
                    <span aria-hidden className="text-[0.625rem] font-bold">
                      {presentation.mark}
                    </span>
                    <span className="text-[0.6875rem] font-medium">
                      {presentation.label}
                    </span>
                  </span>
                </Td>
                <Td className="text-right font-mono text-text-secondary tabular-nums">
                  {node.rows_in?.toLocaleString("en-US") ?? "—"}
                </Td>
                <Td className="text-right font-mono text-text-secondary tabular-nums">
                  {node.rows_out?.toLocaleString("en-US") ?? "—"}
                </Td>
                <Td className="text-right font-mono text-text-muted tabular-nums">
                  {node.duration_ms != null ? `${node.duration_ms}ms` : "—"}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {onSelect && (
        <p className="mt-2 flex items-center gap-1 px-1 text-[0.6875rem] text-text-muted">
          <ChevronRight className="size-3" aria-hidden />
          Select a row to see everything the engine stamped for that step.
        </p>
      )}
    </div>
  );
}

function Th({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        "h-8 px-3 text-left align-bottom text-[0.6875rem] font-semibold text-text-muted",
        className,
      )}
      {...props}
    />
  );
}

function Td({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-3 py-1.5 align-top", className)} {...props} />;
}

/**
 * Execution order.
 *
 * The graph's own `layers` are a topological grouping, which is the order the
 * engine COULD have run things in. A ledger has to say the order it DID: lane
 * first, because the lanes are the governance stages in the order they happen,
 * then the order the nodes arrived within a lane.
 */
function order(graph: TraceGraph): TraceNode[] {
  const position = new Map(graph.nodes.map((n, i) => [n.id, i]));
  return [...graph.nodes].sort((a, b) => {
    const laneA = LAYER_LANE[a.type] ?? LAYER_LABELS.length - 1;
    const laneB = LAYER_LANE[b.type] ?? LAYER_LABELS.length - 1;
    if (laneA !== laneB) return laneA - laneB;
    return (position.get(a.id) ?? 0) - (position.get(b.id) ?? 0);
  });
}
