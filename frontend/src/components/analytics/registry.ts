/**
 * Which picture this result should be, decided from the RESULT'S SHAPE.
 *
 * §21: "The registry should choose visualizations from RESULT SHAPE, not from
 * arbitrary LLM prose." That constraint is the whole design. A model that
 * writes "show this as a Sankey" has made a claim about data it has not seen
 * the shape of; a function that reads the column contract — what each column
 * IS, what it measures, whether it identifies a row, whether it is a period —
 * cannot make that mistake, and can be tested with a fixture instead of a
 * conversation.
 *
 * The columns arrive already classified. The backend's presentation contract
 * records each column's semantic type, its unit, whether it is an identity and
 * where it ranks in the answer. That is a far better basis for choosing a chart
 * than the column names, and it is why this module can be short.
 *
 * The default is a TABLE, and it wins whenever a chart would mislead. §22 lists
 * exactly when: too many categories, unreadable labels, record-level results,
 * precision over pattern, heterogeneous columns. A bar chart of two hundred
 * borrowers is not a picture of anything.
 *
 * Free of React so `node --test` can assert the decision table directly.
 */

import type { ColumnSpec } from "@/lib/format";
import type { Row } from "@/lib/api";

/** Every form the registry can choose. §21's list, plus the table. */
export type ChartKind =
  | "kpi"
  | "bar"
  | "horizontal-bar"
  | "grouped-bar"
  | "stacked-bar"
  | "line"
  | "area"
  | "stacked-area"
  | "waterfall"
  | "diverging-bar"
  | "heatmap"
  | "matrix"
  | "transition-matrix"
  | "sankey"
  | "treemap"
  | "scatter"
  | "bubble"
  | "histogram"
  | "small-multiples"
  | "risk-landscape"
  | "table";

export interface Choice {
  kind: ChartKind;
  /** The column along the bottom, where the form has one. */
  x?: string;
  /** The measures drawn, in the contract's own order. */
  series: string[];
  /** Why this form — shown in the chart's own control, so it is inspectable. */
  because: string;
  /** Other forms this shape genuinely supports, for the reader to switch to. */
  alternatives: ChartKind[];
}

/**
 * Above this many categories a bar chart stops being readable.
 *
 * Twelve is where the labels start overlapping at the widths this product
 * renders at, and twenty-five is where the bars themselves become hairlines.
 * Between the two a horizontal bar chart still works, because the labels have
 * a whole row each.
 */
const VERTICAL_BARS_MAX = 12;
const HORIZONTAL_BARS_MAX = 25;

/** A period column, however the plan happened to name it. */
const PERIOD_HINT = /(^|_)(period|quarter|month|year|as_of|date)($|_)/i;

/** A column holding a signed change rather than a level. */
const CHANGE_HINT = /(change|movement|delta|_pp$|_diff)/i;

/** A from/to pair, which is what a transition or a flow is made of. */
const FROM_HINT = /(^|_)(from|opening|source)($|_)/i;
const TO_HINT = /(^|_)(to|closing|target|destination)($|_)/i;

interface Shaped {
  identity: ColumnSpec[];
  period: ColumnSpec[];
  numeric: ColumnSpec[];
  categorical: ColumnSpec[];
  change: ColumnSpec[];
}

/** What the columns are, before any decision is taken about them. */
export function shapeOf(columns: ColumnSpec[], rows: Row[]): Shaped {
  const visible = columns.filter((c) => !c.hidden);
  const numericByData = (c: ColumnSpec) =>
    rows.some((row) => typeof row[c.name] === "number");

  const period = visible.filter(
    (c) => c.semantic === "period" || PERIOD_HINT.test(c.name),
  );
  const rest = visible.filter((c) => !period.includes(c));
  const identity = rest.filter((c) => c.is_identity);
  const numeric = rest.filter(
    (c) => !c.is_identity && (numericByData(c) || isNumericSemantic(c)),
  );
  const categorical = rest.filter(
    (c) => !c.is_identity && !numeric.includes(c),
  );
  const change = numeric.filter(
    (c) => CHANGE_HINT.test(c.name) || c.role === "change",
  );

  return { identity, period, numeric, categorical, change };
}

function isNumericSemantic(column: ColumnSpec): boolean {
  return ["money", "percent", "ratio", "count", "days"].includes(
    column.semantic ?? "",
  );
}

/**
 * The chart this result should open as, and what else it could be.
 *
 * Read top to bottom: the first rule that matches wins, and they are ordered by
 * how specific the shape is. A transition matrix is a very particular shape and
 * a category-plus-measure is a very common one, so the particular ones are
 * tested first.
 */
