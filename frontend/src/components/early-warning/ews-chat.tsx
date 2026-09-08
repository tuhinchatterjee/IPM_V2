"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Composer } from "@/components/ask/composer";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type EarlyWarningV2Answer } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { chartFor, showsChart, type EwsScope } from "./chart-rules";
import { TrendChart, CategoryBarChart } from "@/components/analytics/charts";

/**
 * The Early Warning chat, answering on the screen it was asked from.
 *
 * The deck puts a chat bar on every early warning screen and treats it as
 * the primary navigation: the drill-downs are reachable from it, not only
 * from the tables. Sending the reader to a separate thread page to ask
 * "which layer moved most?" loses the screen they were reading, which is
 * the context that made the question worth asking.
 *
 * It answers through the Early Warning domain's own endpoint rather than
 * the general one. That is narrower on purpose: it reads this domain and no
 * other, so it cannot reach another book by construction rather than by a
 * lock that has to hold. A question this domain does not answer says so.
 */
export function EarlyWarningChat({
  customerId,
  onOpenBorrower,
}: {
  /** The obligor the screen is currently about, so "what should I do?"
   *  is answered about that obligor rather than about the book. */
  customerId?: string | null;
  onOpenBorrower?: (customerId: string) => void;
}) {
  const suggestions = useAsync(() => api.earlyWarningV2Suggestions(), []);
  const [question, setQuestion] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [turns, setTurns] = React.useState<
    { question: string; answer: EarlyWarningV2Answer }[]
  >([]);

  const ask = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;
      setBusy(true);
      setError(null);
      try {
        const answer = await api.earlyWarningV2Ask({
          question: trimmed,
          customerId: customerId ?? undefined,
        });
        setTurns((prior) => [...prior, { question: trimmed, answer }]);
        setQuestion("");
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "CreditProbe could not answer that question.",
        );
      } finally {
        setBusy(false);
      }
    },
    [busy, customerId],
  );

  return (
    <section className="space-y-3">
      <Composer
        value={question}
        onChange={setQuestion}
        onSubmit={(q) => void ask(q)}
        busy={busy}
        suggestions={(suggestions.data?.questions ?? []).slice(0, 3)}
        placeholder="Ask about this portfolio. Try: which layer moved most?"
      />
      {error && (
        <Card className="border-negative/40 p-3 text-sm text-negative">{error}</Card>
      )}
      {busy && <Skeleton className="h-24 w-full" />}
      {turns
        .slice()
        .reverse()
        .map((turn, i) => (
          <Answer
            key={turns.length - i}
            question={turn.question}
            answer={turn.answer}
            onAsk={(q) => void ask(q)}
            onOpenBorrower={onOpenBorrower}
          />
        ))}
    </section>
  );
}

function Answer({
  question,
  answer,
  onAsk,
  onOpenBorrower,
}: {
  question: string;
  answer: EarlyWarningV2Answer;
  onAsk: (question: string) => void;
  onOpenBorrower?: (customerId: string) => void;
}) {
  const scope = (answer.scope ?? "") as EwsScope;
  const rows = answer.facts?.rows ?? [];
  const kind = answer.answered ? chartFor(scope) : null;

  return (
    <Card className="space-y-3 p-4">
      <p className="text-xs text-text-muted">{question}</p>
      <p className="text-[15px] font-medium leading-relaxed text-text-primary">
        {answer.direct}
      </p>
      {answer.interpretation && (
        <div className="border-l-2 border-accent/50 pl-3">
          <p className="meta mb-1 text-text-muted">CreditProbe interpretation</p>
          <p className="text-sm leading-relaxed text-text-secondary">
            {answer.interpretation}
          </p>
        </div>
      )}
      {answer.points && answer.points.length > 0 && (
        <ul className="space-y-1.5">
          {answer.points.map((point, i) => (
            <li key={i} className="text-sm leading-relaxed text-text-secondary">
              {point}
            </li>
          ))}
        </ul>
      )}

      {showsChart(scope) && kind && <AnswerChart kind={kind} rows={rows} />}

      {answer.drivers && answer.drivers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {answer.drivers.slice(0, 5).map((d) => (
            <Badge key={d.code} variant="outline">
              {d.code} {d.name} {d.score.toFixed(0)}
            </Badge>
          ))}
        </div>
      )}

      {rows.length > 0 && onOpenBorrower && (
        <div className="flex flex-wrap gap-1.5">
          {rows
            .filter((r) => typeof r.customer_id === "string")
            .slice(0, 5)
            .map((r) => (
              <button
                key={String(r.customer_id)}
                type="button"
                onClick={() => onOpenBorrower(String(r.customer_id))}
                className="rounded-md border border-border px-2 py-1 text-xs text-accent hover:bg-surface-hover"
              >
                {String(r.customer_name ?? r.customer_id)}
              </button>
            ))}
        </div>
      )}

      {answer.follow_ups && answer.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-t border-border pt-2.5">
          {answer.follow_ups.slice(0, 4).map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onAsk(q)}
              className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary transition-colors hover:border-accent hover:text-accent"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {answer.facts?.caveats && answer.facts.caveats.length > 0 && (
        <p className="text-[11px] leading-relaxed text-text-muted">
          {answer.facts.caveats.join(" ")}
        </p>
      )}
    </Card>
  );
}

/** The chart, when the answer is genuinely about shape. */
function AnswerChart({
  kind,
  rows,
}: {
  kind: NonNullable<ReturnType<typeof chartFor>>;
  rows: Record<string, unknown>[];
}) {
  if (kind === "movement" && rows.length >= 2) {
    return (
      <CategoryBarChart
        data={rows.map((r) => ({
          label: String(r.name ?? r.layer ?? ""),
          points: Number(r.points_contributed ?? 0),
        }))}
        xKey="label"
        series={[{ key: "points", label: "Points contributed", slot: 0 }]}
        height={180}
      />
    );
  }
  if (kind === "trend" && rows.length >= 3) {
    return (
      <TrendChart
        data={rows.map((r) => ({
          period: String(r.snapshot_month ?? r.period ?? ""),
          ews: Number(r.ews_score ?? 0),
        }))}
        xKey="period"
        series={[{ key: "ews", label: "EWS", slot: 0 }]}
        height={180}
        area
      />
    );
  }
  if (rows.length >= 2) {
    return (
      <CategoryBarChart
        data={rows.slice(0, 10).map((r) => ({
          label: String(r.customer_name ?? r.label ?? r.segment ?? ""),
          score: Number(r.ews_score ?? r.mean_ews ?? r.portfolio_ews ?? 0),
        }))}
        xKey="label"
        series={[{ key: "score", label: "EWS", slot: 0 }]}
        height={200}
      />
    );
  }
  return null;
}
