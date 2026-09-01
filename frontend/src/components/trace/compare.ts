/**
 * What changed between two versions of one analysis.
 *
 * §49 asks for version comparison, and the question behind it is always the
 * same: somebody modified the Trace and a colleague wants to know what that
 * did. "Version 3" and "version 4" side by side answers it only if the reader
 * is prepared to read two graphs and hold them in their head.
 *
 * So this reduces two stored versions to what actually differs — steps added,
 * steps removed, steps whose status or row count moved, and how the answer
 * itself changed. React-free and pure, because a diff is exactly the kind of
 * thing that is easy to get subtly wrong and easy to assert.
 *
 * Nothing is recomputed. Both sides are versions the runtime already produced
 * and persisted; this reads them.
 */

export interface ComparableNode {
  id: string;
  type?: string;
  label?: string;
  status?: string;
  rows_out?: number | null;
}

export interface ComparableVersion {
  version: number;
  label?: string;
  nodes: ComparableNode[];
  /** The direct answer, as it was shown for this version. */
  answer?: string;
  /** How many rows the result carried. */
  rowCount?: number | null;
}

export type ChangeKind = "added" | "removed" | "status" | "rows" | "label";

export interface NodeChange {
  id: string;
  kind: ChangeKind;
  label: string;
  /** What it was, and what it became. Empty on an add or a remove. */
  before: string;
  after: string;
}

export interface Comparison {
  from: number;
  to: number;
  changes: NodeChange[];
  /** True where the two versions produced the same answer. */
  sameAnswer: boolean;
  answerBefore: string;
  answerAfter: string;
  rowsBefore: number | null;
  rowsAfter: number | null;
}

/**
 * The difference between two versions, oldest first.
 *
 * Arguments are ordered rather than sorted here: the caller knows which
 * version the reader is looking at and which they picked to compare against,
 * and silently swapping them would reverse every "before" and "after" in the
 * panel without saying so.
 */
export function compare(
  from: ComparableVersion,
  to: ComparableVersion,
): Comparison {
  const before = new Map(from.nodes.map((n) => [n.id, n]));
  const after = new Map(to.nodes.map((n) => [n.id, n]));
  const changes: NodeChange[] = [];

  for (const node of to.nodes) {
    const was = before.get(node.id);
    if (!was) {
      changes.push({
        id: node.id,
        kind: "added",
        label: node.label ?? node.id,
        before: "",
        after: node.status ?? "",
      });
      continue;
    }
    if ((was.status ?? "") !== (node.status ?? "")) {
      changes.push({
        id: node.id,
        kind: "status",
        label: node.label ?? node.id,
        before: was.status ?? "—",
        after: node.status ?? "—",
      });
    }
    if (numberOf(was.rows_out) !== numberOf(node.rows_out)) {
      changes.push({
        id: node.id,
        kind: "rows",
        label: node.label ?? node.id,
        before: text(was.rows_out),
        after: text(node.rows_out),
      });
    }
    // A relabelled step is worth showing: the planner rewrote what the step
    // says it does, and a reviewer who approved the old wording did not
    // approve the new one.
    if ((was.label ?? "") !== (node.label ?? "")) {
      changes.push({
        id: node.id,
        kind: "label",
        label: node.label ?? node.id,
        before: was.label ?? "",
        after: node.label ?? "",
      });
    }
  }

  for (const node of from.nodes) {
    if (!after.has(node.id)) {
      changes.push({
        id: node.id,
        kind: "removed",
        label: node.label ?? node.id,
        before: node.status ?? "",
        after: "",
      });
    }
  }

  return {
    from: from.version,
    to: to.version,
    changes,
    sameAnswer: (from.answer ?? "").trim() === (to.answer ?? "").trim(),
    answerBefore: from.answer ?? "",
    answerAfter: to.answer ?? "",
    rowsBefore: numberOf(from.rowCount),
    rowsAfter: numberOf(to.rowCount),
  };
}

function numberOf(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function text(value: unknown): string {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

/**
 * The comparison in a sentence, for the panel's heading.
 *
 * A comparison that found nothing is a real and useful answer — the
 * modification changed how the analysis was described and not what it
 * computed — so it says that rather than showing an empty list.
 */
export function summarise(found: Comparison): string {
  const counts = {
    added: found.changes.filter((c) => c.kind === "added").length,
    removed: found.changes.filter((c) => c.kind === "removed").length,
    moved: found.changes.filter((c) => c.kind === "rows").length,
  };
  const parts: string[] = [];
  if (counts.added) parts.push(`${counts.added} step${plural(counts.added)} added`);
  if (counts.removed)
    parts.push(`${counts.removed} step${plural(counts.removed)} removed`);
  if (counts.moved)
    parts.push(`${counts.moved} row count${plural(counts.moved)} changed`);

  if (parts.length === 0) {
    return found.sameAnswer
      ? "Nothing computed differently. The two versions produced the same answer."
      : "The steps are the same; the answer differs.";
  }
  return parts.join(", ") + ".";
}

function plural(count: number): string {
  return count === 1 ? "" : "s";
}
