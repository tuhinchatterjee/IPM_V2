"use client";

import * as React from "react";

import { ResultCard } from "@/components/scorecard-validation/result-card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { ScvAnswer, ScvResult, ScvTest } from "@/lib/api";
import { humanise } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Asking the validation module a question. §21.
 *
 * The design constraint that shapes everything here: **this box does not
 * write sentences about numbers.** It renders what the governed tools
 * returned, and every sentence beside a figure is the runner's own — written
 * to be quoted into a report unedited, and reproducible because a
 * deterministic engine produced it.
 *
 * A chat surface that paraphrases a validation statistic is the single most
 * dangerous thing this module could contain. The paraphrase is what gets read
 * aloud in a committee, and there is no way for the person reading it to tell
 * that it was rewritten.
 *
 * Three outcomes, rendered differently on purpose
 * -------------------------------------------------
 * **Answered** — the tool result, in the same components the rest of the page
 * uses. A result reached by asking must look identical to the same result
 * reached by clicking, because it IS the same result.
 *
 * **Clarified** — the question was about the right thing, too generally. The
 * options are buttons, so the follow-up is one click rather than a
 * rephrasing.
 *
 * **Refused** — out of scope, or a thing this surface has no tool for. It
 * says where the answer does live, because a refusal that leaves somebody
 * stuck is a refusal they route around.
 */

type Turn = {
  id: number;
  question: string;
  answer?: ScvAnswer;
  failed?: string;
};

const SUGGESTIONS = [
  "Is it still ranking risk?",
  "Has the population drifted?",
  "Which characteristics have stopped working?",
  "What does STAB-CSI measure?",
  "Which periods have matured?",
  "What are the biggest weaknesses?",
];

function Provenance({ answer }: { answer: ScvAnswer }) {
  if (!answer.reading) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
      <Badge variant="outline">{answer.reading.source}</Badge>
      <span className="font-mono">{answer.reading.tool_id}</span>
      {answer.reading.because && <span>— {answer.reading.because}</span>}
    </div>
  );
}

/**
 * The tool's result, in the page's own components.
 *
 * Only the shapes this surface can render honestly are rendered. Anything
 * else falls through to the raw payload rather than to a summary: a shape the
 * client does not recognise is a shape it cannot describe, and describing it
 * anyway is inventing.
 */
