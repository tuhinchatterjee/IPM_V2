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
