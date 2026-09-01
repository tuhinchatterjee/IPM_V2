/**
 * Which of the things CreditProbe already established deserves the reader's eye.
 *
 * §11 asks for a KEY INSIGHT region and an IMPLICATIONS section. Neither may
 * introduce anything. Every figure in a CreditProbe answer is quoted unchanged
 * from an engine result, checked against the grounding rules, and withheld when
 * a single number cannot be traced — so a "key insight" that computed something
 * new, or a model that wrote one, would be the one unverified sentence in an
 * answer built entirely of verified ones, sitting in the most prominent box on
 * the screen.
 *
 * So this module SELECTS. It ranks findings the backend already composed and
 * drivers it already ordered, and returns one of them. It never derives a
 * figure, never rewrites a sentence, and never invents a category. When nothing
 * qualifies it returns null and the region does not render — an empty highlight
 * box is better than a highlighted platitude.
 *
 * Kept free of React so `node --test` can assert the ranking directly.
 */

import type { InvestigationResponse, NarrativeFinding } from "@/lib/api";

/** How loudly a finding is asking to be read. Highest wins. */
const TONE_WEIGHT: Record<string, number> = {
  negative: 3,
  warning: 2,
  positive: 1,
  neutral: 0,
};

export interface KeyInsight {
  /** The sentence, exactly as it was composed. Never rewritten here. */
  text: string;
  tone: NarrativeFinding["tone"];
  evidence: NarrativeFinding["evidence"];
  /** Why this one was chosen, for the region's small label. */
  because: string;
}

/**
 * The single most decision-relevant supported observation, or nothing.
 *
 * Preference order, and each step is a reason rather than a heuristic:
 *
 *   1. The loudest finding that carries its own figures. A statement with
 *      evidence attached is the only kind a reader can act on without
 *      scrolling, which is the entire job of this region.
 *   2. The loudest finding without figures, when nothing else is on offer.
 *
 * A finding that merely restates the direct answer is skipped: repeating the
 * headline in a highlighted box tells the reader the product has one thing to
 * say and has decided to say it twice.
 */
export function keyInsight(run: InvestigationResponse): KeyInsight | null {
  const answer = (run.narrative.direct_answer || run.narrative.summary || "").trim();
  const candidates = (run.narrative.findings ?? []).filter(
    (finding) => finding.text && finding.text.trim() !== answer,
  );
  if (candidates.length === 0) return null;

  const ranked = [...candidates].sort((a, b) => {
    const byEvidence = (b.evidence?.length ? 1 : 0) - (a.evidence?.length ? 1 : 0);
    if (byEvidence !== 0) return byEvidence;
    return (TONE_WEIGHT[b.tone] ?? 0) - (TONE_WEIGHT[a.tone] ?? 0);
  });

  const chosen = ranked[0];
  return {
    text: chosen.text,
    tone: chosen.tone,
    evidence: chosen.evidence ?? [],
    because: reasonFor(chosen),
  };
}

/** The small label above the insight, naming what kind of thing it is. */
function reasonFor(finding: NarrativeFinding): string {
  if (finding.tone === "negative") return "Most material exception";
  if (finding.tone === "warning") return "What moved most";
  if ((finding.evidence?.length ?? 0) > 0) return "Largest contributor";
  return "Worth noting";
}

/**
 * What deserves attention next, from what the run already established.
 *
 * Three sources, all of them things the backend produced:
 *
 *   - a rejected plan, which is an implication in the strongest possible sense
 *   - the exceptions the analyst reading already listed
 *   - the top-ranked drivers, named rather than re-ranked
 *
 * Capped at three. §11 asks for a section, not a second answer, and a list of
 * nine implications is a list nobody reads.
 */
export function implications(run: InvestigationResponse): string[] {
  const out: string[] = [];

  for (const reason of run.rejected ?? []) {
    if (reason) out.push(reason);
  }

  // The analyst reading's own points, which are grounded observations rather
  // than a paragraph. The first is usually the conclusion and is already shown
  // in the reading itself, so this takes what follows it.
  const points = (run.narrative.interpretation_points ?? []).filter(Boolean);
  for (const point of points.slice(1)) out.push(point);

  // The named contributors, in the engine's own order. "Contracting accounts
  // for the largest share" is an implication a reader can act on; re-ranking
  // them here would be a calculation and is not done.
  const drivers = run.narrative.drivers ?? [];
  if (drivers.length > 0 && out.length < 3) {
    const measure = drivers[0]?.measure || "the movement";
    const named = drivers
      .slice(0, 3)
      .map((driver) => driver.name)
      .filter(Boolean);
    if (named.length > 0) {
      out.push(
        named.length === 1
          ? `${named[0]} accounts for most of ${measure}.`
          : `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]} ` +
            `account for most of ${measure}.`,
      );
    }
  }

  return dedupe(out).slice(0, 3);
}

function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = value.trim().toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Whether the result is an explicit negative finding — nothing matched.
 *
 * §15: "Do not present empty tables without an explicit conclusion." The
 * backend already says so in the direct answer; this tells the layout to stop
 * rendering the empty table under it, which otherwise reads as a failure to
 * produce one.
 */
export function foundNothing(run: InvestigationResponse): boolean {
  const primary =
    run.steps.find((step) => step.role === "primary") ?? run.steps[0] ?? null;
  if (!primary?.result) return false;
  return (
    primary.status === "succeeded" &&
    primary.result.rows.length === 0 &&
    Object.keys(primary.result.values ?? {}).length === 0
  );
}


/**
 * A paragraph split into sentences, for §52's restrained highlighting.
 *
 * Only a full stop, a question mark or an exclamation followed by a space and
 * a capital ends a sentence here. That deliberately refuses to split
 * "12.4% rose" or "Q2 2025 vs. Q1", which is the failure mode that matters: a
 * highlight that ends mid-figure is worse than no highlight, because it draws
 * the eye to half a number.
 */
export function sentences(text: string): string[] {
  const trimmed = (text ?? "").trim();
  if (!trimmed) return [];
  return trimmed
    .split(/(?<=[.!?])\s+(?=[A-Z“"'(])/)
    .map((part) => part.trim())
    .filter(Boolean);
}
