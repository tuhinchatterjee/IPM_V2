"use client";

/**
 * Metric Catalogue (§46): every governed metric as a persisted, versioned
 * object. Browse the full definition, formula and SQL, the lineage (source
 * relations/fields, version history), live values on each book it applies
 * to, its trend, a breakdown by any of its drill-down dimensions (click a bar
 * to see the rows behind it), and every Lens, breach rule and Requires
 * Attention detector that uses it.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ChartCard } from "@/components/viz/chart-card";
import { breakdownBars, formatValue, gridDimension, metricTrend } from "@/lib/workspace/metric-figures";
import { evaluateMetric, listMetrics, metricRows, readMetric, readMetricLineage, type MetricDefinition, type MetricLineage, type MetricValue } from "@/lib/workspace/metrics";
import type { Filter } from "@/lib/workspace/objects";
import { OriginBackLink } from "@/components/workspace/origin-back";
import { urlWith } from "@/lib/workspace/nav";

const BOOKS = ["corporate", "retail"] as const;
const DIRECTION: Record<string, string> = { lower_is_better: "Lower is better", higher_is_better: "Higher is better", context: "Context (no preferred direction)" };

export function MetricCatalogue() {
  const params = useSearchParams();
  const router = useRouter();
  const [all, setAll] = React.useState<MetricDefinition[] | null>(null);
  const [version, setVersion] = React.useState("");
  const [q, setQ] = React.useState("");
  const [domain, setDomain] = React.useState("");
  const [family, setFamily] = React.useState("");
  const [error, setError] = React.useState("");
  const selected = params.get("m") ?? "M001";

  React.useEffect(() => {
    listMetrics()
      .then((r) => {
        setAll(r.metrics);
        setVersion(r.catalog_version);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const families = React.useMemo(() => [...new Set((all ?? []).map((m) => m.family).filter(Boolean))].sort(), [all]);
  const needle = q.trim().toLowerCase();
  const shown = (all ?? []).filter(
    (m) =>
      (!domain || m.domain === domain || m.domain === "both") &&
      (!family || m.family === family) &&
      (!needle || `${m.metric_id} ${m.name} ${m.definition} ${m.formula}`.toLowerCase().includes(needle)),
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(20rem,24rem)_1fr]" data-testid="metric-catalogue">
      <section className="space-y-2">
        <OriginBackLink testId="metrics-back" />
        <header>
          <h1 className="text-lg font-semibold">Metric Catalogue</h1>
          <p className="text-xs text-text-muted" data-testid="metric-count" data-count={all?.length ?? 0}>
            {all ? `${all.length} governed metrics · catalogue ${version} · persisted, versioned objects` : "Loading…"}
          </p>
        </header>
        {error && (
          <p role="alert" className="text-sm text-negative">
            {error}
          </p>
        )}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id, name, formula…" className="w-full rounded border border-border bg-surface px-2 py-1 text-sm" data-testid="metric-search" />
        <div className="flex gap-2 text-xs">
          <select value={domain} onChange={(e) => setDomain(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="metric-domain">
            <option value="">Both books</option>
            <option value="corporate">Corporate</option>
            <option value="retail">Retail</option>
          </select>
          <select value={family} onChange={(e) => setFamily(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="metric-family">
            <option value="">Every family</option>
            {families.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </div>
        {all && !shown.length && (
          <p className="text-xs text-text-muted" data-testid="metric-empty-by-filter">
            No metric matches these filters (EMPTY_BY_FILTER). Clear the search or filters.
          </p>
        )}
        <ul className="max-h-[70vh] space-y-1 overflow-auto" data-testid="metric-list">
          {shown.map((m) => (
            <li key={m.metric_id}>
              <button
                type="button"
                onClick={() => router.replace(urlWith({ m: m.metric_id }))}
                className={`w-full rounded-lg border p-2 text-left text-xs ${selected === m.metric_id ? "border-accent bg-accent/5" : "border-border bg-surface"}`}
                data-testid="metric-item"
                data-metric-id={m.metric_id}
              >
                <span className="font-mono text-text-muted">{m.metric_id}</span> <span className="font-medium">{m.name}</span>
                <span className="block text-text-muted">
                  {m.domain} · {m.unit} · {m.family || m.kind} · v{m.object_version}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="min-w-0">{all && <MetricDetail key={selected} metricId={selected} />}</section>
    </div>
  );
}

/** A ratio's parts in the unit of its components (money for shares of EAD). */
function fmtPart(x: number | null | undefined, m: MetricDefinition): string {
  if (x === null || x === undefined) return "—";
  const money = /ead|ecl|sar/i.test(`${m.num_sql} ${m.den_sql}`) && !/COUNT\(/i.test(m.den_sql || m.num_sql);
  return money ? formatValue(x, "SAR_mn") : Number.isInteger(x) ? formatValue(x, "count") : x.toFixed(4);
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[11rem_1fr] gap-2 border-t border-border py-1 text-xs">
      <dt className="text-text-muted">{label}</dt>
      <dd className="whitespace-pre-wrap">{children}</dd>
    </div>
  );
}

