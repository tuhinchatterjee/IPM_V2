import type { RunMode, SupportedModification, TraceGraph } from "@/lib/api";

/**
 * What is worth changing about THIS Trace.
 *
 * The failure this fixes
 * ----------------------
 * Every Trace offered the same chips: "Only show Real Estate", "Exclude Real
 * Estate", "Add ECL Movement". Under a Trace for "what fields are in the
 * ratings data?" they are nonsense — there is no sector to exclude and no
 * analysis to add, because nothing was computed. Under a Trace for a
 * Contracting screen they are worse than nonsense: they name a sector the
 * analysis is not about, and a reader who clicks one gets an answer to a
 * question they did not ask.
 *
 * Two rules
 * ---------
 * **A metadata Trace gets navigation, not modification.** Nothing was
 * computed, so there is nothing to recompute. What a reader wants next is the
 * data itself, its fields, or what it connects to.
 *
 * **An analysis Trace gets ITS OWN scope in the examples.** The dimension the
 * analysis grouped by, the measure it reported, the filter it applied. A chip
 * that says "Only show Contracting" under a Contracting analysis is a chip
 * nobody needs; one that says "Only show Real Estate" under it is a chip that
 * changes the subject.
 */

export interface TraceAction {
  kind: string;
  label: string;
  /** The sentence the chip sends, in this Trace's own terms. */
  example: string;
}

/** What kind of run this Trace records. */
export function traceKind(mode: RunMode | undefined): "metadata" | "analysis" {
  return mode?.execution === "metadata" ? "metadata" : "analysis";
}

/**
 * The scope this Trace is about, read off its own nodes.
 *
 * Everything here was stamped by execution, so a chip built from it names
 * something that is genuinely in the analysis rather than something a template
 * guessed at.
 */
interface Scope {
  dataset: string;
  dimension: string;
  measure: string;
  filterValue: string;
}

function scopeOf(graph: TraceGraph): Scope {
  const nodes = graph.nodes ?? [];
  const first = (type: string) => nodes.find((n) => n.type === type);

  const dataset = first("DATASET")?.dataset ?? first("DATASET")?.label ?? "";
  const measure =
    first("AGGREGATION")?.label ??
    first("DERIVED_VARIABLE")?.label ??
    first("VARIABLE")?.label ??
    "";

  // A filter node's label reads "Sector = Contracting"; both halves are useful
  // and they are useful for different chips.
  const filter = first("FILTER")?.label ?? "";
  const [dimension, value] = splitFilter(filter);

  return {
    dataset,
    dimension,
    measure,
    filterValue: value,
  };
}

function splitFilter(label: string): [string, string] {
  const match = label.match(/^\s*([^=:]+?)\s*[=:]\s*(.+?)\s*$/);
  if (!match) return ["", ""];
  return [match[1] ?? "", match[2] ?? ""];
}

/** Navigation a metadata Trace can offer, built from the dataset it read. */
function metadataActions(graph: TraceGraph): TraceAction[] {
  const { dataset } = scopeOf(graph);
  const named =
    dataset ||
    graph.nodes.find((n) => n.type === "GOVERNED_METADATA")?.dataset ||
    "";

  if (!named) {
    return [
      { kind: "open_catalogue", label: "Open the catalogue", example: "What data do you have?" },
    ];
  }
  return [
    { kind: "open_dataset", label: "Open the dataset", example: `Open ${named}.` },
    { kind: "show_fields", label: "Show the fields", example: `What fields are in ${named}?` },
    {
      kind: "show_relationships",
      label: "Show the relationships",
      example: `How is ${named} connected to other data?`,
    },
    {
      kind: "compare_periods",
      label: "Compare periods",
      example: `How many periods of ${named} are there?`,
    },
  ];
}

/**
 * Modifications an analysis Trace can offer, in its own terms.
 *
 * The supported list comes from the backend, so the two can never drift about
 * what is possible. What happens here is only the wording: the example is
 * rewritten to name what this analysis actually did, and an option that cannot
 * mean anything for this run is dropped rather than shown as a dead chip.
 */
function analysisActions(
  graph: TraceGraph,
  supported: SupportedModification[],
): TraceAction[] {
  const scope = scopeOf(graph);
  const out: TraceAction[] = [];

  for (const option of supported) {
    const example = rewrite(option, scope);
    if (example === null) continue;
    out.push({ kind: option.kind, label: option.label, example });
  }
  return out;
}

function rewrite(
  option: SupportedModification,
  scope: Scope,
): string | null {
  const { dimension, measure, filterValue } = scope;

  switch (option.kind) {
    case "only":
      // Narrowing to what it is already narrowed to changes nothing.
      if (filterValue) return null;
      return dimension ? `Only show one ${lower(dimension)}.` : option.example;
    case "exclude":
      return filterValue
        ? `Exclude ${filterValue}.`
        : dimension
          ? `Exclude one ${lower(dimension)}.`
          : option.example;
    case "clear_filters":
      return filterValue ? `Remove the ${lower(dimension)} filter.` : null;
    case "set_basis":
      return measure
        ? `Use number of customers instead of ${lower(measure)}.`
        : option.example;
    case "set_period":
      return "Compare against the same quarter a year earlier.";
    case "set_top_n":
      return option.example;
    default:
      return option.example;
  }
}

function lower(text: string): string {
  const first = text.trim().split(" ")[0] ?? "";
  if (first === first.toUpperCase() && first.length > 1) return text.trim();
  return text.trim().charAt(0).toLowerCase() + text.trim().slice(1);
}

/** The chips to show under this Trace. */
export function traceActions(
  graph: TraceGraph,
  mode: RunMode | undefined,
  supported: SupportedModification[],
): TraceAction[] {
  return traceKind(mode) === "metadata"
    ? metadataActions(graph)
    : analysisActions(graph, supported);
}
