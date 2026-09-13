"use client";

/**
 * The Early Warning chat, at the top of the workspace.
 *
 * §4 asks for it to be a first-class feature rather than a panel somebody has
 * to find, so it sits directly under the title and above the figures, and it
 * stays there at every level — scoped to whatever the reader has drilled into,
 * which the chips say out loud.
 *
 * It talks to `/retail/ews/ask` and nothing else. That endpoint can only read
 * the Early Warning Score domain, so a question about expected credit loss or
 * a stress scenario comes back with a scope notice naming the module that owns
 * it rather than an answer from the wrong book. The notice is rendered, not
 * swallowed: a reader has to be able to see the boundary.
 */

import * as React from "react";
import { CornerDownLeft, Loader2, MessageSquareText, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, type EwsAnswer } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Spark } from "./spark";

interface Turn {
  question: string;
  answer: EwsAnswer | null;
  error?: string;
}

/**
 * The conversation, held outside React.
 *
 * Answering a question can move the screen — "show currently bad customers"
 * applies a cohort filter — and a route the Next router re-renders can unmount
 * this subtree, which threw away the answer the reader had just asked for.
 * Component state cannot survive that; a module-level store can, and the chat
 * is one conversation per workspace rather than one per mount.
 */
const HELD: { turns: Turn[] } = { turns: [] };

