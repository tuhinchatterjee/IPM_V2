"use client";

import * as React from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  type Edge,
  type Node,
  type NodeProps,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import {
  ChevronsLeftRight,
  ChevronsRightLeft,
  Maximize2,
  Minus,
  Plus,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { TraceGraph } from "@/lib/api";

import {
  NODE_HEIGHT,
  NODE_WIDTH,
  ancestorsOf,
  descendantsOf,
  layoutGraph,
  stepsIn,
} from "./graph";
import { presentationFor } from "./node-presentation";

import "@xyflow/react/dist/base.css";

/**
 * The Analytical Reasoning Map.
 *
 * This is not a log view and not a flowchart of a process. It is a map of how
 * one answer was arrived at, and it is built to be read the way a credit officer
 * reads a paper: left to right, question to finding, with the boundary between
 * judgement and arithmetic visible without being explained.
 *
 * Three decisions carry most of that:
 *
 *  - **Interpretive and governed steps are drawn differently.** Everything the
 *    model touched is drawn in the interpretive colour with a dashed rule;
 *    everything the engine computed is solid and governed. That boundary is the
 *    product's central claim, so it is the strongest visual distinction on the
 *    canvas.
 *  - **Selecting a node dims everything that is not part of its lineage.** Not
 *    a highlight added on top, a de-emphasis of the rest: the question "what fed
 *    this, and what does it feed" is answered by looking, not by tracing lines.
 *  - **The layout never moves.** Positions come from the recorded dependency
 *    layers, so the same trace looks the same in every session and can be
 *    pointed at in a meeting.
 */

/** Above this many recorded steps, the map opens collapsed. */
/**
 * When a map opens collapsed.
 *
 * The measure that matters is not how many nodes there are but how WIDE the
 * layout is: the canvas has to fit the deepest chain, and a chain of fourteen
 * columns lands at a zoom where the labels are decoration. A single-analysis
 * investigation now records the full lineage — domain, dataset, variables,
 * filters, transformations, aggregations, function, result — so depth, not
 * count, is what makes a map unreadable.
 *
 * Nine columns is about the widest that stays legible in the standard canvas.
 */
const COLLAPSE_COLUMNS = 9;

export interface MapHighlight {
  /** Nodes a proposed or applied change affects — drawn as changed. */
  changed?: string[];
  /** Nodes that must re-derive because something upstream changed. */
  downstream?: string[];
  /** Nodes newly present in this version. */
  added?: string[];
}

interface NodeData extends Record<string, unknown> {
  label: string;
  type: string;
  status: string;
  rowsOut: number | null;
  durationMs: number | null;
  stepTitle: string;
  step: number | null;
  collapsed: boolean;
  containedCount: number;
  warning: boolean;
  failed: boolean;
  dim: boolean;
  lineage: "none" | "upstream" | "downstream" | "self";
  mark: "none" | "changed" | "downstream" | "added";
  onToggleStep?: (step: number) => void;
}

const MARK_LABEL: Record<string, string> = {
  changed: "Changes",
  downstream: "Re-derives",
  added: "New",
};

function TraceCard({ data, selected }: NodeProps<Node<NodeData>>) {
  const presentation = presentationFor(data.type);
  const Icon = presentation.icon;
  const governed = presentation.governed;

  return (
    <div
      style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
      className={cn(
        "group relative rounded-lg border bg-surface px-3 py-2.5 text-left transition-[opacity,box-shadow,border-color] duration-200",
        governed ? "border-border" : "border-dashed border-border-strong",
        selected && "border-accent shadow-[0_0_0_2px_var(--ipm-accent-muted)]",
        data.mark === "changed" && "border-warning",
        data.mark === "added" && "border-positive",
        data.dim && "opacity-25",
        data.failed && "border-negative",
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-[var(--ipm-trace-edge)]" />
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-[var(--ipm-trace-edge)]" />

      {/* The rule down the left edge is the governed / interpretive tell. */}
      <span
        aria-hidden
        className="absolute inset-y-2 left-0 w-[3px] rounded-full"
        style={{
          backgroundColor: governed
            ? "var(--ipm-trace-governed)"
            : "var(--ipm-trace-interpretive)",
          opacity: governed ? 1 : 0.65,
        }}
      />

      <div className="flex items-center gap-1.5 pl-1.5">
        <Icon
          className="size-3 shrink-0"
          style={{
            color: governed ? "var(--ipm-trace-governed)" : "var(--ipm-trace-interpretive)",
          }}
          aria-hidden
        />
        <span className="truncate text-[9px] font-semibold uppercase tracking-[0.11em] text-text-muted">
          {presentation.label}
        </span>
        {data.status === "cached" && (
          <span
            className="ml-auto shrink-0 rounded-sm bg-surface-sunken px-1 text-[9px] text-text-muted"
            title="Reused — nothing about this step changed, so it was not re-run"
          >
            reused
          </span>
        )}
        {data.mark !== "none" && (
          <span
            className={cn(
              "ml-auto shrink-0 rounded-sm px-1 text-[9px] font-medium",
              data.mark === "changed" && "bg-warning-muted text-warning",
              data.mark === "downstream" && "bg-accent-muted text-accent",
              data.mark === "added" && "bg-positive-muted text-positive",
            )}
          >
            {MARK_LABEL[data.mark]}
          </span>
        )}
      </div>

      <p className="mt-1 line-clamp-2 pl-1.5 text-[12px] leading-snug text-text-primary">
        {data.label}
      </p>

      <div className="mt-1 flex items-center gap-2 pl-1.5 text-[10px] text-text-muted tabular">
        {data.rowsOut !== null && <span>{data.rowsOut.toLocaleString()} rows</span>}
        {data.durationMs !== null && data.durationMs > 0 && <span>{data.durationMs}ms</span>}
        {data.collapsed && <span>{data.containedCount} steps</span>}
        {data.warning && <TriangleAlert className="size-2.5 text-warning" aria-hidden />}
      </div>

      {data.step !== null && data.onToggleStep && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            data.onToggleStep?.(data.step as number);
          }}
          title={data.collapsed ? "Expand this analysis" : "Collapse this analysis"}
          className="absolute -right-1.5 -top-1.5 hidden size-5 items-center justify-center rounded-full border border-border bg-surface-raised text-text-muted shadow-sm transition-colors hover:text-accent group-hover:flex"
        >
          {data.collapsed ? (
            <ChevronsLeftRight className="size-2.5" aria-hidden />
          ) : (
            <ChevronsRightLeft className="size-2.5" aria-hidden />
          )}
        </button>
      )}
    </div>
  );
}

