"use client";

/**
 * One Lens, live (§32.2). Every tile and chart is a governed metric evaluated
 * now. Click a category to cross-filter every compatible visual and the
 * table; click a trend point to move the Lens to that period (the active
 * time and filter state is always shown); box-select categories to make a
 * temporary cohort you can Save, Investigate or take to What-If; click a
 * borrower/customer to investigate it; every visual has View data. Refresh
 * records an immutable observation with what changed and which breach rules
 * fire. Editing writes a new version (your own copy of a library Lens).
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Bell, BellOff, Loader2, RefreshCw, X } from "lucide-react";

import { ChartCard } from "@/components/viz/chart-card";
import { PlotlyChart } from "@/components/viz/plotly-chart";
import { ExportPackage } from "@/components/workspace/export-package";
import { ShareButton } from "@/components/workspace/share-button";
import { formatValue } from "@/lib/workspace/metric-figures";
import { breakdownFigure, clickFilter, groupsFigure, kpiTile, sparkFigure, topOwnersFigure, trendFigure } from "@/lib/workspace/lens-figures";
import { followLens, refreshLens, renderLens, reviseLens, type RenderedLens, type RenderedVisual } from "@/lib/workspace/lenses";
import { readAlert } from "@/lib/workspace/monitoring";
import type { Filter } from "@/lib/workspace/objects";
import { investigateCohort, saveSelection } from "@/lib/workspace/whatif";
import { safeBack, withBack } from "@/lib/workspace/nav";
import { moneyCol } from "@/lib/viz/format";
import { useAddress } from "@/lib/workspace/address";

type Cross = Filter & { domain?: string };

const OWNER: Record<string, string> = { corporate: "borrower_id", retail: "customer_id" };

/** A JSON value carried in the URL, or `fallback` when absent or malformed. */
function fromUrl<T>(raw: string | null, fallback: T, ok: (v: unknown) => boolean): T {
  if (!raw) return fallback;
  try {
    const v = JSON.parse(raw) as unknown;
    return ok(v) ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}
const isObject = (v: unknown) => !!v && typeof v === "object" && !Array.isArray(v);

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

function describe(f: Cross): string {
  return `${f.domain ? `${f.domain}: ` : ""}${f.column} ∈ ${(f.values ?? [f.value]).join(", ")}`;
}


/** Groups visuals whose bars are alerts: a click opens the Monitoring Centre. */
const ALERT_GROUPS = new Set(["M070", "M071", "M072"]);

export function LensView({ lensId }: { lensId: string }) {
  const router = useRouter();
  const address = useAddress();
  const params = useSearchParams();
  // Periods, cross-filters, the chart selection and the cohort frozen from it
  // live in the URL: Back from a destination reopens the Lens as it was, and
  // a selection already saved is not saved again.
  const [data, setData] = React.useState<RenderedLens | null>(null);
  const [periods, setPeriods] = React.useState<Record<string, string>>(() => fromUrl(params.get("p"), {}, isObject));
  const [cross, setCross] = React.useState<Cross[]>(() => fromUrl(params.get("x"), [], Array.isArray));
  const [selection, setSelection] = React.useState<{ domain: "corporate" | "retail"; filters: Filter[]; label: string } | null>(() =>
    fromUrl(params.get("sel"), null, (v) => isObject(v) && Array.isArray((v as { filters?: unknown }).filters)),
  );
  const [savedCohort, setSavedCohort] = React.useState(params.get("cohort") ?? "");
  // Bumped when the selection is cleared: the chart keeps the reader's zoom
  // and legend across re-renders (`uirevision`), and without this it also
  // kept the cleared box and highlighted bars, so dragging over the same
  // bars again deselected them instead of selecting (VAL-DEF-048).
  const [selectionRevision, setSelectionRevision] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  const [name, setName] = React.useState("");
  const [cadence, setCadence] = React.useState("");
  const [trigger, setTrigger] = React.useState("");
  const alertId = params.get("alert") ?? "";
  const back = safeBack(params.get("back"));
  const restored = React.useRef(params.has("x") || params.has("p"));
  // Set when this page navigates away: the URL is then left alone, so a
  // replace cannot overtake (and cancel) the navigation in flight.
  const leaving = React.useRef(false);
  const leave = React.useCallback((href: string) => {
    leaving.current = true;
    router.push(href);
  }, [router]);

  React.useEffect(() => {
    if (leaving.current) return;
    const enc = (v: unknown, empty: boolean) => (empty ? null : JSON.stringify(v));
    address.replace({
      p: enc(periods, !Object.keys(periods).length),
      x: enc(cross, !cross.length),
      sel: enc(selection, !selection),
      cohort: savedCohort || null,
    });
  }, [periods, cross, selection, savedCohort, address]);

  // Opened from an alert: restore the Lens at the triggering period and
  // population, and say so.
  React.useEffect(() => {
    if (!alertId) return;
    let live = true;
    readAlert(alertId)
      .then((d) => {
        if (!live) return;
        // On a return visit the URL already holds the reader's own state.
        if (!restored.current) {
          setPeriods(d.open_lens.periods ?? {});
          setCross((d.open_lens.filters ?? []) as Cross[]);
        }
        const b = d.alert.body as Record<string, unknown>;
        setTrigger(`Opened at alert ${d.alert.object_id} (${d.alert.status}): ${String(b.rule_name || b.alert_type)} · ${String(b.domain_id || "")} ${String(b.period || "")}`);
      })
      .catch((e: unknown) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [alertId]);

  React.useEffect(() => {
    let live = true;
    renderLens(lensId, { periods, cross_filters: cross })
      .then((d) => {
        if (!live) return;
        setData(d);
        setError("");
      })
      .catch((e: unknown) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [lensId, periods, cross]);

  // One governed mutation at a time: a double-click fires twice before
  // `busy` disables the control; the ref closes that window.
  const inFlight = React.useRef(false);
  async function go(fn: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  if (error && !data)
    return (
      <p role="alert" className="text-sm text-negative" data-testid="lens-view-error">
        {error}
      </p>
    );
  if (!data)
    return (
      <p className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Evaluating the Lens on the published books…
      </p>
    );

  const lens = data.lens;
  const spec = lens.body;
  const kpis = data.visuals.filter((v) => v.type === "kpi");
  const charts = data.visuals.filter((v) => !["kpi", "table"].includes(v.type));
  const tables = data.visuals.filter((v) => v.type === "table");
  const obs = data.last_observation;
  const lensFilters = (d: string) => (spec.filters?.[d] ?? []) as Filter[];

  function addCross(f: Cross | null) {
    if (!f) return;
    setCross((prev) => [...prev.filter((p) => !(p.column === f.column && p.domain === f.domain)), f]);
  }

  function select(v: RenderedVisual, points: { customdata?: unknown }[]) {
    const values = points.map((p) => (Array.isArray(p.customdata) ? p.customdata[0] : null)).filter((x) => x !== null && x !== undefined) as (string | number)[];
    if (!values.length || !v.group_by) return;
    const column = v.type === "stage_mix" ? "stage" : v.group_by;
    const filters: Filter[] = [...lensFilters(v.domain), ...cross.filter((c) => !c.domain || c.domain === v.domain).map((c) => ({ column: c.column, op: c.op, values: c.values, value: c.value }) as Filter), { column, op: "in", values }];
    setSavedCohort("");
    setSelection({ domain: v.domain, filters, label: `${column} ∈ ${values.join(", ")}` });
  }

  async function freezeSelection(): Promise<string> {
    if (!selection) return "";
    if (savedCohort) return savedCohort;
    const c = await saveSelection(selection.domain, { mode: "filtered", filters: selection.filters }, `${spec.name}: ${selection.label}`.slice(0, 150));
    setSavedCohort(c.object_id);
    return c.object_id;
  }

  async function investigateOwner(domain: "corporate" | "retail", owner: string) {
    const c = await saveSelection(domain, { mode: "filtered", filters: [{ column: OWNER[domain], op: "in", values: [owner] }] }, `${owner} (from ${spec.name})`.slice(0, 150));
    const t = await investigateCohort(c.object_id);
    leave(withBack(`/cockpit/thread/${t.thread_id}`));
  }

  function chart(v: RenderedVisual) {
    if (v.status !== "OK")
      return (
        <div key={v.visual_id} className="rounded-lg border border-negative p-3 text-xs text-negative" data-testid="lens-visual-error">
          {v.title}: {v.message}
        </div>
      );
    const common = {
      title: v.title,
      subtitle: `${v.metric_id ?? ""} v${v.metric_version ?? ""} · ${v.domain} · ${v.period}${v.filters_applied?.length ? ` · ${v.filters_applied.length} filter(s)` : ""}${v.filters_skipped?.length ? ` · ${v.filters_skipped.length} filter(s) not applicable to this book` : ""}`,
      testId: `lens-visual-${v.visual_id}`,
      context: { releaseId: v.release_id, period: v.period, filters: { applied: v.filters_applied, skipped: v.filters_skipped }, source: `${spec.name} v${lens.version}` },
      height: 300,
    };
    if (v.type === "trend") {
      const fig = trendFigure(v);
      return (
        <ChartCard
          key={v.visual_id}
{...common}
          control="lens-chart-trend"
          data={fig.data}
          layout={fig.layout}
          onPointClick={(p) => {
            const period = Array.isArray(p.customdata) ? String(p.customdata[0]) : "";
            if (period) setPeriods((prev) => ({ ...prev, [v.domain]: period }));
          }}
          table={{ columns: [{ key: "metric", label: "Metric" }, { key: "period", label: "Period" }, { key: "value", label: "Value (raw)", align: "right" }], rows: (v.series ?? []).flatMap((s) => s.points.map((p) => ({ metric: `${s.metric_id} ${s.name}`, period: p.period, value: p.value }))) }}
        />
      );
    }
    if (v.type === "breakdown" || v.type === "stage_mix") {
      const fig = breakdownFigure(v);
      return (
        <ChartCard
          key={v.visual_id}
{...common}
          control="lens-chart-breakdown"
          data={fig.data}
          layout={{ ...fig.layout, selectionrevision: `selection-${selectionRevision}` }}
          selectable
          onPointClick={(p) => addCross(clickFilter(v, p.customdata))}
          onSelected={(pts) => select(v, pts)}
          table={{ columns: [{ key: "dimension", label: v.group_by ?? "" }, { key: "value", label: "Value (raw)", align: "right" }, { key: "rows", label: "Rows", align: "right" }], rows: (v.groups ?? []) as unknown as Record<string, unknown>[] }}
        />
      );
    }
    if (v.type === "top_owners") {
      const fig = topOwnersFigure(v);
      return (
        <ChartCard
          key={v.visual_id}
{...common}
          control="lens-chart-top-owners"
          data={fig.data}
          layout={fig.layout}
          onPointClick={(p) => {
            const owner = Array.isArray(p.customdata) ? String(p.customdata[0]) : "";
            if (owner) void go(() => investigateOwner(v.domain, owner));
          }}
          table={{ columns: [{ key: "owner", label: "Owner" }, { key: "name", label: "Name" }, moneyCol("ead", "EAD", v.rows ?? []), moneyCol("ecl", "ECL", v.rows ?? []), { key: "n", label: "Exposures", align: "right" }], rows: v.rows ?? [] }}
        />
      );
    }
    const fig = groupsFigure(v);
    return (
      <ChartCard
        key={v.visual_id}
{...common}
          control="lens-chart-groups"
        data={fig.data}
        layout={fig.layout}
        onPointClick={(p) => {
          const oid = Array.isArray(p.customdata) ? String(p.customdata[0]) : "";
          if ((v.type === "scenario_results" || v.type === "groups") && oid) leave(withBack(`/what-if/result/${oid}`));
          if (v.type === "alerts" || (v.type === "groups" && ALERT_GROUPS.has(v.metric_id ?? ""))) leave(withBack("/monitoring"));
        }}
        footer={!(v.groups ?? []).some((g) => g.value != null) ? <p className="mt-2 text-xs text-text-muted">{v.type === "scenario_results" ? "No executed scenario you can open on this book yet." : v.type === "alerts" ? "No active breach on this book." : (v.note ?? "Nothing to show yet.")}</p> : null}
        table={{ columns: [{ key: "dimension", label: "Item" }, { key: "value", label: "Value (raw)", align: "right" }], rows: (v.groups ?? []) as unknown as Record<string, unknown>[] }}
      />
    );
  }

  return (
    <article className="space-y-4" data-testid="lens-view" data-object-id={lens.object_id} data-version={lens.version} data-visuals={data.visuals.length}>
      <header className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs text-text-muted">
            <Link href={back || "/lenses"} className="text-accent underline" data-testid="lens-back" data-back-target={back || "/lenses"}>
              {back ? "← Back" : "Lenses"}
            </Link>{" "}
            · {lens.lens_id || "My Lens"} · {lens.persona} · v{lens.version} · owner {lens.owner_id} · refresh {spec.refresh.cadence} ({spec.refresh.timezone})
          </div>
          <h1 className="text-xl font-semibold">{lens.name}</h1>
          <p className="text-sm text-text-muted">{lens.description}</p>
          {spec.note && <p className="text-xs text-warning">{spec.note}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={busy} onClick={() => void go(async () => {
            const o = await refreshLens(lens.object_id);
            const created = o.alerts?.created?.length ?? 0;
            setNote(`Refreshed: ${o.body.what_changed}${created ? ` · ${created} alert(s) raised — see Monitoring Centre` : ""}`);
            setData(await renderLens(lens.object_id, { periods, cross_filters: cross }));
          })} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="lens-refresh">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
          <button type="button" onClick={() => {
            setEditing((v) => !v);
            setName(lens.name);
            setCadence(spec.refresh.cadence);
          }} className="rounded-md border border-border px-3 py-1.5 text-sm" data-testid="lens-edit">
            {lens.can_edit && lens.owner_id !== "creditprobe-library" ? "Edit" : "Customise (my copy)"}
          </button>
          <button type="button" disabled={busy} onClick={() => void go(async () => {
            await followLens(lens.object_id, !lens.following);
            setData(await renderLens(lens.object_id, { periods, cross_filters: cross }));
          })} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="lens-follow" data-following={String(lens.following)}>
            {lens.following ? <BellOff className="h-4 w-4" /> : <Bell className="h-4 w-4" />} {lens.following ? "Following" : "Follow"}
          </button>
          <ShareButton objectId={lens.object_id} testId="lens-share" />
          <ExportPackage objectId={lens.object_id} scopeSelector="main" testId="lens-export" />
        </div>
      </header>
      {trigger && (
        <p className="rounded-lg border border-warning bg-surface p-2 text-xs" data-testid="lens-alert-banner">
          {trigger}{" "}
          <Link href={back.startsWith("/monitoring") ? back : `/monitoring?alert=${alertId}`} className="text-accent underline" data-testid="lens-alert-back">
            back to the alert
          </Link>
        </p>
      )}
      {obs?.status === "FAILED" && (
        <p role="alert" className="rounded-lg border border-negative p-2 text-xs text-negative" data-testid="lens-stale">
          The last refresh FAILED ({new Date(obs.finished_at * 1000).toLocaleString()}): {obs.body.what_changed} The figures below are evaluated live now; the refresh record is not current.
        </p>
      )}

      {editing && (
        <form
          className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface p-2 text-sm"
          data-testid="lens-edit-form"
          onSubmit={(e) => {
            e.preventDefault();
            void go(async () => {
              const obj = await reviseLens(lens.object_id, { name, refresh: { ...spec.refresh, cadence } }, "edited in the Lens view");
              setEditing(false);
              if (obj.object_id !== lens.object_id) leave(`/lenses/${obj.object_id}`);
              else setData(await renderLens(lens.object_id, { periods, cross_filters: cross }));
            });
          }}
        >
          <input value={name} onChange={(e) => setName(e.target.value)} className="min-w-[18rem] flex-1 rounded border border-border bg-surface px-2 py-1" data-testid="lens-edit-name" />
          <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="lens-edit-cadence">
            {["manual", "on_publication", "on_result", "daily", "weekly", "monthly", "continuous"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <button type="submit" disabled={busy} className="rounded-md bg-accent px-3 py-1 text-accent-contrast disabled:opacity-40" data-testid="lens-edit-save">
            Save as a new version
          </button>
        </form>
      )}

      <section className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-raised p-2 text-xs" data-testid="lens-state" data-cross={cross.length}>
        <span className="font-semibold">Active state</span>
        {Object.entries(data.books).map(([d, b]) => (
          <span key={d} className={`rounded px-1.5 py-0.5 ${b.period !== b.latest_period ? "bg-warning/15 text-warning" : "bg-surface-sunken"}`} data-testid={`lens-period-${d}`} data-period={b.period}>
            {d} {b.period}
            {b.period !== b.latest_period ? ` (not latest ${b.latest_period})` : " (latest)"}
          </span>
        ))}
        {Object.entries(spec.filters ?? {}).map(([d, fs]) =>
          (fs as Filter[]).map((f, i) => (
            <span key={`${d}${i}`} className="rounded bg-surface-sunken px-1.5 py-0.5">
              Lens scope: {describe({ ...f, domain: d })}
            </span>
          )),
        )}
        {cross.map((f, i) => (
          <span key={i} className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5" data-testid="lens-cross-chip">
            {describe(f)}
            <button data-testid="lens-cross-remove" type="button" aria-label="remove filter" onClick={() => setCross((prev) => prev.filter((_, j) => j !== i))}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {(cross.length > 0 || Object.keys(periods).length > 0) && (
          <button type="button" onClick={() => {
            setCross([]);
            setPeriods({});
          }} className="text-accent underline" data-testid="lens-reset">
            reset to latest, unfiltered
          </button>
        )}
      </section>

      {note && (
        <p className="text-xs text-positive" data-testid="lens-note">
          {note}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-negative" data-testid="lens-error">
          {error}
        </p>
      )}

      {selection && (
        <section className="flex flex-wrap items-center gap-2 rounded-lg border border-accent bg-surface p-2 text-xs" data-testid="lens-selection">
          <span className="font-semibold">Temporary cohort:</span> {selection.domain} · {selection.label}
          <button type="button" disabled={busy} onClick={() => void go(async () => {
            const id = await freezeSelection();
            setNote(`Saved as governed cohort ${id}.`);
          })} className="rounded-md border border-border px-2 py-1" data-testid="lens-selection-save">
            Save
          </button>
          <button type="button" disabled={busy} onClick={() => void go(async () => {
            const id = await freezeSelection();
            const t = await investigateCohort(id);
            leave(withBack(`/cockpit/thread/${t.thread_id}`));
          })} className="rounded-md border border-border px-2 py-1" data-testid="lens-selection-investigate">
            Investigate
          </button>
          <button type="button" disabled={busy} onClick={() => void go(async () => {
            const id = await freezeSelection();
            leave(withBack(`/what-if?cohort=${id}&domain=${selection?.domain ?? ""}`));
          })} className="rounded-md border border-border px-2 py-1" data-testid="lens-selection-whatif">
            What-If
          </button>
          {savedCohort && <ShareButton objectId={savedCohort} testId="lens-selection-share" />}
          <button
            data-testid="lens-selection-clear"
            type="button"
            onClick={() => {
              setSelection(null);
              setSelectionRevision((n) => n + 1);
            }}
            className="ml-auto text-accent underline"
          >
            clear
          </button>
        </section>
      )}

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6" data-testid="lens-kpis">
        {kpis.map((v) => {
          const k = kpiTile(v);
          const spark = sparkFigure(v);
          return (
            <Link key={v.visual_id} href={withBack(`/metrics?m=${v.metric_id}`)} className="block rounded-lg border border-border bg-surface p-2" title={`${k.metric} — open the definition`} data-testid="lens-kpi" data-metric-id={v.metric_id} data-raw={k.raw} data-tone={k.tone}>
              <div className="truncate text-[11px] text-text-muted">
                {k.title} · {v.domain}
              </div>
              <div className="text-lg font-semibold tabular">{k.value}</div>
              {k.delta && <div className={`text-[11px] ${k.tone === "bad" ? "text-negative" : k.tone === "good" ? "text-positive" : "text-text-muted"}`}>{k.delta}</div>}
              {k.note && <div className="text-[10px] text-text-muted">{k.note}</div>}
              {spark && <PlotlyChart data={spark.data} layout={spark.layout} height={40} ariaLabel={`${k.title} trend`} chrome="minimal" />}
              <div className="text-[10px] text-text-muted">{k.metric}</div>
            </Link>
          );
        })}
      </div>

      <div className="grid gap-4 xl:grid-cols-2" data-testid="lens-charts">
        {charts.map((v) => chart(v))}
      </div>

      {tables.map((v) => (
        <section key={v.visual_id} className="overflow-auto rounded-lg border border-border bg-surface" data-testid={`lens-table-${v.visual_id}`} data-total={v.total}>
          <header className="flex items-center gap-2 border-b border-border p-2 text-xs">
            <span className="font-semibold">{v.title}</span>
            <span className="text-text-muted">
              {v.domain} · {v.period} · {v.total} rows · top 25 · click a row to investigate it
            </span>
          </header>
          <table className="w-full text-xs">
            <thead className="bg-surface-sunken">
              <tr>
                {(v.columns ?? []).map((c) => (
                  <th key={c} className="px-2 py-1 text-left">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(v.rows ?? []).map((r, i) => (
                <tr
                  key={i}
                  className="cursor-pointer border-t border-border hover:bg-surface-hover"
                  data-testid="lens-table-row"
                  onClick={() =>
                    void go(async () => {
                      const key = String(r[v.key ?? ""] ?? "");
                      const c = await saveSelection(v.domain, { mode: "rows", ids: [key] }, `${key} (from ${spec.name})`);
                      const t = await investigateCohort(c.object_id);
                      leave(withBack(`/cockpit/thread/${t.thread_id}`));
                    })
                  }
                >
                  {(v.columns ?? []).map((c) => (
                    <td key={c} className="px-2 py-1 tabular">
                      {typeof r[c] === "number" && /sar_mn$/.test(c) ? formatValue(r[c] as number, "SAR_mn") : String(r[c] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      <section className="grid gap-3 md:grid-cols-2" data-testid="lens-governance">
        <div className="rounded-lg border border-border bg-surface p-3 text-xs" data-testid="lens-rules">
          <h3 className="mb-1 font-semibold">Breach rules</h3>
          {spec.breach_rules.map((r) => {
            const b = obs?.body.breaches.find((x) => x.rule_id === r.rule_id);
            return (
              <div key={r.rule_id} className="border-t border-border py-1" data-testid="lens-rule" data-breached={String(Boolean(b?.breached))}>
                <span className={b?.breached ? "font-semibold text-negative" : ""}>
                  {b?.breached ? "BREACHED · " : ""}
                  {r.name}
                </span>{" "}
                <span className="text-text-muted">
                  {r.metric_id} {r.comparison} {r.threshold} · {r.severity} · cooldown {r.cooldown_hours}h{b ? ` · observed ${b.observed ?? "—"}` : ""}
                </span>
              </div>
            );
          })}
          {!spec.breach_rules.length && <p className="text-text-muted">No breach rule on this Lens.</p>}
        </div>
        <div className="rounded-lg border border-border bg-surface p-3 text-xs" data-testid="lens-observation">
          <h3 className="mb-1 font-semibold">Last refresh</h3>
          {obs ? (
            <>
              <p>
                {new Date(obs.finished_at * 1000).toLocaleString()} · {obs.status} · {obs.trigger} · v{obs.lens_version}
              </p>
              <p data-testid="lens-what-changed">{obs.body.what_changed}</p>
              <ul className="list-disc pl-5">
                {obs.body.material_changes.map((c, i) => (
                  <li key={i}>
                    {c.name} ({c.domain}): {formatValue(c.from, c.unit)} → {formatValue(c.to, c.unit)}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-text-muted">Not refreshed yet. Refresh records the baseline observation.</p>
          )}
          <p className="mt-2 text-text-muted">
            Metrics:{" "}
            {spec.metrics.map((m) => (
              <Link data-testid="lens-governance-metric" key={`${m.metric_id}${m.domain}`} href={withBack(`/metrics?m=${m.metric_id}`)} className="mr-1 text-accent underline">
                {m.metric_id}v{m.version}
              </Link>
            ))}
          </p>
        </div>
      </section>
    </article>
  );
}
