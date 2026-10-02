"use client";

/**
 * Monitoring Centre (§33): breaches and change events from saved Lenses and
 * their governed rules. New today / Active / Worsening / Acknowledged /
 * Resolved / Material changes / Historical replay, filtered by severity,
 * Lens, book and assignee. Opening an alert shows the exact rule, Lens and
 * metric versions, observed vs threshold, release and population, and its
 * full status history; from there: open the Lens at the triggering period
 * and filter, Investigate in Cockpit, What-If, or acknowledge / resolve /
 * assign / comment (auditable; source data never changes).
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, RefreshCw } from "lucide-react";

import { ChartCard } from "@/components/viz/chart-card";
import { ExportPackage } from "@/components/workspace/export-package";
import { SEMANTIC, SEVERITY_COLORS, categorical } from "@/lib/viz/palette";
import { formatValue } from "@/lib/workspace/metric-figures";
import { urlWith, withBack } from "@/lib/workspace/nav";
import { actOnAlert, alertCohort, investigateAlert, readAlert, readMonitoring, runDueRefreshes, type AlertDetail, type AlertSummary, type MonitoringView } from "@/lib/workspace/monitoring";

const VIEWS: { id: string; label: string; count?: keyof MonitoringView["counts"] }[] = [
  { id: "new_today", label: "New today", count: "new" },
  { id: "active", label: "Active", count: "active" },
  { id: "worsening", label: "Worsening", count: "worsening" },
  { id: "acknowledged", label: "Acknowledged", count: "acknowledged" },
  { id: "resolved", label: "Resolved", count: "resolved" },
  { id: "changes", label: "Material changes", count: "changes" },
  { id: "mine", label: "Assigned to me" },
  { id: "history", label: "Historical replay (demo)", count: "history" },
  { id: "all", label: "All" },
];

const STATE_TONE: Record<string, string> = {
  NEW: "bg-negative/15 text-negative",
  ACTIVE: "bg-warning/15 text-warning",
  WORSENING: "bg-negative text-white",
  ACKNOWLEDGED: "bg-accent/15 text-accent",
  RESOLVED: "bg-positive/15 text-positive",
  SUPPRESSED: "bg-surface-sunken text-text-muted",
};

function when(ts: number | null | undefined) {
  return ts ? new Date(ts * 1000).toLocaleString() : "—";
}

/** Observed vs threshold in the rule's own terms: a movement rule compares
 * the MOVE, not the level. */
export function describeBreach(a: { comparison: string; observed: number | null; prior: number | null; threshold: number | null; unit?: string }): string {
  const { comparison: c, observed: o, prior: p, threshold: t } = a;
  const u = a.unit ?? "";
  if (c === "move_pct_gt" && o != null && p != null && p !== 0)
    return `moved ${(((o - p) / Math.abs(p)) * 100).toFixed(1)}% (${formatValue(p, u)} → ${formatValue(o, u)}) vs > ${((t ?? 0) * 100).toFixed(1)}%`;
  if (c === "move_abs_gt" && o != null && p != null) return `moved ${formatValue(o - p, u)} (${formatValue(p, u)} → ${formatValue(o, u)}) vs > ${formatValue(t, u)}`;
  const sym: Record<string, string> = { gt: ">", lt: "<", abs_gt: "|x| >" };
  return `${formatValue(o, u)} vs ${sym[c] ?? c} ${formatValue(t, u)}`;
}

function fmt(v: number | null | undefined, unit = "") {
  return formatValue(v, unit);
}

const VIEW_IDS = ["new_today", "active", "worsening", "acknowledged", "resolved", "all", "changes", "history", "mine"];
const SEVERITIES = ["critical", "high", "moderate", "medium", "low", "info"];

function oneOf(raw: string | null, allowed: string[], fallback: string): string {
  return raw && allowed.includes(raw) ? raw : fallback;
}

