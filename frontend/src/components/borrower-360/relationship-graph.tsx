"use client";

import * as React from "react";

import { borrower360Href } from "@/lib/borrower-link";
import type { RelatedParty, RelationshipNetwork } from "@/lib/api";
import {
  BAND_HEIGHT,
  NODE_HEIGHT,
  NODE_WIDTH,
  PADDING,
  type Direction,
  type Placed,
  directOnly,
  layout,
  money,
  stake,
} from "@/lib/relationship-layout";

/**
 * The group structure, drawn. R2 §2.
 *
 * Not a picture of a graph — a layout that says something. Everything above
 * the borrower is drawn above it, everything below is below it, and everything
 * beside is beside it, so the first glance answers "who is over this, and what
 * hangs off it" before a single label is read. A force-directed blob answers
 * that question with a shrug.
 *
 * Drawn as SVG rather than with a graph library. The layout is three bands and
 * the interaction is pan, zoom and click; a physics engine would add a
 * dependency, a licence and a settling animation in exchange for a worse
 * answer to the only question the screen is for.
 *
 * Control and economics are drawn apart, because they are different facts.
 * A solid edge is control — a voting stake above half, or an explicit control
 * relationship. A dashed edge is economics without control. An officer who
 * reads only the solid lines is reading the group that can be directed, which
 * is the correct group for a great many credit questions.
 */

const BAND_TITLE: Record<Direction, string> = {
  UPSTREAM: "Above — who can be called on, and who has a claim",
  LATERAL: "Beside — what else moves when this moves",
  DOWNSTREAM: "Below — what this borrower carries",
};


function Node({
  spot,
  network,
  selected,
  onSelect,
}: {
  spot: Placed;
  network: RelationshipNetwork;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const party = spot.party;
  const id = party ? party.node_id : network.centre;
  const label = party ? party.label : network.centre_label;
  const isSelected = selected === id;
  const control = party?.controls ?? false;

  return (
    <g
      transform={`translate(${spot.x}, ${spot.y})`}
      className="cursor-pointer"
      onClick={() => onSelect(isSelected ? null : id)}
      role="button"
      tabIndex={0}
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onSelect(isSelected ? null : id);
      }}
    >
      <rect
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={7}
        className={
          spot.centre
            ? "fill-accent/15 stroke-accent"
            : control
              ? "fill-surface stroke-text-primary"
              : "fill-surface stroke-border"
        }
        strokeWidth={isSelected ? 2.5 : spot.centre ? 2 : 1}
      />
      <text x={10} y={19} className="fill-text-primary text-[11px] font-medium">
        {label.length > 24 ? `${label.slice(0, 23)}…` : label}
      </text>
      <text x={10} y={34} className="fill-text-secondary text-[9px]">
        {party
          ? stake(party) || party.relationship.slice(0, 30)
          : network.centre_exposure !== null
            ? `${money(network.centre_exposure)} exposure`
            : "This borrower"}
      </text>
    </g>
  );
}

