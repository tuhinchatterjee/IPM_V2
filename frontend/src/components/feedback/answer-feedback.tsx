"use client";

import * as React from "react";

import { api } from "@/lib/api";
import type { FeedbackOptions } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The feedback control that follows every CreditProbe response. §148–§150.
 *
 * Not visually dominant
 * ---------------------
 * §148 says so explicitly, and the reason is that a prominent control changes
 * what it measures: a large GOOD button next to an answer nobody checked
 * collects agreement rather than correctness. So this is two small text
 * buttons under the answer, and the reasons appear only once somebody has
 * chosen.
 *
 * The reasons come from the backend
 * ----------------------------------
 * Two lists in two places become two different lists, and the one users see
 * will be the stale one. This asks.
 *
 * What the thank-you says
 * -----------------------
 * Whatever the backend's constant says, which is "reviewed to improve
 * CreditProbe" and never "I'll learn from that". §149 forbids claiming
 * immediate learning, and the reason is practical: the claim is contradicted
 * the next time the user asks the same question and gets the same answer.
 *
 * A BAD rating asks for a reason and accepts none
 * -------------------------------------------------
 * §150 says require or strongly encourage. Refusing loses the signal from the
 * user who is annoyed and about to close the tab, and that user's annoyance is
 * the most useful data in the system.
 */

type Rating = "GOOD" | "BAD";

export function AnswerFeedback({
  answerId,
  investigationId,
  analysisRunId,
  traceId,
  className,
}: {
  answerId: string;
  investigationId?: string;
  analysisRunId?: string;
  traceId?: string;
  className?: string;
}) {
  const [options, setOptions] = React.useState<FeedbackOptions | null>(null);
  const [rating, setRating] = React.useState<Rating | null>(null);
  const [chosen, setChosen] = React.useState<string[]>([]);
  const [comment, setComment] = React.useState("");
  const [thanks, setThanks] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    api
      .feedbackOptions()
      .then((data) => live && setOptions(data))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const send = async (which: Rating, codes: string[]) => {
    setBusy(true);
    setError("");
    try {
      const receipt = await api.leaveFeedback({
        rating: which,
        answer_id: answerId,
        reason_codes: codes,
        comment,
        investigation_id: investigationId,
        analysis_run_id: analysisRunId,
        trace_id: traceId,
      });
      setThanks(receipt.acknowledgement);
    } catch (e: unknown) {
      setError(
        e instanceof Error
          ? e.message
          : "That could not be recorded. Nothing was lost — try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (thanks) {
    return (
      <p className={cn("text-xs text-text-tertiary", className)}>{thanks}</p>
    );
  }

  const reasons = rating && options ? options.reasons[rating] : [];

  return (
    <div className={cn("space-y-2", className)}>
      {!rating ? (
        <div className="flex items-center gap-3">
          <span className="text-xs text-text-tertiary">
            Was this answer useful?
          </span>
          <button
            type="button"
            onClick={() => setRating("GOOD")}
            aria-label="Mark this answer good"
            className="text-xs font-medium text-text-secondary hover:text-text-primary"
          >
            <span aria-hidden>&#128077;</span> Good
          </button>
          <button
            type="button"
            onClick={() => setRating("BAD")}
            aria-label="Mark this answer bad"
            className="text-xs font-medium text-text-secondary hover:text-text-primary"
          >
            <span aria-hidden>&#128078;</span> Bad
          </button>
        </div>
      ) : (
        <div className="space-y-2 rounded border border-border p-3">
          <p className="text-xs text-text-secondary">
            {rating === "GOOD"
              ? "What was good about it? Optional."
              : "What went wrong? This helps more than the rating alone."}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {reasons.map((reason) => (
              <button
                key={reason.code}
                type="button"
                aria-pressed={chosen.includes(reason.code)}
                onClick={() =>
                  setChosen((was) =>
                    was.includes(reason.code)
                      ? was.filter((c) => c !== reason.code)
                      : [...was, reason.code],
                  )
                }
                className={cn(
                  "rounded border px-2 py-0.5 text-xs transition-colors",
                  chosen.includes(reason.code)
                    ? "border-border-strong bg-surface-raised text-text-primary"
                    : "border-border text-text-secondary hover:text-text-primary",
                )}
              >
                {reason.label}
              </button>
            ))}
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            placeholder={
              rating === "BAD"
                ? "What did you expect instead? Optional."
                : "Anything to add? Optional."
            }
            aria-label="Comment"
            className="w-full rounded border border-border bg-surface px-2 py-1 text-xs text-text-primary"
          />
          {error ? (
            <p className="text-xs text-status-negative">{error}</p>
          ) : null}
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => send(rating, chosen)}
              className="rounded bg-surface-raised px-3 py-1 text-xs font-medium text-text-primary disabled:opacity-50"
            >
              {busy ? "Sending…" : "Send"}
            </button>
            <button
              type="button"
              onClick={() => {
                setRating(null);
                setChosen([]);
                setComment("");
              }}
              className="text-xs text-text-tertiary hover:text-text-secondary"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
