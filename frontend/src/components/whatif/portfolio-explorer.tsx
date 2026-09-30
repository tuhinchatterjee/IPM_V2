"use client";

/**
 * The portfolio explorer: Plotly views of the latest-period book that share
 * ONE filter state with the grid beneath them. Click a bar to filter (click
 * again to clear); box/lasso-select several bars to filter to them; the grid,
 * the selection and every other chart follow. Aggregates come from the server
 * (`/grid/group`) -- the portfolio is never shipped to the browser.
 */

import * as React from "react";
import { Loader2 } from "lucide-react";

import { ChartCard } from "@/components/viz/chart-card";
import { categoryBars, stageMix } from "@/lib/viz/figures";
import { gridGroup } from "@/lib/workspace/guided";
import type { DomainId, Filter } from "@/lib/workspace/objects";
import { EXPLORER_DIMENSIONS, selectedValues, setFilterValues, toggleFilterValue } from "@/lib/workspace/whatif";

type Group = { value: string | number | null; n: number; ead_sar_mn: number; ecl_sar_mn: number };

export function PortfolioExplorer({
  domain,
  filters,
  onFilters,
  context,
}: {
  domain: DomainId;
  filters: Filter[];
  onFilters: (next: Filter[]) => void;
  context: { releaseId: string; fingerprint: string; period: string };
}) {
  const dims = EXPLORER_DIMENSIONS[domain];
  const [dimension, setDimension] = React.useState(dims[0].key);
  const [measure, setMeasure] = React.useState<"ead_sar_mn" | "ecl_sar_mn">("ecl_sar_mn");
  const dim = dims.some((d) => d.key === dimension) ? dimension : dims[0].key;
  // The dimension chart ignores its OWN filter so every category stays
  // visible and toggleable; the selected ones are highlighted instead.
  const others = React.useMemo(() => filters.filter((f) => f.column !== dim), [filters, dim]);
  const key = JSON.stringify({ domain, dim, others, filters });
  const [loaded, setLoaded] = React.useState<{ key: string; groups: Group[]; stages: Group[]; error: string }>({
    key: "",
    groups: [],
    stages: [],
    error: "",
  });

  React.useEffect(() => {
    let live = true;
    Promise.all([gridGroup(domain, dim, others), gridGroup(domain, "stage", filters)])
      .then(([g, s]) => live && setLoaded({ key, groups: g.groups, stages: s.groups, error: "" }))
      .catch((e: unknown) => live && setLoaded({ key, groups: [], stages: [], error: e instanceof Error ? e.message : String(e) }));
    return () => {
      live = false;
    };
  }, [domain, dim, others, filters, key]);

  const ready = loaded.key === key;
  const selected = selectedValues(filters, dim);
  const groups = [...loaded.groups].sort((a, b) => (b[measure] ?? 0) - (a[measure] ?? 0));
  const bars = categoryBars(groups, measure, { dimension: dims.find((d) => d.key === dim)?.label ?? dim, selected });
  const stageFig = stageMix(loaded.stages.map((s) => ({ stage: Number(s.value), n: s.n, ead: s.ead_sar_mn ?? 0, ecl: s.ecl_sar_mn ?? 0 })));
  const label = dims.find((d) => d.key === dim)?.label ?? dim;

  return (
    <section className="space-y-2" data-testid="whatif-explorer" data-dimension={dim}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <h2 className="font-semibold">Portfolio explorer</h2>
        <select value={dim} onChange={(e) => setDimension(e.target.value)} className="rounded border border-border bg-surface px-2 py-1 text-xs" data-testid="whatif-explorer-dimension" aria-label="Break down by">
          {dims.map((d) => (
            <option key={d.key} value={d.key}>
              By {d.label.toLowerCase()}
            </option>
          ))}
        </select>
        <select value={measure} onChange={(e) => setMeasure(e.target.value as typeof measure)} className="rounded border border-border bg-surface px-2 py-1 text-xs" aria-label="Measure">
          <option value="ecl_sar_mn">Booked ECL</option>
          <option value="ead_sar_mn">EAD</option>
        </select>
        <span className="text-xs text-text-muted">Click a bar to filter; drag a box or lasso to select several. The grid follows.</span>
        {!ready && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
      </div>
      {loaded.error && loaded.key === key && <p className="text-xs text-negative">{loaded.error}</p>}
      <div className="grid gap-3 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartCard
            title={`${measure === "ecl_sar_mn" ? "Booked ECL" : "EAD"} by ${label.toLowerCase()}`}
            subtitle={`${context.period} · ${selected.length ? `${selected.length} selected` : "all categories"}`}
            data={bars.data}
            layout={{ ...bars.layout, dragmode: "select", clickmode: "event+select", margin: { l: 60, r: 10, t: 10, b: 90 } }}
            height={300}
            selectable
            testId="whatif-chart-dimension"
            context={{ releaseId: context.releaseId, fingerprint: context.fingerprint, period: context.period, filters: { applied: others } }}
            onPointClick={(p) => {
              const value = Array.isArray(p.customdata) ? String(p.customdata[0]) : String(p.x ?? "");
              onFilters(toggleFilterValue(filters, dim, dim === "stage" ? Number(value) : value));
            }}
            onSelected={(points) => {
              const values = points.map((p) => (Array.isArray(p.customdata) ? String(p.customdata[0]) : String(p.x ?? "")));
              onFilters(setFilterValues(filters, dim, Array.from(new Set(values))));
            }}
            table={{
              columns: [
                { key: "value", label: label },
                { key: "n", label: "Exposures", align: "right" },
                { key: "ead_sar_mn", label: "EAD (SAR m, raw)", align: "right" },
                { key: "ecl_sar_mn", label: "Booked ECL (SAR m, raw)", align: "right" },
              ],
              rows: groups as unknown as Record<string, unknown>[],
            }}
          />
        </div>
        <ChartCard
          title="Filtered population by stage"
          subtitle="EAD; click a stage to filter"
          data={stageFig.data}
          layout={{ ...stageFig.layout, height: 210, margin: { l: 40, r: 10, t: 6, b: 90 }, legend: { orientation: "h", y: -0.7 } }}
          height={210}
          testId="whatif-chart-stage"
          context={{ releaseId: context.releaseId, fingerprint: context.fingerprint, period: context.period, filters: { applied: filters } }}
          onPointClick={(p) => {
            const name = String(p.data?.name ?? "");
            const stage = Number(name.replace(/\D/g, ""));
            if (stage) onFilters(toggleFilterValue(filters, "stage", stage));
          }}
          table={{
            columns: [
              { key: "value", label: "Stage" },
              { key: "n", label: "Exposures", align: "right" },
              { key: "ead_sar_mn", label: "EAD (SAR m, raw)", align: "right" },
              { key: "ecl_sar_mn", label: "Booked ECL (SAR m, raw)", align: "right" },
            ],
            rows: loaded.stages as unknown as Record<string, unknown>[],
          }}
        />
      </div>
    </section>
  );
}