function Edges({
  placed,
  network,
  width,
}: {
  placed: Placed[];
  network: RelationshipNetwork;
  width: number;
}) {
  const centre = placed.find((s) => s.centre);
  if (!centre) return null;
  const cx = centre.x + NODE_WIDTH / 2;
  const cy = centre.y + NODE_HEIGHT / 2;
  return (
    <g>
      {placed
        .filter((s) => s.party)
        .map((spot) => {
          const party = spot.party as RelatedParty;
          const x = spot.x + NODE_WIDTH / 2;
          const y = spot.y + NODE_HEIGHT / 2;
          // Lateral parties connect through the shared owner, so the line is
          // bowed rather than straight: a straight line would claim a direct
          // relationship the data does not record.
          const bow = party.direction === "LATERAL" ? 42 : 0;
          const path = `M ${cx} ${cy} Q ${(cx + x) / 2 + bow} ${(cy + y) / 2} ${x} ${y}`;
          return (
            <path
              key={party.node_id}
              d={path}
              fill="none"
              className={party.controls ? "stroke-text-primary" : "stroke-border"}
              strokeWidth={party.controls ? 1.6 : 1}
              strokeDasharray={party.controls ? undefined : "4 3"}
              markerEnd={
                party.direction === "DOWNSTREAM" ? "url(#arrow-down)" : undefined
              }
              markerStart={
                party.direction === "UPSTREAM" ? "url(#arrow-up)" : undefined
              }
            />
          );
        })}
      <text
        x={width / 2}
        y={14}
        textAnchor="middle"
        className="fill-text-secondary text-[9px] uppercase tracking-wide"
      >
        {BAND_TITLE.UPSTREAM}
      </text>
      <text
        x={width / 2}
        y={PADDING * 2 + BAND_HEIGHT * 2 + NODE_HEIGHT + 6}
        textAnchor="middle"
        className="fill-text-secondary text-[9px] uppercase tracking-wide"
      >
        {BAND_TITLE.DOWNSTREAM}
      </text>
      <text x={12} y={PADDING + BAND_HEIGHT - 8} className="fill-text-secondary text-[9px] uppercase tracking-wide">
        {network.groups.find((g) => g.direction === "LATERAL")?.count ?? 0} beside
      </text>
    </g>
  );
}

