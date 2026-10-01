"use client";

/**
 * Early Warning in the V4 runtime: the governed EWS rule set (gw-ews-1.0.0)
 * over the book the Cockpit is serving. Every card can freeze its EXACT
 * population as a governed cohort, export it, or open a Cockpit investigation
 * on it -- the same cohort id then travels to What-If and Lenses.
 *
 * A warning reason is a cross-filter (§27): clicking a rule in "Why
 * exposures are warned" -- or pressing Enter on its data row -- narrows the
 * bands, the segment cards, the underlying grid and every cohort /
 * investigation / What-If handoff to exposures tripping that rule. The server
 * applies it; the reasons chart itself stays whole so any rule can be chosen.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { Download, Loader2, Save, Search } from "lucide-react";

import { DomainSwitchPlain } from "@/components/guided/domain-toggle";
import { ChartCard } from "@/components/viz/chart-card";
import { DataGrid } from "@/components/workspace/data-grid";
import { trend } from "@/lib/viz/figures";
import { count, sar } from "@/lib/viz/format";
import { SEVERITY_COLORS, SEMANTIC } from "@/lib/viz/palette";
import { workspaceUrl, wsGet, wsSend } from "@/lib/workspace/client";
import type { DomainId, Filter } from "@/lib/workspace/objects";
import { moneyCol } from "@/lib/viz/format";

interface EwFeed {
  domain_id: DomainId;
  release_id: string;
  period: string;
  ruleset: string;
  rules: { id: string; label: string; weight: number; limitation?: string }[];
  segment_dimension: string;
  bands: { value: string; n: number; ead_sar_mn: number; ecl_sar_mn: number }[];
  by_segment: { segment: string; bands: { value: string; n: number; ead_sar_mn: number; ecl_sar_mn: number }[] }[];
  reasons: { reason: string; n: number; ead: number }[];
  top: Record<string, string | number | null>[];
  severe_total: number;
  severe_ead_trend: { period: string; value: number | null }[];
  reason: string;
  filters: Filter[];
}

const BANDS = ["critical", "high", "moderate", "low"] as const;

export function EarlyWarningV4() {
  const router = useRouter();
  const [domain, setDomain] = React.useState<DomainId>("retail");
  const [reason, setReason] = React.useState("");
  const [loaded, setLoaded] = React.useState<{ key: string; feed: EwFeed | null }>({ key: "", feed: null });
  const key = `${domain}|${reason}`;
  const feed = loaded.key === key ? loaded.feed : null;
  const gridLocked = React.useMemo<Filter[]>(
    () => [{ column: "ews_band", op: "in", values: ["critical", "high"] }, ...(feed?.filters ?? [])],
    [feed],
  );
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    wsGet<EwFeed>(`/early-warning?domain=${domain}${reason ? `&reason=${encodeURIComponent(reason)}` : ""}`)
      .then((f) => live && setLoaded({ key, feed: f }))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [domain, reason, key]);

  function changeDomain(next: DomainId) {
    setReason("");
    setDomain(next);
  }

  const toggleReason = (r: string) => setReason((current) => (current === r ? "" : r));

  async function saveCohort(segment = "", bands: string[] = ["critical", "high"]) {
    const c = await wsSend<{ object_id: string; body: { counts: { entities: number } } }>("/early-warning/cohort", { domain, segment, bands, reason });
    setNote(`Saved ${count(c.body.counts.entities)} exposures as cohort ${c.object_id}.`);
    return c;
  }

  async function exportCohort(segment = "") {
    const c = await saveCohort(segment);
    const response = await fetch(workspaceUrl(`/cohorts/${c.object_id}/export`), { credentials: "include" });
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${c.object_id}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function investigate(segment = "") {
    setBusy(true);
    try {
      const out = await wsSend<{ thread_id: string }>("/early-warning/investigate", { domain, segment, bands: ["critical", "high"], reason });
      router.push(`/cockpit/thread/${out.thread_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  async function whatIf(segment = "") {
    const c = await saveCohort(segment);
    router.push(`/what-if?cohort=${encodeURIComponent(c.object_id)}`);
  }

  if (error) return <p role="alert" className="text-sm text-negative">{error}</p>;
  const severeTrend = feed ? trend([{ name: "High/critical EWS EAD", points: feed.severe_ead_trend, unit: "SAR_mn", color: SEMANTIC.increase }]) : null;
  return (
    <div className="space-y-5" data-testid="early-warning-v4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text-primary">Early Warning</h1>
        <DomainSwitchPlain value={domain} onChange={changeDomain} />
        {feed && (
          <span className="text-xs text-text-muted">
            {feed.release_id} · {feed.period} · rule set {feed.ruleset} · no model call
          </span>
        )}
      </header>
      {!feed ? (
        <p className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Applying the early-warning rules…
        </p>
      ) : (
        <>
          {reason && (
            <p className="flex flex-wrap items-center gap-2 rounded-md border border-accent bg-accent-muted px-3 py-2 text-xs" data-testid="ew-reason-filter" data-reason={reason}>
              Showing exposures that trip <span className="font-semibold">{reason}</span> — bands, segments, the grid and every
              Save / Investigate / What-If below use this filter.
              <button type="button" onClick={() => setReason("")} className="text-accent underline" data-testid="ew-reason-clear">
                Clear
              </button>
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {BANDS.map((band) => {
              const row = feed.bands.find((b) => b.value === band);
              return (
                <div key={band} className="rounded-xl border border-border bg-surface p-3" data-testid={`ew-band-${band}`}>
                  <div className="text-xs font-semibold uppercase" style={{ color: SEVERITY_COLORS[band] }}>
                    {band}
                  </div>
                  <div className="mt-1 text-lg font-semibold tabular">{count(row?.n ?? 0)}</div>
                  <div className="text-xs text-text-muted">
                    EAD {sar(row?.ead_sar_mn ?? 0)} · ECL {sar(row?.ecl_sar_mn ?? 0)}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => void investigate()} className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast" data-testid="ew-investigate">
              <Search className="h-4 w-4" /> Investigate high/critical{reason ? " (this rule)" : ""} in Cockpit
            </button>
            <button type="button" onClick={() => void saveCohort()} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="ew-save-cohort">
              <Save className="h-4 w-4" /> Save high/critical cohort
            </button>
            <button type="button" onClick={() => void exportCohort()} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="ew-export">
              <Download className="h-4 w-4" /> Export cohort
            </button>
            <button type="button" onClick={() => void whatIf()} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="ew-whatif">
              Run What-If on this cohort
            </button>
            {note && <span className="self-center text-xs text-positive" data-testid="ew-note">{note}</span>}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {severeTrend && (
              <ChartCard
                title="High/critical EWS EAD over time"
                subtitle="Metric M063 · governed rule set"
                data={severeTrend.data}
                layout={severeTrend.layout}
                testId="ew-trend"
                table={{ columns: [{ key: "period", label: "Period" }, moneyCol("value", "EAD", feed.severe_ead_trend as unknown as Record<string, unknown>[])], rows: feed.severe_ead_trend as unknown as Record<string, unknown>[] }}
              />
            )}
            <ChartCard
              title="Why exposures are warned"
              subtitle="Rules tripped (an exposure can trip several). Click a rule to filter the page to it; again to clear."
              data={[
                {
                  type: "bar",
                  orientation: "h",
                  y: feed.reasons.map((r) => r.reason).reverse(),
                  x: feed.reasons.map((r) => r.n).reverse(),
                  customdata: feed.reasons.map((r) => [r.reason, sar(r.ead)]).reverse(),
                  marker: {
                    color: feed.reasons.map((r) => (reason && r.reason !== reason ? `${SEMANTIC.stage}55` : SEMANTIC.stage)).reverse(),
                    line: { color: feed.reasons.map((r) => (r.reason === reason ? SEMANTIC.increase : "rgba(0,0,0,0)")).reverse(), width: 2 },
                  },
                  hovertemplate: "%{y}: %{x:,} exposures · EAD %{customdata[1]}<extra></extra>",
                },
              ]}
              layout={{ margin: { l: 280, r: 20, t: 10, b: 40 }, xaxis: { title: { text: "Exposures" } } }}
              testId="ew-reasons"
              context={{ releaseId: feed.release_id, period: feed.period, source: `EWS rule set ${feed.ruleset}` }}
              onPointClick={(p) => {
                const r = Array.isArray(p.customdata) ? String(p.customdata[0]) : String(p.y ?? "");
                if (r) toggleReason(r);
              }}
              table={{
                columns: [{ key: "reason", label: "Rule" }, { key: "n", label: "Exposures", align: "right" }, moneyCol("ead", "EAD", feed.reasons as unknown as Record<string, unknown>[])],
                rows: feed.reasons as unknown as Record<string, unknown>[],
                onRowActivate: (row) => toggleReason(String(row.reason)),
                activateLabel: "Filter the page to the rule",
              }}
            />
          </div>
          <section>
            <h2 className="mb-2 text-sm font-semibold">By {feed.segment_dimension}</h2>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {feed.by_segment.map((s) => {
                const severe = s.bands.filter((b) => b.value === "critical" || b.value === "high");
                const n = severe.reduce((a, b) => a + b.n, 0);
                const ead = severe.reduce((a, b) => a + (b.ead_sar_mn ?? 0), 0);
                return (
                  <div key={s.segment} className="rounded-xl border border-border bg-surface p-3" data-testid="ew-segment-card">
                    <div className="flex items-baseline justify-between">
                      <span className="font-medium">{s.segment}</span>
                      <span className="text-xs text-text-muted">
                        {count(n)} high/critical · {sar(ead)}
                      </span>
                    </div>
                    <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-surface-sunken">
                      {BANDS.map((band) => {
                        const row = s.bands.find((b) => b.value === band);
                        const total = s.bands.reduce((a, b) => a + b.n, 0) || 1;
                        return <div key={band} style={{ width: `${((row?.n ?? 0) / total) * 100}%`, background: SEVERITY_COLORS[band] }} title={`${band}: ${row?.n ?? 0}`} />;
                      })}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                      <button type="button" disabled={!n || busy} onClick={() => void investigate(s.segment)} className="rounded border border-border px-2 py-0.5 disabled:opacity-40">
                        Investigate
                      </button>
                      <button type="button" disabled={!n} onClick={() => void saveCohort(s.segment)} className="rounded border border-border px-2 py-0.5 disabled:opacity-40">
                        Save cohort
                      </button>
                      <button type="button" disabled={!n} onClick={() => void exportCohort(s.segment)} className="rounded border border-border px-2 py-0.5 disabled:opacity-40">
                        Export
                      </button>
                      <button type="button" disabled={!n} onClick={() => void whatIf(s.segment)} className="rounded border border-border px-2 py-0.5 disabled:opacity-40">
                        What-If
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">
              High/critical exposures{reason ? <span className="font-normal text-text-muted"> tripping {reason}</span> : null}
            </h2>
            <DataGrid
              key={key}
              domain={domain}
              lockedFilters={gridLocked}
              testId="ew-grid"
              compact
            />
          </section>
          <section className="rounded-lg border border-border bg-surface p-3 text-xs">
            <h2 className="mb-1 text-sm font-semibold">Rule set {feed.ruleset}</h2>
            <ul className="list-disc pl-5">
              {feed.rules.map((r) => (
                <li key={r.id}>
                  <span className="font-medium">{r.id}</span> {r.label} (weight {r.weight})
                  {r.limitation ? <span className="text-warning"> — {r.limitation}</span> : null}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
