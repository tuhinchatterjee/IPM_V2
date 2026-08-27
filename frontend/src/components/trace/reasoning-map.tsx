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
  ChevronDown,
  ChevronRight,
  ChevronsLeftRight,
  ChevronsRightLeft,
  Crosshair,
  Maximize2,
  Minus,
  Plus,
  Search,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { TraceGraph, TraceNode } from "@/lib/api";

import {
  CLUSTER_ORDER,
  type Cluster,
  type ClusterId,
  clusterOf,
  clustersOf,
  defaultCollapsed,
  issuesIn,
  search as searchNodes,
} from "./clusters";
import {
  HEADER_HEIGHT,
  KIND_LABEL,
  NODE_HEIGHT,
  NODE_WIDTH,
  SUMMARY_HEIGHT,
  SUMMARY_WIDTH,
  ancestorsOf,
  descendantsOf,
  groupIdFor,
  layoutClusters,
  summaryIdFor,
  type PlacedEdge,
} from "./cluster-layout";
import { presentationFor } from "./node-presentation";
import { STATUS, statusOf } from "./status";

import "@xyflow/react/dist/base.css";

/**
 * The Analytical Reasoning Map — the detailed Lineage view.
 *
 * This is not a log and not a flowchart of a process. It is a map of how one
 * answer was arrived at, built to be read the way a credit officer reads a
 * paper: question to finding, with the boundary between judgement and
 * arithmetic visible without being explained.
 *
 * What changed, and why
 * ---------------------
 * The map used to be forty equally-weighted rectangles in coloured bands. A
 * band is a hint about position; it is not something a reader can collapse,
 * focus, isolate, or roll an issue up into. So everything in the trace was on
 * screen and almost none of it was legible without clicking nearly every node —
 * "how was this produced?" answered with a diagram.
 *
 * Now every node lives inside one of eight governed clusters, and a cluster is
 * a real subgraph: it has a boundary, a summary you can read without opening
 * it, a health its members roll up into, and edges that survive when its
 * internals are hidden. A reviewer sees the shape first and opens what they
 * want.
 *
 * Four decisions carry the rest:
 *
 *  - **Interpretive and governed steps are drawn differently.** Everything the
 *    model touched is dashed and interpretive; everything the engine computed
 *    is solid and governed. That boundary is the product's central claim, so it
 *    is the strongest visual distinction on the canvas.
 *  - **Selecting anything dims what is not in its lineage.** Not a highlight on
 *    top — a de-emphasis of the rest, so "what fed this, and what does it feed"
 *    is answered by looking.
 *  - **Status is never colour alone.** Every cluster header and every node
 *    carries a word and a mark as well as a colour.
 *  - **Opening a cluster does not move the others.** Clusters stack in a fixed
 *    order and each grows downward from its own top edge, so a reader never has
 *    to re-find their place after a click.
 */

export interface MapHighlight {
  /** Nodes a proposed or applied change affects — drawn as changed. */
  changed?: string[];
  /** Nodes that must re-derive because something upstream changed. */
  downstream?: string[];
  /** Nodes newly present in this version. */
  added?: string[];
}

type Lineage = "none" | "upstream" | "downstream" | "self";

interface NodeData extends Record<string, unknown> {
  label: string;
  type: string;
  status: string;
  rowsOut: number | null;
  durationMs: number | null;
  warning: boolean;
  failed: boolean;
  dim: boolean;
  lineage: Lineage;
  mark: "none" | "changed" | "downstream" | "added";
  found: boolean;
}

const MARK_LABEL: Record<string, string> = {
  changed: "Changes",
  downstream: "Re-derives",
  added: "New",
};

/* -------------------------------------------------------------- one node */

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
        data.found && "border-accent shadow-[0_0_0_2px_var(--ipm-accent-muted)]",
        data.mark === "changed" && "border-warning",
        data.mark === "added" && "border-positive",
        data.dim && "opacity-20",
        data.failed && "border-negative",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-1.5 !border-0 !bg-[var(--ipm-trace-edge)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!size-1.5 !border-0 !bg-[var(--ipm-trace-edge)]"
      />

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
        {data.warning && <TriangleAlert className="size-2.5 text-warning" aria-hidden />}
      </div>
    </div>
  );
}

