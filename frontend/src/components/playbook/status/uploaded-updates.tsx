"use client";

import * as React from "react";

import { Locator, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import { api, type PbUploadedMetricUpdates } from "@/lib/api";

/**
 * A file was uploaded, and some of it looks like metrics this document
 * already tracks. §24.
 *
 * Shown, never applied. A column header resembling a tracked metric is not
 * evidence that it is that metric — that is the standing rule for every
 * mapping in this product, and an uploaded workbook is exactly where it is
 * most tempting to break it. So each row says what the document currently
 * says, what the file says, and where in the file it came from, and nothing
 * moves until somebody ticks it and confirms.
 */
export function UploadedMetricUpdates({
  workspaceId,
  sourceId,
  onApplied,
}: {
  workspaceId: number;
  sourceId: number;
  onApplied: () => void;
}) {
  const [found, setFound] = React.useState<PbUploadedMetricUpdates | null>(
    null,
  );
  const [chosen, setChosen] = React.useState<number[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState("");
  const [error, setError] = React.useState("");
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    api
      .playbookUploadedMetricUpdates(workspaceId, sourceId)
      .then((result) => {
        if (cancelled) return;
        setFound(result);
        // Pre-ticked only where the value actually differs: a row that
        // changes nothing is noise, and ticking everything by default would
        // make "confirm" a formality.
        setChosen(result.rows.filter((r) => r.changes_value)
          .map((r) => r.binding_id));
      })
      .catch(() => {
        /* a file with nothing to propose is the normal case */
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId, sourceId]);

  if (dismissed || !found || found.detected === 0) return null;

  if (done) {
    return (
      <div className="rounded-lg border border-positive/40 bg-positive-muted p-3"
        data-testid="playbook-uploaded-applied">
        <p className="text-xs text-text-primary">{done}</p>
      </div>
    );
  }

  const apply = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.playbookApplyUploadedMetrics(
        workspaceId, sourceId, { binding_ids: chosen });
      setDone(result.message);
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-warning/40 bg-surface p-3"
      data-testid="playbook-uploaded-updates">
      <p className="text-xs font-semibold text-text-primary">
        {found.message}
      </p>
      <p className="mt-0.5 text-[11px] text-text-muted">
        Suggested from {found.filename}. Nothing is updated until you confirm
        it.
      </p>

      <ul className="mt-2 space-y-1.5">
        {found.rows.map((row) => (
          <li key={row.binding_id}
            className="flex items-start gap-2 rounded border border-border bg-surface-sunken px-2 py-1.5">
            <input
              type="checkbox"
              checked={chosen.includes(row.binding_id)}
              onChange={() =>
                setChosen((c) =>
                  c.includes(row.binding_id)
                    ? c.filter((x) => x !== row.binding_id)
                    : [...c, row.binding_id])}
              aria-label={`Update ${row.document_metric}`}
              data-testid="playbook-uploaded-select"
              className="mt-0.5 size-3.5 accent-[var(--ipm-accent)]"
            />
            <div className="min-w-0 flex-1">
              <p className="text-[11px] text-text-primary">
                {row.document_metric}
              </p>
              <p className="text-[11px] text-text-muted">
                <span className="tabular-nums">
                  {row.current_document_value || "—"}
                </span>
                {" → "}
                <span className="tabular-nums text-text-secondary">
                  {row.uploaded_value}
                </span>
              </p>
              <Locator value={row.source_locator} />
            </div>
            <StatusChip tone="amber">
              {row.changes_value ? "changes" : "same value"}
            </StatusChip>
          </li>
        ))}
      </ul>

      {error && (
        <p className="mt-2 text-[11px] text-negative">{error}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-1.5">
        <SmallButton onClick={apply} disabled={busy || chosen.length === 0}
          testId="playbook-uploaded-confirm">
          {busy ? "Updating…" : `Confirm ${chosen.length} selected`}
        </SmallButton>
        <SmallButton onClick={() => setDismissed(true)} disabled={busy}
          testId="playbook-uploaded-ignore">
          Ignore
        </SmallButton>
      </div>
    </div>
  );
}
