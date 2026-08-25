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
import { Clock3, Maximize2, Minus, Plus, ShieldCheck, Table2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { RelationshipEdge, RelationshipNode } from "@/lib/api";

import { NODE_HEIGHT, NODE_WIDTH, layoutRelationships } from "./relationship-layout";

import "@xyflow/react/dist/base.css";

/**
 * The relationship map, as a canvas.
 *
 * A credit book's data model is a hub: the facility position at the centre,
 * the customer beside it, and everything else hanging off one of the two. The
 * layout is built from that shape rather than from a force simulation, for
 * three reasons.
 *
 *  - **It is deterministic.** The same relationship model draws the same
 *    picture in every session, so a steward can point at a box in a meeting
 *    and find it again afterwards. A force-directed layout re-settles on every
 *    load and looks more impressive while telling a reader less.
 *  - **Distance from the centre means something.** Ring 0 is the busiest
 *    dataset; ring 1 joins to it directly; ring 2 needs a hop through ring 1.
 *    That is the same number the join resolver charges per hop.
 *  - **Selecting an edge dims the rest.** "What does this join actually do"
 *    is answered by looking, not by reading a table row.
 *
 * Edges carry their own state: a relationship that is not ACTIVE is drawn
 * dashed and pale, because the runtime will not join on it and a map that
 * shows a draft the same as a governed join is telling a comfortable lie.
 */

const CARDINALITY_LABEL: Record<string, string> = {
  one_to_one: "1 : 1",
  many_to_one: "many : 1",
  one_to_many: "1 : many",
  many_to_many: "many : many",
};

/** Cardinalities that can multiply the left side, so the edge is marked. */
const MULTIPLYING = new Set(["one_to_many", "many_to_many"]);

interface DatasetData extends Record<string, unknown> {
  name: string;
  grain: string;
  domain: string;
  ring: number;
  degree: number;
  authoritative: boolean;
  periodic: boolean;
  dim: boolean;
  onCentre: boolean;
}

function DatasetCard({ data, selected }: NodeProps<Node<DatasetData>>) {
  return (
    <div
      style={{ width: NODE_WIDTH, minHeight: NODE_HEIGHT }}
      className={cn(
        "relative rounded-lg border bg-surface px-2.5 py-2 text-left transition-[opacity,border-color,box-shadow] duration-200",
        data.onCentre ? "border-border-strong" : "border-border",
        selected && "border-accent shadow-[0_0_0_2px_var(--ipm-accent-muted)]",
        data.dim && "opacity-20",
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-1 !border-0 !bg-border" />
      <Handle type="source" position={Position.Right} className="!size-1 !border-0 !bg-border" />

      <div className="flex items-center gap-1.5">
        <Table2 className="size-3 shrink-0 text-text-muted" aria-hidden />
        <span className="truncate font-mono text-[11px] font-semibold text-text-primary">
          {data.name}
        </span>
        {data.authoritative && (
          <ShieldCheck className="ml-auto size-3 shrink-0 text-accent" aria-hidden
            /* Authoritative for at least one concept. */ />
        )}
      </div>
      <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-text-muted">
        {data.grain || "grain not declared"}
      </p>
      <div className="mt-1 flex items-center gap-1.5 text-[9px] text-text-muted tabular">
        <span>{data.degree} {data.degree === 1 ? "join" : "joins"}</span>
        {data.periodic && (
          <span className="flex items-center gap-0.5">
            <Clock3 className="size-2.5" aria-hidden />
            periodic
          </span>
        )}
      </div>
    </div>
  );
}

const nodeTypes = { dataset: DatasetCard };

export interface RelationshipCanvasProps {
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
  selectedEdge: number | null;
  onSelectEdge: (id: number | null) => void;
  height?: number;
}

function Canvas({
  nodes,
  edges,
  selectedEdge,
  onSelectEdge,
  height = 560,
}: RelationshipCanvasProps) {
  const { placed } = React.useMemo(
    () => layoutRelationships(nodes, edges),
    [nodes, edges],
  );

  const chosen = React.useMemo(
    () => edges.find((e) => e.id === selectedEdge) ?? null,
    [edges, selectedEdge],
  );
  const lit = React.useMemo(
    () => new Set(chosen ? [chosen.from_dataset, chosen.to_dataset] : []),
    [chosen],
  );

  const degrees = React.useMemo(() => {
    const counts = new Map<string, number>();
    for (const edge of edges) {
      counts.set(edge.from_dataset, (counts.get(edge.from_dataset) ?? 0) + 1);
      counts.set(edge.to_dataset, (counts.get(edge.to_dataset) ?? 0) + 1);
    }
    return counts;
  }, [edges]);

  const flowNodes: Node<DatasetData>[] = React.useMemo(
    () =>
      placed.map((p) => ({
        id: p.name,
        type: "dataset",
        position: { x: p.x, y: p.y },
        draggable: false,
        connectable: false,
        selectable: false,
        data: {
          name: p.name,
          grain: p.node?.grain ?? "",
          domain: p.node?.domain ?? "",
          ring: p.ring,
          degree: degrees.get(p.name) ?? 0,
          authoritative: (p.node?.authoritative_for?.length ?? 0) > 0,
          periodic: Boolean(p.node?.period_field),
          dim: Boolean(chosen) && !lit.has(p.name),
          onCentre: p.ring === 0,
        },
      })),
    [placed, degrees, chosen, lit],
  );

  const flowEdges: Edge[] = React.useMemo(
    () =>
      edges
        // A self-join has nowhere to go on a canvas; it is shown in the list
        // beside the map instead of drawn as a loop nobody can click.
        .filter((edge) => edge.from_dataset !== edge.to_dataset)
        .map((edge) => {
          const active = !chosen || chosen.id === edge.id;
          const runnable = edge.is_runnable;
          return {
            id: String(edge.id),
            source: edge.from_dataset,
            target: edge.to_dataset,
            type: "smoothstep",
            animated: false,
            label: chosen?.id === edge.id
              ? (CARDINALITY_LABEL[edge.cardinality] ?? edge.cardinality)
              : undefined,
            labelStyle: { fontSize: 10, fill: "var(--ipm-text-secondary)" },
            labelBgStyle: { fill: "var(--ipm-surface-raised)" },
            style: {
              stroke: chosen?.id === edge.id
                ? "var(--ipm-accent)"
                : MULTIPLYING.has(edge.cardinality)
                  ? "var(--ipm-warning)"
                  : "var(--ipm-border-strong)",
              strokeWidth: chosen?.id === edge.id ? 2 : 1.1,
              strokeDasharray: runnable ? undefined : "4 3",
              opacity: active ? (runnable ? 1 : 0.5) : 0.12,
            },
          };
        }),
    [edges, chosen],
  );

  return (
    <div style={{ height }} className="relative">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onEdgeClick={(_, clicked) => {
          const id = Number(clicked.id);
          onSelectEdge(id === selectedEdge ? null : id);
        }}
        onPaneClick={() => onSelectEdge(null)}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        minZoom={0.15}
        maxZoom={1.8}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
        // The canvas sits in a scrolling page, so the wheel pans rather than
        // zooming: trapping the page scroll on a diagram is a hostile default.
        zoomOnScroll={false}
        panOnScroll
        panOnDrag
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--ipm-border)" />
        <CanvasControls />
        <Panel position="bottom-left">
          <div className="rounded-md border border-border bg-surface-raised/90 px-2 py-1.5 text-[10px] text-text-muted shadow-sm">
            <div className="flex items-center gap-3">
              <Key colour="var(--ipm-border-strong)">safe to join</Key>
              <Key colour="var(--ipm-warning)">multiplies rows</Key>
              <Key colour="var(--ipm-border-strong)" dashed>
                not active
              </Key>
            </div>
            <p className="mt-1 max-w-96 leading-snug">
              Rings are hops from the busiest dataset. Click a line to inspect the join.
            </p>
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}

function Key({
  colour,
  dashed,
  children,
}: {
  colour: string;
  dashed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1">
      <span
        aria-hidden
        className="inline-block h-0 w-5"
        style={{
          borderTop: `${dashed ? "1.5px dashed" : "1.5px solid"} ${colour}`,
        }}
      />
      {children}
    </span>
  );
}

function CanvasControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <Panel position="top-right">
      <div className="flex items-center gap-0.5 rounded-md border border-border bg-surface-raised p-0.5 shadow-sm">
        <IconButton title="Zoom out" onClick={() => zoomOut({ duration: 180 })}>
          <Minus className="size-3.5" aria-hidden />
        </IconButton>
        <IconButton title="Zoom in" onClick={() => zoomIn({ duration: 180 })}>
          <Plus className="size-3.5" aria-hidden />
        </IconButton>
        <IconButton
          title="Fit the whole map on screen"
          onClick={() => fitView({ padding: 0.15, duration: 220, maxZoom: 1 })}
        >
          <Maximize2 className="size-3.5" aria-hidden />
        </IconButton>
      </div>
    </Panel>
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
      aria-label={title}
      onClick={onClick}
      className="flex size-6 items-center justify-center rounded text-text-muted transition-colors hover:bg-surface-sunken hover:text-text-primary"
    >
      {children}
    </button>
  );
}

export function RelationshipCanvas(props: RelationshipCanvasProps) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}
