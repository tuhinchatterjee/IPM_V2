"use client";

/** A saved comparison: common KPIs and every component side by side, copied
 * from the results' published decompositions (nothing recomputed). */

import * as React from "react";
import Link from "next/link";

import { ChartCard } from "@/components/viz/chart-card";
import { ExportPackage } from "@/components/workspace/export-package";
import { ShareButton } from "@/components/workspace/share-button";
import { comparisonBars, type Comparison } from "@/lib/viz/decomposition";
import { sar, sarDelta } from "@/lib/viz/format";
import { driverColor, driverLabel } from "@/lib/viz/palette";
import { readObject, type GovernedObject } from "@/lib/workspace/objects";

export function ComparisonPage({ comparisonId }: { comparisonId: string }) {
  const [obj, setObj] = React.useState<GovernedObject<Comparison> | null>(null);
  const [error, setError] = React.useState("");
  const [scope, setScope] = React.useState<"selected" | "total">("selected");
  React.useEffect(() => {
    readObject<Comparison>(comparisonId)
      .then(setObj)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [comparisonId]);
  if (error)
    return (
      <p role="alert" className="text-sm text-negative" data-testid="comparison-error">
        {error}
      </p>
    );
  if (!obj) return <p className="text-sm text-text-muted">Loading comparison…</p>;
  const c = obj.body;
  const fig = comparisonBars(c, scope);
  const context = { period: c.period, source: `comparison ${obj.object_id} v${obj.version} · ${c.method}` };
  return (
    <section className="space-y-4" data-testid="comparison" data-comparison-id={obj.object_id} data-items={c.items.length}>
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">{obj.title}</h1>
        <span className="text-xs text-text-muted">
          {c.domain_id} {c.period} · method {c.method} · {c.note}
        </span>
        <span className="ml-auto">
          <ShareButton objectId={obj.object_id} testId="comparison-share" />
          <ExportPackage objectId={obj.object_id} scopeSelector="main" testId="comparison-export" compact />
        </span>
      </header>
      <div className="overflow-auto rounded-lg border border-border" data-testid="comparison-kpis">
        <table className="w-full text-xs">
          <thead className="bg-surface-sunken">
            <tr>
              <th className="px-2 py-1 text-left">Result</th>
              <th className="px-2 py-1 text-left">Baseline</th>
              <th className="px-2 py-1 text-right">Selected opening</th>
              <th className="px-2 py-1 text-right">Selected Δ</th>
              <th className="px-2 py-1 text-right">Selected Δ %</th>
              <th className="px-2 py-1 text-right">Total-book Δ</th>
              <th className="px-2 py-1 text-right">Total Δ %</th>
            </tr>
          </thead>
          <tbody>
            {c.items.map((i, n) => {
              const k = c.kpis[n];
              return (
                <tr key={i.result_id} className="border-t border-border" data-result-id={i.result_id}>
                  <td className="px-2 py-1">
                    <Link href={`/what-if/result/${i.result_id}`} className="text-accent underline">
                      {i.scenario_name}
                    </Link>{" "}
                    <span className="text-text-muted">{i.cohort}</span>
                  </td>
                  <td className="px-2 py-1">{i.baseline_mode === "PRIOR_SCENARIO" ? `layered on ${i.chain.join(" → ")}` : "original"}</td>
                  <td className="px-2 py-1 text-right tabular">{sar(Number(k.selected_opening))}</td>
                  <td className="px-2 py-1 text-right tabular">{sarDelta(Number(k.selected_change))}</td>
                  <td className="px-2 py-1 text-right tabular">{k.selected_change_pct ?? "—"}%</td>
                  <td className="px-2 py-1 text-right tabular">{sarDelta(Number(k.total_change))}</td>
                  <td className="px-2 py-1 text-right tabular">{k.total_change_pct ?? "—"}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex gap-1 text-xs">
        {(["selected", "total"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={scope === s} onClick={() => setScope(s)} className={`rounded-md border px-2 py-1 ${scope === s ? "border-accent bg-accent text-accent-contrast" : "border-border"}`} data-testid={`comparison-scope-${s}`}>
            {s === "selected" ? "Selected scope" : "Total active book"}
          </button>
        ))}
      </div>
      <ChartCard
        title={`Component by component — ${scope === "selected" ? "selected scope" : "total active book"}`}
        subtitle="Each bar is one result's published component value; components not measured in any result are listed in the table only"
        testId="comparison-chart"
        context={context}
        data={fig.data}
        layout={fig.layout}
        height={420}
        table={{
          columns: [
            { key: "label", label: "Component" },
            ...c.items.map((i) => ({ key: i.result_id, label: `${i.scenario_name} (SAR mn)`, align: "right" as const })),
          ],
          rows: c.components.map((k) => ({
            label: k.label,
            ...Object.fromEntries(c.items.map((i) => [i.result_id, k.values[i.result_id]?.[scope]?.status === "N/A" ? "N/A" : (k.values[i.result_id]?.[scope]?.value ?? "")])),
          })),
        }}
        defaultShowData
      />
      <ul className="flex flex-wrap gap-2 text-[10px] text-text-muted" aria-label="Component colours">
        {c.components.map((k) => (
          <li key={k.id}>
            <span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: driverColor(k.id) }} />
            {driverLabel(k.id)}
          </li>
        ))}
      </ul>
    </section>
  );
}
