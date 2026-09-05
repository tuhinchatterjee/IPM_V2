"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { ValidationChart } from "@/components/scorecard-validation/validation-chart";
import { count, humanise, technical } from "@/lib/format";
import type { ScvResult, ScvState, ScvTest } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * One validation test result on the screen. §21.
 *
 * The whole design of this component is the ten states, and the reason it is
 * a component rather than a row in a table is that six of those states have no
 * number and still have to say something useful. A table forces every result
 * into the same shape — a value column, a limit column, a verdict — and six
 * times out of ten the honest content of that row is a sentence.
 *
 * What this refuses to do
 * ------------------------
 * **It never shows a value for an unmeasured state.** The backend will not
 * construct such a result, and this will not render one: `measured` gates the
 * number, the limit, the chart and the table together, so there is no path by
 * which a refusal acquires a figure on the way to the screen.
 *
 * **It never paints NO_LIMIT green.** A measurement with nothing governed to
 * compare it against is its own state with its own colour. Reading it as a
 * pass is precisely the defect that let a real monotonicity breach ship as a
 * green tick, and the colour is the fix.
 *
 * **It never collapses the six refusals into one grey chip.** NOT_MATURED
 * means wait; INSUFFICIENT_SAMPLE means the cohort is too thin; UNAVAILABLE
 * means a column is missing; NOT_APPLICABLE means this model has no such
 * thing. Those are four different actions and one chip would name none of
 * them.
 */

/**
 * Colour by state, and the four groups are deliberately distinguishable.
 *
 * Verdicts carry status colour. NO_LIMIT carries a warning-adjacent neutral,
 * because it is a measurement nobody agreed a threshold for — not good news
 * and not bad news, but not nothing either. The refusals are muted, and
 * CALCULATION_ERROR is not: a test that threw is a defect in the environment
 * and it should look like one.
 */
const TONE: Record<ScvState, string> = {
  PASS: "border-positive/40 bg-positive/10 text-positive",
  WARNING: "border-warning/40 bg-warning/10 text-warning",
  FAIL: "border-negative/40 bg-negative/10 text-negative",
  NO_LIMIT: "border-border-strong bg-surface-hover text-text",
  CALCULATION_ERROR: "border-negative/40 bg-negative/10 text-negative",
  UNAVAILABLE: "border-border bg-surface text-text-muted",
  INSUFFICIENT_SAMPLE: "border-border bg-surface text-text-muted",
  NOT_MATURED: "border-border bg-surface text-text-muted",
  NOT_AUTHORISED: "border-border bg-surface text-text-muted",
  NOT_APPLICABLE: "border-border bg-surface text-text-muted",
};

export function StateChip({ result, className }: {
  result: Pick<ScvResult, "state" | "state_label">;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 text-[10px]",
        "font-semibold uppercase tracking-wider",
        TONE[result.state] ?? TONE.NOT_APPLICABLE,
        className,
      )}
    >
      {result.state_label || result.state}
    </span>
  );
}

/**
 * The measured figure, at four decimals.
 *
 * Validation statistics are exempt from the two-decimal display contract, and
 * the exemption is not cosmetic: an AUC of 0.6547 against a limit of 0.65 is a
 * breach, and written as 0.65 it is a pass. The contract governs the money and
 * the rates a committee reads as amounts. This is neither.
 */
function Figure({ result }: { result: ScvResult }) {
  if (!result.measured || result.value === null) return null;
  return (
    <div className="flex items-baseline gap-3">
      <span className="font-mono text-2xl tabular-nums text-text">
        {technical(result.value, 4)}
      </span>
      {result.limit !== null && (
        <span className="text-xs text-text-muted">
          limit {technical(result.limit, 4)}
          {result.limit_source && (
            <span className="ml-1 text-text-muted">
              ({result.limit_source.toLowerCase()})
            </span>
          )}
        </span>
      )}
      {result.limit === null && result.state === "NO_LIMIT" && (
        <span className="text-xs text-warning">
          measured, but no governed limit to compare it against
        </span>
      )}
    </div>
  );
}

