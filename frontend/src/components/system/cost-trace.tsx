"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type CostTrace as Trace } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Where the intelligence spend goes. R2 §16, administrator only.
 *
 * The question this panel answers is "which kinds of question are expensive,
 * and why" — not "what did this cost in money". Cost is shown in units, which
 * are a declared weighting of measured tokens by tier; a currency figure would
 * need a price list, and a stale price list in a governed product is a number
 * somebody quotes.
 *
 * No model id appears here. §16 is explicit that the model serving a request
 * is not shown in the product, and the model NAMES the backend can return are
 * deliberately not rendered: what an administrator needs from this screen is
 * whether the routing is working, which the class and the tier already say.
 */

const CLASS_TONE: Record<string, string> = {
  A_DATA: "border-positive/30 bg-positive/10 text-positive",
  B_ORCHESTRATION: "border-accent/30 bg-accent/10 text-accent",
  C_JUDGEMENT: "border-caution/30 bg-caution/10 text-caution",
};

function tidy(value: number, places = 0): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
}

function ClassBadge({ name, label }: { name: string; label: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
        CLASS_TONE[name] ?? "border-border bg-surface-sunken text-text-secondary"
      }`}
    >
      {label}
    </span>
  );
}

function ByClass({ trace }: { trace: Trace }) {
  const rows = Object.values(trace.summary.by_class).filter((row) => row.questions > 0);
  if (!rows.length) {
    return (
      <p className="text-xs text-text-secondary">
        No questions have been asked since this deployment started, so there is nothing to
        report. Ask one and it appears here.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-left text-xs">
        <thead>
          <tr className="border-b border-border text-[10px] uppercase tracking-wide text-text-secondary">
            <th className="py-1.5 pr-3 font-medium">Kind of question</th>
            <th className="py-1.5 pr-3 text-right font-medium">Asked</th>
            <th className="py-1.5 pr-3 text-right font-medium">Model calls each</th>
            <th className="py-1.5 pr-3 text-right font-medium">Input tokens each</th>
            <th className="py-1.5 pr-3 text-right font-medium">Cost units each</th>
            <th className="py-1.5 text-right font-medium">Time each</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.class} className="border-b border-border/50 last:border-0">
              <td className="py-1.5 pr-3">
                <ClassBadge name={row.class} label={row.label} />
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{tidy(row.questions)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{tidy(row.avg_model_calls, 2)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{tidy(row.avg_input_tokens)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{tidy(row.avg_cost_units, 1)}</td>
              <td className="py-1.5 text-right tabular-nums">{tidy(row.avg_duration_ms)} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Questions({ trace }: { trace: Trace }) {
  const rows = trace.questions.slice(0, 20);
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-left text-xs">
        <thead>
          <tr className="border-b border-border text-[10px] uppercase tracking-wide text-text-secondary">
            <th className="py-1.5 pr-3 font-medium">Question</th>
            <th className="py-1.5 pr-3 font-medium">Kind</th>
            <th className="py-1.5 pr-3 text-right font-medium">Calls</th>
            <th className="py-1.5 pr-3 text-right font-medium">Tools</th>
            <th className="py-1.5 pr-3 text-right font-medium">In</th>
            <th className="py-1.5 pr-3 text-right font-medium">Out</th>
            <th className="py-1.5 pr-3 text-right font-medium">Cached</th>
            <th className="py-1.5 text-right font-medium">Units</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.question ?? index}-${index}`} className="border-b border-border/50 last:border-0">
              <td className="max-w-[22rem] truncate py-1.5 pr-3" title={row.question ?? ""}>
                {row.question || "—"}
                {row.reproduced ? (
                  <span className="ml-2 text-[10px] uppercase tracking-wide text-positive">
                    served from store
                  </span>
                ) : null}
              </td>
              <td className="py-1.5 pr-3">
                <ClassBadge name={row.question_class} label={row.class_label} />
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{row.model_calls}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">
                {row.tool_calls}
                {row.repeated_tool_calls > 0 ? (
                  <span className="text-caution"> +{row.repeated_tool_calls} refused</span>
                ) : null}
              </td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{tidy(row.input_tokens)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">{tidy(row.output_tokens)}</td>
              <td className="py-1.5 pr-3 text-right tabular-nums">
                {row.cached_share > 0 ? `${Math.round(row.cached_share * 100)}%` : "—"}
              </td>
              <td className="py-1.5 text-right tabular-nums">{tidy(row.cost_units, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CostTracePanel() {
  const trace = useAsync(() => api.askCost(50), []);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Where the intelligence spend goes</CardTitle>
          {trace.data ? (
            <Badge variant="outline">
              {tidy(trace.data.summary.questions)} question(s) since start
            </Badge>
          ) : null}
        </div>
        <CardDescription>
          Every question is measured: how many model calls it took, how many tokens went in
          and out, how much of the input arrived from cache, and how many governed tool calls
          it made. Cost is shown in units — a declared weighting of measured tokens by tier —
          rather than in money, because a price list goes stale and a stale one gets quoted.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {trace.error ? (
          <p className="text-xs text-text-secondary">
            The cost trace could not be read. It is available to administrators only.
          </p>
        ) : null}
        {trace.loading && !trace.data ? (
          <p className="text-xs text-text-secondary">Reading the cost trace…</p>
        ) : null}
        {trace.data ? (
          <>
            <ByClass trace={trace.data} />
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-text-secondary">
              <span>
                <span className="text-text-primary">{tidy(trace.data.summary.model_calls)}</span>{" "}
                model call(s) in total
              </span>
              <span>
                <span className="text-text-primary">
                  {tidy(trace.data.summary.cost_units, 1)}
                </span>{" "}
                cost unit(s) spent
              </span>
              <span>
                <span className="text-text-primary">
                  {tidy(trace.data.summary.cost_units_avoided, 1)}
                </span>{" "}
                avoided by answering from the store
              </span>
              <span>
                <span className="text-text-primary">
                  {Math.round(trace.data.summary.cache_hit_rate * 100)}%
                </span>{" "}
                of questions served without a model call
              </span>
            </div>
            <Questions trace={trace.data} />
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
