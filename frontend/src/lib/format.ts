/**
 * Number and label formatting.
 *
 * Credit-risk figures are read in columns and compared at a glance, so the
 * rules here are about legibility rather than decoration: thousands separators
 * always, a fixed number of decimals per unit, and an explicit sign on anything
 * that represents a movement. Tabular figures are applied in globals.css so the
 * digits line up.
 */

/** Money in USD millions — the unit the whole portfolio is denominated in. */
export function money(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Large money, abbreviated to billions once it stops being readable. */
export function moneyCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(2)}bn`;
  return `${money(value, 0)}mn`;
}

export function percent(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

/** A movement, always signed, so a fall is never mistaken for a level. */
export function delta(value: number | null | undefined, decimals = 2, suffix = ""): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}${suffix}`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

/**
 * Which way is good.
 *
 * In credit risk most metrics are bad when they rise — ECL, NPL, stage 2 — so
 * the caller states the direction rather than the component guessing it.
 */
export type Direction = "up-is-bad" | "up-is-good" | "neutral";

export function toneFor(value: number, direction: Direction): "positive" | "negative" | "muted" {
  if (direction === "neutral" || value === 0) return "muted";
  const good = direction === "up-is-good" ? value > 0 : value < 0;
  return good ? "positive" : "negative";
}

/** Format any value the engine returned, using the unit it declared. */
export function byUnit(value: unknown, unit?: string | null): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  if (typeof value !== "number" || Number.isNaN(value)) return String(value);
  switch (unit) {
    case "%":
      return percent(value);
    case "pp":
      return `${value.toFixed(2)}pp`;
    case "USD mn":
      // Thousands of millions do not need a decimal; a single facility does.
      return money(value, Math.abs(value) >= 1000 ? 0 : 1);
    case "days":
    case "facilities":
    case "count":
      return count(value);
    case "x":
      return `${value.toFixed(2)}x`;
    default:
      return Number.isInteger(value) ? count(value) : money(value, 2);
  }
}

/**
 * One value, formatted the way its column's display contract says.
 *
 * The contract comes from the backend, where the semantic ontology knows what
 * a concept is: money in millions, an ordinal grade, a ratio, a count of days.
 * Guessing from the column name here produced 73391.774000000012 in a table a
 * credit officer was reading — the right number, looking like a defect.
 */
export function byContract(value: unknown, column?: ColumnSpec | null): string {
  if (!column) return byUnit(value);
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value !== "number" || Number.isNaN(value)) return String(value);

  const decimals =
    column.semantic === "money" && Math.abs(value) < 1000
      ? Math.max(column.decimals ?? 0, 2)
      : (column.decimals ?? 2);
  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  if (column.unit === "%") return `${text}%`;
  return column.unit ? `${text} ${column.unit}` : text;
}

/** What a column IS, as the backend's presentation contract describes it. */
export interface ColumnSpec {
  name: string;
  label?: string;
  semantic?: string;
  unit?: string;
  currency?: string;
  scale?: string;
  decimals?: number;
  align?: string;
  is_identity?: boolean;
  role?: string;
}

/** Turn a governed field name into a column heading: ead_pct -> "Ead Pct". */
export function humanise(key: string): string {
  const overrides: Record<string, string> = {
    ead: "EAD",
    ead_pct: "EAD %",
    total_ecl: "Total ECL",
    ecl_change: "ECL change",
    ecl_coverage_pct: "ECL coverage",
    coverage_pct: "Coverage",
    npl_pct: "NPL %",
    npl_ratio_pct: "NPL ratio",
    ifrs9_stage: "Stage",
    stage2_pct: "Stage 2 %",
    stage3_pct: "Stage 3 %",
    dpd_days: "DPD",
    pd_change: "PD change",
    row_pct: "Share of row",
    largest_obligor_pct: "Largest name",
    facility_count: "Facilities",
    borrower_count: "Borrowers",
    weighted_pd_pct: "Weighted PD",
    weighted_lgd_pct: "Weighted LGD",
    utilisation_pct: "Utilisation",
    utilisation_change_pp: "Utilisation change",
    notch_change: "Notches",
    stage_change: "Stage change",
    dpd_change: "DPD change",
    from: "From",
    to: "To",
  };
  if (overrides[key]) return overrides[key];
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bPct\b/, "%")
    .replace(/\bEcl\b/, "ECL")
    .replace(/\bEad\b/, "EAD")
    .replace(/\bPd\b/, "PD")
    .replace(/\bLgd\b/, "LGD");
}

/**
 * The unit as it should appear beside a figure, not inside it.
 *
 * A KPI tile shows "48,600" in the display size and "USD mn" small beside it —
 * repeating the unit at full size on four tiles in a row is noise, and dropping
 * it altogether leaves the reader guessing between millions and billions.
 */
