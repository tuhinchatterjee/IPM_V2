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
 * The universal ECL decomposition taxonomy: stable id, label, order and
 * colour. Every decomposition in the product -- a scenario's selected scope
 * and total book, a method comparison, a reopened or shared result, an
 * export -- is drawn from this list, so the same component has the same
 * identity everywhere. The server owns the same ids in the same order
 * (`backend/cockpit_v4/scenario/decomposition.py` TAXONOMY) and
 * `tests/cockpit_v4/test_gw_decomposition_palette.py` pins the two together.
 *
 * Colours are deliberately varied (not one blue): each driver family keeps
 * its §10.2 token, and the between-period flows get their own hues.
 */
export const DRIVERS = [
  { id: "opening", label: "Opening ECL", color: SEMANTIC.baseline },
  { id: "new_originations", label: "New originations", color: "#0891B2" },
  { id: "repayment_amortisation", label: "Repayment / amortisation", color: "#65A30D" },
  { id: "stage_1_to_2", label: "Stage 1 → 2", color: SEMANTIC.stage },
  { id: "stage_2_to_3", label: "Stage 2 → 3", color: "#BE185D" },
  { id: "cures", label: "Cures", color: SEMANTIC.decrease },
  { id: "new_defaults", label: "New defaults", color: "#DC2626" },
  { id: "pd", label: "PD", color: SEMANTIC.pd },
  { id: "lgd", label: "LGD", color: SEMANTIC.lgd },
  { id: "ccf_ead", label: "CCF / EAD / utilisation", color: SEMANTIC.ccf },
  { id: "collateral", label: "Collateral", color: "#B45309" },
  { id: "rating_score", label: "Rating / score migration", color: SEMANTIC.rating },
  { id: "macro", label: "Macro (MEV)", color: SEMANTIC.macro },
  { id: "sector_segment", label: "Sector / segment rule", color: SEMANTIC.sector },
  { id: "management_overlay", label: "Management overlay / user-defined", color: SEMANTIC.userDefined },
  { id: "recoveries", label: "Recoveries / write-offs", color: "#4D7C0F" },
  { id: "unattributed_method_effect", label: "Method effect (not attributable)", color: SEMANTIC.selected },
  { id: "calibration_gap", label: "Calibration gap", color: SEMANTIC.calibration },
  { id: "residual", label: "Interaction / residual", color: SEMANTIC.residual },
  { id: "closing", label: "Closing ECL", color: "#334155" },
] as const satisfies readonly { id: string; label: string; color: string }[];

export type DriverId = (typeof DRIVERS)[number]["id"];

/** Older driver names still used by some callers, mapped to the taxonomy. */
const ALIASES: Record<string, DriverId> = {
  stage: "stage_1_to_2",
  user_defined: "management_overlay",
  new_business: "new_originations",
  exits: "repayment_amortisation",
};

function driver(id: string) {
  const key = ALIASES[id] ?? id;
  return DRIVERS.find((d) => d.id === key);
}

export function driverColor(id: string): string {
  return driver(id)?.color ?? SEMANTIC.residual;
}

export function driverLabel(id: string): string {
  return driver(id)?.label ?? id;
}

export function driverOrder(id: string): number {
  const found = driver(id);
  return found ? DRIVERS.indexOf(found) : DRIVERS.length;
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