const nodeTypes = { trace: TraceCard };

interface ReasoningMapProps {
  graph: TraceGraph;
  selected: string | null;
  onSelect: (id: string | null) => void;
  highlight?: MapHighlight;
  className?: string;
  height?: number;
}

function MapCanvas({ graph, selected, onSelect, highlight, height = 520 }: ReasoningMapProps) {
  const steps = React.useMemo(() => stepsIn(graph), [graph]);

  // A map wider than the canvas can show legibly opens collapsed to one node
  // per analysis, which is the level a reader actually starts at, and expands
  // from there. The width is measured from the graph's own layers rather than
  // guessed from the node count.
  const [collapsed, setCollapsed] = React.useState<Set<number>>(
    () =>
      new Set(
        (graph.layers?.length ?? 0) > COLLAPSE_COLUMNS ? steps.map((s) => s.step) : [],
      ),
  );

  const toggleStep = React.useCallback((step: number) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(step)) next.delete(step);
      else next.add(step);
      return next;
    });
  }, []);

  const layout = React.useMemo(() => layoutGraph(graph, collapsed), [graph, collapsed]);

  // The selected node may be inside a collapsed analysis. Lineage and dimming
  // are computed against the node actually on the canvas, so selecting a step
  // and then collapsing its analysis keeps the highlight rather than losing it.
  const selectedPlacedId = React.useMemo(() => {
    if (!selected) return null;
    const hit = layout.nodes.find(
      (p) => p.id === selected || p.containedIds.includes(selected),
    );
    return hit?.id ?? null;
  }, [layout.nodes, selected]);

  const lineage = React.useMemo(() => {
    if (!selectedPlacedId) return null;
    return {
      up: ancestorsOf(layout.edges, selectedPlacedId),
      down: descendantsOf(layout.edges, selectedPlacedId),
    };
  }, [layout.edges, selectedPlacedId]);

  const changed = React.useMemo(() => new Set(highlight?.changed ?? []), [highlight]);
  const downstream = React.useMemo(() => new Set(highlight?.downstream ?? []), [highlight]);
  const added = React.useMemo(() => new Set(highlight?.added ?? []), [highlight]);
  const hasHighlight = changed.size > 0 || downstream.size > 0 || added.size > 0;

  const nodes: Node<NodeData>[] = React.useMemo(
    () =>
      layout.nodes.map((placed) => {
        const inLineage =
          !lineage ||
          placed.id === selectedPlacedId ||
          lineage.up.has(placed.id) ||
          lineage.down.has(placed.id);
        // A collapsed stand-in inherits the marks of everything inside it, so a
        // change is never hidden by collapsing the step that contains it.
        const ids = placed.containedIds;
        const mark: NodeData["mark"] = ids.some((id) => added.has(id))
          ? "added"
          : ids.some((id) => changed.has(id))
            ? "changed"
            : ids.some((id) => downstream.has(id)) || downstream.has(placed.id)
              ? "downstream"
              : "none";
        return {
          id: placed.id,
          type: "trace",
          position: { x: placed.x, y: placed.y },
          selected: placed.id === selectedPlacedId,
          draggable: false,
          connectable: false,
          data: {
            label: placed.node.label,
            type: placed.node.type,
            status: placed.node.status,
            rowsOut: placed.node.rows_out,
            durationMs: placed.node.duration_ms,
            stepTitle: placed.stepTitle,
            step: placed.step,
            collapsed: placed.collapsed,
            containedCount: placed.containedIds.length,
            warning: placed.node.warnings.length > 0,
            failed: placed.node.status === "failed",
            dim: !inLineage || (hasHighlight && mark === "none" && !selectedPlacedId),
            lineage: !lineage
              ? "none"
              : placed.id === selectedPlacedId
                ? "self"
                : lineage.up.has(placed.id)
                  ? "upstream"
                  : lineage.down.has(placed.id)
                    ? "downstream"
                    : "none",
            mark,
            onToggleStep: placed.step !== null ? toggleStep : undefined,
          },
        };
      }),
    [layout.nodes, lineage, selectedPlacedId, changed, downstream, added, hasHighlight, toggleStep],
  );

  const edges: Edge[] = React.useMemo(
    () =>
      layout.edges.map((edge) => {
        const active =
          !lineage ||
          ((lineage.up.has(edge.source) || edge.source === selectedPlacedId) &&
            (lineage.up.has(edge.target) || edge.target === selectedPlacedId)) ||
          ((lineage.down.has(edge.target) || edge.target === selectedPlacedId) &&
            (lineage.down.has(edge.source) || edge.source === selectedPlacedId));
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "smoothstep",
          animated: false,
          style: {
            stroke: active && lineage ? "var(--ipm-accent)" : "var(--ipm-trace-edge)",
            strokeWidth: active && lineage ? 1.6 : 1,
            opacity: lineage && !active ? 0.15 : 1,
          },
        };
      }),
    [layout.edges, lineage, selectedPlacedId],
  );

  return (
    <div style={{ height }} className="relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, clicked) => {
          const placed = layout.nodes.find((p) => p.id === clicked.id);
          // A collapsed analysis has no recorded node of its own, so selecting
          // it selects the engine-function step it stands for — the inspector
          // then shows real evidence rather than an empty panel.
          const target = placed?.collapsed
            ? (placed.containedIds.find(
                (id) => graph.nodes.find((n) => n.id === id)?.type === "ENGINE_FUNCTION",
              ) ?? placed.containedIds[placed.containedIds.length - 1])
            : clicked.id;
          onSelect(placed?.id === selectedPlacedId ? null : target);
        }}
        onPaneClick={() => onSelect(null)}
        fitView
        fitViewOptions={{ padding: 0.18, maxZoom: 1 }}
        minZoom={0.2}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        // The canvas is inside a scrolling page, so the wheel pans rather than
        // zooming — trapping the page scroll on a diagram is a hostile default.
        zoomOnScroll={false}
        panOnScroll
        panOnDrag
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={22}
          size={1}
          color="var(--ipm-border)"
        />
        <MapControls steps={steps} collapsed={collapsed} setCollapsed={setCollapsed} />
        <Panel position="bottom-left">
          <Legend />
        </Panel>
      </ReactFlow>
    </div>
  );
}

