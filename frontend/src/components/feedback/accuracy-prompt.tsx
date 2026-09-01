"use client";

import * as React from "react";

import { opensDetail, safeAcknowledgement } from "@/components/feedback/present";
import { api } from "@/lib/api";
import type { FeedbackPrompt } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * "Was this answer accurate and useful?" §7–§11, §25, §31.
 *
 * Why the question is two words long
 * -----------------------------------
 * ACCURATE is about the figures and belongs to whoever can check them. USEFUL
 * is about the answer and belongs to whoever asked. An answer can be perfectly
 * accurate and useless, and the two lead to completely different work — so the
 * question asks both and the reply is one of five, not a thumb.
 *
 * PARTLY and NOT SURE carry the load
 * ------------------------------------
 * PARTLY is the commonest honest answer to a long analytical response and the
 * one a binary control destroys: forced to choose, a user who thinks three of
 * four numbers are right picks YES and the fourth number is never reported.
 * NOT SURE says the answer was not verifiable by the person reading it, which
 * is a product failure that no accuracy measurement will ever find.
 *
 * The placement decision is not made here
 * ----------------------------------------
 * §7's rules about when the prompt must NOT appear — while the answer is
 * running, on a skeleton, on a system error, after a dismissal, in a muted
 * thread — are the half that protects the user rather than the product. They
 * are decided by the backend so there is one implementation of them, and this
 * component renders what it is told. `show: false` renders nothing at all.
 *
 * §31: unobtrusive, no modal, keyboard-reachable, theme-aware, dismissible
 * -------------------------------------------------------------------------
 * Five text buttons in a row, no colour until chosen, no modal at any point,
 * and the detail panel opens inline below rather than over anything. Every
 * control is a real <button> so it is in the tab order without help.
 *
 * What the acknowledgement never says
 * -------------------------------------
 * That anything has been learned. §25 forbids it and the backend's own
 * constant is what is rendered — a promise added here could not reach the
 * screen without also being added there, where a test asserts against it.
 */

const SURFACE_DEFAULT = "COCKPIT";