/* --------------------------------------------------------- a whole cluster */

interface GroupData extends Record<string, unknown> {
  cluster: Cluster;
  collapsed: boolean;
  width: number;
  height: number;
  dim: boolean;
  focused: boolean;
  onToggle: (id: ClusterId) => void;
  onIsolate: (id: ClusterId) => void;
}

/**
 * The cluster boundary, its name, and its health.
 *
 * Drawn on the canvas rather than beside it. In a panel the label would sit
 * still while the graph moved underneath, which is worse than no label — it
 * would name the wrong group.
 */
function ClusterFrame({ data }: NodeProps<Node<GroupData>>) {
  const { cluster } = data;
  const health = STATUS[cluster.status];
  const failing = cluster.status === "failed";

  return (
    <div
      style={{ width: data.width, height: data.height }}
      className={cn(
        "rounded-xl border bg-surface-raised/40 transition-[opacity,border-color] duration-200",
        failing ? "border-negative/60" : "border-border",
        data.focused && "border-accent",
        data.dim && "opacity-30",
      )}
    >
      <div className="flex items-center gap-2 px-3 pt-2">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            data.onToggle(cluster.id);
          }}
          aria-expanded={!data.collapsed}
          aria-label={`${data.collapsed ? "Expand" : "Collapse"} ${cluster.title}`}
          className="flex items-center gap-1 rounded text-[9px] font-semibold uppercase tracking-[0.13em] text-text-secondary transition-colors hover:text-accent"
        >
          {data.collapsed ? (
            <ChevronRight className="size-3" aria-hidden />
          ) : (
            <ChevronDown className="size-3" aria-hidden />
          )}
          {cluster.title}
        </button>

        <span className="text-[10px] text-text-muted tabular">
          {cluster.nodes.length} {cluster.nodes.length === 1 ? "step" : "steps"}
        </span>

        {/* Word, mark and colour. Remove the colour and this still reads. */}
        <span
          className={cn(
            "flex items-center gap-1 rounded-sm px-1.5 py-px text-[10px] font-medium",
            health.surface,
            health.text,
          )}
        >
          <span aria-hidden>{health.mark}</span>
          {health.label}
          {cluster.issues.length > 0 && <span className="tabular">· {cluster.issues.length}</span>}
        </span>

        {cluster.durationMs !== null && cluster.durationMs > 0 && (
          <span className="text-[10px] text-text-muted tabular">{cluster.durationMs}ms</span>
        )}

        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            data.onIsolate(cluster.id);
          }}
          title={`Isolate ${cluster.title}`}
          className="ml-auto flex size-5 items-center justify-center rounded text-text-muted transition-colors hover:bg-surface-hover hover:text-accent"
        >
          <Crosshair className="size-3" aria-hidden />
        </button>
      </div>

      {data.collapsed && <CollapsedSummary cluster={cluster} />}
    </div>
  );
}

/**
 * What a cluster says about itself while it is shut.
 *
 * Everything a reader needs to decide whether to open it: what it did, what it
 * represents, how much went in and came out, and whether anything went wrong.
 * A collapsed box that only says "6 steps" moves the wall of nodes one click
 * away rather than replacing it.
 */
