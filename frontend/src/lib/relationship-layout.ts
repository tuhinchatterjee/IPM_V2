/**
 * Where each party sits in a group structure, and what its edge says. R2 §2.
 *
 * Separated from the component because it is the part with rules in it. The
 * layout decides that upstream is drawn above and downstream below — which is
 * the whole claim the picture makes — and a rule that only exists inside a
 * render function is a rule no test can reach.
 */

import type { RelatedParty, RelationshipNetwork } from "@/lib/api";

export const BAND_HEIGHT = 150;
export const NODE_WIDTH = 168;
export const NODE_HEIGHT = 46;
export const GAP = 22;
export const PADDING = 40;

export type Direction = RelatedParty["direction"];

/** Top to bottom. Upstream above, lateral level, downstream below. */
export const BAND_ORDER: Direction[] = ["UPSTREAM", "LATERAL", "DOWNSTREAM"];

export interface Placed {
  party: RelatedParty | null;
  x: number;
  y: number;
  centre: boolean;
}

export interface Layout {
  placed: Placed[];
  width: number;
  height: number;
}

/**
 * A monetary figure in the currency the corporate lake is denominated in.
 *
 * Millions below a billion, billions above, and never a bare number: R2 §3
 * applies to every screen, not only to Early Warning, and a group exposure
 * printed as "4953.87" is a figure a reader has to guess the unit of.
 */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  if (Math.abs(value) >= 1000) return `SAR ${(value / 1000).toFixed(2)}bn`;
  return `SAR ${value.toFixed(1)}m`;
}

/**
 * What the edge to this party says, in one line.
 *
 * Ownership and voting are shown separately WHEN THEY DIFFER. Showing both
 * always would put "80.0% owned · 80.0% votes" on most edges, which is noise;
 * showing only one would hide the dual-class structures, which is the case
 * that matters. So the rule is: show the second only when it says something
 * different from the first.
 */
export function stake(party: RelatedParty): string {
  const bits: string[] = [];
  if (party.ownership_pct !== null) bits.push(`${party.ownership_pct.toFixed(1)}% owned`);
  if (party.voting_pct !== null && party.voting_pct !== party.ownership_pct) {
    bits.push(`${party.voting_pct.toFixed(1)}% votes`);
  }
  if (party.amount !== null) bits.push(money(party.amount));
  return bits.join(" · ");
}

/** Only the parties one step from the centre. */
export function directOnly(network: RelationshipNetwork): RelationshipNetwork {
  return {
    ...network,
    groups: network.groups.map((group) => {
      const parties = group.parties.filter((party) => party.depth === 1);
      return { ...group, parties, count: parties.length };
    }),
    party_count: network.groups.reduce(
      (total, group) => total + group.parties.filter((p) => p.depth === 1).length,
      0,
    ),
  };
}

/**
 * Three bands, laid out around the centre.
 *
 * The middle band holds the borrower AND everything lateral to it, in one row
 * at one height. "Beside" has to mean beside: a sister drawn even half a node
 * lower than the borrower reads as a subsidiary at a glance, which is the one
 * misreading this layout exists to prevent. So the centre takes a slot in the
 * lateral row rather than sitting above it.
 */
export function layout(network: RelationshipNetwork): Layout {
  const byDirection = new Map<Direction, RelatedParty[]>();
  for (const group of network.groups) byDirection.set(group.direction, group.parties);

  const lateral = byDirection.get("LATERAL") ?? [];
  const widest = Math.max(
    1,
    (byDirection.get("UPSTREAM") ?? []).length,
    (byDirection.get("DOWNSTREAM") ?? []).length,
    lateral.length + 1,
  );
  const width = Math.max(720, widest * (NODE_WIDTH + GAP) - GAP + PADDING * 2);
  const height = PADDING * 2 + BAND_HEIGHT * 3 + NODE_HEIGHT;
  const placed: Placed[] = [];

  const rowY = (band: number) => PADDING + band * BAND_HEIGHT;
  const rowStart = (count: number) =>
    (width - (count * (NODE_WIDTH + GAP) - GAP)) / 2;

  for (const direction of ["UPSTREAM", "DOWNSTREAM"] as const) {
    const parties = byDirection.get(direction) ?? [];
    const y = rowY(BAND_ORDER.indexOf(direction));
    const start = rowStart(parties.length);
    parties.forEach((party, index) => {
      placed.push({ party, x: start + index * (NODE_WIDTH + GAP), y, centre: false });
    });
  }

  // The middle row: the borrower first, then everything beside it.
  const middle = rowY(BAND_ORDER.indexOf("LATERAL"));
  const start = rowStart(lateral.length + 1);
  placed.push({ party: null, x: start, y: middle, centre: true });
  lateral.forEach((party, index) => {
    placed.push({
      party,
      x: start + (index + 1) * (NODE_WIDTH + GAP),
      y: middle,
      centre: false,
    });
  });
  return { placed, width, height };
}