function MapControls({
  steps,
  collapsed,
  setCollapsed,
}: {
  steps: { step: number; title: string; nodes: number }[];
  collapsed: Set<number>;
  setCollapsed: (next: Set<number>) => void;
}) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const allCollapsed = steps.length > 0 && steps.every((s) => collapsed.has(s.step));

  return (
    <>
    <Panel position="top-right" className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-0.5 rounded-md border border-border bg-surface-raised p-0.5 shadow-sm">
        <IconButton title="Zoom out" onClick={() => zoomOut({ duration: 180 })}>
          <Minus className="size-3.5" aria-hidden />
        </IconButton>
        <IconButton title="Zoom in" onClick={() => zoomIn({ duration: 180 })}>
          <Plus className="size-3.5" aria-hidden />
        </IconButton>
        <IconButton
          title="Fit the whole map on screen"
          onClick={() => fitView({ padding: 0.18, duration: 220, maxZoom: 1 })}
        >
          <Maximize2 className="size-3.5" aria-hidden />
        </IconButton>
        {steps.length > 0 && (
          <IconButton
            title={allCollapsed ? "Expand every analysis" : "Collapse every analysis"}
            onClick={() =>
              setCollapsed(allCollapsed ? new Set() : new Set(steps.map((s) => s.step)))
            }
          >
            {allCollapsed ? (
              <ChevronsLeftRight className="size-3.5" aria-hidden />
            ) : (
              <ChevronsRightLeft className="size-3.5" aria-hidden />
            )}
          </IconButton>
        )}
      </div>

    </Panel>
    {steps.length > 1 && (
      <Panel position="top-left">
        <div className="max-w-56 rounded-md border border-border bg-surface-raised p-1 shadow-sm">
          <p className="px-1.5 pb-1 pt-0.5 text-[9px] font-semibold uppercase tracking-[0.11em] text-text-muted">
            Analyses
          </p>
          {steps.map((s) => (
            <button
              key={s.step}
              type="button"
              onClick={() => {
                const next = new Set(collapsed);
                if (next.has(s.step)) next.delete(s.step);
                else next.add(s.step);
                setCollapsed(next);
              }}
              className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[11px] text-text-secondary transition-colors hover:bg-surface-hover"
            >
              {collapsed.has(s.step) ? (
                <ChevronsLeftRight className="size-2.5 shrink-0 text-text-muted" aria-hidden />
              ) : (
                <ChevronsRightLeft className="size-2.5 shrink-0 text-text-muted" aria-hidden />
              )}
              <span className="truncate">{s.title}</span>
              <span className="ml-auto shrink-0 text-[10px] text-text-muted tabular">
                {s.nodes}
              </span>
            </button>
          ))}
        </div>
      </Panel>
    )}
    </>
  );
}

function IconButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
    >
      {children}
    </button>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border border-border bg-surface-raised/90 px-2.5 py-1.5 text-[10px] text-text-muted backdrop-blur">
      <span className="flex items-center gap-1.5">
        <span
          className="h-3 w-[3px] rounded-full"
          style={{ backgroundColor: "var(--ipm-trace-governed)" }}
          aria-hidden
        />
        Governed — deterministic engine
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="h-3 w-[3px] rounded-full opacity-65"
          style={{ backgroundColor: "var(--ipm-trace-interpretive)" }}
          aria-hidden
        />
        Interpretive — judgement, never arithmetic
      </span>
      <span className="flex items-center gap-1">
        <Sparkles className="size-2.5" aria-hidden />
        Select a step to see what feeds it
      </span>
    </div>
  );
}

export function ReasoningMap(props: ReasoningMapProps) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-surface-sunken",
        props.className,
      )}
    >
      <ReactFlowProvider>
        <MapCanvas {...props} />
      </ReactFlowProvider>
    </div>
  );
}
