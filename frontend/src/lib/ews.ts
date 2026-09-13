/**
 * What Early Warning IS, written once.
 *
 * §15 of the acceptance brief: one source of truth for the description of
 * Early Warning, everywhere it appears. It appeared in four places with three
 * different meanings — the sidebar called it a "Forward Risk Signal ...
 * estimate of the chance a facility moves to a worse IFRS 9 stage", the
 * signals entry promised "34 named tests across eight families" (the retail
 * rulebook has twenty rules in eleven families; thirty-four across eight was
 * the corporate book's), and the page headers said something else again. A
 * reader who read two of them learned two different products.
 *
 * Two different things genuinely exist here and they are described
 * separately, because collapsing them would be the opposite error:
 *
 *   - EWS_*        the governed rulebook and its layer roll-up. This is what
 *                  the Early Warning screens show and what the portfolio
 *                  score means.
 *   - FORWARD_*    the fitted Forward Risk Signal, a statistical estimate of
 *                  an IFRS 9 stage transition, which lives in the Model Lab.
 *
 * The rulebook version is NOT written here. It is served with every payload
 * that carries a figure, and a version stamped into a frontend constant is a
 * version that goes stale without anything failing.
 */

/** The Early Warning capability, in one sentence. */
export const EWS_DESCRIPTION =
  "Where the retail book is deteriorating, how badly, and who it is — one "
  + "governed score over four layers, from total retail down through product, "
  + "sub-portfolio and customer to the trigger that fired.";

/** The one workspace. There is no second Early Warning entry. */
export const EWS_LABEL = "Early Warning Score";
export const EWS_ROUTE = "/early-warning";

/** The signals list — the same rulebook, one row per signal. */
export const EWS_SIGNALS_DESCRIPTION =
  "Every signal the governed rulebook raised this month, one row each: what "
  + "it measured, what it compared against, the threshold somebody owns and "
  + "what to do about it. The same rules the Early Warning portfolio rolls up.";

/** The methodology page. */
export const EWS_METHODOLOGY_DESCRIPTION =
  "The model that is running, not one to be fitted: the governed rules, the "
  + "six layers they roll up into, and every input they read.";

/** What the score means, for a tooltip or a header. */
export const EWS_SCORE_MEANING =
  "Each layer scores the worst signal that fired in it, plus ten points for "
  + "each additional signal, capped at 100. The overall score is the weighted "
  + "mean of the five scored layers.";

/** The separate fitted model, so the two are never confused. */
export const FORWARD_SIGNAL_DESCRIPTION =
  "A fitted, factor-based estimate of the chance a facility moves to a worse "
  + "IFRS 9 stage next quarter, for three transitions. Separate from the "
  + "Early Warning rulebook and not used to score it.";

/** Said wherever a figure from this module is shown. */
export const EWS_PHASE = "Synthetic demonstration data";
