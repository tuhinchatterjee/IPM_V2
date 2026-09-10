"use client";

/**
 * The response panel: answer, partial answer, referral, clarification,
 * unsupported, or an explicit stop.
 *
 * A stop is rendered as a stop. There is no branch here that dresses a
 * failure as a short answer, and no "try rephrasing" on a failure that
 * rephrasing cannot fix -- the terminal reason is shown with the support
 * reference, because that is what an operator needs and what the user can
 * act on.
 */

import type { FinalResponse } from "./client";
import type { RunView } from "./reducer";

const DISPOSITION_LABEL: Record<string, string> = {
  answer: "Answer",
  partial_answer: "Partial answer",
  referral: "This belongs to another part of CreditProbe",
  clarification: "One question first",
  unsupported: "Not supported here",
  safe_failure: "Could not complete",
};

const COVERAGE_LABEL: Record<string, string> = {
  answered: "answered",
  partial: "partly answered",
  referred: "referred",
  needs_clarification: "needs clarification",
  unsupported: "not supported",
};

function Coverage({ response }: { response: FinalResponse }) {
  if (!response.coverage.length) return null;
  return (
    <div className="mt-3">
      <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">
        What was covered
      </h4>
      <ul className="mt-1 space-y-1 text-sm">
        {response.coverage.map((item, i) => (
          <li key={i} className="flex gap-2">
            <span
              className={
                item.status === "answered"
                  ? "text-emerald-600"
                  : item.status === "unsupported"
                    ? "text-rose-600"
                    : "text-amber-600"
              }
              aria-hidden
            >
              •
            </span>
            <span className="text-slate-700">
              {item.subquestion}{" "}
              <span className="text-slate-500">
                — {COVERAGE_LABEL[item.status] ?? item.status}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ResponsePanel({
  view,
  onAsk,
}: {
  view: RunView;
  onAsk?: (question: string) => void;
}) {
  if (!view.terminal) return null;

  const response = view.response;
  if (!response) {
    return (
      <section className="rounded-lg border border-rose-200 bg-rose-50 p-3">
        <h3 className="text-sm font-medium text-rose-900">
          {view.state === "CANCELLED"
            ? "Cancelled"
            : view.state === "EXPIRED"
              ? "This request ran out of time"
              : view.state === "INTERRUPTED"
                ? "This request was interrupted"
                : "This request stopped"}
        </h3>
        <p className="mt-1 text-sm text-rose-800">
          {view.errorCode
            ? `Reason: ${view.errorCode}.`
            : "No answer was produced, and nothing was substituted for one."}
        </p>
        {view.errorId ? (
          <p className="mt-1 text-xs text-rose-700">
            Quote <span className="font-mono">{view.errorId}</span> to an
            operator. Rephrasing the question is unlikely to help.
          </p>
        ) : null}
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-slate-200 p-3">
      <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {DISPOSITION_LABEL[response.disposition] ?? response.disposition}
      </h3>

      <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
        {response.narrative}
      </div>

      {response.disposition === "clarification" &&
      response.clarification_question ? (
        <div className="mt-3 rounded border border-sky-200 bg-sky-50 p-2">
          <p className="text-sm text-sky-900">{response.clarification_question}</p>
          {response.clarification_options.length ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {response.clarification_options.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => onAsk?.(option)}
                  className="rounded border border-sky-300 bg-white px-2 py-1 text-xs text-sky-800"
                >
                  {option}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {response.disposition === "referral" && response.referral_owner ? (
        <p className="mt-2 text-sm text-slate-600">
          {response.referral_reason}
        </p>
      ) : null}

      <Coverage response={response} />

      {response.numeric_claims.length ? (
        <div className="mt-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Figures, and where each came from
          </h4>
          <ul className="mt-1 space-y-1 text-xs text-slate-600">
            {response.numeric_claims.map((claim) => (
              <li key={claim.claim_id} className="font-mono">
                {claim.claim_id}: {claim.decimal_value} {claim.unit}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {response.limitations.length ? (
        <div className="mt-3">
          <h4 className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Limitations
          </h4>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-600">
            {response.limitations.map((item, i) => (
              <li key={i}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {response.suggested_questions.length && onAsk ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {response.suggested_questions.map((suggestion, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onAsk(suggestion.question)}
              className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-50"
            >
              {suggestion.question}
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