export function EwsChat({
  month, product, subProduct, customer, level, onFilters,
}: {
  month: string;
  product: string;
  subProduct: string;
  customer: string;
  level: "portfolio" | "product" | "customer";
  /** The chat can move the screen: a filter it resolves is applied. */
  onFilters?: (filters: Record<string, unknown>) => void;
}) {
  const [typed, setTyped] = React.useState("");
  const [turns, setTurnsState] = React.useState<Turn[]>(() => HELD.turns);
  const setTurns = React.useCallback(
    (next: Turn[] | ((old: Turn[]) => Turn[])) => {
      HELD.turns = typeof next === "function"
        ? (next as (old: Turn[]) => Turn[])(HELD.turns) : next;
      setTurnsState(HELD.turns);
    }, []);
  const [busy, setBusy] = React.useState(false);
  const [prompts, setPrompts] = React.useState<string[]>([]);
  const [scopeNote, setScopeNote] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    api.ewsScorePrompts(level)
      .then((served) => {
        if (!alive) return;
        setPrompts(served.prompts);
        setScopeNote(served.scope_note);
      })
      .catch(() => undefined);
    return () => { alive = false; };
  }, [level]);

  const send = React.useCallback(async (question: string) => {
    const asked = question.trim();
    if (!asked || busy) return;
    setBusy(true);
    setTyped("");
    setTurns((old) => [{ question: asked, answer: null }, ...old].slice(0, 6));
    try {
      const answer = await api.ewsScoreAsk({
        question: asked, month, product, sub_product: subProduct, customer,
      });
      setTurns((old) => old.map((turn, index) =>
        index === 0 ? { ...turn, answer } : turn));
      if (onFilters && answer.in_scope
          && Object.keys(answer.filters ?? {}).length) {
        onFilters(answer.filters);
      }
    } catch (problem) {
      setTurns((old) => old.map((turn, index) =>
        index === 0 ? { ...turn, error: String(problem) } : turn));
    } finally {
      setBusy(false);
    }
  }, [busy, month, product, subProduct, customer, onFilters, setTurns]);

  const scope = customer ? `customer ${customer}`
    : subProduct ? "this sub-portfolio"
      : product ? "this product" : "total retail";

  return (
    <Card className="p-4" data-testid="ews-chat">
      <div className="flex items-center gap-2">
        <MessageSquareText className="size-4 shrink-0 text-accent" aria-hidden />
        <p className="text-sm font-semibold text-text-primary">
          Ask the Early Warning Score
        </p>
        <span className="text-[11px] text-text-muted">
          scoped to {scope} at {month || "the latest month"}
        </span>
      </div>

      <div className="mt-2.5 flex items-end gap-2">
        <textarea
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send(typed);
            }
          }}
          rows={2}
          aria-label="Ask a question about the Early Warning Score"
          data-testid="ews-chat-input"
          placeholder="Which sub-product is deteriorating fastest?"
          className="min-h-[52px] flex-1 resize-none rounded-md border
                     border-border bg-surface px-3 py-2 text-sm
                     text-text-primary placeholder:text-text-muted"
        />
        <Button size="sm" onClick={() => void send(typed)} disabled={busy}
                data-testid="ews-chat-send">
          {busy ? <Loader2 className="mr-1 size-3.5 animate-spin" aria-hidden />
                : <CornerDownLeft className="mr-1 size-3.5" aria-hidden />}
          Ask
        </Button>
      </div>

      {prompts.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5"
             data-testid="ews-chat-prompts">
          {prompts.slice(0, 6).map((prompt) => (
            <button key={prompt} type="button" onClick={() => void send(prompt)}
                    className="rounded-full border border-border px-2.5 py-1
                               text-[11px] text-text-secondary
                               transition-colors hover:bg-surface-muted">
              {prompt}
            </button>
          ))}
        </div>
      ) : null}

      {scopeNote ? (
        <p className="mt-2 flex items-start gap-1 text-[10px] text-text-muted"
           data-testid="ews-chat-scope">
          <Sparkles className="mt-px size-3 shrink-0" aria-hidden />
          {scopeNote}
        </p>
      ) : null}

      {turns.length ? (
        <div className="mt-3 space-y-3 border-t border-border pt-3"
             data-testid="ews-chat-answers">
          {turns.map((turn, index) => (
            <Turn key={`${turn.question}-${index}`} turn={turn}
                  onAsk={(next) => void send(next)} />
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function Turn({ turn, onAsk }: {
  turn: Turn; onAsk: (question: string) => void;
}) {
  const answer = turn.answer;
  return (
    <div className="space-y-2">
      <p className="text-[12px] font-medium text-text-primary">
        <span className="mr-1.5 text-text-muted">You asked:</span>
        {turn.question}
      </p>

      {turn.error ? (
        <p className="text-[12px] text-negative">{turn.error}</p>
      ) : !answer ? (
        <p className="text-[12px] text-text-muted">Reading the domain…</p>
      ) : (
        <div className={cn(
          "rounded-md border p-3",
          answer.in_scope ? "border-border bg-surface-muted/40"
            : "border-warning/40 bg-warning-subtle/40",
        )} data-testid={answer.in_scope ? "ews-chat-answer"
                                        : "ews-chat-out-of-scope"}>
          <p className="text-[11px] italic text-text-muted">
            {answer.interpretation}
          </p>
          <p className="mt-1.5 text-[13px] leading-relaxed text-text-primary">
            {answer.answer}
          </p>

          {!answer.in_scope ? (
            <p className="mt-2 text-[11px] text-text-secondary">
              {answer.scope_note}
            </p>
          ) : null}

          {answer.evidence?.length ? (
            <div className="mt-2.5 flex flex-wrap gap-3">
              {answer.evidence.slice(0, 6).map((one) => (
                <div key={one.label} className="min-w-0">
                  <p className="truncate text-[9px] uppercase tracking-[0.08em] text-text-muted">
                    {one.label}
                  </p>
                  <p className="text-[13px] font-medium tabular-nums text-text-primary">
                    {one.value}
                  </p>
                  {one.note ? (
                    <p className="text-[10px] text-text-muted">{one.note}</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}

          {answer.chart?.points?.length ? (
            <div className="mt-2.5 max-w-xs">
              <Spark label={`${answer.chart.y} by ${answer.chart.x}`}
                     points={answer.chart.points.map((point) => ({
                       month: point.label, value: point.value }))}
                     height={44} testId="ews-chat-chart" />
              <p className="mt-0.5 text-[9px] text-text-muted">
                {answer.chart.points.map((p) => p.label).join(" · ")}
              </p>
            </div>
          ) : null}

          {answer.table?.rows?.length ? (
            <div className="mt-2.5 overflow-x-auto">
              <table className="w-full text-[11px]" data-testid="ews-chat-table">
                <thead className="border-b border-border text-left">
                  <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                    {answer.table.columns.map((column) => (
                      <th key={column} className="px-2 py-1 font-semibold">
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {answer.table.rows.slice(0, 12).map((row, index) => (
                    <tr key={index} className="border-b border-border/60 last:border-0">
                      {row.map((cell, column) => (
                        <td key={column} className="px-2 py-1 tabular-nums text-text-secondary">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {answer.follow_ups?.length ? (
            <div className="mt-2.5 flex flex-wrap gap-1.5"
                 data-testid="ews-chat-follow-ups">
              {answer.follow_ups.slice(0, 5).map((next) => (
                <button key={next} type="button" onClick={() => onAsk(next)}
                        className="rounded-full border border-accent/40
                                   bg-accent-subtle/50 px-2 py-0.5 text-[11px]
                                   text-accent transition-colors
                                   hover:bg-accent-subtle">
                  {next}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