export function AccuracyFeedback({
  answerId,
  threadId,
  investigationId,
  projectId,
  question,
  agenticRunId,
  planFingerprint,
  assuranceRecordId,
  buildSha,
  officerLevel,
  surface = SURFACE_DEFAULT,
  complete = true,
  isError = false,
  className,
}: {
  answerId: string;
  threadId?: string;
  investigationId?: string;
  projectId?: string;
  question?: string;
  agenticRunId?: string;
  planFingerprint?: string;
  assuranceRecordId?: string;
  buildSha?: string;
  officerLevel?: number | null;
  surface?: string;
  complete?: boolean;
  isError?: boolean;
  className?: string;
}) {
  const [prompt, setPrompt] = React.useState<FeedbackPrompt | null>(null);
  const [rating, setRating] = React.useState("");
  const [categories, setCategories] = React.useState<string[]>([]);
  const [comment, setComment] = React.useState("");
  const [conclusion, setConclusion] = React.useState("");
  const [period, setPeriod] = React.useState("");
  const [consent, setConsent] = React.useState(false);
  const [said, setSaid] = React.useState("");
  const [next, setNext] = React.useState("");
  const [dismissed, setDismissed] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [problem, setProblem] = React.useState("");

  React.useEffect(() => {
    let live = true;
    if (!answerId) return;
    api
      .feedbackPrompt({
        answer_id: answerId,
        thread_id: threadId,
        complete,
        is_error: isError,
      })
      .then((found) => {
        if (live) setPrompt(found);
      })
      .catch(() => {
        // A prompt that cannot be fetched is a prompt that is not shown.
        // Feedback is worth collecting and never worth an error beside an
        // answer the user is trying to read.
        if (live) setPrompt(null);
      });
    return () => {
      live = false;
    };
  }, [answerId, threadId, complete, isError]);

  if (!prompt?.show || dismissed) return null;

  const wantsDetail = opensDetail(rating, prompt.detail_on);
  const submitted = Boolean(said);

  async function send(chosen: string, withDetail: boolean) {
    setBusy(true);
    setProblem("");
    try {
      const receipt = await api.leaveAccuracyFeedback({
        rating: chosen,
        answer_id: answerId,
        categories: withDetail ? categories : [],
        comment: withDetail ? comment : "",
        correction: withDetail
          ? { conclusion, preferred_period: period }
          : undefined,
        consent: consent ? "GRANTED" : "UNSET",
        surface,
        investigation_id: investigationId,
        project_id: projectId,
        message_id: answerId,
        question,
        agentic_run_id: agenticRunId,
        plan_fingerprint: planFingerprint,
        assurance_record_id: assuranceRecordId,
        build_sha: buildSha,
        officer_level: officerLevel ?? null,
      });
      setSaid(safeAcknowledgement(receipt.acknowledgement));
      setNext(receipt.what_happens_next);
    } catch (error) {
      setProblem(
        error instanceof Error ? error.message : "That could not be recorded.",
      );
    } finally {
      setBusy(false);
    }
  }

  function choose(value: string) {
    setRating(value);
    // SKIP and the two ratings that carry no claim go straight through. The
    // detail panel exists to collect what went wrong, and there is nothing to
    // collect from somebody who said it was right.
    if (!opensDetail(value, prompt!.detail_on)) void send(value, false);
  }

  if (submitted) {
    return (
      <div
        className={cn("space-y-1 text-xs text-muted-foreground", className)}
        role="status"
      >
        <p>{said}</p>
        {next && <p className="text-[11px] opacity-80">{next}</p>}
      </div>
    );
  }

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-xs text-muted-foreground">{prompt.question}</span>
        {prompt.answers.map((answer) => (
          <button
            key={answer.value}
            type="button"
            disabled={busy}
            title={answer.means}
            onClick={() => choose(answer.value)}
            className={cn(
              "rounded px-1.5 py-0.5 text-xs transition-colors",
              "hover:bg-muted focus-visible:outline focus-visible:outline-2",
              "focus-visible:outline-offset-2 disabled:opacity-50",
              rating === answer.value
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground",
            )}
          >
            {answer.label}
          </button>
        ))}
        {prompt.dont_ask_again_in_this_thread && (
          <button
            type="button"
            className="ml-auto text-[11px] text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => {
              setDismissed(true);
              if (threadId) void api.muteFeedbackThread(threadId).catch(() => {});
            }}
          >
            Don&apos;t ask again in this thread
          </button>
        )}
      </div>

      {wantsDetail && (
        <div className="space-y-2 rounded border border-border/60 p-2">
          <p className="text-[11px] text-muted-foreground">
            What went wrong? Pick the earliest thing — a wrong period produces a
            wrong result, and reporting the result loses the cause.
          </p>
          <div className="flex flex-wrap gap-1">
            {prompt.categories.map((category) => {
              const chosen = categories.includes(category.id);
              return (
                <button
                  key={category.id}
                  type="button"
                  title={category.means}
                  aria-pressed={chosen}
                  onClick={() =>
                    setCategories((was) =>
                      chosen
                        ? was.filter((c) => c !== category.id)
                        : [...was, category.id],
                    )
                  }
                  className={cn(
                    "rounded border px-1.5 py-0.5 text-[11px] transition-colors",
                    "focus-visible:outline focus-visible:outline-2",
                    "focus-visible:outline-offset-2",
                    chosen
                      ? "border-foreground/40 bg-muted text-foreground"
                      : "border-border/60 text-muted-foreground hover:bg-muted/60",
                  )}
                >
                  {category.label}
                </button>
              );
            })}
          </div>

          <label className="block text-[11px] text-muted-foreground">
            What should it have said?
            <textarea
              value={conclusion}
              onChange={(event) => setConclusion(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded border border-border/60 bg-transparent p-1.5 text-xs"
              placeholder="The correction, in your words. It is evidence, not a change."
            />
          </label>

          <label className="block text-[11px] text-muted-foreground">
            Which period did you mean?
            <input
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
              className="mt-1 w-full rounded border border-border/60 bg-transparent p-1.5 text-xs"
              placeholder="Q2 2025"
            />
          </label>

          <label className="block text-[11px] text-muted-foreground">
            Anything else
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded border border-border/60 bg-transparent p-1.5 text-xs"
            />
          </label>

          <label className="flex items-start gap-2 text-[11px] text-muted-foreground">
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
              className="mt-0.5"
            />
            <span>
              {prompt.consent_question}.{" "}
              <span className="opacity-80">
                {prompt.consent_options.GRANTED}
              </span>
            </span>
          </label>

          {problem && (
            <p className="text-[11px] text-destructive" role="alert">
              {problem}
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void send(rating, true)}
              className="rounded bg-foreground px-2 py-1 text-[11px] text-background disabled:opacity-50"
            >
              {busy ? "Recording…" : "Send"}
            </button>
            <button
              type="button"
              onClick={() => setDismissed(true)}
              className="text-[11px] text-muted-foreground hover:underline"
            >
              Cancel
            </button>
            <span className="ml-auto text-[10px] text-muted-foreground">
              Nothing changes automatically.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