export function MonitoringCentre() {
  const params = useSearchParams();
  const router = useRouter();
  // The view and every filter live in the URL, so Back from a Lens, the
  // Cockpit or What-If returns to the same list; an unknown value is ignored.
  const [view, setView] = React.useState(() => oneOf(params.get("view"), VIEW_IDS, "active"));
  const [severity, setSeverity] = React.useState(() => oneOf(params.get("severity"), SEVERITIES, ""));
  const [lens, setLens] = React.useState(params.get("lens") ?? "");
  const [domain, setDomain] = React.useState(() => oneOf(params.get("domain"), ["corporate", "retail"], ""));
  const [data, setData] = React.useState<MonitoringView | null>(null);
  const [error, setError] = React.useState("");
  const [reload, setReload] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [note, setNote] = React.useState("");
  const selected = params.get("alert") ?? "";

  React.useEffect(() => {
    let live = true;
    readMonitoring({ view, severity, lens, domain })
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [view, severity, lens, domain, reload]);

  React.useEffect(() => {
    const next = urlWith({ view, severity, lens, domain });
    if (next && next !== `${window.location.pathname}${window.location.search}`) router.replace(next, { scroll: false });
  }, [view, severity, lens, domain, router]);

  function open(id: string) {
    // Pushed: browser Back closes the alert and keeps the list as it was.
    router.push(urlWith({ alert: id }), { scroll: false });
  }

  const alerts = data?.alerts ?? [];
  const bySeverity = ["critical", "high", "moderate", "low", "info"].map((s) => ({ s, n: alerts.filter((a) => a.severity === s).length })).filter((x) => x.n);
  const byLens = Object.entries(alerts.reduce<Record<string, { n: number; id: string }>>((acc, a) => {
    acc[a.lens_name] = { n: (acc[a.lens_name]?.n ?? 0) + 1, id: a.lens_id };
    return acc;
  }, {})).sort((a, b) => b[1].n - a[1].n);

  return (
    <div className="space-y-4" data-testid="monitoring-centre" data-total={data?.total ?? 0}>
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-lg font-semibold">Monitoring Centre</h1>
          <p className="text-xs text-text-muted">Breaches and material changes from saved Lenses and their governed rules. Acting on an alert never changes source data.</p>
        </div>
        <button type="button" disabled={busy} onClick={() => {
          setBusy(true);
          runDueRefreshes()
            .then((r) => {
              setNote(`Scheduler step: ${r.refreshed.length} Lens(es) refreshed, ${r.failed.length} failed, ${r.skipped.length} not due.`);
              setReload((n) => n + 1);
            })
            .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
            .finally(() => setBusy(false));
        }} className="ml-auto inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="monitoring-tick">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Refresh due Lenses now
        </button>
      </header>
      {note && <p className="text-xs text-positive" data-testid="monitoring-note">{note}</p>}
      {error && (
        <p role="alert" className="text-sm text-negative">
          {error}
        </p>
      )}

      <nav className="flex flex-wrap gap-1 text-xs" data-testid="monitoring-views">
        {VIEWS.map((v) => (
          <button key={v.id} type="button" aria-pressed={view === v.id} onClick={() => setView(v.id)} className={`rounded-md border px-2 py-1 ${view === v.id ? "border-accent bg-accent text-accent-contrast" : "border-border"}`} data-testid={`monitoring-view-${v.id}`}>
            {v.label}
            {v.id === "active" && data ? ` (${data.counts.new + data.counts.active + data.counts.worsening})` : v.count && data ? ` (${data.counts[v.count]})` : ""}
          </button>
        ))}
      </nav>
      <div className="flex flex-wrap gap-2 text-xs">
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="monitoring-severity">
          <option value="">Every severity</option>
          {["critical", "high", "moderate", "info"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <select value={lens} onChange={(e) => setLens(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="monitoring-lens">
          <option value="">Every Lens</option>
          {(data?.lens_health ?? []).map((l) => (
            <option key={l.lens_id} value={l.lens_id}>
              {l.name}
            </option>
          ))}
        </select>
        <select value={domain} onChange={(e) => setDomain(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="monitoring-domain">
          <option value="">Both books</option>
          <option value="corporate">Corporate</option>
          <option value="retail">Retail</option>
        </select>
      </div>

      {data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard
            title="By severity"
            subtitle={`${alerts.length} in this view`}
            testId="monitoring-by-severity"
            data={[{ type: "bar", x: bySeverity.map((x) => x.s), y: bySeverity.map((x) => x.n), marker: { color: bySeverity.map((x) => SEVERITY_COLORS[x.s] ?? SEMANTIC.residual) }, customdata: bySeverity.map((x) => [x.s]), hovertemplate: "%{x}: %{y}<extra></extra>" }]}
            layout={{ showlegend: false, yaxis: { title: { text: "alerts" }, dtick: 1 } }}
            height={220}
            onPointClick={(p) => Array.isArray(p.customdata) && setSeverity(String(p.customdata[0]))}
            table={{ columns: [{ key: "s", label: "Severity" }, { key: "n", label: "Alerts", align: "right" }], rows: bySeverity }}
          />
          <ChartCard
            title="By Lens"
            subtitle="click a bar to filter to that Lens"
            testId="monitoring-by-lens"
            data={[{ type: "bar", orientation: "h", y: byLens.map(([n]) => n), x: byLens.map(([, v]) => v.n), marker: { color: byLens.map((_, i) => categorical(i)) }, customdata: byLens.map(([, v]) => [v.id]), hovertemplate: "%{y}: %{x}<extra></extra>" }]}
            layout={{ showlegend: false, margin: { l: 220, r: 20, t: 10, b: 40 }, xaxis: { dtick: 1 } }}
            height={220}
            onPointClick={(p) => Array.isArray(p.customdata) && setLens(String(p.customdata[0]))}
            table={{ columns: [{ key: "lens", label: "Lens" }, { key: "n", label: "Alerts", align: "right" }], rows: byLens.map(([lensName, v]) => ({ lens: lensName, n: v.n })) }}
          />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1fr_minmax(24rem,32rem)]">
        <section className="overflow-auto rounded-lg border border-border bg-surface" data-testid="monitoring-list" data-count={alerts.length} data-state={data?.state ?? ""}>
          {data && !alerts.length && (
            <p className="p-3 text-sm text-text-muted" data-testid="monitoring-empty">
              {data.state === "EMPTY_BY_FILTER" ? "Nothing in this view with these filters (EMPTY_BY_FILTER)." : "No alert has been raised yet."}
            </p>
          )}
          <table className="w-full text-xs">
            <thead className="bg-surface-sunken">
              <tr>
                {["State", "Severity", "Lens · rule", "Metric", "Observed vs threshold", "Book · period", "Last seen", "Assignee"].map((h) => (
                  <th key={h} className="px-2 py-1 text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {alerts.map((a: AlertSummary) => (
                <tr key={a.alert_id} onClick={() => open(a.alert_id)} className={`cursor-pointer border-t border-border hover:bg-surface-hover ${selected === a.alert_id ? "bg-accent/5" : ""}`} data-testid="monitoring-alert" data-alert-id={a.alert_id} data-state={a.state} data-type={a.alert_type} data-historical={String(a.demo_historical)}>
                  <td className="px-2 py-1">
                    <span className={`rounded px-1.5 py-0.5 ${STATE_TONE[a.state] ?? ""}`}>{a.state}</span>
                    {a.demo_historical && <span className="ml-1 rounded bg-warning/15 px-1 text-warning">HISTORICAL · demo</span>}
                  </td>
                  <td className="px-2 py-1" style={{ color: SEVERITY_COLORS[a.severity] }}>
                    {a.severity}
                  </td>
                  <td className="px-2 py-1">
                    <div className="font-medium">{a.lens_name}</div>
                    <div className="text-text-muted">{a.rule_name || a.alert_type}</div>
                  </td>
                  <td className="px-2 py-1">{a.metric_id ? `${a.metric_id} v${a.metric_version}` : "—"}</td>
                  <td className="px-2 py-1 tabular">{a.alert_type === "breach" ? describeBreach(a) : a.label.slice(0, 60)}</td>
                  <td className="px-2 py-1">
                    {a.domain_id || "—"} {a.period}
                  </td>
                  <td className="px-2 py-1">{when(a.last_seen)}</td>
                  <td className="px-2 py-1">{a.assignee || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section>{selected ? <AlertPanel key={selected} alertId={selected} onChanged={() => setReload((n) => n + 1)} /> : <p className="text-sm text-text-muted">Choose an alert.</p>}</section>
      </div>

      {data && (
        <section className="overflow-auto rounded-lg border border-border bg-surface" data-testid="monitoring-health">
          <h2 className="p-2 text-sm font-semibold">Lens refresh health</h2>
          <table className="w-full text-xs">
            <thead className="bg-surface-sunken">
              <tr>
                {["Lens", "Cadence", "Last refresh", "Last success", "Status", "Next"].map((h) => (
                  <th key={h} className="px-2 py-1 text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.lens_health.map((l) => (
                <tr key={l.lens_id} className="border-t border-border" data-testid="monitoring-health-row" data-lens-id={l.lens_id} data-stale={String(l.stale)}>
                  <td className="px-2 py-1">
                    <Link href={`/lenses/${l.lens_id}`} className="text-accent underline">
                      {l.name}
                    </Link>
                  </td>
                  <td className="px-2 py-1">{l.cadence}</td>
                  <td className="px-2 py-1">{when(l.last_at)}</td>
                  <td className="px-2 py-1">{when(l.last_success_at)}</td>
                  <td className={`px-2 py-1 ${l.stale ? "font-semibold text-negative" : ""}`}>{l.stale ? "STALE — last refresh failed" : l.last_status}</td>
                  <td className="px-2 py-1 text-text-muted">{l.due ? `due: ${l.why}` : l.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function AlertPanel({ alertId, onChanged }: { alertId: string; onChanged: () => void }) {
  const router = useRouter();
  const [d, setD] = React.useState<AlertDetail | null>(null);
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    readAlert(alertId)
      .then(setD)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [alertId, reload]);

  async function go(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      setNote("");
      setReload((n) => n + 1);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!d) return <p className="text-sm text-text-muted">{error || "Loading alert…"}</p>;
  const a = d.alert;
  const b = a.body as Record<string, unknown>;
  const lensHref = withBack(`/lenses/${d.open_lens.lens_id}?alert=${a.object_id}`);
  const breachType = b.alert_type === "breach";
  return (
    <article className="space-y-3 rounded-xl border border-border bg-surface p-3 text-xs" data-testid="alert-panel" data-state={a.status}>
      <header>
        <div className="flex items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 ${STATE_TONE[a.status] ?? ""}`} data-testid="alert-state">
            {a.status}
          </span>
          <span className="text-sm font-semibold">{a.title}</span>
        </div>
        {Boolean(b.label) && <p className={b.demo_historical ? "text-warning" : "text-text-muted"}>{String(b.label)}</p>}
      </header>
      <dl className="grid grid-cols-[9rem_1fr] gap-x-2 gap-y-0.5">
        <dt className="text-text-muted">Rule</dt>
        <dd>
          {String(b.rule_id)} v{String(b.rule_version)} · {String(b.rule_name)}
        </dd>
        <dt className="text-text-muted">Lens</dt>
        <dd>
          {String(b.lens_name)} ({String(b.lens_id)} v{String(b.lens_version)})
        </dd>
        <dt className="text-text-muted">Metric</dt>
        <dd>
          {b.metric_id ? (
            <Link href={`/metrics?m=${String(b.metric_id)}`} className="text-accent underline">
              {String(b.metric_id)} v{String(b.metric_version)} {d.metric}
            </Link>
          ) : (
            "—"
          )}
        </dd>
        <dt className="text-text-muted">Observed vs threshold</dt>
        <dd className="tabular">
          {describeBreach({ comparison: String(b.comparison), observed: (b.observed as number) ?? null, prior: (b.prior as number) ?? null, threshold: (b.threshold as number) ?? null, unit: String(b.unit ?? "") })}
        </dd>
        <dt className="text-text-muted">Window · period</dt>
        <dd>
          {String(b.window || "latest")} · {String(b.domain_id || "—")} {String(b.period || "")}
        </dd>
        <dt className="text-text-muted">Release</dt>
        <dd className="break-all">{String(b.release_id)}</dd>
        <dt className="text-text-muted">Population</dt>
        <dd>{(b.filters as unknown[] | undefined)?.length ? JSON.stringify(b.filters) : "the Lens's whole book"}</dd>
        <dt className="text-text-muted">First / last seen</dt>
        <dd>
          {when(b.first_seen as number)} / {when(b.last_seen as number)}
        </dd>
        <dt className="text-text-muted">Assignee</dt>
        <dd>{String(b.assignee || "—")}</dd>
      </dl>
      {Array.isArray(b.changes) && (b.changes as { name: string; domain: string }[]).length > 0 && (
        <ul className="list-disc pl-5">
          {(b.changes as { name: string; domain: string; unit: string; from: number | null; to: number | null }[]).map((c, i) => (
            <li key={i}>
              {c.name} ({c.domain}): {fmt(c.from, c.unit)} → {fmt(c.to, c.unit)}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-1">
        <Link href={lensHref} className="rounded-md bg-accent px-2 py-1 text-accent-contrast" data-testid="alert-open-lens">
          Open Lens at the trigger
        </Link>
        <ExportPackage objectId={alertId} testId="alert-export" compact />
        {breachType && (
          <>
            <button type="button" disabled={busy} onClick={() => void go(async () => {
              const t = await investigateAlert(a.object_id);
              router.push(withBack(`/cockpit/thread/${t.thread_id}`));
            })} className="rounded-md border border-border px-2 py-1" data-testid="alert-investigate">
              Investigate in Cockpit
            </button>
            <button type="button" disabled={busy} onClick={() => void go(async () => {
              const c = await alertCohort(a.object_id);
              router.push(withBack(`/what-if?cohort=${c.object_id}`));
            })} className="rounded-md border border-border px-2 py-1" data-testid="alert-whatif">
              What-If
            </button>
          </>
        )}
      </div>
      {d.can_act && (
        <div className="space-y-1 rounded-lg border border-border p-2">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (required to acknowledge / resolve)" className="w-full rounded border border-border bg-surface px-2 py-1" data-testid="alert-note" />
          <div className="flex flex-wrap gap-1">
            {(["acknowledge", "resolve", "reopen", "suppress"] as const).map((act) => (
              <button key={act} type="button" disabled={busy} onClick={() => void go(async () => {
                await actOnAlert(a.object_id, act, note);
              })} className="rounded-md border border-border px-2 py-1 capitalize" data-testid={`alert-${act}`}>
                {act}
              </button>
            ))}
            <button type="button" disabled={busy} onClick={() => void go(async () => {
              await actOnAlert(a.object_id, "assign");
            })} className="rounded-md border border-border px-2 py-1" data-testid="alert-assign">
              Assign to me
            </button>
            <button type="button" disabled={busy || !note.trim()} onClick={() => void go(async () => {
              await actOnAlert(a.object_id, "comment", note);
            })} className="rounded-md border border-border px-2 py-1" data-testid="alert-comment">
              Comment
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="text-negative" data-testid="alert-error">
          {error}
        </p>
      )}
      <section data-testid="alert-history">
        <h3 className="font-semibold">Status history</h3>
        <ol className="space-y-0.5">
          {d.events.map((e) => (
            <li key={e.event_id} data-to={e.to_state}>
              {when(e.at)} · {e.from_state || "∅"} → {e.to_state} · {e.actor_id}
              {e.note ? ` · ${e.note}` : ""}
              {e.observed ? ` · observed ${e.observed}` : ""}
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
