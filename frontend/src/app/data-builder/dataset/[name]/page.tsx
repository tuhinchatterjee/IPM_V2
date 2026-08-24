"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, Loader2, Rocket, ShieldCheck } from "lucide-react";

import { LifecycleBadge } from "@/app/data-builder/page";
import { ResultTable } from "@/components/analytics/primitives";
import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { BackLink } from "@/components/layout/back-link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { ApiError, api, type Lifecycle, type ValidationReport } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/** The lifecycle a dataset walks through, shown as a progression. */
const LIFECYCLE: Lifecycle[] = ["draft", "mapped", "validated", "published"];

export default function DatasetPage({ params }: { params: Promise<{ name: string }> }) {
  const { name } = React.use(params);
  const canEdit = useCanEditData();
  const [tab, setTab] = React.useState("overview");
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [report, setReport] = React.useState<ValidationReport | null>(null);

  const detail = useAsync(() => api.dataset(name), [name]);
  const versions = useAsync(() => api.versions(name), [name]);

  const dataset = detail.data;
  const stageIndex = dataset ? LIFECYCLE.indexOf(dataset.lifecycle) : -1;

  async function act(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await fn();
      if (result && typeof result === "object" && "findings" in result) {
        setReport(result as ValidationReport);
      }
      setMessage(success);
      detail.reload();
      versions.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <BackLink href="/data-builder" label="Data Builder" />

      {detail.loading && <Skeleton className="h-64 w-full" />}
      {detail.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{detail.error}</Card>
      )}

      {dataset && (
        <>
          <PageHeader
            title={dataset.business_name || dataset.name}
            description={dataset.purpose || dataset.grain}
            status="live"
            actions={
              <div className="flex items-center gap-2">
                <LifecycleBadge lifecycle={dataset.lifecycle} />
                {canEdit && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => act(() => api.validate(name), "Validation complete.")}
                    >
                      {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ShieldCheck aria-hidden />}
                      Validate
                    </Button>
                    <Button
                      size="sm"
                      disabled={busy || dataset.lifecycle === "draft"}
                      onClick={() => act(() => api.publish(name), "Published and available to the engine.")}
                    >
                      <Rocket aria-hidden />
                      Publish
                    </Button>
                  </>
                )}
              </div>
            }
          />

          {!canEdit && <ReadOnlyNotice action="validate or publish this dataset" />}

          {/* Lifecycle progression */}
          <div className="flex flex-wrap items-center gap-1.5">
            {LIFECYCLE.map((stage, i) => (
              <React.Fragment key={stage}>
                <span
                  className={cn(
                    "rounded-full px-3 py-1 text-xs font-medium capitalize",
                    i < stageIndex && "bg-positive-muted text-positive",
                    i === stageIndex && "bg-accent text-accent-contrast",
                    i > stageIndex && "border border-border text-text-muted",
                  )}
                >
                  {stage}
                </span>
                {i < LIFECYCLE.length - 1 && <span className="h-px w-4 bg-border" aria-hidden />}
              </React.Fragment>
            ))}
            {dataset.lifecycle === "published" && (
              <span className="ml-2 inline-flex items-center gap-1.5 text-xs font-medium text-positive">
                <CheckCircle2 className="size-3.5" aria-hidden />
                Available to CreditProbe Engine
              </span>
            )}
          </div>

          {message && (
            <Card className="flex items-center gap-2 border-positive/30 bg-positive-muted p-3 text-sm text-positive">
              <CheckCircle2 className="size-4" aria-hidden />
              {message}
            </Card>
          )}
          {error && (
            <Card className="flex items-start gap-2 border-negative/40 p-3 text-sm text-negative">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              {error}
            </Card>
          )}

          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "overview", label: "Overview" },
              { id: "dictionary", label: "Dictionary", count: dataset.fields.length },
              { id: "mappings", label: "Mappings", count: dataset.mappings.length },
              { id: "relationships", label: "Relationships", count: dataset.relationships.length },
              { id: "quality", label: "Quality" },
              { id: "versions", label: "Versions", count: versions.data?.count ?? 0 },
            ]}
          />

          {tab === "overview" && (
            <div className="grid gap-4 md:grid-cols-2">
              <Card className="p-5">
                <h3 className="mb-3 text-sm font-semibold text-text-primary">Definition</h3>
                <dl className="space-y-2 text-sm">
                  <Row label="Governed name" value={dataset.name} mono />
                  <Row label="Domain" value={dataset.domain} />
                  <Row label="Grain" value={dataset.grain || "—"} />
                  <Row label="Primary key" value={dataset.primary_keys.join(", ") || "—"} mono />
                  <Row label="Period field" value={dataset.period_field || "—"} mono />
                  <Row label="Owner" value={dataset.owner || "—"} />
                  <Row label="Source" value={dataset.source_type} />
                </dl>
              </Card>
              <Card className="p-5">
                <h3 className="mb-3 text-sm font-semibold text-text-primary">Latest upload</h3>
                {dataset.latest_upload ? (
                  <dl className="space-y-2 text-sm">
                    <Row label="File" value={dataset.latest_upload.filename} />
                    <Row label="Format" value={dataset.latest_upload.file_format} />
                    <Row label="Rows" value={dataset.latest_upload.row_count.toLocaleString()} />
                    <Row label="Columns" value={String(dataset.latest_upload.column_count)} />
                    <Row
                      label="Checksum"
                      value={dataset.latest_upload.file_sha256.slice(0, 16) + "…"}
                      mono
                    />
                    <Row
                      label="Uploaded"
                      value={dataset.latest_upload.uploaded_at?.slice(0, 19).replace("T", " ") ?? "—"}
                    />
                  </dl>
                ) : (
                  <p className="text-sm text-text-muted">No file uploaded.</p>
                )}
              </Card>
            </div>
          )}

          {tab === "dictionary" && (
            <Card>
              <ResultTable
                rows={dataset.fields.map((f) => ({
                  field: f.name,
                  business_name: f.business_name,
                  type: f.data_type,
                  unit: f.unit ?? "—",
                  sensitivity: f.sensitivity,
                  source_field: f.source_field,
                  definition: f.definition,
                }))}
                emptyMessage="No dictionary entries yet."
                renderCell={(column, value) =>
                  column === "definition" ? (
                    <span className="block max-w-lg text-xs text-text-muted">{String(value)}</span>
                  ) : undefined
                }
              />
            </Card>
          )}

          {tab === "mappings" && (
            <Card>
              <ResultTable
                rows={dataset.mappings.map((m) => ({
                  source_column: m.source_column,
                  governed_field: m.governed_field ?? "—",
                  status: m.status,
                  confidence: m.confidence !== null ? `${(m.confidence * 100).toFixed(0)}%` : "set by hand",
                }))}
                emptyMessage="No mappings yet."
              />
            </Card>
          )}

          {tab === "relationships" && (
            <Card>
              {dataset.relationships.length === 0 ? (
                <EmptyState
                  title="No relationships"
                  description="A relationship records a governed join and is checked at validation."
                  className="border-0"
                />
              ) : (
                <ResultTable
                  rows={dataset.relationships.map((r) => ({
                    from: `${r.from_dataset}.${r.from_field}`,
                    to: `${r.to_dataset}.${r.to_field}`,
                    cardinality: r.cardinality,
                    kind: r.kind,
                  }))}
                />
              )}
            </Card>
          )}

          {tab === "quality" && (
            <Card className="p-5">
              {!report ? (
                <EmptyState
                  icon={ShieldCheck}
                  title="No validation run in this session"
                  description="Press Validate to run every quality check: duplicate and null keys, missing required fields, invalid stages and dates, negative money, allowed values and relationship integrity."
                  className="border-0"
                  action={
                    canEdit ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => act(() => api.validate(name), "Validation complete.")}
                      >
                        Run validation
                      </Button>
                    ) : undefined
                  }
                />
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <Badge variant={report.passed ? "positive" : "negative"}>
                      {report.passed ? "Passed" : `${report.error_count} blocking error(s)`}
                    </Badge>
                    <span className="text-xs text-text-muted">
                      {report.row_count.toLocaleString()} rows · {report.field_count} fields ·{" "}
                      {report.warning_count} warning(s)
                    </span>
                  </div>
                  {report.findings.length === 0 ? (
                    <p className="text-sm text-positive">Every quality check passed.</p>
                  ) : (
                    <ul className="space-y-2">
                      {report.findings.map((f, i) => (
                        <li
                          key={i}
                          className={cn(
                            "rounded-md border px-3 py-2 text-sm",
                            f.severity === "error"
                              ? "border-negative/30 bg-negative-muted text-negative"
                              : "border-warning/30 bg-warning-muted text-warning",
                          )}
                        >
                          <span className="font-medium">{f.rule.replace(/_/g, " ")}</span>
                          <span className="ml-2 text-xs opacity-90">{f.detail}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </Card>
          )}

          {tab === "versions" && (
            <Card>
              {(versions.data?.count ?? 0) === 0 ? (
                <EmptyState
                  title="Not published yet"
                  description="Publishing records an immutable version with its row counts, periods and quality report."
                  className="border-0"
                />
              ) : (
                <ResultTable
                  rows={(versions.data?.versions ?? []).map((v) => ({
                    version: `v${v.version}`,
                    rows: v.row_count,
                    fields: v.field_count,
                    periods: v.periods.join(", ") || "—",
                    quality: v.quality_report?.passed ? "passed" : "with findings",
                    published: v.published_at?.slice(0, 19).replace("T", " ") ?? "—",
                  }))}
                />
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <dt className="shrink-0 text-xs text-text-muted">{label}</dt>
      <dd className={cn("text-right text-text-secondary", mono && "font-mono text-xs")}>{value}</dd>
    </div>
  );
}