export function chooseVisualization(
  columns: ColumnSpec[],
  rows: Row[],
): Choice {
  const shape = shapeOf(columns, rows);
  const dimension = shape.identity[0] ?? shape.categorical[0] ?? null;
  const measures = shape.numeric.filter((c) => !shape.change.includes(c));
  const measure = measures[0] ?? shape.numeric[0] ?? null;

  // Nothing to draw.
  if (rows.length === 0 || !measure) {
    return table("The result has no measure to draw.");
  }

  // One row, one figure: there is no distribution and no trend, and a bar of
  // one bar is a number wearing a costume.
  if (rows.length === 1 && !shape.period.length) {
    return {
      kind: "kpi",
      series: measures.map((c) => c.name),
      because: "One row: the figures are the answer.",
      alternatives: ["table"],
    };
  }

  // A from/to pair with a measure IS a transition. Stage migration, rating
  // transition, DPD bucket movement — the shape and the meaning coincide.
  const from = shape.categorical.find((c) => FROM_HINT.test(c.name));
  const to = shape.categorical.find((c) => TO_HINT.test(c.name));
  if (from && to && from !== to) {
    return {
      kind: "transition-matrix",
      x: from.name,
      series: [measure.name],
      because: `Every row moves from ${label(from)} to ${label(to)}.`,
      alternatives: ["sankey", "heatmap", "table"],
    };
  }

  // A period column and a measure is a trend, whatever else is present.
  if (shape.period.length > 0) {
    const period = shape.period[0];
    const groups = dimension ? distinct(rows, dimension.name) : 0;
    if (dimension && groups > 1) {
      return {
        kind: groups <= 6 ? "line" : "small-multiples",
        x: period.name,
        series: [measure.name],
        because:
          groups <= 6
            ? `${groups} series over ${rows.length} periods.`
            : `${groups} series is too many to read on one axis.`,
        alternatives: ["stacked-area", "grouped-bar", "table"],
      };
    }
    return {
      kind: "line",
      x: period.name,
      series: measures.slice(0, 3).map((c) => c.name),
      because: `A measure over ${rows.length} periods.`,
      alternatives: ["area", "bar", "table"],
    };
  }

  // A signed change per category is a waterfall or a diverging bar: the zero
  // line is the point, and a plain bar chart hides it.
  if (shape.change.length > 0 && dimension) {
    if (rows.length > HORIZONTAL_BARS_MAX) {
      return table(
        `${rows.length} contributors is past the point where bars can be read.`,
      );
    }
    return {
      kind: "diverging-bar",
      x: dimension.name,
      series: [shape.change[0].name],
      because: "The figures are signed changes, so the zero line is the point.",
      alternatives: ["waterfall", "bar", "table"],
    };
  }

  // Two measures against each other, per named thing, is a scatter — and three
  // is a bubble, with the third as size.
  if (dimension && measures.length >= 2 && rows.length > 6) {
    return {
      kind: measures.length >= 3 ? "bubble" : "scatter",
      x: measures[0].name,
      series: measures.slice(1, 3).map((c) => c.name),
      because:
        measures.length >= 3
          ? "Three measures per name: two positions and a size."
          : "Two measures per name, which is a relationship rather than a ranking.",
      alternatives: ["risk-landscape", "table"],
    };
  }

  // A category and one measure: the ordinary case, and the count decides.
  if (dimension && measures.length >= 1) {
    if (rows.length > HORIZONTAL_BARS_MAX) {
      return table(
        `${rows.length} ${label(dimension).toLowerCase()} values is too many ` +
          `for a chart; the table stays readable.`,
      );
    }
    if (measures.length > 1) {
      return {
        kind: "grouped-bar",
        x: dimension.name,
        series: measures.slice(0, 3).map((c) => c.name),
        because: `${measures.length} measures across ${rows.length} groups.`,
        alternatives: ["stacked-bar", "table"],
      };
    }
    return {
      kind: rows.length <= VERTICAL_BARS_MAX ? "bar" : "horizontal-bar",
      x: dimension.name,
      series: [measure.name],
      because:
        rows.length <= VERTICAL_BARS_MAX
          ? `${rows.length} groups, one measure.`
          : `${rows.length} groups: the labels need a row each.`,
      alternatives: ["treemap", "table"],
    };
  }

  // Record-level output — a list of facilities with their attributes. §22 says
  // a table, and it is right: precision matters more than pattern here.
  return table("The result is record-level, where precision beats pattern.");
}

function table(because: string): Choice {
  return { kind: "table", series: [], because, alternatives: [] };
}

function distinct(rows: Row[], key: string): number {
  return new Set(rows.map((row) => String(row[key] ?? ""))).size;
}

function label(column: ColumnSpec): string {
  return column.label ?? column.name;
}

/** Whether a chart form is one this result could honestly be drawn as. */
export function supports(choice: Choice, kind: ChartKind): boolean {
  return kind === choice.kind || choice.alternatives.includes(kind);
}
