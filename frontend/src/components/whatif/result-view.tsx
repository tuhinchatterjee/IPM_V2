"use client";

/**
 * A persisted Scenario Result, drawn on the universal decomposition contract.
 *
 * Selected scope and total book side by side on ONE scale, the same
 * component in the same colour and position in both, and the exact table
 * beneath listing every taxonomy component (N/A ones with their reason).
 * Clicking a bar highlights that component in both charts and in the table.
 * Nothing here computes a number: every value is the server's string.
 */

import * as React from "react";
import Link from "next/link";

import { ChartCard, type ChartData } from "@/components/viz/chart-card";
import { ExportPackage } from "@/components/workspace/export-package";
import { ShareButton } from "@/components/workspace/share-button";
import { distribution, pareto } from "@/lib/viz/advanced";
import { contributions } from "@/lib/viz/figures";
import { componentTable, identities, kpis, methodComparison, plotted, scopeEquivalence, sharedScale, stageBeforeAfter, waterfall, type Decomposition, type DecompositionScope } from "@/lib/viz/decomposition";
import { count, moneyCol, sar, sarDelta } from "@/lib/viz/format";
import { METHOD_LABEL } from "@/lib/workspace/method-labels";
import type { ScenarioResult } from "@/lib/workspace/runs";


export function ResultView({ result, actions }: { result: ScenarioResult; actions?: React.ReactNode }) {
  const b = result.body;
  const methods = Object.keys(b.decomposition);
  const [method, setMethod] = React.useState(methods[0] ?? "");
  const [compact, setCompact] = React.useState(false);
  const [highlight, setHighlight] = React.useState("");
  const d = b.decomposition[method];
  const context = { releaseId: b.release_id, period: b.period, source: `scenario_result ${result.object_id} v${result.version} · ${METHOD_LABEL[method] ?? method}` };
  const ran = b.methods.ran;
  const unavailable = Object.entries(b.methods.unavailable ?? {});
  const layered = b.baseline.mode === "PRIOR_SCENARIO";

  return (
    <section className="space-y-4" data-testid="whatif-result" data-result-id={result.object_id} data-methods-ran={ran.join(",")}>
      <header className="flex flex-wrap items-start gap-3 rounded-xl border border-border bg-surface p-3 text-xs">
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold">
            {b.scenario_name} <span className="text-text-muted">· result {result.object_id}</span>
          </h3>
          <p className="text-text-muted">
            {b.cohort.description} · release {b.release_id} ·{" "}
            <span data-testid="whatif-result-stage-policy" data-policy={b.stage_policy_requested ?? b.stage_policy}>
              stages {b.stage_policy_requested ?? b.stage_policy}
            </span>
          </p>
          <p data-testid="whatif-result-baseline" data-mode={b.baseline.mode}>
            Baseline:{" "}
            {layered ? (
              <>
                layered on{" "}
                {b.chain.map((c, i) => (
                  <span key={c.executed_run_id}>
                    {i > 0 && " → "}
                    <span className="font-semibold">{c.name}</span> ({c.executed_run_id})
                  </span>
                ))}
              </>
            ) : (
              <>original reported baseline {b.period}</>
            )}
          </p>
          <p className="font-mono text-[10px] text-text-muted">
            contract {b.contract_digest.slice(0, 16)} · execution {b.execution_digest.slice(0, 16)} · {b.evidence}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {methods.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMethod(m)}
              aria-pressed={m === method}
              className={`rounded-md border px-2 py-1 ${m === method ? "border-accent bg-accent text-accent-contrast" : "border-border"}`}
              data-testid={`whatif-result-method-${m}`}
            >
              {METHOD_LABEL[m] ?? m}
            </button>
          ))}
          {actions}
          <ShareButton objectId={result.object_id} testId="whatif-result-share" />
          <ExportPackage objectId={result.object_id} scopeSelector={`[data-result-id="${result.object_id}"]`} testId="whatif-result-export" />
        </div>
      </header>

      {unavailable.length > 0 && (
        <ul className="rounded-lg border border-warning bg-surface p-2 text-xs" data-testid="whatif-result-unavailable">
          {unavailable.map(([m, why]) => (
            <li key={m}>
              <span className="font-semibold">{METHOD_LABEL[m] ?? m} not run:</span> {why}
            </li>
          ))}
        </ul>
      )}

      {b.notes.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-border bg-surface-sunken p-2 text-xs" data-testid="whatif-result-notes">
          {b.notes.map((n, i) => (
            <li key={i} className={n.includes("SIGN_REVIEW") ? "font-semibold text-negative" : ""}>
              {n}
            </li>
          ))}
        </ul>
      )}

      {d && <DecompositionPanel d={d} compact={compact} setCompact={setCompact} highlight={highlight} setHighlight={setHighlight} context={context} />}

      {ran.length > 1 && (
        <ChartCard
          title="Method comparison"
          subtitle="Every method on the same confirmed scenario, cohort and baseline"
          testId="whatif-result-methods"
          context={context}
          {...methodComparison(b.results)}
          height={260}
          table={{
            columns: [
              { key: "label", label: "Method" },
              { key: "status", label: "Status" },
              moneyCol("baseline", "Baseline", Object.values(b.results) as unknown as Record<string, unknown>[]),
              moneyCol("scenario", "Scenario", Object.values(b.results) as unknown as Record<string, unknown>[]),
              moneyCol("change", "Change", Object.values(b.results) as unknown as Record<string, unknown>[]),
              { key: "reason", label: "Reason / limitations" },
            ],
            rows: Object.values(b.results).map((r) => ({ ...r, reason: [r.reason, ...r.limitations].filter(Boolean).join("; ") })),
          }}
          defaultShowData
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {b.stages.length > 0 && (
          <ChartCard
            title="ECL by stage, before and after"
            subtitle={`Stages ${b.stage_policy_requested ?? b.stage_policy}: exposures keep their stage unless an approved rule moves them`}
            testId="whatif-result-stages"
            context={context}
            {...stageBeforeAfter(b.stages)}
            height={260}
            table={{
              columns: [
                { key: "stage", label: "Stage" },
                { key: "exposures", label: "Exposures", align: "right", format: (v) => count(Number(v)) },
                moneyCol("ecl_before", "ECL before", b.stages as unknown as Record<string, unknown>[]),
                moneyCol("ecl_after", "ECL after", b.stages as unknown as Record<string, unknown>[]),
                moneyCol("change", "Change", b.stages as unknown as Record<string, unknown>[]),
              ],
              rows: b.stages as unknown as Record<string, unknown>[],
            }}
          />
        )}
        {b.top_contributors.length > 0 && (
          <ChartCard
            title="Largest contributors"
            subtitle="Exposures with the largest Delta change"
            testId="whatif-result-top"
            context={context}
            {...contributions(
              b.top_contributors.map((t) => ({ label: `${t.entity_id} · ${t.group}`, value: Number(t.change) })),
              "SAR_mn",
              { dimension: "Exposure" },
            )}
            height={320}
            table={{
              columns: [
                { key: "entity_id", label: "Exposure" },
                { key: "owner_id", label: "Owner" },
                { key: "group", label: "Group" },
                { key: "stage", label: "Stage" },
                { key: "ecl_before", label: "ECL before", align: "right" },
                { key: "ecl_after", label: "ECL after", align: "right" },
                { key: "change", label: "Change", align: "right" },
              ],
              rows: b.top_contributors as unknown as Record<string, unknown>[],
            }}
          />
        )}
        {(b.pareto?.length ?? 0) > 0 && (
          <ChartCard
            title={`Delta change by ${b.pareto?.[0]?.dimension === "product" ? "product" : "sector"}, largest first`}
            subtitle="Bars: change in SAR; line: cumulative share of the selected-scope change"
            testId="whatif-result-pareto"
            context={context}
            {...pareto(b.pareto ?? [])}
            height={320}
            table={{
              columns: [
                { key: "group", label: "Segment" },
                { key: "change", label: "ECL change (SAR m, raw)", align: "right" },
                { key: "cumulative_share", label: "Cumulative share", align: "right" },
              ],
              rows: (b.pareto ?? []) as unknown as Record<string, unknown>[],
            }}
          />
        )}
        {(b.change_distribution?.length ?? 0) > 0 && (
          <ChartCard
            title="How the change is spread across exposures"
            subtitle="Exposures by the change in their own ECL (Delta); unmoved exposures are in the table"
            testId="whatif-result-distribution"
            context={context}
            {...distribution(b.change_distribution ?? [])}
            height={300}
            table={{
              columns: [
                { key: "label", label: "Band" },
                { key: "n", label: "Exposures", align: "right" },
                { key: "ead", label: "EAD (SAR m, raw)", align: "right" },
              ],
              rows: (b.change_distribution ?? []) as unknown as Record<string, unknown>[],
            }}
          />
        )}
      </div>
    </section>
  );
}

