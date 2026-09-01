/**
 * Which of §39's eight kinds an answer turned out to be.
 *
 * A pure module rather than a helper inside the renderer, because this
 * decides where every correction gets filed and it is worth testing without
 * mounting a component.
 *
 * Derived from what the run actually DID rather than from what was asked,
 * because the two differ exactly when it matters: a question that was going
 * to be an analysis and became a clarification is a clarification, and
 * filing that feedback under "analysis" loses the one signal that says the
 * clarification was unwelcome.
 */

/** The eight §39 names, as the backend spells them. */
export const ANSWER_KINDS = [
  "metadata",
  "analysis",
  "clarification",
  "unsupported",
  "controlled_failure",
  "agentic",
  "regulatory",
  "project_planner",
] as const;

export type AnswerKind = (typeof ANSWER_KINDS)[number];

/** The minimum an answer has to expose for its kind to be decided. */
export type KindInput = {
  rejected?: string[];
  status?: string;
  clarification?: unknown;
  unmatched?: boolean;
  mode?: { execution?: string } | null;
  steps?: unknown[];
};

/**
 * Ordered most specific first, and the order carries two judgements.
 *
 * A refused plan is a CONTROLLED FAILURE even though it also produced no
 * result: reporting it as "unsupported" would tell the reader we cannot do
 * this, when what happened is that we would not.
 *
 * A clarification outranks "unmatched" for the same reason — stopping to ask
 * is a decision, and grouping it with the questions we could not parse loses
 * the distinction the user is complaining about.
 */
export function answerKindOf(run: KindInput): AnswerKind {
  if ((run.rejected?.length ?? 0) > 0) return "controlled_failure";
  if (run.status && run.status !== "succeeded" && run.status !== "ok")
    return "controlled_failure";
  if (run.clarification) return "clarification";
  if (run.unmatched) return "unsupported";
  if (run.mode?.execution === "agentic") return "agentic";
  if ((run.steps?.length ?? 0) === 0) return "metadata";
  return "analysis";
}