export function unitSuffix(unit?: string | null): string {
  if (!unit) return "";
  if (unit === "%" || unit === "pp" || unit === "x") return "";
  return unit;
}

export function titleCase(value: string): string {
  return value.replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/* -------------------------------------------------------------------------- */
/*  Semantic figures                                                           */
/* -------------------------------------------------------------------------- */

/**
 * A figure and its unit, kept apart.
 *
 * Every number in the product is formatted through here so a table, a KPI tile
 * and a chart tooltip cannot disagree about what "12,261" means. The unit is
 * returned separately rather than glued on, because a table puts it in the
 * column header once and a tile sets it small beside the value — and a column
 * that repeats "USD mn" on all twenty-five rows is twenty-four wasted
 * repetitions of the one fact that does not change.
 */
export interface Figure {
  /** The number, formatted. Never carries the unit. */
  text: string;
  /** The unit as it should be shown, or "" when the format already implies it. */
  unit: string;
  /** True when the value was scaled — 12,261 USD mn shown as 12.3, unit "bn". */
  scaled: boolean;
}

const EMPTY: Figure = { text: "—", unit: "", scaled: false };

/**
 * Money held in millions, scaled to the magnitude a person would say out loud.
 *
 * A credit officer says "twelve point three billion", never "twelve thousand
 * two hundred and sixty-one million". Below a thousand millions the figure
 * stays in millions, because that is how a single facility is discussed.
 */
export function scaleMoney(
  value: number,
  currency = "USD",
  scale = "mn",
): Figure {
  const abs = Math.abs(value);
  if (scale === "mn" && abs >= 1000) {
    const billions = value / 1000;
    return {
      text: billions.toLocaleString("en-US", {
        minimumFractionDigits: 1,
        maximumFractionDigits: abs >= 100_000 ? 0 : 1,
      }),
      unit: `${currency} bn`,
      scaled: true,
    };
  }
  // One decimal, always, below a billion. A single facility at 321.8 rounded
  // to 322 has lost the precision the reader is checking the figure for, and
  // the column is no wider for keeping it.
  return {
    text: value.toLocaleString("en-US", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }),
    unit: `${currency} ${scale}`,
    scaled: false,
  };
}

/**
 * One value as a figure plus a unit, following the column's contract.
 *
 * This is `byContract` split in two. The old one returned "12,261 USD mn" as a
 * single string, which is correct and unreadable in a column of twenty-five,
 * and gave a table no way to lift the unit into its header.
 */
export function figure(value: unknown, column?: ColumnSpec | null): Figure {
  if (value === null || value === undefined) return EMPTY;
  if (typeof value === "boolean") {
    return { text: value ? "Yes" : "No", unit: "", scaled: false };
  }
  if (typeof value !== "number" || Number.isNaN(value)) {
    return { text: String(value), unit: "", scaled: false };
  }

  const semantic = column?.semantic ?? "";
  const unit = column?.unit ?? "";

  if (semantic === "money" || unit === "USD mn" || unit === "SAR mn") {
    const [currency, scale] = unit.split(" ");
    return scaleMoney(value, column?.currency ?? currency ?? "USD", scale ?? "mn");
  }
  if (unit === "%" || semantic === "percent" || semantic === "share") {
    return {
      text: value.toFixed(column?.decimals ?? 2),
      unit: "%",
      scaled: false,
    };
  }
  if (unit === "pp") {
    return { text: value.toFixed(column?.decimals ?? 2), unit: "pp", scaled: false };
  }
  if (unit === "x" || semantic === "ratio") {
    return { text: value.toFixed(column?.decimals ?? 2), unit: "x", scaled: false };
  }
  if (unit === "days" || semantic === "days") {
    return { text: count(value), unit: "days", scaled: false };
  }
  if (semantic === "count" || Number.isInteger(value)) {
    return { text: count(value), unit: "", scaled: false };
  }
  return {
    text: value.toLocaleString("en-US", {
      minimumFractionDigits: column?.decimals ?? 2,
      maximumFractionDigits: column?.decimals ?? 2,
    }),
    unit,
    scaled: false,
  };
}

/**
 * The unit a whole column shares, for its header — or "" when the rows differ.
 *
 * Money is the case that matters: a column whose values straddle the billion
 * boundary would show "12.3" and "840.0" under one header, meaning two
 * different things. When that happens the unit stays on the rows.
 */
export function columnUnit(values: unknown[], column?: ColumnSpec | null): string {
  const figures = values
    .filter((v) => typeof v === "number" && !Number.isNaN(v))
    .map((v) => figure(v, column));
  if (!figures.length) return "";
  const units = new Set(figures.map((f) => f.unit));
  return units.size === 1 ? [...units][0] : "";
}

/** A movement, with its sign, as a figure. */
export function deltaFigure(value: number, column?: ColumnSpec | null): Figure {
  const base = figure(Math.abs(value), column);
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return { ...base, text: `${sign}${base.text}` };
}