function ToolResult({ answer, tests }: {
  answer: ScvAnswer;
  tests: Record<string, ScvTest>;
}) {
  const result = answer.result;
  const tool = answer.reading?.tool_id ?? "";
  if (!result) return null;

  if (tool === "scv_run_test") {
    const one = result.result as ScvResult | undefined;
    if (!one) return null;
    return <ResultCard result={one} test={tests[one.test_id]} defaultOpen />;
  }

  if (tool === "scv_run_category") {
    const many = (result.results ?? []) as ScvResult[];
    return (
      <div className="space-y-2">
        {many.map((one) => (
          <ResultCard
            key={`${one.test_id}-${one.segment}`}
            result={one}
            test={tests[one.test_id]}
          />
        ))}
      </div>
    );
  }

  if (tool === "scv_explain_test") {
    const test = result.test as ScvTest | undefined;
    const blind = (result.cannot_tell_you ?? []) as string[];
    if (!test) return null;
    return (
      <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-text-muted">
            {test.test_id}
          </span>
          <h4 className="text-sm font-semibold text-text">{test.name}</h4>
          {test.cbuae.map((reference) => (
            <Badge key={reference} variant="outline">{reference}</Badge>
          ))}
        </div>
        <p className="text-sm leading-relaxed text-text">{test.purpose}</p>
        <div className="space-y-1">
          <h5 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            How it is calculated
          </h5>
          <p className="text-sm leading-relaxed text-text-muted">
            {test.method}
          </p>
        </div>
        {blind.length > 0 && (
          <div className="space-y-1 border-t border-border pt-3">
            <h5 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              What it cannot tell you
            </h5>
            <ul className="space-y-1 text-sm leading-relaxed text-text-muted">
              {blind.map((limitation) => (
                <li key={limitation}>— {limitation}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  }

  // Everything else — the periods, the model list, the regulatory map, the
  // report draft — is rendered as its own governed document rather than
  // summarised. A key/value reading of a payload is honest; a sentence about
  // it is not.
  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface p-4">
      {Object.entries(result).map(([key, value]) => (
        <div key={key} className="space-y-0.5">
          <h5 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            {humanise(key)}
          </h5>
          <p className="break-words text-sm leading-relaxed text-text-muted">
            {Array.isArray(value)
              ? value.length > 12
                ? `${value.slice(0, 12).map(String).join(", ")} … and ${value.length - 12} more`
                : value.map(String).join(", ")
              : typeof value === "object" && value !== null
                ? JSON.stringify(value)
                : String(value)}
          </p>
        </div>
      ))}
    </div>
  );
}

function AnswerBody({ answer, tests, onFollowUp }: {
  answer: ScvAnswer;
  tests: Record<string, ScvTest>;
  onFollowUp: (question: string) => void;
}) {
  if (answer.refusal) {
    // `refused` is a FLAG, not a sentence — rendering it directly puts the
    // word "true" in front of a validator. What was refused is `what`, and it
    // is absent when the whole question was out of domain rather than one
    // thing in it.
    const what = answer.refusal.what;
    return (
      <div className="space-y-2 rounded-lg border border-border bg-surface-sunken p-4">
        <p className="text-sm leading-relaxed text-text">
          {typeof what === "string" && what
            ? `This surface has no tool for ${what}.`
            : "This is not a question this surface answers."}
        </p>
        {typeof answer.refusal.why === "string" && (
          <p className="text-sm leading-relaxed text-text-muted">
            {answer.refusal.why}
          </p>
        )}
        {/* Where the answer does live. A refusal that leaves somebody stuck
            is a refusal they route around. */}
        {typeof answer.refusal.where_instead === "string" && (
          <p className="text-sm leading-relaxed text-text-muted">
            {answer.refusal.where_instead}
          </p>
        )}
        <p className="border-t border-border pt-2 text-[11px] leading-relaxed text-text-muted">
          {answer.scope}
        </p>
      </div>
    );
  }

  if (answer.clarification) {
    const { question, because, options } = answer.clarification;
    return (
      <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
        <p className="text-sm font-medium text-text">{question}</p>
        {because && (
          <p className="text-sm leading-relaxed text-text-muted">{because}</p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {options.map((option, i) => {
            const label = option.title ?? option.name ?? option.category
              ?? option.model_id ?? `Option ${i + 1}`;
            const asks = option.asks ?? option.portfolio ?? "";
            return (
              <button
                key={label}
                type="button"
                title={asks}
                onClick={() => onFollowUp(asks || label)}
                className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Provenance answer={answer} />
      <ToolResult answer={answer} tests={tests} />
      <p className="text-[11px] leading-relaxed text-text-muted">
        {answer.figures}
      </p>
    </div>
  );
}

export function Ask({ modelId, tests, className }: {
  modelId: string;
  tests: Record<string, ScvTest>;
  className?: string;
}) {
  const [draft, setDraft] = React.useState("");
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [busy, setBusy] = React.useState(false);
  const next = React.useRef(1);

  const send = React.useCallback(async (question: string) => {
    const asked = question.trim();
    if (!asked || busy) return;
    const id = next.current++;
    setTurns((was) => [...was, { id, question: asked }]);
    setDraft("");
    setBusy(true);
    try {
      const answer = await api.scorecardValidation.ask(asked, modelId);
      setTurns((was) => was.map(
        (turn) => (turn.id === id ? { ...turn, answer } : turn)));
    } catch (error) {
      setTurns((was) => was.map(
        (turn) => (turn.id === id
          ? { ...turn, failed: (error as Error).message }
          : turn)));
    } finally {
      setBusy(false);
    }
  }, [busy, modelId]);

  return (
    <div className={cn("space-y-4", className)}>
      <form
        onSubmit={(event) => { event.preventDefault(); void send(draft); }}
        className="flex gap-2"
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about validating this scorecard"
          disabled={busy}
          className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-muted focus:border-border-strong focus:outline-none disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="rounded-md border border-border-strong bg-surface-hover px-4 py-2 text-sm font-medium text-text transition-colors hover:bg-surface disabled:opacity-50"
        >
          {busy ? "Running…" : "Ask"}
        </button>
      </form>

      {turns.length === 0 && (
        <div className="flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => void send(suggestion)}
              className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {turns.map((turn) => (
        <div key={turn.id} className="space-y-2 border-l-2 border-border pl-4">
          <p className="text-sm font-medium text-text">{turn.question}</p>
          {turn.failed && (
            <p className="text-sm text-negative">{turn.failed}</p>
          )}
          {!turn.failed && !turn.answer && (
            <p className="text-sm text-text-muted">Running the tests…</p>
          )}
          {turn.answer && (
            <AnswerBody
              answer={turn.answer}
              tests={tests}
              onFollowUp={(question) => void send(question)}
            />
          )}
        </div>
      ))}
    </div>
  );
}
