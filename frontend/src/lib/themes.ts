/**
 * The eight IPM themes.
 *
 * A theme is nothing more than a set of values for the semantic tokens defined
 * in globals.css. It changes background, surface, border, text, accent, status
 * and chart colours — and nothing else. Layout, typography, spacing, hierarchy
 * and interaction are identical across all eight, so switching theme changes how
 * IPM looks and never how it works.
 *
 * Each palette is checked rather than judged by eye: tests/frontend/
 * test_theme_contrast.py reads globals.css and asserts body text, secondary
 * text, muted text, every status colour and every chart slot clear their
 * contrast floors on that theme's own surfaces, and that adjacent chart slots
 * are perceptually separated in CIELAB.
 *
 * The swatches below are for the Theme Gallery preview only. The values that
 * actually render the application live in globals.css; these mirror three of
 * them so the gallery can show a card without mounting the theme.
 */

/**
 * The identifiers are internal and stay fixed. Only the display names changed
 * when the themes were renamed, so a choice remembered in a browser survives the
 * rename and no stylesheet selector had to move.
 */
export type ThemeId =
  | "executive-light"
  | "midnight"
  | "graphite"
  | "warm-institutional"
  | "alpine"
  | "porcelain"
  | "oxblood"
  | "forest";

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
    name: "Executive Ivory",
    description:
      "Paper-like and high contrast. Reads as a printed board pack rather than a screen.",
    mode: "light",
    swatch: ["#f7f6f3", "#ffffff", "#10527a"],
  },
  {
    id: "midnight",
    name: "Midnight Boardroom",
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
    name: "Warm Sand",
    description:
      "Warm off-white and ink. Traditional and document-like, in the manner of a committee paper.",
    mode: "light",
    swatch: ["#f2ede4", "#fdfcf8", "#6b4423"],
  },
  {
    id: "alpine",
    name: "Alpine",
    description:
      "Cool glacial light with a deep teal accent. The crispest of the light themes.",
    mode: "light",
    swatch: ["#f3f6f8", "#ffffff", "#12657a"],
  },
  {
    id: "porcelain",
    name: "Porcelain",
    description:
      "Near-white and almost chroma-free, so the only saturated colour belongs to the data.",
    mode: "light",
    swatch: ["#fafafb", "#ffffff", "#37445f"],
  },
  {
    id: "oxblood",
    name: "Oxblood",
    description:
      "Deep wine and brass. Warm and closed — the panelled room rather than the trading floor.",
    mode: "dark",
    swatch: ["#160d10", "#201318", "#d2a86f"],
  },
  {
    id: "forest",
    name: "Forest",
    description:
      "Deep pine with a eucalyptus accent. The calmest of the dark themes at low light.",
    mode: "dark",
    swatch: ["#0a1210", "#111b18", "#6dc09b"],
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