function scopeKpis(s: DecompositionScope, testId: string) {
  return (
    <dl className="grid grid-cols-3 gap-2 text-xs md:grid-cols-6" data-testid={testId}>
      {kpis(s).map((k) => (
        <div key={k.label} className="rounded border border-border bg-surface-sunken p-2" title={`raw ${k.raw}`}>
          <dt className="text-text-muted">{k.label}</dt>
          <dd className="font-semibold tabular" data-raw={k.raw}>
            {k.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function DecompositionPanel({
  d,
  compact,
  setCompact,
  highlight,
  setHighlight,
  context,
}: {
  d: Decomposition;
  compact: boolean;
  setCompact: (v: boolean) => void;
  highlight: string;
  setHighlight: (id: string) => void;
  context: { releaseId?: string; period?: string; source?: string };
}) {
  const scale = sharedScale(d);
  const checks = identities(d);
  const table = componentTable(d);
  // DECOMP21: one population -> one bridge, once the equality is proven.
  const eq = scopeEquivalence(d);
  const single = eq.proven;
  const hidden = d.scopes.selected.components.filter((c) => c.status === "N/A").length;
  const selCol = moneyCol("selected", "Selected scope", table as unknown as Record<string, unknown>[]);
  const totCol = moneyCol("total", "Total book", table as unknown as Record<string, unknown>[]);
  const tableData: ChartData = {
    columns: [
      { key: "label", label: "Component" },
      selCol,
      { key: "selected_status", label: "Status" },
      totCol,
      { key: "total_status", label: "Status" },
      ...(single ? [{ key: "identical", label: "Identical" }] : []),
      { key: "reason", label: "Reason / definition" },
    ],
    rows: table.map((r) => ({
      ...r,
      identical: r.selected === r.total && r.selected_status === r.total_status ? "✓ same population" : "✗ differs",
      reason: r.reason || r.definition,
    })),
  };
  const click = (p: { customdata?: unknown }) => {
    const id = Array.isArray(p.customdata) ? String(p.customdata[0]) : "";
    setHighlight(highlight === id ? "" : id);
  };
  const cross = d.cross_scope;
  return (
    <div className="space-y-3" data-testid="whatif-decomposition" data-method={d.method} data-reconciles={String(checks.selected && checks.total && checks.cross)} data-contract={d.contract_version} data-scope-equals-total={String(single)}>
      {single ? (
        <section className="space-y-2 rounded-lg border-2 border-accent bg-accent-muted p-3 text-xs" data-testid="whatif-scope-equivalence">
          <h4 className="text-sm font-semibold">Selected scope = Total book</h4>
          <p>
            The selected population is the entire active book ({d.scopes.selected.kpis.exposures.toLocaleString()} exposures), so there is no rest of book.
          </p>
          <ul className="list-disc pl-5 tabular">
            <li data-testid="whatif-equivalence-rest">
              Rest-of-book ECL delta = <b>{sarDelta(Number(cross.rest_of_book_delta))}</b> (zero by definition)
            </li>
            <li data-testid="whatif-equivalence-deltas">
              Selected-scope delta <b>{sarDelta(Number(cross.selected_delta))}</b> = total-book delta <b>{sarDelta(Number(cross.total_delta))}</b>
            </li>
            <li data-testid="whatif-equivalence-components" data-identical={eq.identical} data-components={eq.components}>
              {eq.identical} of {eq.components} components identical in both scopes; opening, closing and change identical
            </li>
          </ul>
          {scopeKpis(d.scopes.selected, "whatif-kpis-selected")}
        </section>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <h4 className="text-sm font-semibold">Selected scope — {d.scopes.selected.label}</h4>
            {scopeKpis(d.scopes.selected, "whatif-kpis-selected")}
          </div>
          <div className="space-y-2">
            <h4 className="text-sm font-semibold">Total active book</h4>
            {scopeKpis(d.scopes.total, "whatif-kpis-total")}
          </div>
        </div>
      )}
      <p className="rounded-lg border border-border bg-surface p-2 text-xs tabular" data-testid="whatif-cross-scope" data-reconciles={String(cross.reconciles)}>
        Selected Δ <b>{sarDelta(Number(cross.selected_delta))}</b> + rest-of-book Δ <b>{sarDelta(Number(cross.rest_of_book_delta))}</b> = total-book Δ{" "}
        <b>{sarDelta(Number(cross.total_delta))}</b> {cross.reconciles ? "✓ reconciles" : "✗ DOES NOT RECONCILE"}
        {cross.selected_share_of_total_change_pct && <> · selected share {cross.selected_share_of_total_change_pct}%</>}
        <span className="block text-text-muted">{cross.rest_of_book_reason}</span>
      </p>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={compact} onChange={(e) => setCompact(e.target.checked)} data-testid="whatif-decomp-compact" />
        Compact chart: hide the {hidden} N/A components (the table always lists all {table.length})
      </label>
      <div className={single ? "grid gap-4" : "grid gap-4 xl:grid-cols-2"}>
        {(single ? (["selected"] as const) : (["selected", "total"] as const)).map((name) => {
          const s = d.scopes[name];
          const fig = waterfall(s, { compact, highlight, scale });
          return (
            <ChartCard
              key={name}
              title={single ? "ECL bridge — Selected scope = Total book" : name === "selected" ? "ECL bridge — selected scope" : "ECL bridge — total active book"}
              subtitle={`${s.identity} · ${s.reconciles ? "reconciles" : "DOES NOT RECONCILE"} · residual ${s.residual}`}
              testId={`whatif-waterfall-${name}`}
              context={context}
              data={fig.data}
              layout={fig.layout}
              height={380}
              onPointClick={click}
              table={{
                columns: [
                  { key: "label", label: "Component" },
                  moneyCol("value", "Value", plotted(s, compact) as unknown as Record<string, unknown>[]),
                  { key: "status", label: "Status" },
                  { key: "reason", label: "Reason" },
                ],
                rows: plotted(s, compact).map((c) => ({ label: c.label, value: c.value ?? "", status: c.status, reason: c.reason })),
              }}
            />
          );
        })}
      </div>
      <div className="overflow-auto rounded-lg border border-border" data-testid="whatif-decomp-table">
        <table className="w-full text-xs">
          <thead className="bg-surface-sunken">
            <tr>
              {tableData.columns.map((c) => (
                <th key={c.key + c.label} className={`px-2 py-1 ${c.align === "right" ? "text-right" : "text-left"}`}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.map((r) => (
              <tr
                key={r.id}
                data-component={r.id}
                data-selected={r.selected}
                data-total={r.total}
                data-status={r.selected_status}
                className={`border-t border-border ${highlight === r.id ? "bg-accent/10 font-semibold" : ""}`}
                onClick={() => setHighlight(highlight === r.id ? "" : r.id)}
              >
                <td className="px-2 py-1">
                  <span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: r.colour }} aria-hidden />
                  {r.label}
                </td>
                <td className="px-2 py-1 text-right tabular" title={r.selected}>
                  {r.selected_status === "N/A" ? "N/A" : selCol.format(r.selected)}
                </td>
                <td className="px-2 py-1">{r.selected_status}</td>
                <td className="px-2 py-1 text-right tabular" title={r.total}>
                  {r.total_status === "N/A" ? "N/A" : totCol.format(r.total)}
                </td>
                <td className="px-2 py-1">{r.total_status}</td>
                {single && (
                  <td className="px-2 py-1" data-testid="whatif-decomp-identical">
                    {r.selected === r.total && r.selected_status === r.total_status ? "✓ same population" : "✗ differs"}
                  </td>
                )}
                <td className="px-2 py-1 text-text-muted">{r.reason || r.definition}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ResultLink({ resultId }: { resultId: string }) {
  return (
    <Link href={`/what-if/result/${resultId}`} className="text-accent underline" data-testid="whatif-result-link">
      Open result {resultId}
    </Link>
  );
}
