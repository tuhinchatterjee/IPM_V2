"use client";

/**
 * The Model Log: which version is running, what ran before it, and how they
 * compare when both are measured on the same book.
 *
 * The numbers here are not remembered from an old run. The retired version is
 * rescored on today's panel, over the same facilities, months and outcomes as
 * the active one, so the comparison is like for like — the versions differ in
 * how the four layers are weighted together, not in what the layers are.
 *
 * Where a statistic cannot honestly be produced, this says so rather than
 * filling the box. The hard-trigger cohort reports operational capture rather
 * than discrimination, and calibration is declared not applicable, because the
 * Early Warning Score ranks and explains and does not claim to be a
 * probability.
 */

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Download, GitBranch, Network } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type EwsModelLog } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { isRetail } from "@/lib/profile";

function show(value: unknown, places = 4): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(places) : String(value);
}

function pct(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : String(value);
}

export default function EwsModelLogPage() {
  const load = React.useCallback(() => api.ewsModelLog(), []);
  const { data, loading, error } = useAsync<EwsModelLog>(load, [load]);

  if (!isRetail()) {
    return (
      <div className="space-y-6">
        <PageHeader title="Early Warning Score model log"
                    description="Version history for the retail Early Warning Score." />
        <EmptyState title="Not a retail installation" description="" />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="ews-model-log-page">
      <PageHeader
        eyebrow="Govern"
        title="Early Warning Score — model log"
        description="Every version of the model, when it ran, what changed, and how it performed."
        status="live"
        phase="Governed model on synthetic demonstration data"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning/model/tree">
                <GitBranch aria-hidden /> Model Tree
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning/model">
                <Network aria-hidden /> View Model
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning" data-testid="ews-model-log-back">
                <ArrowLeft aria-hidden /> Back to the workspace
              </Link>
            </Button>
          </div>
        }
      />

      {loading && !data ? <Skeleton className="h-96 w-full" /> : null}
      {error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {String(error)}
        </Card>
      ) : null}

      {data ? (
        <>
          <Card className="p-4" data-testid="ews-model-log-target">
            <p className="text-sm font-semibold text-text-primary">
              What every figure below is measured against
            </p>
            <p className="mt-1 text-[12px] text-text-secondary">
              {data.target_definition}
            </p>
            <p className="mt-1.5 text-[12px] text-text-secondary">
              {data.calibration}
            </p>
            <p className="mt-1.5 text-[11px] text-text-muted">
              Active version {data.active_version} ·{" "}
              {data.months.length} monthly snapshots ·{" "}
              outcome horizon {data.horizon_months} months · data manifest{" "}
              <span className="font-mono">{data.data_manifest_hash}</span>
            </p>
          </Card>

          <Card className="overflow-x-auto p-0" data-testid="ews-version-table">
            <table className="w-full min-w-[1100px] text-[12px]">
              <thead className="border-b border-border bg-surface-muted/40">
                <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  {["Version", "Status", "Effective", "Development",
                    "Validation", "Cutoff", "KS", "Gini", "AUC", "Precision",
                    "Recall", "F1", "PSI", "Lead time", "Alert rate",
                    "Report"].map((one) => (
                    <th key={one} className="px-2 py-2 text-left font-semibold">
                      {one}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.versions.map((one) => {
                  const p = one.performance ?? {};
                  return (
                    <tr key={one.model_version}
                        className="border-b border-border/60 last:border-0"
                        data-testid={`ews-version-${one.model_version}`}>
                      <td className="px-2 py-2">
                        <Link href={`/early-warning/model-log/${one.model_version}`}
                              className="font-medium text-accent hover:underline"
                              data-testid={`ews-version-open-${one.model_version}`}>
                          {one.model_version}
                        </Link>
                        <span className="ml-1 block font-mono text-[9px] text-text-muted">
                          {one.version_id}
                        </span>
                      </td>
                      <td className="px-2 py-2">
                        <Badge variant={one.status === "active"
                                 ? "default" : "outline"}>
                          {one.status}
                        </Badge>
                      </td>
                      <td className="px-2 py-2 text-text-secondary">
                        {one.effective_from} → {one.effective_to || "current"}
                      </td>
                      <td className="px-2 py-2 text-text-secondary">
                        {one.development_sample}
                      </td>
                      <td className="px-2 py-2 text-text-secondary">
                        {one.validation_sample}
                      </td>
                      <td className="px-2 py-2 tabular-nums">
                        {one.warning_threshold}
                      </td>
                      <td className="px-2 py-2 tabular-nums">{show(p.ks)}</td>
                      <td className="px-2 py-2 tabular-nums">{show(p.gini)}</td>
                      <td className="px-2 py-2 tabular-nums">{show(p.auc)}</td>
                      <td className="px-2 py-2 tabular-nums">
                        {pct(p.precision)}
                      </td>
                      <td className="px-2 py-2 tabular-nums">{pct(p.recall)}</td>
                      <td className="px-2 py-2 tabular-nums">{show(p.f1)}</td>
                      <td className="px-2 py-2 tabular-nums">{show(p.psi)}</td>
                      <td className="px-2 py-2 tabular-nums">
                        {p.lead_time_months === null
                         || p.lead_time_months === undefined
                          ? "—" : `${p.lead_time_months} mo`}
                      </td>
                      <td className="px-2 py-2 tabular-nums">
                        {pct(p.alert_rate)}
                      </td>
                      <td className="px-2 py-2">
                        <a href={api.ewsModelReportUrl(one.model_version)}
                           className="inline-flex items-center gap-1 text-accent
                                      hover:underline"
                           data-testid={`ews-report-${one.model_version}`}>
                          <Download className="size-3" aria-hidden />
                          .docx
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>

          <div className="grid gap-3 lg:grid-cols-2">
            {data.versions.map((one) => (
              <Card key={one.model_version} className="p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-semibold text-text-primary">
                    Version {one.model_version}
                  </p>
                  <Badge variant={one.status === "active"
                           ? "default" : "outline"}>
                    {one.status}
                  </Badge>
                  <span className="font-mono text-[10px] text-text-muted">
                    config {one.config_hash}
                  </span>
                </div>
                <p className="mt-1.5 text-[12px] leading-relaxed text-text-secondary">
                  {one.change_summary}
                </p>
                <p className="mt-1.5 text-[11px] text-text-muted">
                  Taxonomy {one.taxonomy_version} · rulebook{" "}
                  {one.rulebook_version} · scale {one.score_scale}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" asChild>
                    <Link href={`/early-warning/model-log/${one.model_version}`}>
                      Open the full record
                    </Link>
                  </Button>
                </div>
              </Card>
            ))}
          </div>

          <Card className="p-4" data-testid="ews-model-log-cohorts">
            <p className="text-sm font-semibold text-text-primary">
              Performance is measured by the state a facility was in when it
              was scored
            </p>
            <ul className="mt-2 space-y-1.5">
              {data.cohorts.map((one) => (
                <li key={one.key} className="text-[12px] text-text-secondary">
                  <span className="font-medium text-text-primary">
                    {one.name}
                  </span>{" "}
                  — {one.meaning}
                  {one.caveat ? (
                    <span className="block text-[11px] italic text-text-muted">
                      {one.caveat}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>

          <p className="text-[11px] text-text-muted">{data.disclaimer}</p>
        </>
      ) : null}
    </div>
  );
}
