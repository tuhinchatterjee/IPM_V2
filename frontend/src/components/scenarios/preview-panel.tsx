"use client";

/**
 * A Scenario Definition resolved against the book -- and NOT calculated.
 *
 * Shows the population, each component's governed translation, the overlap
 * matrix (with policy choices where the viewer may record them), which
 * methods could run and why not, the blocking items, and the readable
 * equation beside the machine-readable contract (§30.3).
 */

import * as React from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { ChartCard } from "@/components/viz/chart-card";
import { count, pct, sar } from "@/lib/viz/format";
import {
  componentMatrix,
  derivedRows,
  methodTone,
  pendingOverlaps,
  readinessText,
  readinessTone,
  resolutionsFrom,
  scopeBandFigure,
  scopeStageFigure,
  statusTone,
} from "@/lib/workspace/scenario-figures";
import type { Definition, Preview, Resolution } from "@/lib/workspace/scenarios";
import { methodLabel } from "@/lib/workspace/method-labels";
import { moneyCol } from "@/lib/viz/format";

export function PreviewPanel({
  preview,
  definition,
  onResolve,
  resolveLabel = "Record composition policy",
  testId = "scenario-preview",
}: {
  preview: Preview;
  definition?: Pick<Definition, "components">;
  onResolve?: (resolutions: Record<string, Resolution>) => Promise<void> | void;
  resolveLabel?: string;
  testId?: string;
}) {
  const s = preview.scope.summary;
  const rows = componentMatrix(preview, definition);
  const pending = pendingOverlaps(preview);
  const [choices, setChoices] = React.useState<Record<string, string>>({});
  const [open, setOpen] = React.useState<string>("");
  const [busy, setBusy] = React.useState(false);
  const inFlight = React.useRef(false);
  const stageFig = scopeStageFigure(preview);
  const bandFig = scopeBandFigure(preview);
  const methods = (["delta", "ml", "user_defined"] as const).map((m) => [m, preview.methods[m]] as const);

  return (
    <section className="space-y-4" data-testid={testId} data-readiness={preview.readiness}>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-sunken p-3 text-sm">
        <Badge variant={readinessTone(preview.readiness)} data-testid="scenario-readiness">
          {readinessText(preview.readiness)}
        </Badge>
        <span className="text-text-secondary" data-testid="scenario-not-calculated">
          {preview.statement}
        </span>
        <span className="ml-auto text-xs text-text-muted">
          {preview.release_id} · {preview.period} · contract {preview.contract_hash.slice(0, 12)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-surface p-3 text-sm sm:grid-cols-3 lg:grid-cols-6" data-testid="scenario-scope-kpis">
        <Kpi label="Scope" value={preview.scope.label ?? preview.scope.type} />
        <Kpi label="Exposures" value={count(s.entities)} sub={`of ${count(preview.scope.book.entities)}`} />
        <Kpi label="Owners" value={count(s.owners)} />
        <Kpi label="EAD" value={sar(s.ead)} sub={preview.scope.share_of_book_ead == null ? "" : `${pct(preview.scope.share_of_book_ead)} of book`} />
        <Kpi label="Booked ECL" value={sar(s.ecl)} sub={preview.scope.share_of_book_ecl == null ? "" : `${pct(preview.scope.share_of_book_ecl)} of book`} />
        <Kpi label="Stage policy" value={preview.stage_policy.policy} sub={preview.stage_policy.text} />
      </div>

      {preview.blocking.length > 0 && (
        <ul className="space-y-1 rounded-lg border border-negative bg-negative-muted p-3 text-sm text-negative" data-testid="scenario-blocking">
          {preview.blocking.map((b, i) => (
            <li key={i} className="flex gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                <span className="font-semibold">{b.code}</span> — {b.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Scope by IFRS 9 stage"
          subtitle="EAD of the exposures the definition selects"
          data={stageFig.data}
          layout={stageFig.layout}
          height={140}
          testId="scenario-stage-mix"
          context={{ releaseId: preview.release_id, fingerprint: preview.fingerprint, period: preview.period }}
          table={{
            columns: [
              { key: "stage", label: "Stage" },
              { key: "n", label: "Exposures", align: "right" },
              moneyCol("ead", "EAD", s.stage_mix as unknown as Record<string, unknown>[]),
              moneyCol("ecl", "ECL", s.stage_mix as unknown as Record<string, unknown>[]),
            ],
            rows: s.stage_mix as unknown as Record<string, unknown>[],
          }}
        />
        <ChartCard
          title={`Scope by ${s.band_dimension.replace(/_/g, " ")}`}
          subtitle="EAD per band"
          data={bandFig.data}
          layout={bandFig.layout}
          height={220}
          testId="scenario-band-mix"
          context={{ releaseId: preview.release_id, fingerprint: preview.fingerprint, period: preview.period }}
          table={{
            columns: [
              { key: "band", label: "Band" },
              { key: "n", label: "Exposures", align: "right" },
              moneyCol("ead", "EAD", s.band_mix as unknown as Record<string, unknown>[]),
            ],
            rows: s.band_mix as unknown as Record<string, unknown>[],
          }}
        />
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold">Component matrix</h3>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs" data-testid="scenario-component-matrix">
            <thead className="bg-surface-sunken text-left text-text-muted">
              <tr>
                <th className="p-2" />
                <th className="p-2">Component</th>
                <th className="p-2">Status</th>
                <th className="p-2">Variables</th>
                <th className="p-2 text-right">Exposures</th>
                <th className="p-2">Delta</th>
                <th className="p-2">ML</th>
                <th className="p-2">User-defined</th>
                <th className="p-2">Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const full = preview.components.find((c) => c.component_id === r.component_id);
                const expanded = open === r.component_id;
                return (
                  <React.Fragment key={r.component_id}>
                    <tr className="border-t border-border" data-testid="scenario-component-row" data-status={r.status}>
                      <td className="p-2">
                        <button data-testid="preview-show-translation" type="button" aria-label="Show translation" onClick={() => setOpen(expanded ? "" : r.component_id)}>
                          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                        </button>
                      </td>
                      <td className="p-2">
                        <span className="font-mono text-text-muted">{r.component_id}</span> {r.label}
                      </td>
                      <td className="p-2">
                        <Badge variant={statusTone(r.status)}>{r.status}</Badge>
                        {full?.sign_review && (
                          <Badge variant="warning" className="ml-1" data-testid="scenario-sign-review">
                            sign review
                          </Badge>
                        )}
                      </td>
                      <td className="p-2">{r.variables}</td>
                      <td className="p-2 text-right tabular">{count(r.entities)}</td>
                      <td className="p-2">{r.delta === "COMPATIBLE" ? "✓" : "—"}</td>
                      <td className="p-2">{r.ml === "COMPATIBLE" ? "✓" : "—"}</td>
                      <td className="p-2">{r.user_defined === "COMPATIBLE" ? "✓" : "—"}</td>
                      <td className="p-2 text-text-muted">{r.source}</td>
                    </tr>
                    {expanded && full && (
                      <tr className="bg-surface-sunken">
                        <td />
                        <td colSpan={8} className="p-2">
                          <Translation reason={r.reason} translation={full.translation} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold">Overlap and conflict matrix</h3>
        {preview.overlaps.length === 0 ? (
          <p className="text-xs text-text-muted" data-testid="scenario-overlap-none">
            One component: nothing can overlap.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-xs" data-testid="scenario-overlap-matrix">
              <thead className="bg-surface-sunken text-left text-text-muted">
                <tr>
                  <th className="p-2">Pair</th>
                  <th className="p-2">Variable</th>
                  <th className="p-2 text-right">Shared exposures</th>
                  <th className="p-2">Status</th>
                  <th className="p-2">Policy</th>
                </tr>
              </thead>
              <tbody>
                {preview.overlaps.map((o, i) => (
                  <tr key={`${o.overlap_id ?? o.a + o.b}-${i}`} className="border-t border-border" data-testid="scenario-overlap-row" data-status={o.status}>
                    <td className="p-2">
                      {o.a_label} <span className="text-text-muted">×</span> {o.b_label}
                    </td>
                    <td className="p-2">{o.variable ?? (o.variables.join(", ") || "—")}</td>
                    <td className="p-2 text-right tabular">{count(o.shared_entities)}</td>
                    <td className="p-2">
                      <Badge variant={statusTone(o.status)}>{o.status}</Badge>
                      {o.reason && <div className="mt-0.5 text-text-muted">{o.reason}</div>}
                    </td>
                    <td className="p-2">
                      {(o.status === "NEEDS_POLICY" || o.status === "INVALID_POLICY") && onResolve && o.overlap_id ? (
                        <select
                          className="rounded border border-border bg-surface px-1 py-0.5"
                          value={choices[o.overlap_id] ?? ""}
                          onChange={(e) => setChoices({ ...choices, [o.overlap_id as string]: e.target.value })}
                          data-testid="overlap-policy-select"
                          aria-label={`Composition policy for ${o.a_label} and ${o.b_label}`}
                        >
                          <option value="">Choose…</option>
                          {(o.allowed ?? []).map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span title={o.policy_text}>{o.policy ?? (o.status === "NO_CONFLICT" ? "—" : "not chosen")}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {onResolve && pending.length > 0 && (
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              disabled={busy || !pending.every((o) => o.overlap_id && choices[o.overlap_id])}
              onClick={async () => {
                // A double-click fires twice before `busy` disables this.
                if (inFlight.current) return;
                inFlight.current = true;
                setBusy(true);
                try {
                  await onResolve(resolutionsFrom(pending, choices));
                } finally {
                  inFlight.current = false;
                  setBusy(false);
                }
              }}
              className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-contrast disabled:opacity-40"
              data-testid="overlap-resolve"
            >
              {resolveLabel}
            </button>
            <span className="text-xs text-text-muted">Every overlap needs its own explicit choice; none is assumed.</span>
          </div>
        )}
      </div>

      <div data-testid="scenario-methods">
        <h3 className="mb-1 text-sm font-semibold">Methods</h3>
        <div className="grid gap-2 md:grid-cols-3">
          {methods.map(([m, st]) => (
            <div key={m} className="rounded-lg border border-border bg-surface p-2 text-xs" data-testid={`scenario-method-${m}`} data-status={st.status}>
              <div className="flex items-center justify-between">
                <span className="font-semibold">{methodLabel(m)}</span>
                <Badge variant={methodTone(st.status)}>{st.status}</Badge>
              </div>
              {st.reason && <p className="mt-1 text-text-secondary">{st.reason}</p>}
              {st.does_not_cover && st.does_not_cover.length > 0 && (
                <p className="mt-1 text-text-muted">Not covered: {st.does_not_cover.join(", ")}</p>
              )}
            </div>
          ))}
        </div>
        <p className="mt-1 flex items-center gap-1 text-xs text-text-muted">
          <Info className="h-3 w-3" /> {preview.methods.note}
        </p>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-sm font-semibold">Scenario equation</h3>
          <p className="rounded-lg border border-border bg-surface p-3 font-mono text-xs" data-testid="scenario-equation">
            {preview.equation}
          </p>
        </div>
        <div>
          <h3 className="mb-1 text-sm font-semibold">Normalized contract</h3>
          <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-surface-sunken p-3 text-[11px]" data-testid="scenario-contract">
            {JSON.stringify(preview.contract, null, 2)}
          </pre>
        </div>
      </div>
    </section>
  );
}

function Translation({ reason, translation }: { reason: string; translation: Record<string, unknown> | null }) {
  if (!translation) return <p className="text-xs text-text-muted">{reason || "No translation needed."}</p>;
  const derived = derivedRows(translation);
  const moves = (translation.moves as Record<string, unknown>[] | undefined) ?? [];
  const bands = (translation.band_moves as Record<string, unknown>[] | undefined) ?? [];
  const warnings = (translation.warnings as string[] | undefined) ?? [];
  const excluded = (translation.excluded as Record<string, unknown>[] | undefined) ?? [];
  return (
    <div className="space-y-2 text-xs" data-testid="scenario-translation">
      {reason && <p className="text-warning">{reason}</p>}
      {typeof translation.rule === "string" && <p className="text-text-secondary">{translation.rule}</p>}
      {typeof translation.conversion === "string" && (
        <p>
          <span className="font-semibold">{String(translation.factor_name ?? translation.factor_id)}</span>: {translation.conversion}
          {translation.level != null && ` (level ${String(translation.level)} at ${String(translation.level_period)})`}
        </p>
      )}
      {derived.length > 0 && (
        <table className="w-full">
          <thead className="text-left text-text-muted">
            <tr>
              <th>Parameter</th>
              <th>Change</th>
              <th className="text-right">Scope mean before</th>
              <th className="text-right">After</th>
              <th>Governed slope</th>
            </tr>
          </thead>
          <tbody>
            {derived.map((d) => (
              <tr key={d.field}>
                <td>{d.field}</td>
                <td className="tabular">{d.change}</td>
                <td className="text-right tabular">{d.from == null ? "—" : pct(d.from)}</td>
                <td className="text-right tabular">{d.to == null ? "—" : pct(d.to)}</td>
                <td className="text-text-muted">
                  {d.slope} ({d.slope_unit}), lag {d.lag}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {excluded.length > 0 && (
        <p className="text-text-muted">
          Not applied: {excluded.map((e) => `${String(e.parameter)} (${String(e.readiness)})`).join(", ")}
        </p>
      )}
      {moves.length > 0 && (
        <p>
          {moves
            .map((m) => `${String(m.from)} → ${String(m.to ?? "unmapped")} (${count(Number(m.n))}${m.pd_relative_factor ? `, PD ×${Number(m.pd_relative_factor).toFixed(2)}` : ""})`)
            .join(" · ")}
        </p>
      )}
      {bands.length > 0 && (
        <p>
          {bands
            .filter((b) => b.from !== b.to)
            .map((b) => `${String(b.from ?? "unmapped")} → ${String(b.to ?? "off-scale")} (${count(Number(b.n))})`)
            .join(" · ") || "No account changes scorecard band label."}
        </p>
      )}
      {warnings.map((w, i) => (
        <p key={i} className="text-warning">
          {w}
        </p>
      ))}
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-text-muted">{label}</div>
      <div className="font-semibold tabular text-text-primary">{value}</div>
      {sub && <div className="line-clamp-2 text-[11px] text-text-muted">{sub}</div>}
    </div>
  );
}
