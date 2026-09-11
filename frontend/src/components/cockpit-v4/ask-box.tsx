"use client";

/**
 * The Ask surface as the landing page wants it: wide, primary, and first.
 *
 * The earlier Cockpit put one large question box across the workspace with a
 * few business prompts under it, and that is the shape restored here. What is
 * NOT restored is any of the backend behind it — this posts to the V4 run API
 * and nothing else.
 *
 * The process panel appears when a run exists and not before. An idle landing
 * page reserves no space for it, because a blank frame where the work will go
 * is not information.
 */

import * as React from "react";

import type { RunMode } from "./client";

export const PROMPTS: readonly string[] = [
  "Where is risk building across the book?",
  "Which exposures deteriorated this quarter?",
  "What is driving Stage 2 and ECL growth?",
  "Show latest-quarter EAD by sector.",
  "Which sectors deteriorated most this year?",
];

const MODES: { id: RunMode; label: string; hint: string }[] = [
  {
    id: "standard",
    label: "Standard",
    hint: "Enough for most questions.",
  },
  {
    id: "deep",
    label: "Deep",
    hint: "A longer allowance, for work that needs it.",
  },
];

export function AskBox({
  question,
  onQuestionChange,
  mode,
  onModeChange,
  onAsk,
  busy,
  showPrompts,
  onDismissPrompts,
}: {
  question: string;
  onQuestionChange: (value: string) => void;
  mode: RunMode;
  onModeChange: (mode: RunMode) => void;
  onAsk: (text: string) => void;
  busy: boolean;
  showPrompts: boolean;
  onDismissPrompts: () => void;
}) {
  return (
    <form
      data-testid="cockpit-v4-ask-box"
      onSubmit={(event) => {
        event.preventDefault();
        onAsk(question);
      }}
      className="w-full rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center">
        <label className="sr-only" htmlFor="cockpit-v4-question">
          Ask the Cockpit
        </label>
        <input
          id="cockpit-v4-question"
          data-testid="cockpit-v4-question"
          dir="auto"
          value={question}
          onChange={(event) => onQuestionChange(event.target.value)}
          placeholder="What deteriorated this period?"
          className="w-full flex-1 bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400"
        />
        <div className="flex shrink-0 items-center gap-3 self-end sm:self-auto">
          <span className="hidden text-xs text-slate-400 sm:inline">
            Enter to ask
          </span>
          <button
            type="submit"
            data-testid="cockpit-v4-ask"
            disabled={busy || !question.trim()}
            className="rounded-lg bg-slate-700 px-5 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-40"
          >
            ↵ Ask
          </button>
        </div>
      </div>

      {showPrompts ? (
        <div
          data-testid="cockpit-v4-prompts"
          className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-5 py-3"
        >
          {PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              data-testid="cockpit-v4-prompt"
              disabled={busy}
              onClick={() => onAsk(prompt)}
              className="rounded-full border border-slate-200 px-4 py-1.5 text-sm text-slate-700 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-40"
            >
              {prompt}
            </button>
          ))}
          <button
            type="button"
            aria-label="Hide suggested questions"
            data-testid="cockpit-v4-prompts-dismiss"
            onClick={onDismissPrompts}
            className="ml-auto rounded px-2 py-1 text-slate-400 hover:bg-slate-100"
          >
            ✕
          </button>
        </div>
      ) : null}

      <fieldset
        className="flex flex-wrap items-center gap-3 border-t border-slate-100 px-5 py-2.5"
        disabled={busy}
      >
        <legend className="sr-only">Analysis depth</legend>
        {MODES.map((option) => (
          <label
            key={option.id}
            className="inline-flex items-center gap-1.5 text-xs text-slate-600"
          >
            <input
              type="radio"
              name="cockpit-v4-mode"
              data-testid={`cockpit-v4-mode-${option.id}`}
              value={option.id}
              checked={mode === option.id}
              onChange={() => onModeChange(option.id)}
            />
            {option.label}
          </label>
        ))}
        <span className="text-xs text-slate-400">
          {MODES.find((m) => m.id === mode)?.hint}
        </span>
      </fieldset>
    </form>
  );
}