/** What it was computed over. Absent from a refusal, because there is no over. */
function Provenance({ result }: { result: ScvResult }) {
  const parts: string[] = [];
  if (result.period) parts.push(result.period);
  if (result.reference_period) parts.push(`vs ${result.reference_period}`);
  if (result.segment) parts.push(result.segment);
  if (result.observations) parts.push(`${count(result.observations)} rows`);
  if (result.events) parts.push(`${count(result.events)} defaults`);
  if (!parts.length) return null;
  return (
    <p className="text-[11px] text-text-muted">{parts.join(" · ")}</p>
  );
}

/** The result's own table, when it carries one. */
function ResultTable({ result }: { result: ScvResult }) {
  const table = result.table ?? [];
  if (!table.length) return null;
  const columns = Object.keys(table[0]).filter(
    (key) => !Array.isArray(table[0][key])
      && typeof table[0][key] !== "object");
  if (!columns.length) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border">
            {columns.map((column) => (
              <th
                key={column}
                className="px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-text-muted"
              >
                {humanise(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.slice(0, 40).map((row, i) => (
            <tr key={i} className="border-b border-border/50 last:border-0">
              {columns.map((column) => {
                const value = row[column];
                return (
                  <td
                    key={column}
                    className={cn(
                      "px-2 py-1.5",
                      typeof value === "number"
                        && "text-right font-mono tabular-nums",
                    )}
                  >
                    {typeof value === "number"
                      ? technical(value, 4)
                      : String(value ?? "—")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {table.length > 40 && (
        <p className="mt-1 text-[11px] text-text-muted">
          First 40 of {count(table.length)} rows. The full table is in the
          report.
        </p>
      )}
    </div>
  );
}

export function ResultCard({ result, test, defaultOpen = false }: {
  result: ScvResult;
  test?: ScvTest;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  const hasDetail = Boolean(
    result.chart || (result.table ?? []).length || result.method
    || (result.limitations ?? []).length || test);

  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] text-text-muted">
              {result.test_id}
            </span>
            <h3 className="text-sm font-semibold text-text">
              {test?.name ?? humanise(result.test_id)}
            </h3>
            <StateChip result={result} />
          </div>
          <Figure result={result} />
          {/* The sentence is the product on a refusal, and it is written to be
              quoted into a report unedited rather than paraphrased. */}
          {result.detail && (
            <p className="max-w-3xl text-sm leading-relaxed text-text-muted">
              {result.detail}
            </p>
          )}
          {result.remedy && (
            <p className="max-w-3xl text-xs leading-relaxed text-text-muted">
              <span className="font-semibold uppercase tracking-wider">
                What to do
              </span>{" "}
              — {result.remedy}
            </p>
          )}
          <Provenance result={result} />
        </div>

        {hasDetail && (
          <button
            type="button"
            onClick={() => setOpen((was) => !was)}
            className="shrink-0 rounded border border-border px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
          >
            {open ? "Hide evidence" : "Evidence"}
          </button>
        )}
      </div>

      {open && (
        <div className="space-y-5 border-t border-border p-4">
          {test?.purpose && (
            <div className="space-y-1">
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                What this asks
              </h4>
              <p className="text-sm leading-relaxed text-text-muted">
                {test.purpose}
              </p>
            </div>
          )}

          <ValidationChart result={result} />
          <ResultTable result={result} />

          {result.method && (
            <div className="space-y-1">
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                How it was calculated
              </h4>
              <p className="text-sm leading-relaxed text-text-muted">
                {result.method}
              </p>
            </div>
          )}

          {(result.limitations ?? []).length > 0 && (
            <div className="space-y-1">
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                What this does not tell you
              </h4>
              <ul className="space-y-1 text-sm leading-relaxed text-text-muted">
                {result.limitations.map((limitation) => (
                  <li key={limitation}>— {limitation}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
            {(test?.cbuae ?? []).map((reference) => (
              <Badge key={reference} variant="outline">{reference}</Badge>
            ))}
            {result.calculation_version && (
              <span className="text-[11px] text-text-muted">
                calculation {result.calculation_version}
              </span>
            )}
            {result.score_direction && (
              <span className="text-[11px] text-text-muted">
                {result.score_direction.toLowerCase().replace(/_/g, " ")}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
