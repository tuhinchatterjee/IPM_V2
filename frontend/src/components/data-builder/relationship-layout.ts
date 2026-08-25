/**
 * Where the boxes go on the relationship map.
 *
 * Kept apart from the canvas that draws them so the layout can be reasoned
 * about and tested on its own: the property that matters — the same
 * relationship model always draws the same picture — is a property of this
 * function, not of React Flow.
 */

import type { RelationshipEdge, RelationshipNode } from "@/lib/api";

/** Box size, shared with the canvas so ring spacing can avoid overlaps. */
export const NODE_WIDTH = 176;
export const NODE_HEIGHT = 62;
const RING_GAP = 250;

export interface Placed {
  name: string;
  x: number;
  y: number;
  ring: number;
  node?: RelationshipNode;
}

/**
 * Rings by hop distance from the busiest dataset.
 *
 * Ties are broken by name so the picture is stable, and anything the BFS never
 * reaches is placed in a final ring of its own rather than dropped — a dataset
 * joined to nothing is a finding, not an absence.
 */
export function layoutRelationships(
  nodes: RelationshipNode[],
  edges: RelationshipEdge[],
): { placed: Placed[]; rings: number } {
  const byName = new Map(nodes.map((n) => [n.name, n]));
  const involved = new Set<string>();
  const neighbours = new Map<string, Set<string>>();
  const touch = (a: string, b: string) => {
    involved.add(a);
    involved.add(b);
    if (!neighbours.has(a)) neighbours.set(a, new Set());
    if (!neighbours.has(b)) neighbours.set(b, new Set());
    neighbours.get(a)!.add(b);
    neighbours.get(b)!.add(a);
  };
  for (const edge of edges) touch(edge.from_dataset, edge.to_dataset);

  const names = Array.from(involved).sort();
  if (names.length === 0) return { placed: [], rings: 0 };

  const degree = (name: string) => neighbours.get(name)?.size ?? 0;
  const centre = names.reduce((best, name) =>
    degree(name) > degree(best) || (degree(name) === degree(best) && name < best)
      ? name
      : best,
  );

  const ringOf = new Map<string, number>([[centre, 0]]);
  let frontier = [centre];
  while (frontier.length) {
    const next: string[] = [];
    for (const name of frontier) {
      for (const other of Array.from(neighbours.get(name) ?? []).sort()) {
        if (ringOf.has(other)) continue;
        ringOf.set(other, (ringOf.get(name) ?? 0) + 1);
        next.push(other);
      }
    }
    frontier = next;
  }
  // Unreachable from the centre: its own outer ring rather than dropped.
  const orphanRing = Math.max(0, ...ringOf.values()) + 1;
  for (const name of names) if (!ringOf.has(name)) ringOf.set(name, orphanRing);

  const byRing = new Map<number, string[]>();
  for (const name of names) {
    const ring = ringOf.get(name)!;
    if (!byRing.has(ring)) byRing.set(ring, []);
    byRing.get(ring)!.push(name);
  }

  const placed: Placed[] = [];
  for (const [ring, members] of Array.from(byRing.entries()).sort((a, b) => a[0] - b[0])) {
    members.sort();
    if (ring === 0) {
      placed.push({ name: members[0], x: 0, y: 0, ring, node: byName.get(members[0]) });
      continue;
    }
    // A ring wide enough that the boxes never overlap: the circumference has
    // to hold every member at its full width plus a gutter.
    const spacing = NODE_WIDTH + 70;
    const radius = Math.max(ring * RING_GAP, (members.length * spacing) / (2 * Math.PI));
    members.forEach((name, index) => {
      // Start at the top and go clockwise, and offset odd rings by half a step
      // so a ring never lines its boxes up directly behind the ring inside it.
      const turn = (index / members.length) * 2 * Math.PI
        - Math.PI / 2
        + (ring % 2 ? Math.PI / members.length : 0);
      placed.push({
        name,
        x: Math.cos(turn) * radius,
        y: Math.sin(turn) * radius * 0.72,
        ring,
        node: byName.get(name),
      });
    });
  }
  return { placed, rings: Math.max(...placed.map((p) => p.ring)) + 1 };
}