function CollapsedSummary({ cluster }: { cluster: Cluster }) {
  const represents = cluster.represents.slice(0, 3).join(", ");
  const more = Math.max(0, cluster.represents.length - 3);

  return (
    <div
      style={{ width: SUMMARY_WIDTH, minHeight: SUMMARY_HEIGHT - 12 }}
      className="mx-3 mt-1.5"
    >
      <p className="line-clamp-2 text-[12px] leading-snug text-text-primary">{cluster.summary}</p>
      {represents && (
        <p className="mt-1 truncate text-[10px] text-text-muted">
          {represents}
          {more > 0 && ` and ${more} more`}
        </p>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted tabular">
        {cluster.rowsIn !== null && <span>{cluster.rowsIn.toLocaleString()} in</span>}
        {cluster.rowsOut !== null && <span>{cluster.rowsOut.toLocaleString()} out</span>}
        {cluster.issues.length > 0 && (
          <span className="flex items-center gap-1 text-warning">
            <TriangleAlert className="size-2.5" aria-hidden />
            {cluster.issues.length} needing attention
          </span>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { trace: TraceCard, cluster: ClusterFrame };

/* ------------------------------------------------------------- the canvas */

interface ReasoningMapProps {
  graph: TraceGraph;
  selected: string | null;
  onSelect: (id: string | null) => void;
  highlight?: MapHighlight;
  className?: string;
  height?: number;
}

function MapCanvas({ graph, selected, onSelect, highlight, height = 560 }: ReasoningMapProps) {
  const clusters = React.useMemo(() => clustersOf(graph), [graph]);
  const issues = React.useMemo(() => issuesIn(clusters), [clusters]);

  const [collapsed, setCollapsed] = React.useState<Set<ClusterId>>(() =>
    defaultCollapsed(clusters),
  );
  const [isolated, setIsolated] = React.useState<ClusterId | null>(null);
  const [term, setTerm] = React.useState("");
  const [issueAt, setIssueAt] = React.useState(0);

  const layout = React.useMemo(
    () => layoutClusters(graph, collapsed, isolated),
    [graph, collapsed, isolated],
  );

  const { fitView } = useReactFlow();
  const refit = React.useCallback(() => {
    window.setTimeout(() => fitView({ padding: 0.14, duration: 220, maxZoom: 1 }), 60);
  }, [fitView]);

  const toggle = React.useCallback(
    (id: ClusterId) => {
      setCollapsed((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      refit();
    },
    [refit],
  );

  const isolate = React.useCallback(
    (id: ClusterId) => {
      setIsolated((current) => (current === id ? null : id));
      setCollapsed((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
      refit();
    },
    [refit],
  );

  /**
   * Take the reader to one node: open the cluster holding it, select it, and
   * bring it on screen. Used by the issue navigator and by search — in both
   * cases the reader has named something they want to look at, and leaving it
   * inside a shut box would be answering a request with a hint.
   */
  const reveal = React.useCallback(
    (node: TraceNode) => {
      const owner = clusterOf(node);
      setIsolated(null);
      setCollapsed((current) => {
        const next = new Set(current);
        next.delete(owner);
        return next;
      });
      onSelect(node.id);
      refit();
    },
    [onSelect, refit],
  );

  const found = React.useMemo(() => searchNodes(graph, term), [graph, term]);
  const foundIds = React.useMemo(() => new Set(found.map((n) => n.id)), [found]);

  // The selected node may be inside a collapsed cluster. Lineage and dimming
  // are computed against whatever is actually ON the canvas, so selecting a
  // step and then collapsing its cluster keeps the highlight rather than
  // losing it.
  const drawnId = React.useMemo(() => {
    if (!selected) return null;
    if (layout.nodes.some((placed) => placed.id === selected)) return selected;
    const owner = graph.nodes?.find((n) => n.id === selected);
    if (!owner) return null;
    const cluster = clusterOf(owner);
    return collapsed.has(cluster) ? summaryIdFor(cluster) : null;
  }, [layout.nodes, selected, graph.nodes, collapsed]);

  const lineage = React.useMemo(() => {
    if (!drawnId) return null;
    return {
      up: ancestorsOf(layout.edges, drawnId),
      down: descendantsOf(layout.edges, drawnId),
    };
  }, [layout.edges, drawnId]);

  const changed = React.useMemo(() => new Set(highlight?.changed ?? []), [highlight]);
  const downstream = React.useMemo(() => new Set(highlight?.downstream ?? []), [highlight]);
  const added = React.useMemo(() => new Set(highlight?.added ?? []), [highlight]);
  const hasHighlight = changed.size > 0 || downstream.size > 0 || added.size > 0;

  const lineageOf = React.useCallback(
    (id: string): Lineage => {
      if (!lineage) return "none";
      if (id === drawnId) return "self";
      if (lineage.up.has(id)) return "upstream";
      if (lineage.down.has(id)) return "downstream";
      return "none";
    },
    [lineage, drawnId],
  );

  /* --- the React Flow nodes ---------------------------------------------
   *
   * Groups come first in the array, because React Flow requires a parent to be
   * declared before any child that names it. Children carry positions relative
   * to their group, which is what makes a cluster a real subgraph rather than
   * a rectangle drawn behind some nodes.
   */
  const groupNodes: Node<GroupData>[] = React.useMemo(
    () =>
      layout.clusters.map((placed) => {
        const inLineage =
          !lineage ||
          placed.cluster.nodes.some(
            (n) => lineageOf(n.id) !== "none" || n.id === drawnId,
          ) ||
          (placed.collapsed && lineageOf(placed.summaryId) !== "none");
        return {
          id: groupIdFor(placed.cluster.id),
          type: "cluster",
          position: { x: placed.x, y: placed.y },
          draggable: false,
          selectable: false,
          connectable: false,
          zIndex: 0,
          data: {
            cluster: placed.cluster,
            collapsed: placed.collapsed,
            width: placed.width,
            height: placed.height,
            dim: Boolean(lineage) && !inLineage,
            focused: isolated === placed.cluster.id,
            onToggle: toggle,
            onIsolate: isolate,
          },
        };
      }),
    [layout.clusters, lineage, lineageOf, drawnId, isolated, toggle, isolate],
  );

  const collapsedCards: Node<NodeData>[] = React.useMemo(
    () =>
      layout.clusters
        .filter((placed) => placed.collapsed)
        .map((placed) => ({
          id: placed.summaryId,
          type: "trace",
          // An invisible anchor inside the group: the collapsed card's content
          // is drawn by the frame itself, but the graph still needs a node the
          // inter-cluster edges can attach to.
          position: { x: 8, y: HEADER_HEIGHT + 4 },
          parentId: groupIdFor(placed.cluster.id),
          extent: "parent" as const,
          draggable: false,
          connectable: false,
          hidden: true,
          data: {
            label: placed.cluster.summary,
            type: "RESULT",
            status: "ok",
            rowsOut: placed.cluster.rowsOut,
            durationMs: placed.cluster.durationMs,
            warning: placed.cluster.issues.length > 0,
            failed: placed.cluster.status === "failed",
            dim: false,
            lineage: "none" as Lineage,
            mark: "none" as const,
            found: false,
          },
        })),
    [layout.clusters],
  );

  const nodes: Node<NodeData>[] = React.useMemo(
    () =>
      layout.nodes.map((placed) => {
        const relation = lineageOf(placed.id);
        const mark: NodeData["mark"] = added.has(placed.id)
          ? "added"
          : changed.has(placed.id)
            ? "changed"
            : downstream.has(placed.id)
              ? "downstream"
              : "none";
        const status = statusOf(placed.node);
        return {
          id: placed.id,
          type: "trace",
          position: { x: placed.x, y: placed.y },
          parentId: groupIdFor(placed.cluster),
          extent: "parent" as const,
          selected: placed.id === drawnId,
          draggable: false,
          connectable: false,
          zIndex: 1,
          data: {
            label: placed.node.label,
            type: placed.node.type,
            status: placed.node.status,
            rowsOut: placed.node.rows_out,
            durationMs: placed.node.duration_ms,
            warning: STATUS[status].attention,
            failed: status === "failed",
            dim:
              (Boolean(lineage) && relation === "none") ||
              (hasHighlight && mark === "none" && !lineage) ||
              (term.length > 0 && !foundIds.has(placed.id)),
            lineage: relation,
            mark,
            found: foundIds.has(placed.id),
          },
        };
      }),
    [
      layout.nodes,
      lineage,
      lineageOf,
      drawnId,
      changed,
      downstream,
      added,
      hasHighlight,
      term,
      foundIds,
    ],
  );

  const edges: Edge[] = React.useMemo(
    () => layout.edges.map((edge) => toFlowEdge(edge, lineage, drawnId)),
    [layout.edges, lineage, drawnId],
  );

  const allCollapsed = layout.clusters.length > 0 && layout.clusters.every((c) => c.collapsed);

  return (
    <div style={{ height }} className="relative">
      <ReactFlow
        nodes={[...groupNodes, ...collapsedCards, ...nodes] as Node[]}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, clicked) => {
          if (clicked.id.startsWith("group__")) return;
          if (clicked.id.startsWith("cluster__")) {
            // The collapsed stand-in: open the cluster it represents rather
            // than selecting a node that does not exist.
            toggle(clicked.id.replace("cluster__", "") as ClusterId);
            return;
          }
          onSelect(clicked.id === drawnId ? null : clicked.id);
        }}
        onPaneClick={() => onSelect(null)}
        fitView
        fitViewOptions={{ padding: 0.14, maxZoom: 1 }}
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

        <Panel position="top-right" className="flex flex-col items-end gap-1.5">
          <div className="flex items-center gap-0.5 rounded-md border border-border bg-surface-raised p-0.5 shadow-sm">
            <ZoomControls />
          </div>

          <button
            type="button"
            onClick={() => {
              setCollapsed(
                allCollapsed ? new Set() : new Set(layout.clusters.map((c) => c.cluster.id)),
              );
              refit();
            }}
            className="flex items-center gap-1.5 rounded-md border border-border bg-surface-raised px-2 py-1 text-[11px] font-medium text-text-secondary shadow-sm transition-colors hover:border-accent hover:text-accent"
          >
            {allCollapsed ? (
              <ChevronsLeftRight className="size-3" aria-hidden />
            ) : (
              <ChevronsRightLeft className="size-3" aria-hidden />
            )}
            {allCollapsed ? "Expand all" : "Collapse all"}
          </button>

          {isolated && (
            <button
              type="button"
              onClick={() => {
                setIsolated(null);
                refit();
              }}
              className="flex items-center gap-1.5 rounded-md border border-accent bg-accent-muted px-2 py-1 text-[11px] font-medium text-accent shadow-sm"
            >
              <X className="size-3" aria-hidden />
              Back to the whole map
            </button>
          )}
        </Panel>

        <Panel position="top-left" className="flex flex-col gap-1.5">
          <NodeFinder term={term} setTerm={setTerm} found={found} onReveal={reveal} />
          {issues.length > 0 && (
            <IssueNavigator
              issues={issues}
              at={issueAt}
              setAt={setIssueAt}
              onReveal={reveal}
              clusters={clusters}
            />
          )}
        </Panel>

        <Panel position="bottom-left">
          <Legend />
        </Panel>
      </ReactFlow>
    </div>
  );
}

/**
 * The summarised dependency between two drawn steps.
 *
 * When a cluster is collapsed its internal edges vanish with its internals and
 * the ones crossing its boundary land on the collapsed card instead — so the
 * SHAPE of the dependency survives even when the detail does not, which is what
 * makes collapsing safe. Cross-cluster edges are drawn heavier and labelled
 * with what the dependency is; a join that multiplied its left side or a
 * relationship that could not be resolved marks its own edge, because that
 * fault is in the link and not in either box it connects.
 */
function toFlowEdge(edge: PlacedEdge, lineage: { up: Set<string>; down: Set<string> } | null, drawnId: string | null): Edge {
  const active =
    !lineage ||
    ((lineage.up.has(edge.source) || edge.source === drawnId) &&
      (lineage.up.has(edge.target) || edge.target === drawnId)) ||
    ((lineage.down.has(edge.target) || edge.target === drawnId) &&
      (lineage.down.has(edge.source) || edge.source === drawnId));

  const colour = edge.warning
    ? "var(--ipm-warning)"
    : active && lineage
      ? "var(--ipm-accent)"
      : "var(--ipm-trace-edge)";

  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: "smoothstep",
    animated: false,
    label: edge.crossesClusters ? KIND_LABEL[edge.kind] : undefined,
    labelStyle: { fontSize: 9, fill: "var(--ipm-text-muted)" },
    labelBgStyle: { fill: "var(--ipm-surface-raised)" },
    labelBgPadding: [3, 1],
    style: {
      stroke: colour,
      strokeWidth: edge.warning ? 2 : edge.crossesClusters ? 1.5 : 1,
      strokeDasharray: edge.warning ? "4 3" : undefined,
      opacity: lineage && !active ? 0.12 : 1,
    },
  };
}

/* ------------------------------------------------------------ the controls */

function ZoomControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <>
      <IconButton title="Zoom out" onClick={() => zoomOut({ duration: 180 })}>
        <Minus className="size-3.5" aria-hidden />
      </IconButton>
      <IconButton title="Zoom in" onClick={() => zoomIn({ duration: 180 })}>
        <Plus className="size-3.5" aria-hidden />
      </IconButton>
      <IconButton
        title="Fit the whole map on screen"
        onClick={() => fitView({ padding: 0.14, duration: 220, maxZoom: 1 })}
      >
        <Maximize2 className="size-3.5" aria-hidden />
      </IconButton>
    </>
  );
}

/**
 * Find a step by name, dataset or field.
 *
 * A forty-node trace is searchable in the same sense a filing cabinet is: the
 * thing is in there. Typing "covenant" and being taken to the invariant that
 * checked it is the difference between a record and a tool.
 */
function NodeFinder({
  term,
  setTerm,
  found,
  onReveal,
}: {
  term: string;
  setTerm: (value: string) => void;
  found: TraceNode[];
  onReveal: (node: TraceNode) => void;
}) {
  return (
    <div className="w-56 rounded-md border border-border bg-surface-raised shadow-sm">
      <label className="flex items-center gap-1.5 px-2 py-1.5">
        <Search className="size-3 shrink-0 text-text-muted" aria-hidden />
        <span className="sr-only">Search the steps in this trace</span>
        <input
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          placeholder="Find a step, field or dataset"
          className="w-full bg-transparent text-[11px] text-text-primary outline-none placeholder:text-text-muted"
        />
        {term && (
          <button
            type="button"
            onClick={() => setTerm("")}
            aria-label="Clear the search"
            className="shrink-0 text-text-muted hover:text-text-primary"
          >
            <X className="size-3" aria-hidden />
          </button>
        )}
      </label>
      {term.length > 0 && (
        <div className="max-h-40 overflow-y-auto border-t border-border p-1">
          {found.length === 0 ? (
            <p className="px-1.5 py-1 text-[11px] text-text-muted">Nothing matches.</p>
          ) : (
            found.slice(0, 8).map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => onReveal(node)}
                className="block w-full truncate rounded px-1.5 py-1 text-left text-[11px] text-text-secondary transition-colors hover:bg-surface-hover hover:text-accent"
              >
                {node.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The issues, and a way through them.
 *
 * A trace with one failed invariant among forty passing steps is the case this
 * exists for. The cluster header already says VALIDATION & EVIDENCE FAILED, so
 * a reader knows where to look; this takes them there without asking them to
 * scan dozens of ordinary nodes to find which one.
 */
function IssueNavigator({
  issues,
  at,
  setAt,
  onReveal,
  clusters,
}: {
  issues: { node: TraceNode; cluster: ClusterId }[];
  at: number;
  setAt: (value: number) => void;
  onReveal: (node: TraceNode) => void;
  clusters: Cluster[];
}) {
  const index = Math.min(Math.max(at, 0), issues.length - 1);
  const current = issues[index];
  const status = STATUS[statusOf(current.node)];
  const title = clusters.find((c) => c.id === current.cluster)?.title ?? "";

  const move = (delta: number) => {
    const next = (index + delta + issues.length) % issues.length;
    setAt(next);
    onReveal(issues[next].node);
  };

  return (
    <div className="w-56 rounded-md border border-warning/40 bg-surface-warning p-1.5 shadow-sm">
      <div className="flex items-center gap-1.5">
        <TriangleAlert className="size-3 shrink-0 text-warning" aria-hidden />
        <span className="text-[10px] font-semibold uppercase tracking-[0.11em] text-warning">
          {issues.length} needing attention
        </span>
        <span className="ml-auto text-[10px] text-text-muted tabular">
          {index + 1}/{issues.length}
        </span>
      </div>

      <button
        type="button"
        onClick={() => onReveal(current.node)}
        className="mt-1 block w-full rounded px-1 py-0.5 text-left transition-colors hover:bg-surface-hover"
      >
        <span className={cn("text-[10px] font-medium", status.text)}>
          <span aria-hidden>{status.mark}</span> {status.label}
        </span>
        <span className="ml-1 text-[10px] text-text-muted">· {title}</span>
        <span className="mt-0.5 block line-clamp-2 text-[11px] leading-snug text-text-primary">
          {current.node.label}
        </span>
      </button>

      {issues.length > 1 && (
        <div className="mt-1 flex items-center gap-1">
          <button
            type="button"
            onClick={() => move(-1)}
            className="flex-1 rounded border border-border bg-surface-raised px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:text-accent"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => move(1)}
            className="flex-1 rounded border border-border bg-surface-raised px-1.5 py-0.5 text-[10px] text-text-secondary transition-colors hover:text-accent"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function IconButton({
  title,
  onClick,
  children,
}: {
  title: string;
  onClick: () => void;
  children?: React.ReactNode;
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

/**
 * The clusters as a list, for readers who are not using the canvas.
 *
 * Not a fallback and not a lesser view: a spatial diagram is unusable with a
 * screen reader and awkward with a keyboard, and "open the Audit tab instead"
 * is an answer that makes the disabled reader take a different route to a
 * different thing. This is the same eight clusters, the same summaries, the
 * same health, in a list that tabs.
 */
export function ClusterList({
  graph,
  onSelect,
  className,
}: {
  graph: TraceGraph;
  onSelect: (id: string) => void;
  className?: string;
}) {
  const clusters = React.useMemo(() => clustersOf(graph), [graph]);

  return (
    <ol className={cn("space-y-2", className)}>
      {CLUSTER_ORDER.map((id) => {
        const cluster = clusters.find((c) => c.id === id);
        if (!cluster) return null;
        const health = STATUS[cluster.status];
        return (
          <li key={id} className="rounded-lg border border-border bg-surface p-3">
            <div className="flex items-center gap-2">
              <h4 className="text-[11px] font-semibold uppercase tracking-[0.11em] text-text-secondary">
                {cluster.title}
              </h4>
              <span className={cn("text-[11px] font-medium", health.text)}>
                <span aria-hidden>{health.mark}</span> {health.label}
              </span>
              <span className="ml-auto text-[11px] text-text-muted tabular">
                {cluster.nodes.length} {cluster.nodes.length === 1 ? "step" : "steps"}
              </span>
            </div>
            <p className="mt-1 text-[13px] leading-snug text-text-primary">{cluster.summary}</p>
            <ul className="mt-1.5 flex flex-wrap gap-1">
              {cluster.nodes.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(node.id)}
                    className="rounded border border-border px-1.5 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-accent hover:text-accent"
                  >
                    {node.label}
                  </button>
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ol>
  );
}

export function ReasoningMap(props: ReasoningMapProps) {
  // The canvas is keyed by the trace it is drawing, so opening a different
  // investigation — or a different version of one — starts from that trace's
  // own collapsed defaults. Assigning the state from an effect would work and
  // would render one frame of the previous trace's layout first.
  const key = `${props.graph.nodes?.length ?? 0}:${props.graph.nodes?.[0]?.id ?? ""}:${
    props.graph.nodes?.at(-1)?.id ?? ""
  }`;

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-border bg-surface-sunken",
        props.className,
      )}
    >
      <ReactFlowProvider>
        <MapCanvas key={key} {...props} />
      </ReactFlowProvider>
    </div>
  );
}
