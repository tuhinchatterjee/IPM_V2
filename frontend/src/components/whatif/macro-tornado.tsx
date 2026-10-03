"use client";

/**
 * Macro sensitivity (MAC07): the governed MEV sensitivities of the population
 * the explorer is filtered to, ranked as a tornado. Each bar is the parameter
 * movement a symmetric standard shock implies through the published slope --
 * the Scenario Library's own translation, never a model's estimate. PD and
 * LGD are separate rows and colours; a counter-intuitive fitted sign is drawn
 * as fitted and marked for review. Diagnostic-only estimates are listed, not
 * drawn.
 */

import * as React from "react";
import { Loader2 } from "lucide-react";

import { ChartCard } from "@/components/viz/chart-card";
import { tornado, type TornadoRow } from "@/lib/viz/tornado";
import { wsSend } from "@/lib/workspace/client";
import type { DomainId, Filter } from "@/lib/workspace/objects";

interface TornadoResponse {
  release_id: string;
  fingerprint: string;
  period: string;
  population: { entities: number; mean_pd: number | null; mean_lgd_pct: number | null };
  rows: TornadoRow[];
  material_rows: number;
  excluded: { factor_id: string; factor_name: string; parameter_label: string; readiness: string; reason: string }[];
  evidence: string;
  /** Set when the filter matches nothing: an empty state, not an error. */
  empty: { error_code: string; message: string } | null;
}

export function MacroTornado({ domain, filters }: { domain: DomainId; filters: Filter[] }) {
  const [parameter, setParameter] = React.useState<"all" | "pd" | "lgd">("all");
  const [top, setTop] = React.useState(12);
  const [scale, setScale] = React.useState(1);
  const key = JSON.stringify({ domain, filters, parameter, top, scale });
  const [state, setState] = React.useState<{ key: string; data: TornadoResponse | null; error: string }>({ key: "", data: null, error: "" });

  React.useEffect(() => {
    let live = true;
    wsSend<TornadoResponse>("/whatif/sensitivity/tornado", { domain, filters, parameter, top, scale })
      .then((data) => live && setState({ key, data, error: "" }))
      .catch((e: unknown) => live && setState({ key, data: null, error: e instanceof Error ? e.message : String(e) }));
    return () => {
      live = false;
    };
  }, [domain, filters, parameter, top, scale, key]);

  const data = state.data;
  const fig = React.useMemo(() => tornado(data?.rows ?? []), [data]);
  const reviews = (data?.rows ?? []).filter((r) => r.sign_review);
  return (
    <section className="space-y-2" data-testid="whatif-macro-tornado" data-rows={data?.rows.length ?? 0}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <h2 className="font-semibold">Macro sensitivity</h2>
        <select value={parameter} onChange={(e) => setParameter(e.target.value as typeof parameter)} className="rounded border border-border bg-surface px-2 py-1 text-xs" aria-label="Risk parameter" data-testid="tornado-parameter">
          <option value="all">PD and LGD</option>
          <option value="pd">PD only</option>
          <option value="lgd">LGD only</option>
        </select>
        <select data-testid="tornado-top" value={top} onChange={(e) => setTop(Number(e.target.value))} className="rounded border border-border bg-surface px-2 py-1 text-xs" aria-label="How many">
          {[8, 12, 20, 40].map((n) => (
            <option key={n} value={n}>
              Top {n}
            </option>
          ))}
        </select>
        <select data-testid="tornado-scale" value={scale} onChange={(e) => setScale(Number(e.target.value))} className="rounded border border-border bg-surface px-2 py-1 text-xs" aria-label="Shock size">
          {[0.5, 1, 2].map((n) => (
            <option key={n} value={n}>
              {n}× standard shock
            </option>
          ))}
        </select>
        {state.key !== key && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
      </div>
      {state.error && <p className="text-xs text-negative">{state.error}</p>}
      {data?.empty && (
        <p className="text-xs text-text-muted" data-testid="tornado-empty" data-code={data.empty.error_code}>
          {data.empty.message} ({data.empty.error_code})
        </p>
      )}
      {data && !data.empty && (
        <ChartCard
          title="Governed MEV sensitivities of this population, ranked"
          subtitle={`${data.population.entities.toLocaleString()} exposures · ${data.period} · ${data.rows.length} of ${data.material_rows} supported (MEV, parameter) pairs · bars = parameter movement for a down / up standard shock`}
          data={fig.data}
          layout={fig.layout}
          height={Math.max(260, 28 * data.rows.length + 90)}
          testId="whatif-chart-tornado"
          context={{ releaseId: data.release_id, fingerprint: data.fingerprint, period: data.period, filters: { applied: filters }, source: "governed sensitivity library (no model call)" }}
          table={{
            columns: [
              { key: "factor_name", label: "MEV" },
              { key: "series_id", label: "Source series" },
              { key: "parameter_label", label: "Risk parameter" },
              { key: "shock_label", label: "Shock" },
              { key: "coefficient", label: "Coefficient", align: "right" },
              { key: "down_pp", label: "Down shock (pp)", align: "right" },
              { key: "up_pp", label: "Up shock (pp)", align: "right" },
              { key: "sign", label: "Sign (as fitted)" },
              { key: "readiness", label: "Status" },
              { key: "method", label: "Method" },
              { key: "lag", label: "Lag", align: "right" },
              { key: "train_start", label: "Window from" },
              { key: "train_end", label: "Window to" },
              { key: "sign_review", label: "Sign review" },
            ],
            rows: data.rows as unknown as Record<string, unknown>[],
          }}
          footer={
            <div className="mt-2 space-y-1 text-[11px] text-text-muted">
              {reviews.map((r) => (
                <p key={`${r.factor_id}-${r.parameter}`} className="text-warning" data-testid="tornado-sign-review">
                  {r.factor_name} → {r.parameter_label}: {r.sign_review}
                </p>
              ))}
              {data.excluded.length > 0 && (
                <p data-testid="tornado-excluded">
                  Not drawn (diagnostic only, never applied automatically):{" "}
                  {data.excluded.map((x) => `${x.factor_name} → ${x.parameter_label}`).join("; ")}.
                </p>
              )}
              <p>{data.evidence}</p>
            </div>
          }
        />
      )}
    </section>
  );
}
