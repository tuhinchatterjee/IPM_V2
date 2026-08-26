"use client";

import * as React from "react";
import { ChevronLeft } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ReferenceAnswer, ValidationCase, ValidationTurn } from "@/lib/api";

/**
 * One benchmark case, opened.
 *
 * The panel exists because a score on its own is not evidence. "92%" invites
 * trust without offering anything to check; what a credit officer needs is the
 * question, what CreditProbe said, what the reference says, and — where they
 * differ — a sentence explaining the difference in their own vocabulary.
 *
 * So nothing here is hidden, including a bad answer. The reference is shown
 * beside the answer rather than instead of it, and every deduction is written
 * out. A validation panel that only displayed its wins would be a marketing
 * page with a percentage on it.
 *
 * The reference was computed AFTER the answer, by a separate implementation
 * over the same governed data. It was never available to the model.
 */

const COMPONENT_LABELS: Record<string, string> = {
  intent: "Intent match",
  plan: "Concept and plan match",
  dataset: "Dataset match",
  relationship: "Relationship match",
  period: "Period and grain match",
  result: "Result-value match",
  context: "Conversation context",
  grounding: "Grounding",
};

export function ValidationCaseDetail({
  detail,
  onBack,
  isAdministrator,
}: {
  detail: ValidationCase;
  onBack: () => void;
  isAdministrator: boolean;
}) {
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2 mb-1">
            <ChevronLeft className="size-4" aria-hidden />
            All cases
          </Button>
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
            {detail.category}
          </p>
          <h3 className="mt-0.5 text-[15px] font-semibold text-text-primary">
            {detail.title}
          </h3>
        </div>
        <MatchDial score={detail.score} verdict={detail.verdict} />
      </div>

      <ComponentBreakdown components={detail.components} overall={detail.score} />

      {detail.deductions.length > 0 && (
        <Section title="Why the score was not 100%">
          <ul className="space-y-2">
            {detail.deductions.map((line, index) => (
              <li
                key={index}
                className="flex gap-2 text-[13px] leading-relaxed text-text-secondary"
              >
                <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-warning" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section
        title={detail.turns.length > 1 ? "The conversation, turn by turn" : "The request"}
        note={
          detail.turns.length > 1
            ? "A multi-turn case shows every turn, so you can see exactly where context held and where it did not."
            : undefined
        }
      >
        <div className="space-y-4">
          {detail.turns.map((turn) => (
            <TurnBlock
              key={turn.index}
              turn={turn}
              showTurnNumber={detail.turns.length > 1}
              isAdministrator={isAdministrator}
            />
          ))}
        </div>
      </Section>
    </div>
  );
}

function TurnBlock({
  turn,
  showTurnNumber,
  isAdministrator,
}: {
  turn: ValidationTurn;
  showTurnNumber: boolean;
  isAdministrator: boolean;
}) {
  return (
    <article className="rounded-lg border border-border bg-surface">
      <header className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          {showTurnNumber && (
            <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
              Turn {turn.index}
            </span>
          )}
          {!turn.live && (
            <Badge variant="warning">Answered without the live model</Badge>
          )}
        </div>
        <span
          className={cn(
            "font-display text-[13px] font-semibold tabular-nums",
            toneOf(turn.score),
          )}
        >
          {Math.round(turn.score)}%
        </span>
      </header>

      <div className="space-y-3 px-3 py-3">
        <p className="font-user text-[13px] text-text-primary">
          <span className="mr-2 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
            Asked
          </span>
          {turn.question}
        </p>

        <TwoUp
          left={{
            title: "CreditProbe answered",
            body: turn.answer || "— nothing —",
            note: turn.interpretation,
          }}
          right={{
            title: "Reference result",
            body: turn.reference?.summary || "No independent reference for this turn.",
            note:
              "Computed independently by the CreditProbe validation runtime, " +
              "after the answer above. It was never shown to the model.",
          }}
        />

        {turn.reference && <ValueComparison turn={turn} reference={turn.reference} />}

        {turn.expected.length > 0 && (
          <Detail summary="What a correct answer had to do">
            <ul className="space-y-1">
              {turn.expected.map((line, index) => (
                <li key={index} className="text-[12px] text-text-secondary">
                  {line}
                </li>
              ))}
            </ul>
          </Detail>
        )}

        {isAdministrator && (
          <Detail summary="How CreditProbe read it, and what it ran">
            <div className="space-y-3">
              <KeyValues
                title="Live reading"
                values={pick(turn.reading, [
                  "intent",
                  "conversation_action",
                  "confidence",
                  "concepts",
                  "metrics",
                  "entities",
                  "dimensions",
                  "grain",
                  "periods",
                  "source",
                  "model",
                ])}
              />
              <KeyValues
                title="Plan"
                values={pick(turn.plan, [
                  "shape",
                  "dataset",
                  "datasets",
                  "grain",
                  "period",
                  "opening_period",
                  "closing_period",
                  "dimension",
                  "top_n",
                  "filters",
                  "conditions",
                  "summary",
                ])}
              />
              {turn.sql && (
                <div>
                  <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
                    Generated query
                  </p>
                  <pre className="max-h-56 overflow-auto rounded-md border border-border bg-surface-sunken p-2 font-mono text-[11px] leading-relaxed text-text-secondary">
                    {turn.sql}
                  </pre>
                </div>
              )}
              {turn.reference?.derivation && (
                <div>
                  <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
                    How the reference was computed
                  </p>
                  <pre className="max-h-56 overflow-auto rounded-md border border-border bg-surface-sunken p-2 font-mono text-[11px] leading-relaxed text-text-secondary">
                    {turn.reference.derivation}
                  </pre>
                  <p className="mt-1 text-[11px] text-text-muted">
                    Mathematically equivalent SQL is expected to differ. What is
                    compared is the result, never the text of the query.
                  </p>
                </div>
              )}
            </div>
          </Detail>
        )}
      </div>
    </article>
  );
}

/**
 * Figure-by-figure, reference against answer.
 *
 * Only the figures both sides actually carry. A row that says "—" on one side
 * would look like a disagreement when it is an absence, and the point of this
 * table is that a tick means something.
 */
function ValueComparison({
  turn,
  reference,
}: {
  turn: ValidationTurn;
  reference: ReferenceAnswer;
}) {
  const rows = React.useMemo(() => {
    const out: { label: string; expected: string; actual: string; ok: boolean }[] = [];
    for (const [name, expected] of Object.entries(reference.values ?? {})) {
      if (typeof expected !== "number") continue;
      const actual = findValue(turn.values, name);
      if (actual === null) continue;
      out.push({
        label: humanise(name),
        expected: format(expected),
        actual: format(actual),
        ok: close(actual, expected),
      });
    }
    // Only where the reference's ids ARE identities. A dataset reference lists
    // field names, and comparing those against returned rows would compare two
    // different things and call the difference an error — which is exactly what
    // the backend scorer refuses to do.
    const identifies = ["ranking", "cohort", "aggregate", "count"].includes(
      reference.kind,
    );
    const returned = turn.row_count ?? turn.rows?.length ?? 0;
    if (identifies && reference.ids?.length) {
      out.push({
        label: "Rows returned",
        expected: String(reference.ids.length),
        actual: String(returned),
        ok: returned === reference.ids.length,
      });
    }
    return out;
  }, [reference, turn]);

  if (rows.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <table className="w-full text-left text-[12px]">
        <thead className="bg-surface-sunken">
          <tr className="text-text-muted">
            <th className="px-2.5 py-1.5 font-medium">Metric</th>
            <th className="px-2.5 py-1.5 text-right font-medium">Reference</th>
            <th className="px-2.5 py-1.5 text-right font-medium">CreditProbe</th>
            <th className="w-10 px-2.5 py-1.5 text-center font-medium">Match</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={row.label}>
              <td className="px-2.5 py-1.5 text-text-secondary">{row.label}</td>
              <td className="px-2.5 py-1.5 text-right font-mono tabular-nums text-text-secondary">
                {row.expected}
              </td>
              <td className="px-2.5 py-1.5 text-right font-mono tabular-nums text-text-primary">
                {row.actual}
              </td>
              <td
                className={cn(
                  "px-2.5 py-1.5 text-center font-semibold",
                  row.ok ? "text-positive" : "text-negative",
                )}
              >
                {row.ok ? "✓" : "✗"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ComponentBreakdown({
  components,
  overall,
}: {
  components: Record<string, number>;
  overall: number;
}) {
  const entries = Object.entries(components).filter(([name]) => COMPONENT_LABELS[name]);
  if (entries.length === 0) return null;
  return (
    <Section title="Component match">
      <dl className="space-y-1.5">
        {entries.map(([name, value]) => (
          <div key={name} className="flex items-center gap-3">
            <dt className="w-44 shrink-0 text-[12px] text-text-secondary">
              {COMPONENT_LABELS[name]}
            </dt>
            <dd className="flex-1">
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                <div
                  className={cn("h-full rounded-full", barOf(value))}
                  style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
                />
              </div>
            </dd>
            <dd
              className={cn(
                "w-12 shrink-0 text-right font-mono text-[11px] tabular-nums",
                toneOf(value),
              )}
            >
              {Math.round(value)}%
            </dd>
          </div>
        ))}
        <div className="flex items-center gap-3 border-t border-border pt-2">
          <dt className="w-44 shrink-0 text-[12px] font-semibold text-text-primary">
            Overall match
          </dt>
          <dd className="flex-1" />
          <dd
            className={cn(
              "w-12 shrink-0 text-right font-display text-[13px] font-semibold tabular-nums",
              toneOf(overall),
            )}
          >
            {Math.round(overall)}%
          </dd>
        </div>
      </dl>
    </Section>
  );
}

function MatchDial({ score, verdict }: { score: number; verdict: string }) {
  return (
    <div className="shrink-0 text-right">
      <p className={cn("font-display text-2xl font-semibold tabular-nums", toneOf(score))}>
        {Math.round(score)}%
      </p>
      <Badge variant={verdict === "PASS" ? "positive" : verdict === "PARTIAL" ? "warning" : "negative"}>
        {verdict}
      </Badge>
    </div>
  );
}

function TwoUp({
  left,
  right,
}: {
  left: { title: string; body: string; note?: string };
  right: { title: string; body: string; note?: string };
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {[left, right].map((side, index) => (
        <div
          key={index}
          className="rounded-md border border-border bg-surface-sunken p-2.5"
        >
          <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
            {side.title}
          </p>
          <p className="text-[12px] leading-relaxed text-text-primary">{side.body}</p>
          {side.note && (
            <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
              {side.note}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h4 className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
        {title}
      </h4>
      {note && <p className="mb-2 text-[11px] text-text-muted">{note}</p>}
      {children}
    </section>
  );
}

function Detail({
  summary,
  children,
}: {
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded-md border border-border">
      <summary className="cursor-pointer px-2.5 py-1.5 text-[12px] text-text-secondary">
        {summary}
      </summary>
      <div className="border-t border-border px-2.5 py-2">{children}</div>
    </details>
  );
}

function KeyValues({
  title,
  values,
}: {
  title: string;
  values: [string, unknown][];
}) {
  if (values.length === 0) return null;
  return (
    <div>
      <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.12em] text-text-muted">
        {title}
      </p>
      <dl className="divide-y divide-border rounded-md border border-border">
        {values.map(([key, value]) => (
          <div key={key} className="flex gap-3 px-2 py-1">
            <dt className="w-36 shrink-0 text-[11px] text-text-muted">
              {humanise(key)}
            </dt>
            <dd className="min-w-0 flex-1 break-words font-mono text-[11px] text-text-secondary">
              {render(value)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// --------------------------------------------------------------- helpers

function pick(source: Record<string, unknown>, keys: string[]): [string, unknown][] {
  return keys
    .filter((key) => {
      const value = source?.[key];
      if (value === undefined || value === null || value === "") return false;
      if (Array.isArray(value) && value.length === 0) return false;
      if (typeof value === "object" && Object.keys(value as object).length === 0)
        return false;
      return true;
    })
    .map((key) => [key, source[key]] as [string, unknown]);
}

function render(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => render(v)).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function humanise(key: string): string {
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function format(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString()
    : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function close(actual: number, expected: number): boolean {
  if (expected === 0) return Math.abs(actual) < 1e-6;
  return (Math.abs(actual - expected) / Math.abs(expected)) * 100 <= 0.5;
}

/**
 * The observed figure matching a reference figure's name.
 *
 * Mirrors the aliases the backend scorer uses, so the table a user reads agrees
 * with the score they were given.
 */
function findValue(values: Record<string, unknown>, name: string): number | null {
  const aliases: Record<string, string[]> = {
    total: ["total", "total_ead", "total_ecl", "grand_total"],
    row_count: ["row_count", "rows", "count", "customers", "facilities"],
    groups: ["groups", "group_count", "sectors", "dimension_count"],
    top_value: ["top_value", "largest", "max"],
    covered_pct: ["covered_pct", "share_covered_pct"],
    population_total: ["population_total"],
    members: ["members", "population", "member_count"],
    field_count: ["field_count", "fields"],
    period_count: ["period_count", "periods"],
    hops: ["hops", "steps"],
  };
  for (const key of aliases[name] ?? [name]) {
    const value = values?.[key];
    if (typeof value === "number") return value;
  }
  return null;
}

export function toneOf(score: number): string {
  if (score >= 90) return "text-positive";
  if (score >= 70) return "text-warning";
  return "text-negative";
}

function barOf(score: number): string {
  if (score >= 90) return "bg-positive";
  if (score >= 70) return "bg-warning";
  return "bg-negative";
}
