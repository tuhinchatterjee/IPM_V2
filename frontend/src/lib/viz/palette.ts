/**
 * The governed semantic palette for every Plotly visual in CreditProbe.
 *
 * ONE place. Charts never pick a colour: they name a SEMANTIC (a driver
 * family, a direction, a stage, a severity) and this module answers. That is
 * what makes a PD bar the same violet in the selected-scope bridge, the
 * total-book bridge, a reopened scenario and an export, and what stops the
 * product turning into a wall of identical blue bars.
 *
 * The driver tokens are the master specification's §10.2 table, verbatim.
 * Meaning is never carried by colour alone: every bar also carries a signed
 * label, and increase/decrease use a sign and an annotation as well as
 * coral/emerald (checked in `palette.test.ts` for luminance separation).
 */

export const SEMANTIC = {
  baseline: "#64748B", // slate — opening/closing totals, neutral
  pd: "#7C3AED", // violet
  lgd: "#F59E0B", // amber
  ccf: "#0EA5E9", // sky — CCF / EAD / exposure
  stage: "#EC4899", // magenta — stage migration
  macro: "#14B8A6", // teal
  userDefined: "#6366F1", // indigo — user-defined / overlay
  increase: "#EF4444", // coral-red — deterioration / ECL increase
  decrease: "#10B981", // emerald — improvement / ECL decrease
  residual: "#94A3B8", // cool gray — interaction / residual
  rating: "#8B5CF6", // violet-light — rating / score movement
  sector: "#F97316", // orange — sector / segment rules
  calibration: "#A16207", // ochre — methodology calibration gap
  selected: "#2563EB", // selected cohort vs total-book context
  context: "#CBD5E1",
} as const;

export type SemanticToken = keyof typeof SEMANTIC;

/**
 * The universal ECL decomposition driver taxonomy: stable id, label, order
 * and colour. Every bridge in the product -- historical movement, What-If on
 * a customer, a cohort or the whole book, comparisons, reopen, export -- is
 * drawn from this list, so the same driver has the same identity everywhere.
 * The server (`backend/workspace/decomposition.py`) owns the same list and a
 * test pins the two together.
 */
export const DRIVERS = [
  { id: "pd", label: "PD", token: "pd" },
  { id: "lgd", label: "LGD", token: "lgd" },
  { id: "ccf_ead", label: "CCF / EAD", token: "ccf" },
  { id: "rating_score", label: "Rating / score", token: "rating" },
  { id: "stage", label: "Stage / SICR", token: "stage" },
  { id: "macro", label: "Macro (MEV)", token: "macro" },
  { id: "sector_segment", label: "Sector / segment", token: "sector" },
  { id: "user_defined", label: "User-defined / overlay", token: "userDefined" },
  { id: "new_business", label: "New business", token: "ccf" },
  { id: "exits", label: "Exits / repayments", token: "decrease" },
  { id: "calibration_gap", label: "Calibration gap", token: "calibration" },
  { id: "residual", label: "Interaction / residual", token: "residual" },
] as const satisfies readonly { id: string; label: string; token: SemanticToken }[];

export type DriverId = (typeof DRIVERS)[number]["id"];

export function driverColor(id: string): string {
  const found = DRIVERS.find((d) => d.id === id);
  return SEMANTIC[(found?.token ?? "residual") as SemanticToken];
}

export function driverLabel(id: string): string {
  return DRIVERS.find((d) => d.id === id)?.label ?? id;
}

export function driverOrder(id: string): number {
  const index = DRIVERS.findIndex((d) => d.id === id);
  return index < 0 ? DRIVERS.length : index;
}

/** Stage colours: calm → alarming, legible without colour via labels. */
export const STAGE_COLORS: Record<string, string> = {
  "1": "#10B981",
  "2": "#F59E0B",
  "3": "#EF4444",
};

/** Severity for issues and alerts. */
export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#B91C1C",
  high: "#EF4444",
  moderate: "#F59E0B",
  medium: "#F59E0B",
  low: "#0EA5E9",
  informational: "#64748B",
};

/**
 * A categorical sequence for dimensions with no semantic meaning (sectors,
 * products, regions). Ten hues, ordered for adjacent contrast; deliberately
 * NOT ten shades of blue.
 */
export const CATEGORICAL = [
  "#2563EB",
  "#F97316",
  "#10B981",
  "#8B5CF6",
  "#EC4899",
  "#14B8A6",
  "#EAB308",
  "#EF4444",
  "#6366F1",
  "#84CC16",
];

export function categorical(index: number): string {
  return CATEGORICAL[((index % CATEGORICAL.length) + CATEGORICAL.length) % CATEGORICAL.length];
}

/** Relative luminance, for the colour-blind legibility checks. */
export function luminance(hex: string): number {
  const v = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
