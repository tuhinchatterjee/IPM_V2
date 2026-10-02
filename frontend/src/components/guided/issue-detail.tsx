"use client";

/**
 * One Requires Attention issue, opened: the evidence, the drivers, the
 * population and the underlying rows -- every chart a Plotly figure whose
 * click narrows the governed data grid below (server-side), never a picture.
 */

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FlaskConical, Loader2, Save, Search } from "lucide-react";

import { SeverityPill } from "@/components/guided/requires-attention";
import { ChartCard } from "@/components/viz/chart-card";
import { DataGrid } from "@/components/workspace/data-grid";
import { contributions, stageMix, trend } from "@/lib/viz/figures";
import { count, pct, sar } from "@/lib/viz/format";
import { SEMANTIC } from "@/lib/viz/palette";
import {
  investigateIssue,
  readIssue,
  recordStep,
  saveIssueCohort,
  type Issue,
} from "@/lib/workspace/guided";
import type { Filter } from "@/lib/workspace/objects";
import { moneyCol } from "@/lib/viz/format";
import { useSingleFlight } from "@/lib/workspace/single-flight";
import { OriginBackLink } from "@/components/workspace/origin-back";
import { urlWith, withBack } from "@/lib/workspace/nav";

export function IssueDetail({ issueId }: { issueId: string }) {
  const router = useRouter();
  const [issue, setIssue] = React.useState<Issue | null>(null);
  const [error, setError] = React.useState("");
  const params = useSearchParams();
  const driverParam = params.get("driver");
  const stageParam = params.get("stage");
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState("");
  const [savedId, setSavedId] = React.useState("");
  const flight = useSingleFlight();

  React.useEffect(() => {
    readIssue(issueId)
      .then(setIssue)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [issueId]);

  async function investigate(question?: string, suggestionId?: string, kind?: string) {
    if (!issue) return;
    setBusy(true);
    try {
      const opened = await investigateIssue(issue.issue_id);
      if (question) await recordStep(opened.investigation_id, { suggestion_id: suggestionId, kind, question }).catch(() => undefined);
      router.push(`/cockpit/thread/${opened.thread_id}${question ? `?ask=${encodeURIComponent(question)}` : ""}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  if (error) return <p role="alert" className="text-sm text-negative">{error}</p>;
  if (!issue) {
    return (
      <p className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading the evidence…
      </p>
    );
  }
  // The drill lives in the URL (?driver= / ?stage=): a chart click pushes a
  // history entry, so browser Back returns to the unfiltered issue, and a
  // driver link from the Cockpit card opens here already narrowed.
  const drill: Filter[] =
    driverParam && issue.evidence.breakdown.some((d) => String(d.label) === driverParam)
      ? [{ column: issue.evidence.breakdown_dimension, op: "in", values: [driverParam] }]
      : stageParam && ["1", "2", "3"].includes(stageParam)
        ? [{ column: "stage", op: "in", values: [Number(stageParam)] }]
        : [];
  const setDrill = (next: Filter[]) => {
    const f = next[0];
    const href =
      f && f.column === "stage"
        ? urlWith({ stage: String(f.values?.[0] ?? ""), driver: null })
        : urlWith({ driver: f ? String(f.values?.[0] ?? "") : null, stage: null });
    router.push(href, { scroll: false });
  };
  async function whatIf() {
    if (!issue) return;
    const c = await flight.run(() => saveIssueCohort(issue.issue_id));
    if (c) router.push(withBack(`/what-if?cohort=${encodeURIComponent(c.object_id)}&from=issue`));
  }
  const m = issue.materiality;
  const trendFig = trend([{ name: issue.metric_name, points: issue.evidence.series, unit: issue.metric_unit, color: SEMANTIC.pd }]);
  const eclFig = trend([{ name: "Booked ECL", points: issue.evidence.ecl_series, unit: "SAR_mn", color: SEMANTIC.increase }]);
  const driverFig = contributions(
    issue.evidence.breakdown.map((d) => ({ label: d.label, value: d.value, display: d.display })),
    issue.evidence.breakdown[0]?.unit ?? "SAR_mn",
    { dimension: issue.evidence.breakdown_dimension },
  );
  const mixFig = stageMix(issue.evidence.stage_mix);
  const locked = issue.cohort.filters;
  return (
    <div className="space-y-5" data-testid="issue-detail" data-issue-id={issue.issue_id}>
      <OriginBackLink fallback="/" fallbackLabel="Cockpit" testId="issue-detail-back" />
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityPill severity={issue.severity} />
          <span className="text-xs text-text-muted">
            {issue.domain_id} · {issue.release_id} · rule {issue.detection_rule.id} ({issue.detection_rule.version}) ·{" "}
            {issue.evidence.prior_period} → {issue.evidence.period}
          </span>
        </div>
        <h1 className="text-xl font-semibold text-text-primary">{issue.title}</h1>
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-surface p-3 text-sm sm:grid-cols-3 lg:grid-cols-6" data-testid="issue-kpis">
          <Kpi label={issue.metric_name} value={m.level_display} />
          <Kpi label="Movement" value={m.movement_abs === null ? "—" : m.movement_display} />
          <Kpi label={`Affected ${issue.entity_plural}`} value={count(m.affected_entities)} />
          <Kpi label={`Affected ${issue.owner_plural}`} value={count(m.affected_owners)} />
          <Kpi label="Affected EAD" value={sar(m.affected_ead)} />
          <Kpi label="Affected ECL" value={sar(m.affected_ecl)} sub={`${pct(m.share_of_book_ecl)} of book ECL`} />
        </div>
        <div className="rounded-lg border border-border bg-surface-sunken p-3 text-sm">
          <p>
            <span className="font-semibold">Fact.</span> {issue.fact_vs_inference.fact}
          </p>
          {issue.fact_vs_inference.inference && (
            <p className="mt-1">
              <span className="font-semibold">Measured association.</span> {issue.fact_vs_inference.inference}{" "}
              <span className="text-text-muted">({issue.fact_vs_inference.caveat})</span>
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={busy} onClick={() => void investigate()} className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast" data-testid="issue-detail-investigate">
            <Search className="h-4 w-4" /> Investigate why
          </button>
          <button
            type="button"
            disabled={flight.busy || Boolean(savedId)}
            onClick={() =>
              flight
                .run(() => saveIssueCohort(issue.issue_id))
                .then((c) => {
                  if (!c) return;
                  setSavedId(c.object_id);
                  setSaved(`Saved ${count(c.body.counts.entities)} ${issue.entity_plural} as ${c.object_id}`);
                })
                .catch((e: unknown) => setSaved(e instanceof Error ? e.message : String(e)))
            }
            className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm"
            data-testid="issue-detail-save-cohort"
          >
            <Save className="h-4 w-4" /> Save cohort
          </button>
          <button
            type="button"
            disabled={flight.busy}
            onClick={() => void whatIf().catch((e: unknown) => setSaved(e instanceof Error ? e.message : String(e)))}
            className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm"
            data-testid="issue-detail-whatif"
            title="Freeze this exact population and open it in What-If"
          >
            <FlaskConical className="h-4 w-4" /> What-If on this population
          </button>
          {drill.length > 0 && (
            <button type="button" onClick={() => setDrill([])} className="text-xs text-accent underline" data-testid="issue-detail-clear-drill">
              Clear the chart filter
            </button>
          )}
          {saved && <span className="self-center text-xs text-positive">{saved}</span>}
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title={`${issue.metric_name} over time`}
          subtitle={`${issue.segment.value} · metric ${issue.metric_id} · ${issue.release_id}`}
          data={trendFig.data}
          layout={trendFig.layout}
          testId="issue-trend"
          context={{ releaseId: issue.release_id, fingerprint: issue.fingerprint, filters: { predicate: locked }, source: issue.metric_id }}
          table={{ columns: [{ key: "period", label: "Period" }, { key: "value", label: `${issue.metric_name} (raw)`, align: "right" }], rows: issue.evidence.series as unknown as Record<string, unknown>[] }}
        />
        <ChartCard
          title="Booked ECL over time"
          subtitle={`${issue.segment.value} · M001`}
          data={eclFig.data}
          layout={eclFig.layout}
          testId="issue-ecl-trend"
          context={{ releaseId: issue.release_id, fingerprint: issue.fingerprint, source: "M001" }}
          table={{ columns: [{ key: "period", label: "Period" }, moneyCol("value", "Booked ECL", issue.evidence.ecl_series as unknown as Record<string, unknown>[])], rows: issue.evidence.ecl_series as unknown as Record<string, unknown>[] }}
        />
        <ChartCard
          title={`What contributed, by ${issue.evidence.breakdown_dimension.replace(/_/g, " ")}`}
          subtitle="Click a bar to show those rows below. Contributions are associations, not causes."
          data={driverFig.data}
          layout={driverFig.layout}
          testId="issue-drivers"
          onPointClick={(p) => {
            const label = Array.isArray(p.customdata) ? String(p.customdata[0]) : String(p.y ?? "");
            setDrill([{ column: issue.evidence.breakdown_dimension, op: "in", values: [label] }]);
          }}
          table={{
            columns: [{ key: "label", label: issue.evidence.breakdown_dimension }, { key: "value", label: "Value (raw)", align: "right" }, { key: "display", label: "Display" }],
            rows: issue.evidence.breakdown as unknown as Record<string, unknown>[],
            onRowActivate: (row) => setDrill([{ column: issue.evidence.breakdown_dimension, op: "in", values: [String(row.label)] }]),
            activateLabel: "Show the rows for",
          }}
        />
        <ChartCard
          title="Stage mix of the affected population"
          subtitle="EAD by IFRS 9 stage; click a stage to show those rows below"
          data={mixFig.data}
          layout={mixFig.layout}
          height={140}
          testId="issue-stage-mix"
          onPointClick={(p) => {
            const stage = Number(String(p.data?.name ?? "").replace(/\D/g, ""));
            if (stage) setDrill([{ column: "stage", op: "in", values: [stage] }]);
          }}
          table={{
            columns: [{ key: "stage", label: "Stage" }, { key: "n", label: "Exposures", align: "right" }, moneyCol("ead", "EAD", issue.evidence.stage_mix as unknown as Record<string, unknown>[]), moneyCol("ecl", "ECL", issue.evidence.stage_mix as unknown as Record<string, unknown>[])],
            rows: issue.evidence.stage_mix as unknown as Record<string, unknown>[],
            onRowActivate: (row) => setDrill([{ column: "stage", op: "in", values: [Number(row.stage)] }]),
            activateLabel: "Show the rows for stage",
          }}
        />
      </div>

      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="mb-2 text-sm font-semibold">Ask next</h2>
        <ul className="space-y-1.5">
          {issue.next_best_questions.primary.map((s) => (
            <li key={s.suggestion_id} className="text-sm">
              <button type="button" disabled={busy} onClick={() => void investigate(s.exact_request, s.suggestion_id, s.type)} className="text-left text-accent hover:underline" data-testid="issue-detail-nbq">
                {s.text}
              </button>
              <span className="ml-2 text-xs text-text-muted">— {s.rationale}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold">
          Underlying {issue.entity_plural}{" "}
          {drill.length ? <span className="text-xs font-normal text-text-muted">(narrowed by the chart you clicked)</span> : null}
        </h2>
        <DataGrid domain={issue.domain_id} lockedFilters={locked} initialFilters={drill} testId="issue-grid" compact />
      </section>
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-xs text-text-muted">{label}</div>
      <div className="font-semibold tabular text-text-primary">{value}</div>
      {sub && <div className="text-[11px] text-text-muted">{sub}</div>}
    </div>
  );
}