function Detail({
  party,
  network,
}: {
  party: RelatedParty;
  network: RelationshipNetwork;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface-sunken p-3 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium text-text-primary">{party.label}</span>
        <span className="text-[10px] uppercase tracking-wide text-text-secondary">
          {party.node_type} · {party.depth === 1 ? "direct" : `${party.depth} steps away`}
        </span>
      </div>
      <p className="mt-1 text-text-secondary">{party.relationship}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
        {party.ownership_pct !== null ? (
          <Fact label="Economic ownership" value={`${party.ownership_pct.toFixed(2)}%`} />
        ) : null}
        {party.voting_pct !== null ? (
          <Fact label="Voting rights" value={`${party.voting_pct.toFixed(2)}%`} />
        ) : null}
        {party.amount !== null ? <Fact label="Amount" value={money(party.amount)} /> : null}
        {party.exposure !== null ? (
          <Fact label="Exposure at default" value={money(party.exposure)} />
        ) : null}
        <Fact label="Carries control" value={party.controls ? "Yes" : "No"} />
        {party.source ? <Fact label="Source" value={party.source} /> : null}
      </dl>
      {party.via.length > 2 ? (
        <p className="mt-2 text-[11px] text-text-secondary">
          Reached through {party.via.slice(1, -1).join(" → ")}.
        </p>
      ) : null}
      {party.is_borrower ? (
        <a
          className="mt-2 inline-block text-[11px] font-medium text-accent hover:underline"
          href={borrower360Href(party.node_id, network.period)}
        >
          Open this borrower →
        </a>
      ) : (
        <p className="mt-2 text-[11px] text-text-secondary">
          Not a borrower on this book, so there is no Borrower 360 for it.
        </p>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-text-secondary">{label}</dt>
      <dd className="tabular-nums text-text-primary">{value}</dd>
    </div>
  );
}

export function RelationshipGraph({
  network,
  depth,
  onDepth,
  scope,
  onScope,
}: {
  network: RelationshipNetwork;
  depth: number;
  onDepth: (depth: number) => void;
  scope: "direct" | "network";
  onScope: (scope: "direct" | "network") => void;
}) {
  const [selected, setSelected] = React.useState<string | null>(null);
  const [zoom, setZoom] = React.useState(1);
  const [pan, setPan] = React.useState({ x: 0, y: 0 });
  const dragging = React.useRef<{ x: number; y: number } | null>(null);

  const shown = React.useMemo<RelationshipNetwork>(
    () => (scope === "network" ? network : directOnly(network)),
    [network, scope],
  );

  const { placed, width, height } = React.useMemo(() => layout(shown), [shown]);
  const chosen =
    selected === null
      ? null
      : (shown.groups.flatMap((g) => g.parties).find((p) => p.node_id === selected) ?? null);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <div className="flex items-center gap-1">
          <span className="text-text-secondary">Show</span>
          {(["direct", "network"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onScope(option)}
              className={`rounded-md border px-2 py-1 text-[11px] ${
                scope === option
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border text-text-secondary hover:text-text-primary"
              }`}
            >
              {option === "direct" ? "Direct relationships" : "Full network"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-text-secondary">
          Depth
          <select
            value={depth}
            onChange={(event) => onDepth(Number(event.target.value))}
            className="rounded-md border border-border bg-surface px-2 py-1 text-[11px] text-text-primary"
          >
            {[1, 2, 3].map((step) => (
              <option key={step} value={step}>
                {step}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="rounded-md border border-border px-2 py-1 text-[11px] text-text-secondary hover:text-text-primary"
            onClick={() => setZoom((z) => Math.max(0.4, z - 0.2))}
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            className="rounded-md border border-border px-2 py-1 text-[11px] text-text-secondary hover:text-text-primary"
            onClick={() => setZoom((z) => Math.min(2.4, z + 0.2))}
            aria-label="Zoom in"
          >
            +
          </button>
          <button
            type="button"
            className="rounded-md border border-border px-2 py-1 text-[11px] text-text-secondary hover:text-text-primary"
            onClick={() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}
          >
            Reset
          </button>
        </div>
        <span className="ml-auto text-text-secondary">
          <span className="text-text-primary">{money(shown.group_exposure)}</span> across{" "}
          {shown.group_borrowers} borrower(s)
          {shown.exposure_is_floor ? " — at least, the network was truncated" : ""}
        </span>
      </div>

      <div
        className="overflow-hidden rounded-lg border border-border bg-surface"
        onMouseDown={(event) => {
          dragging.current = { x: event.clientX - pan.x, y: event.clientY - pan.y };
        }}
        onMouseMove={(event) => {
          if (!dragging.current) return;
          setPan({
            x: event.clientX - dragging.current.x,
            y: event.clientY - dragging.current.y,
          });
        }}
        onMouseUp={() => {
          dragging.current = null;
        }}
        onMouseLeave={() => {
          dragging.current = null;
        }}
      >
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          height={Math.min(height, 520)}
          role="img"
          aria-label={`Group structure around ${network.centre_label}`}
        >
          <defs>
            <marker
              id="arrow-down"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M 0 0 L 8 4 L 0 8 z" className="fill-text-primary" />
            </marker>
            <marker
              id="arrow-up"
              viewBox="0 0 8 8"
              refX="1"
              refY="4"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M 8 0 L 0 4 L 8 8 z" className="fill-text-primary" />
            </marker>
          </defs>
          <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
            <Edges placed={placed} network={shown} width={width} />
            {placed.map((spot) => (
              <Node
                key={spot.centre ? shown.centre : (spot.party as RelatedParty).node_id}
                spot={spot}
                network={shown}
                selected={selected}
                onSelect={setSelected}
              />
            ))}
          </g>
        </svg>
      </div>

      <div className="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-text-secondary">
        <span className="flex items-center gap-1.5">
          <svg width="22" height="6" aria-hidden>
            <line x1="0" y1="3" x2="22" y2="3" className="stroke-text-primary" strokeWidth="1.6" />
          </svg>
          Carries control
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="22" height="6" aria-hidden>
            <line
              x1="0"
              y1="3"
              x2="22"
              y2="3"
              className="stroke-border"
              strokeWidth="1"
              strokeDasharray="4 3"
            />
          </svg>
          Economic interest, no control
        </span>
        <span>Above the centre: upstream. Below: downstream. Beside: lateral.</span>
      </div>

      {chosen ? <Detail party={chosen} network={network} /> : null}
      {shown.truncated ? (
        <p className="text-[11px] text-caution">{shown.truncation_note}</p>
      ) : null}
    </div>
  );
}
