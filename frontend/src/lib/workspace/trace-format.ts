/** Pure display helpers for the governance Trace (unit-tested). */

/** Short form of a SHA-256 for display; the full value is in the title. */
export const shortHash = (h: string | undefined | null) => (h ? `${h.slice(0, 10)}…${h.slice(-4)}` : "—");

/** The name a chart's snapshot is filed under: its testid, made safe. */
export function snapshotName(testId: string | null, index: number): string {
  const base = (testId ?? `chart-${index + 1}`).toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+/, "");
  return (base || `chart-${index + 1}`).slice(0, 60);
}
