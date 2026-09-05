"use client";

import * as React from "react";
import { AlertTriangle, CheckCircle2, Download, Loader2, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, type DatasetCoverage, type PeriodRelease } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * One reporting period at a time.
 *
 * Publishing a dataset used to mean rewriting all of it. That is right when a
 * book is loaded in full and catastrophic when a steward sends the next
 * quarter, so this screen never offers to republish the dataset: it offers to
 * add a period, or to replace one, and says which one it is about to touch.
 *
 * Nothing here publishes as a side effect of arriving. A file is staged and
 * checked; a person reads the findings, locks it, and publishes it. Each of
 * those is a separate press by somebody with the right to make it, and the
 * screen shows which press is available rather than greying out the rest.
 */
export function PeriodReleases({
  dataset,
  coverage,
  canEdit,
  onPublished,
}: {
  dataset: string;
  coverage: DatasetCoverage | undefined;
  canEdit: boolean;
  onPublished: () => void;
}) {
  const history = useAsync(() => api.periodHistory(dataset), [dataset]);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  async function act(fn: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setMessage(success);
      history.reload();
      onPublished();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  const releases = history.data?.releases ?? [];
  const periods = coverage?.periods ?? [];

  return (
    <div className="space-y-4">
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

      <PublishedPeriods dataset={dataset} coverage={coverage} />

      {canEdit && (
        <PeriodUpload dataset={dataset} periods={periods} busy={busy} onUpload={act} />
      )}

      <Card>
        <div className="border-b border-border px-5 py-3">
          <h3 className="text-sm font-semibold text-text-primary">Release history</h3>
          <p className="mt-0.5 text-xs text-text-muted">
            Every release of every period, newest first. A superseded release is
            kept, not deleted — an analysis that cited it can still say so.
          </p>
        </div>
        {history.loading && <Skeleton className="m-5 h-32" />}
        {!history.loading && releases.length === 0 && (
          <EmptyState
            title="No period has been uploaded"
            description="The periods this dataset holds were loaded with it. A period uploaded here is staged, checked and published on its own."
            className="border-0"
          />
        )}
        {releases.length > 0 && (
          <ul className="divide-y divide-border">
            {releases.map((r) => (
              <ReleaseRow
                key={r.id}
                release={r}
                canEdit={canEdit}
                busy={busy}
                onAct={act}
              />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/** The periods that are live, each with the two downloads. */
function PublishedPeriods({
  dataset,
  coverage,
}: {
  dataset: string;
  coverage: DatasetCoverage | undefined;
}) {
  if (!coverage || coverage.periods.length === 0) return null;
  return (
    <Card className="p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-text-primary">Periods in service</h3>
        <span className="text-xs text-text-muted">{coverage.coverage}</span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {[...coverage.periods].reverse().map((period) => (
          <li
            key={period}
            className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2"
          >
            <span className="text-sm text-text-secondary">{period}</span>
            <span className="flex items-center gap-1">
              <Button variant="ghost" size="sm" asChild title={`CSV of ${period}`}>
                <a href={api.datasetExportUrl(dataset, { period })} download>
                  <Download aria-hidden />
                  CSV
                </a>
              </Button>
              <Button variant="ghost" size="sm" asChild title={`Excel workbook of ${period}`}>
                <a href={api.datasetWorkbookUrl(dataset, { period })} download>
                  <Download aria-hidden />
                  Excel
                </a>
              </Button>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/**
 * Add a period, or replace one.
 *
 * The mode is a choice the person makes, not something inferred from whether
 * the period happens to exist: inferring it means a typo in the period label
 * silently creates a sixteenth quarter instead of replacing the fifteenth.
 */
function PeriodUpload({
  dataset,
  periods,
  busy,
  onUpload,
}: {
  dataset: string;
  periods: string[];
  busy: boolean;
  onUpload: (fn: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const [mode, setMode] = React.useState<"NEW_PERIOD" | "REPLACE_PERIOD">("NEW_PERIOD");
  const [period, setPeriod] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);

  const ready = Boolean(file) && period.trim().length > 0;

  return (
    <Card className="p-5">
      <h3 className="text-sm font-semibold text-text-primary">Upload a period</h3>
      <p className="mt-0.5 text-xs text-text-muted">
        The file is read, staged and checked against this dataset&apos;s contract.
        It is not published — you decide that afterwards, once you have read what
        the checks found.
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block text-xs text-text-muted">What this is</span>
          <select
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
            value={mode}
            onChange={(e) => setMode(e.target.value as "NEW_PERIOD" | "REPLACE_PERIOD")}
          >
            <option value="NEW_PERIOD">A new period</option>
            <option value="REPLACE_PERIOD">A correction to a period already in service</option>
          </select>
        </label>

        <label className="text-sm">
          <span className="mb-1 block text-xs text-text-muted">Period</span>
          {mode === "REPLACE_PERIOD" ? (
            <select
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            >
              <option value="">Choose the period to replace…</option>
              {[...periods].reverse().map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm"
              placeholder="Q3 2026"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            />
          )}
        </label>

        <label className="text-sm">
          <span className="mb-1 block text-xs text-text-muted">File</span>
          <input
            type="file"
            accept=".csv,.xlsx,.xls,.parquet"
            className="w-full text-xs text-text-secondary"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>
      </div>

      <div className="mt-4">
        <Button
          size="sm"
          disabled={!ready || busy}
          onClick={() =>
            onUpload(
              () => api.uploadPeriod(dataset, file!, period.trim(), mode),
              `${period.trim()} is staged and checked. Nothing is live yet.`,
            )
          }
        >
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Upload aria-hidden />}
          Stage and check
        </Button>
      </div>
    </Card>
  );
}

/** How a state reads, and what colour it earns. */
const TONE: Record<string, string> = {
  PUBLISHED: "border-positive/30 bg-positive-muted text-positive",
  VALIDATED: "border-accent/30 text-accent",
  LOCKED: "border-accent/30 text-accent",
  REVIEW: "border-warning/30 bg-warning-muted text-warning",
  FAILED: "border-negative/30 bg-negative-muted text-negative",
  DISCARDED: "border-border text-text-muted",
  SUPERSEDED: "border-border text-text-muted",
};

function ReleaseRow({
  release,
  canEdit,
  busy,
  onAct,
}: {
  release: PeriodRelease;
  canEdit: boolean;
  busy: boolean;
  onAct: (fn: () => Promise<unknown>, success: string) => Promise<void>;
}) {
  const findings = release.validation.findings ?? [];
  const errors = findings.filter((f) => f.severity === "error");
  const rest = findings.filter((f) => f.severity !== "error");

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium text-text-primary">{release.period}</span>
        <span className="font-mono text-xs text-text-muted">v{release.version}</span>
        <Badge
          className={cn("border", TONE[release.state] ?? "border-border text-text-secondary")}
        >
          {release.state.toLowerCase()}
        </Badge>
        <span className="text-xs text-text-muted">
          {release.rows.toLocaleString()} rows · {release.fields} fields ·{" "}
          {release.mode === "REPLACE_PERIOD" ? "a correction" : "a new period"}
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          {canEdit && release.state === "VALIDATED" && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() =>
                onAct(
                  () => api.periodAction(release.id, "review"),
                  `${release.period} v${release.version} is waiting to be read.`,
                )
              }
            >
              Send to review
            </Button>
          )}
          {canEdit && release.state === "REVIEW" && (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() =>
                onAct(
                  () => api.periodAction(release.id, "lock"),
                  `${release.period} v${release.version} is locked and may be published.`,
                )
              }
            >
              I have read it — lock
            </Button>
          )}
          {canEdit && release.state === "LOCKED" && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() =>
                onAct(
                  () => api.publishPeriod(release.id),
                  `${release.period} v${release.version} is published and available to the engine.`,
                )
              }
            >
              Publish this period
            </Button>
          )}
          {canEdit &&
            ["UPLOADED", "VALIDATED", "REVIEW", "FAILED"].includes(release.state) && (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() =>
                  onAct(
                    () => api.periodAction(release.id, "discard"),
                    `${release.period} v${release.version} was thrown away.`,
                  )
                }
              >
                Discard
              </Button>
            )}
        </span>
      </div>

      <p className="mt-1 text-xs text-text-muted">
        {release.source_filename} ·{" "}
        {(release.published_at ?? release.reviewed_at ?? release.uploaded_at ?? "")
          .slice(0, 19)
          .replace("T", " ") || "—"}
        {release.superseded_by !== null && ` · superseded by release ${release.superseded_by}`}
      </p>

      {findings.length > 0 && (
        <ul className="mt-2 space-y-1">
          {[...errors, ...rest].map((f, i) => (
            <li
              key={i}
              className={cn(
                "rounded-md border px-3 py-1.5 text-xs",
                f.severity === "error"
                  ? "border-negative/30 bg-negative-muted text-negative"
                  : f.severity === "warning"
                    ? "border-warning/30 bg-warning-muted text-warning"
                    : "border-border text-text-muted",
              )}
            >
              <span className="font-medium">{f.rule.replace(/_/g, " ")}</span>
              <span className="ml-2 opacity-90">{f.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
