"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  api,
  ApiError,
  type CopilotCommand,
  type CopilotQuestion,
  type CopilotScope,
  type CopilotTurn,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The Copilot's conversation, wherever it appears.
 *
 * The same component sits on the delivery home page, on a project, and beside
 * the plan being built. It differs only in what it is given: a draft key, a
 * project id, or neither. There is one chat in this product, not three that
 * drift apart.
 *
 * Two things it does deliberately.
 *
 * **A refusal looks different from an answer.** When the backend says a
 * question belongs to another part of CreditProbe, that comes back as a card
 * naming where the answer lives — not as an apology in the assistant's voice,
 * and not as an error. The person asked a reasonable question in the wrong
 * room, and the useful response is a direction.
 *
 * **Nothing here decides anything.** The backend reads the sentence, resolves
 * the names, and either applies the change, asks which of two things was
 * meant, or shows what it would do and waits. This component renders those
 * three outcomes and sends back what the person clicked. It never assembles a
 * command: a confirmation re-sends the ORIGINAL WORDS with `confirm`, and a
 * clarification re-sends them with the answer, so there is no path from this
 * file to a mutation that did not go through the reader.
 */

export type ChatTurn = {
  id: number;
  who: "person" | "copilot";
  text: string;
  refusal?: CopilotScope;
  /** What the sentence was read as, shown before it is agreed to. */
  proposed?: CopilotCommand[];
  /** Which of two things was meant, as buttons. */
  question?: CopilotQuestion;
  /** The words that produced this turn, re-sent on confirm or on an answer. */
  said?: string;
  /** True while this turn is still waiting for a yes. */
  open?: boolean;
};

const OPENING =
  "Tell me what you want to do. I can start a plan, add milestones and " +
  "tasks, link things together, and tell you what is overdue or blocked.";

export function CopilotChat({
  draftKey,
  projectId,
  suggestions = [],
  onTurn,
  className,
}: {
  draftKey?: string;
  projectId?: number;
  suggestions?: string[];
  onTurn?: (turn: CopilotTurn) => void;
  className?: string;
}) {
  const [turns, setTurns] = React.useState<ChatTurn[]>([
    { id: 0, who: "copilot", text: OPENING },
  ]);
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  // What the conversation is currently about, so "it starts on the first"
  // has a subject. The backend works it out and hands it back each turn.
  const [focus, setFocus] = React.useState("");
  const next = React.useRef(1);
  const foot = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    foot.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const say = React.useCallback((turn: Omit<ChatTurn, "id">) => {
    setTurns((existing) => [...existing, { ...turn, id: next.current++ }]);
  }, []);

  const send = React.useCallback(
    async (message: string, options: {
      confirm?: boolean;
      answers?: Record<string, string>;
      echo?: boolean;
    } = {}) => {
      const text = message.trim();
      if (!text || busy) return;
      setDraft("");
      if (options.echo !== false) say({ who: "person", text });
      setBusy(true);
      // A new turn settles the previous one: nothing stays clickable once
      // the conversation has moved on, so there is no stale "go ahead"
      // button that would apply a reading of a plan that has since changed.
      setTurns((existing) => existing.map((t) => ({ ...t, open: false })));
      try {
        const turn = await api.planner.copilot.chat({
          message: text,
          draft: draftKey,
          project_id: projectId,
          focus,
          confirm: options.confirm,
          answers: options.answers,
        });
        if (!turn.in_scope && turn.refusal) {
          say({ who: "copilot", text: turn.refusal.message,
                refusal: turn.refusal });
          return;
        }
        setFocus(turn.focus ?? "");
        const question = turn.questions?.[0];
        say({
          who: "copilot",
          text: turn.said ?? "",
          question,
          said: text,
          proposed: turn.needs_confirmation ? turn.commands : undefined,
          open: Boolean(question) || Boolean(turn.needs_confirmation),
        });
        if ((turn.applied?.length ?? 0) > 0) onTurn?.(turn);
      } catch (error) {
        say({
          who: "copilot",
          text:
            error instanceof ApiError
              ? error.message
              : "I could not reach the planner just then. Try again.",
        });
      } finally {
        setBusy(false);
      }
    },
    [busy, draftKey, projectId, focus, onTurn, say],
  );

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border border-border bg-surface",
        className,
      )}
    >
      <div className="max-h-[22rem] min-h-[10rem] flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {turns.map((turn) => (
          <Turn
            key={turn.id}
            turn={turn}
            busy={busy}
            onConfirm={() =>
              void send(turn.said ?? "", { confirm: true, echo: false })}
            onAnswer={(value) =>
              void send(turn.said ?? "", {
                confirm: true,
                echo: false,
                answers: { [turn.question?.fragment ?? ""]: value },
              })}
          />
        ))}
        <div ref={foot} />
      </div>

      {suggestions.length > 0 && turns.length === 1 && (
        <div className="flex flex-wrap gap-2 border-t border-border px-4 py-2.5">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => void send(suggestion)}
              className="rounded-full border border-border px-3 py-1 text-xs text-text-secondary hover:border-accent hover:text-text-primary"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <form
        className="flex items-center gap-2 border-t border-border px-3 py-2.5"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Start a project, add a milestone, ask what is late…"
          aria-label="Ask the Project Planner Copilot"
          className="h-9 flex-1 rounded-md border border-border bg-surface-raised px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        <Button type="submit" size="sm" disabled={busy || !draft.trim()}>
          {busy ? "Thinking…" : "Send"}
        </Button>
      </form>
    </div>
  );
}

