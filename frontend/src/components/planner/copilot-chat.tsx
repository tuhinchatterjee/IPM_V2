"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { api, ApiError, type CopilotScope, type CopilotTurn } from "@/lib/api";
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
 * **Nothing here mutates.** Every change the conversation produces goes
 * through `onCommand`, which the parent turns into `api.planner.copilot.apply`
 * — the same call the structured panels make. A chat that wrote to its own
 * endpoint would be the second mutation path §39 exists to prevent.
 */

export type ChatTurn = {
  id: number;
  who: "person" | "copilot";
  text: string;
  refusal?: CopilotScope;
  /** Something the person can do next, offered rather than performed. */
  offer?: { label: string; command: string; payload: Record<string, unknown> };
};

const OPENING =
  "Tell me what you want to do. I can start a plan, add milestones and " +
  "tasks, link things together, and tell you what is overdue or blocked.";

export function CopilotChat({
  draftKey,
  projectId,
  suggestions = [],
  onTurn,
  onCommand,
  className,
}: {
  draftKey?: string;
  projectId?: number;
  suggestions?: string[];
  onTurn?: (turn: CopilotTurn) => void;
  onCommand?: (command: string, payload: Record<string, unknown>) => void;
  className?: string;
}) {
  const [turns, setTurns] = React.useState<ChatTurn[]>([
    { id: 0, who: "copilot", text: OPENING },
  ]);
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const next = React.useRef(1);
  const foot = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    foot.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const say = React.useCallback((turn: Omit<ChatTurn, "id">) => {
    setTurns((existing) => [...existing, { ...turn, id: next.current++ }]);
  }, []);

  const send = React.useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || busy) return;
      setDraft("");
      say({ who: "person", text });
      setBusy(true);
      try {
        const turn = await api.planner.copilot.chat({
          message: text,
          draft: draftKey,
          project_id: projectId,
        });
        if (!turn.in_scope && turn.refusal) {
          say({
            who: "copilot",
            text: turn.refusal.message,
            refusal: turn.refusal,
          });
        } else {
          say({ who: "copilot", text: describe(turn) });
          onTurn?.(turn);
        }
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
    [busy, draftKey, projectId, onTurn, say],
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
          <Turn key={turn.id} turn={turn} onCommand={onCommand} />
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
  onCommand,
}: {
  turn: ChatTurn;
  onCommand?: (command: string, payload: Record<string, unknown>) => void;
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
    <div className="max-w-[85%] space-y-2">
      <p className="rounded-lg bg-surface-raised px-3 py-2 text-sm text-text-secondary">
        {turn.text}
      </p>
      {turn.offer && onCommand && (
        <Button
          size="sm"
          variant="outline"
          onClick={() => onCommand(turn.offer!.command, turn.offer!.payload)}
        >
          {turn.offer.label}
        </Button>
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

/** What the Copilot says back when it understood and is ready to act. */
function describe(turn: CopilotTurn): string {
  const completeness = turn.completeness;
  if (!turn.draft) {
    return (
      "Right — that is delivery, so it is mine. Open the plan you mean, or " +
      "start a new one, and I will work on it with you."
    );
  }
  if (!completeness) return "I have the plan open.";
  if (completeness.publishable && completeness.complete) {
    return "The plan is complete. Have a look at the preview and publish it when you are happy.";
  }
  if (completeness.publishable) {
    const first = completeness.warnings[0];
    return first
      ? `Nothing is blocking publication. Worth a look: ${first.message}`
      : "Nothing is blocking publication.";
  }
  const first = completeness.blockers[0];
  const count = completeness.blockers.length;
  return count === 1
    ? `One thing still to settle: ${first.message}`
    : `${count} things still to settle. The first: ${first?.message ?? ""}`;
}
