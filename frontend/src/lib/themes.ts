/**
 * The four IPM themes.
 *
 * A theme is nothing more than a set of values for the semantic tokens defined
 * in globals.css. It changes background, surface, border, text, accent, status
 * and chart colours — and nothing else. Layout, typography, spacing, hierarchy
 * and interaction are identical across all four, so switching theme changes how
 * IPM looks and never how it works.
 *
 * The swatches below are for the Theme Gallery preview only. The values that
 * actually render the application live in globals.css; these mirror three of
 * them so the gallery can show a card without mounting the theme.
 */

export type ThemeId =
  | "executive-light"
  | "midnight"
  | "graphite"
  | "warm-institutional";

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  /** One line, shown under the name in the Theme Gallery. */
  description: string;
  /** "light" | "dark" — drives the icon and groups the gallery. */
  mode: "light" | "dark";
  /** Preview swatches: [canvas, surface, accent]. */
  swatch: [string, string, string];
}

export const THEMES: ThemeDefinition[] = [
  {
    id: "executive-light",
    name: "Executive Light",
    description:
      "Paper-like and high contrast. Reads as a printed board pack rather than a screen.",
    mode: "light",
    swatch: ["#f6f7f9", "#ffffff", "#10527a"],
  },
  {
    id: "midnight",
    name: "Midnight",
    description:
      "Deep navy-black, for long analytical sessions and presentation rooms.",
    mode: "dark",
    swatch: ["#0a0f16", "#111823", "#4d9fd4"],
  },
  {
    id: "graphite",
    name: "Graphite",
    description:
      "Neutral low-chroma grey. Sober and engineering-toned; colour is reserved for data.",
    mode: "dark",
    swatch: ["#131415", "#1b1d1f", "#c8cdd1"],
  },
  {
    id: "warm-institutional",
    name: "Warm Institutional",
    description:
      "Warm off-white and ink. Traditional and document-like, in the manner of a committee paper.",
    mode: "light",
    swatch: ["#f4f1ea", "#fdfcf8", "#6b4423"],
  },
];

export const DEFAULT_THEME: ThemeId = "executive-light";

/** Where the choice is remembered until user preferences move to PostgreSQL. */
export const THEME_STORAGE_KEY = "ipm.theme";

export function isThemeId(value: unknown): value is ThemeId {
  return (
    typeof value === "string" && THEMES.some((theme) => theme.id === value)
  );
}

export function getTheme(id: ThemeId): ThemeDefinition {
  return THEMES.find((theme) => theme.id === id) ?? THEMES[0];
}

/**
 * Chart series colours for the active theme.
 *
 * Recharts needs real colour values rather than Tailwind class names, so charts
 * read the CSS custom properties at render time. That keeps a single source of
 * truth: change a theme's palette in globals.css and every chart follows.
 */
export function chartColors(count = 8): string[] {
  return Array.from({ length: count }, (_, i) => `var(--ipm-chart-${i + 1})`);
}