function Turn({
  turn,
  busy,
  onConfirm,
  onAnswer,
}: {
  turn: ChatTurn;
  busy: boolean;
  onConfirm: () => void;
  onAnswer: (value: string) => void;
}) {
  if (turn.who === "person") {
    return (
      <p className="ml-auto max-w-[85%] rounded-lg bg-accent-muted px-3 py-2 text-sm text-text-primary">
        {turn.text}
      </p>
    );
  }
  if (turn.refusal) {
    return <Redirect scope={turn.refusal} />;
  }
  return (
    <div className="max-w-[95%] space-y-2">
      <p className="whitespace-pre-line rounded-lg bg-surface-raised px-3 py-2 text-sm text-text-secondary">
        {turn.text}
      </p>

      {/*
        §3. A clarification is two buttons, not an instruction to type the
        sentence again more carefully. The answer travels back with the
        original words, so what runs is still a reading of what they said.
      */}
      {turn.question && turn.question.options.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {turn.question.options.map((option) => (
            <Button
              key={option.value}
              size="sm"
              variant="outline"
              disabled={busy || !turn.open}
              onClick={() => onAnswer(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      )}

      {/*
        §4. A change that moves a date, an owner or a dependency is shown
        first. The button re-sends the same sentence with a confirmation —
        it does not send a command, because then this file would be a second
        way into the planner.
      */}
      {turn.proposed && turn.proposed.length > 0 && (
        <div className="rounded-lg border border-border bg-surface-raised px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">
            Before I change anything
          </p>
          <ul className="mt-1 space-y-1">
            {turn.proposed.map((command, index) => (
              <li key={index} className="text-sm text-text-secondary">
                · {command.sentence}
              </li>
            ))}
          </ul>
          <Button
            size="sm"
            className="mt-2"
            disabled={busy || !turn.open}
            onClick={onConfirm}
          >
            {turn.open ? "Go ahead" : "Done"}
          </Button>
        </div>
      )}
    </div>
  );
}


/**
 * A question that belongs somewhere else, answered with a direction.
 *
 * Rendered as its own card rather than as chat text so it is obvious at a
 * glance that nothing was attempted. The phrase that triggered it is quoted,
 * because "it refused and I do not know why" is how people stop trusting a
 * boundary.
 */
function Redirect({ scope }: { scope: CopilotScope }) {
  return (
    <div className="max-w-[95%] rounded-lg border border-border bg-surface-raised px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">
        Not my area
      </p>
      <p className="mt-1 text-sm text-text-secondary">{scope.message}</p>
      {scope.matched && (
        <p className="mt-1.5 text-xs text-text-muted">
          I stopped at “{scope.matched}”.
        </p>
      )}
    </div>
  );
}

