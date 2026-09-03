"use client";

import * as React from "react";

import { Empty, SectionCard } from "@/components/planner/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type PlannerImportPreview } from "@/lib/api";

/**
 * Upload a plan, see exactly what it would do, then apply it.
 *
 * The preview is not a courtesy. A workbook is the one door into this product
 * through which somebody can change four hundred rows in one action, usually
 * from a file a colleague emailed them, and often without having read all of
 * it. Showing the changes and requiring a second, deliberate click is what
 * turns "I uploaded the wrong file" into something noticed rather than
 * something undone.
 *
 * Row-level errors are listed with their sheet, row number and column,
 * because the person fixing them is going back to Excel and needs to know
 * where to click.
 */
export function ImportPanel({
  projectId,
  onApplied,
}: {
  projectId: number;
  onApplied: () => void;
}) {
  const [preview, setPreview] = React.useState<PlannerImportPreview | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [applied, setApplied] = React.useState<string | null>(null);
  const input = React.useRef<HTMLInputElement>(null);

  async function choose(file: File) {
    setBusy(true);
    setError(null);
    setApplied(null);
    setPreview(null);
    try {
      setPreview(await api.planner.upload(projectId, file));
    } catch (e) {
      setError(e instanceof Error ? e.message : "That file could not be read.");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.planner.commitImport(preview.import_id);
      const parts = Object.entries(result.applied)
        .filter(([, n]) => n > 0)
        .map(([name, n]) => `${n} ${name}${n === 1 ? "" : "s"}`);
      setApplied(
        parts.length ? `Applied ${parts.join(", ")}.` : "Nothing needed changing.");
      setPreview(null);
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That could not be applied.");
    } finally {
      setBusy(false);
    }
  }

  const summary = preview?.summary;

  return (
    <SectionCard
      title="Update the plan from a workbook"
      action={
        <a href={api.planner.templateUrl()}
           className="text-xs text-accent hover:underline">
          Download the template
        </a>
      }
    >
      <div className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={input}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void choose(file);
              e.target.value = "";
            }}
          />
          <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => input.current?.click()}>
            {busy ? "Reading…" : "Choose a workbook"}
          </Button>
          <a href={api.planner.exportUrl(projectId)}
             className="text-xs text-accent hover:underline">
            Export this plan first
          </a>
        </div>

        <p className="mt-2 text-xs text-text-muted">
          Deleting a row from the workbook does nothing. A file is often a
          partial extract, so an import only adds and updates — cancel a task
          here, or set its status to CANCELLED in the sheet.
        </p>

        {error && <p className="mt-3 text-sm text-negative">{error}</p>}
        {applied && <p className="mt-3 text-sm text-positive">{applied}</p>}

        {preview && summary && (
          <div className="mt-4 rounded-md border border-border">
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
              <span className="text-sm font-medium text-text-primary">
                {preview.filename}
              </span>
              <Badge variant={summary.creates ? "info" : "default"}>
                {summary.creates} to add
              </Badge>
              <Badge variant={summary.updates ? "warning" : "default"}>
                {summary.updates} to change
              </Badge>
              <Badge variant="default">{summary.unchanged} unchanged</Badge>
              {summary.issues > 0 && (
                <Badge variant="negative">{summary.issues} to fix</Badge>
              )}
              <div className="ml-auto flex gap-2">
                <Button variant="ghost" size="sm"
                        onClick={() => setPreview(null)}>
                  Discard
                </Button>
                <Button size="sm" disabled={!summary.ok || busy}
                        onClick={apply}>
                  {summary.ok
                    ? `Apply ${summary.creates + summary.updates} changes`
                    : "Fix the errors first"}
                </Button>
              </div>
            </div>

            {preview.issues.length > 0 && (
              <div className="border-b border-border">
                <p className="px-3 py-2 text-xs font-medium uppercase tracking-wide text-negative">
                  Rows that need fixing
                </p>
                <ul className="max-h-56 overflow-y-auto">
                  {preview.issues.map((issue, i) => (
                    <li key={i}
                        className="flex gap-3 border-t border-border px-3 py-1.5 text-xs">
                      <span className="w-40 shrink-0 font-mono text-text-muted">
                        {issue.sheet} row {issue.row}
                      </span>
                      <span className="w-32 shrink-0 text-text-secondary">
                        {issue.column}
                      </span>
                      <span className="text-text-primary">{issue.message}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {preview.changes.filter((c) => c.action !== "UNCHANGED").length ===
              0 && preview.issues.length === 0 ? (
              <Empty>
                Nothing in that workbook differs from the plan as it stands.
              </Empty>
            ) : (
              <ul className="max-h-72 overflow-y-auto">
                {preview.changes
                  .filter((c) => c.action !== "UNCHANGED")
                  .map((c, i) => (
                    <li key={i}
                        className="flex gap-3 border-t border-border px-3 py-1.5 text-xs first:border-0">
                      <Badge
                        variant={c.action === "CREATE" ? "info" : "warning"}
                        className="shrink-0"
                      >
                        {c.action === "CREATE" ? "add" : "change"}
                      </Badge>
                      <span className="w-28 shrink-0 font-mono text-text-muted">
                        {c.sheet} {c.row}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-text-primary">
                        {c.label}
                      </span>
                      {c.changed.length > 0 && (
                        <span className="shrink-0 text-text-muted">
                          {c.changed.join(", ")}
                        </span>
                      )}
                    </li>
                  ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </SectionCard>
  );
}