function MetricDetail({ metricId }: { metricId: string }) {
  const [m, setM] = React.useState<MetricDefinition | null>(null);
  const [lineage, setLineage] = React.useState<MetricLineage | null>(null);
  const [values, setValues] = React.useState<Record<string, MetricValue | string>>({});
  const [dim, setDim] = React.useState("");
  const [book, setBook] = React.useState<string>("corporate");
  const [breakdown, setBreakdown] = React.useState<MetricValue | null>(null);
  const [drill, setDrill] = React.useState<{ label: string; rows: Record<string, unknown>[]; total: number } | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    Promise.all([readMetric(metricId), readMetricLineage(metricId)])
      .then(async ([def, lin]) => {
        if (!live) return;
        setM(def);
        setLineage(lin);
        const books = BOOKS.filter((b) => def.domain === "both" || def.domain === b);
        setBook(books[0]);
        const first = def.drilldown_dimensions.map((d) => gridDimension(d, books[0])).find(Boolean);
        setDim(first ?? "");
        const out: Record<string, MetricValue | string> = {};
        for (const b of books) {
          try {
            out[b] = await evaluateMetric(b, metricId, { series_periods: 8 });
          } catch (e) {
            out[b] = e instanceof Error ? e.message : String(e);
          }
        }
        if (live) setValues(out);
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [metricId]);

  React.useEffect(() => {
    if (!m || !dim) return;
    let live = true;
    evaluateMetric(book, metricId, { group_by: dim })
      .then((r) => live && setBreakdown(r))
      .catch(() => live && setBreakdown(null));
    return () => {
      live = false;
    };
  }, [m, dim, book, metricId]);

  if (error)
    return (
      <p role="alert" className="text-sm text-negative" data-testid="metric-error">
        {error}
      </p>
    );
  if (!m) return <p className="text-sm text-text-muted">Loading definition…</p>;
  const books = BOOKS.filter((b) => m.domain === "both" || m.domain === b);
  const trendSeries = books
    .map((b) => ({ b, v: values[b] }))
    .filter((x): x is { b: (typeof BOOKS)[number]; v: MetricValue } => typeof x.v === "object" && Boolean(x.v?.series?.length))
    .map((x) => ({ name: x.b === "corporate" ? "Corporate" : "Retail", points: x.v.series! }));
  const dims = [...new Set(m.drilldown_dimensions.map((d) => gridDimension(d, book)).filter((d): d is string => Boolean(d)))];
  const bars = breakdown?.groups ? breakdownBars(breakdown.groups, m.unit, dim) : null;

  async function drillTo(value: string) {
    const filters: Filter[] = [{ column: dim, op: "in", values: [value] }];
    const r = await metricRows(metricId, book, filters, 100);
    setDrill({ label: `${dim} = ${value}`, rows: r.rows, total: r.total });
  }

  return (
    <article className="space-y-4" data-testid="metric-detail" data-metric-id={m.metric_id} data-version={m.object_version}>
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">
          <span className="font-mono text-text-muted">{m.metric_id}</span> {m.name}
        </h2>
        <p className="text-xs text-text-muted">
          {m.object_id} v{m.object_version} · {m.status} · owner {m.owner} · {m.domain} · {m.family || m.kind} · content {m.content_hash.slice(0, 12)}
        </p>
        <p className="text-sm">{m.definition}</p>
      </header>

      <div className="grid gap-2 md:grid-cols-2" data-testid="metric-values">
        {books.map((b) => {
          const v = values[b];
          return (
            <div key={b} className="rounded-lg border border-border bg-surface p-3" data-testid={`metric-value-${b}`}>
              <div className="text-xs text-text-muted">
                {b === "corporate" ? "Corporate" : "Retail"} {typeof v === "object" ? `· ${v.period} · ${v.release_id}` : ""}
              </div>
              {v === undefined ? (
                <div className="text-sm text-text-muted">evaluating…</div>
              ) : typeof v === "string" ? (
                <div className="text-sm text-negative">{v}</div>
              ) : (
                <>
                  <div className="text-xl font-semibold tabular" data-raw={String(v.value ?? "")}>
                    {v.status === "PER_LENS" ? "per Lens" : formatValue(v.value, m.unit)}
                  </div>
                  <div className="text-xs text-text-muted">
                    {v.note ??
                      (v.groups && !m.num_sql
                        ? `${v.groups.length} groups${v.latest_result ? ` · latest ${v.latest_result}` : ""}`
                        : `numerator ${fmtPart(v.numerator, m)} · denominator ${fmtPart(v.denominator, m)} · ${v.rows ?? 0} rows`)}
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>

      {trendSeries.length > 0 && (
        <div className={`grid gap-3 ${trendSeries.length > 1 ? "lg:grid-cols-2" : ""}`}>
          {/* One chart per book: quarters and months never share an axis. */}
          {trendSeries.map((s) => (
            <ChartCard
              key={s.name}
              title={`Trend — ${s.name}`}
              subtitle={`${m.metric_id} v${m.version} over the last published ${s.name === "Corporate" ? "quarters" : "months"}`}
              testId={`metric-trend-${s.name.toLowerCase()}`}
              {...metricTrend([s], m.unit)}
              height={240}
              table={{
                columns: [
                  { key: "period", label: "Period" },
                  { key: "value", label: "Value (raw)", align: "right" },
                ],
                rows: s.points.map((p) => ({ period: p.period, value: p.value })),
              }}
            />
          ))}
        </div>
      )}

      {dims.length > 0 && (
        <section className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-semibold">Breakdown</span>
            {books.length > 1 && (
              <select value={book} onChange={(e) => setBook(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="metric-breakdown-book">
                {books.map((b) => (
                  <option key={b}>{b}</option>
                ))}
              </select>
            )}
            <select value={dim} onChange={(e) => setDim(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="metric-breakdown-dim">
              {dims.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
            <span className="text-text-muted">click a bar to see the rows behind it</span>
          </div>
          {bars && breakdown?.groups && (
            <ChartCard
              title={`${m.name} by ${dim}`}
              subtitle={`${book} · ${breakdown.period}`}
              testId="metric-breakdown"
              {...bars}
              height={300}
              onPointClick={(p) => {
                const value = Array.isArray(p.customdata) ? String(p.customdata[0]) : "";
                if (value) void drillTo(value);
              }}
              table={{
                columns: [
                  { key: "dimension", label: dim },
                  { key: "value", label: "Value (raw)", align: "right" },
                  { key: "numerator", label: "Numerator", align: "right" },
                  { key: "denominator", label: "Denominator", align: "right" },
                  { key: "rows", label: "Rows", align: "right" },
                ],
                rows: breakdown.groups as unknown as Record<string, unknown>[],
              }}
            />
          )}
          {drill && (
            <div className="overflow-auto rounded-lg border border-border" data-testid="metric-drill" data-total={drill.total}>
              <p className="bg-surface-sunken px-2 py-1 text-xs">
                Rows behind {drill.label}: {drill.total} ({Math.min(drill.total, drill.rows.length)} shown)
              </p>
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    {Object.keys(drill.rows[0] ?? {})
                      .slice(0, 10)
                      .map((k) => (
                        <th key={k} className="px-2 py-1 text-left">
                          {k}
                        </th>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {drill.rows.slice(0, 25).map((r, i) => (
                    <tr key={i} className="border-t border-border">
                      {Object.keys(drill.rows[0] ?? {})
                        .slice(0, 10)
                        .map((k) => (
                          <td key={k} className="px-2 py-1">
                            {String(r[k] ?? "")}
                          </td>
                        ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <dl className="rounded-lg border border-border bg-surface p-3" data-testid="metric-definition">
        <Field label="Formula">{m.formula}</Field>
        <Field label="Numerator">{m.numerator}</Field>
        <Field label="Denominator">{m.denominator}</Field>
        <Field label="Executable SQL">
          <code className="font-mono text-[11px]">{m.num_sql ? `${m.num_sql}${m.den_sql ? `  /  ${m.den_sql}` : ""}` : m.evaluator ? `evaluator: ${m.evaluator}` : `movement of ${m.relative_to}`}</code>
        </Field>
        <Field label="Unit / scaling">
          {m.unit} — {m.scaling}
        </Field>
        <Field label="Aggregation">{m.aggregation}</Field>
        <Field label="Grain">{m.grain}</Field>
        <Field label="Eligible population">{m.eligible_population}</Field>
        <Field label="Exclusions">{m.exclusions}</Field>
        <Field label="Null policy">{m.null_treatment}</Field>
        <Field label="Period semantics">{m.period_semantics}</Field>
        <Field label="Direction">{DIRECTION[m.directionality] ?? m.directionality}</Field>
        <Field label="Thresholds / materiality">
          <code className="font-mono text-[11px]" data-testid="metric-thresholds">
            {JSON.stringify(m.thresholds)}
          </code>
        </Field>
        <Field label="Drill-down dimensions">{m.drilldown_dimensions.join(", ")}</Field>
        <Field label="Scenario interpretation">{m.scenario_interpretation}</Field>
        <Field label="Example rendering">{m.example_rendering}</Field>
        <Field label="Validation rule">{m.validation_rule}</Field>
      </dl>

      {lineage && (
        <section className="grid gap-3 md:grid-cols-2" data-testid="metric-lineage">
          <div className="rounded-lg border border-border bg-surface p-3 text-xs">
            <h3 className="mb-1 font-semibold">Lineage — sources</h3>
            <ul className="space-y-0.5 font-mono">
              {lineage.sources.map((s) => (
                <li key={s.ref}>
                  {s.relation}
                  {s.field ? `.${s.field}` : ""}
                </li>
              ))}
            </ul>
            <h3 className="mb-1 mt-2 font-semibold">Versions</h3>
            <ul>
              {lineage.versions.map((v) => (
                <li key={v.version}>
                  v{v.version} · {v.reason} · {v.content_hash.slice(0, 12)}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-border bg-surface p-3 text-xs" data-testid="metric-used-by">
            <h3 className="mb-1 font-semibold">Used by</h3>
            <div>
              Lenses:{" "}
              {lineage.used_by.lenses.length
                ? lineage.used_by.lenses.map((l) => (
                    <Link key={l.object_id} href={`/lenses/${l.object_id}`} className="mr-2 text-accent underline">
                      {l.title} v{l.version}
                    </Link>
                  ))
                : "none yet"}
            </div>
            <div>Breach rules: {lineage.used_by.breach_rules.length ? lineage.used_by.breach_rules.map((r) => `${r.title} (${r.rule_id})`).join(", ") : "none yet"}</div>
            <div>
              Requires Attention detectors:{" "}
              {lineage.used_by.issue_detectors.length ? (
                <Link href="/" className="text-accent underline">
                  {lineage.used_by.issue_detectors.join(", ")}
                </Link>
              ) : (
                "none"
              )}
            </div>
          </div>
        </section>
      )}
    </article>
  );
}
