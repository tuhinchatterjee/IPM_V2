"use client";

import * as React from "react";
import { RefreshCw } from "lucide-react";

import { Field, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import type { PbSourceReading, PbSourceReadings } from "@/lib/api";
import { orderSources, shortDateTime } from "@/lib/intelligence";

/**
 * Sources, their readings, and re-reading. §19.
 *
 * The idea a user has to take from this screen is that **the upload is not
 * the problem — the reading is**. The bytes are immutable and still on disk,
 * so a reader that has since improved is a reason to read them again, not a
 * reason to ask for the file a second time.
 *
 * So a stale source says which reader read it, which reader is current, and
 * what a re-read would now find, in words rather than a version number alone.
 * "Re-read" is the whole remedy: no upload, no provider call, nothing
 * billable, and no change to any document already written.
 */
export function SourcesTab({
  sources,
  busy,
  error,
  rereadingAll,
  onReread,
  onRereadAll,
}: {
  sources: PbSourceReadings;
  busy: number;
  error: string;
  rereadingAll: boolean;
  onReread: (source: PbSourceReading) => void;
  onRereadAll: () => void;
}) {
  const items = orderSources(sources.items ?? []);

  return (
    <div className="space-y-4" data-testid="playbook-sources-tab">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-3">
        <p className="text-sm text-text-secondary">
          <span className="font-semibold text-text-primary">
            {sources.message}
          </span>
          {sources.sources > 0 && (
            <span className="ml-2 text-[11px] text-text-muted">
              {sources.current} of {sources.sources} read with the current
              reader
            </span>
          )}
        </p>
        {sources.needs_reread > 0 && (
          <div className="ml-auto">
            <SmallButton
              onClick={onRereadAll}
              icon={RefreshCw}
              disabled={rereadingAll}
              testId="playbook-reread-all"
            >
              {rereadingAll ? "Re-reading…" : "Re-read all stale sources"}
            </SmallButton>
          </div>
        )}
      </div>

      {error && (
        <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative"
          data-testid="playbook-sources-error">
          {error}
        </p>
      )}

      {items.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
          Nothing has been uploaded to this Playbook.
        </p>
      ) : (
        <ul className="space-y-3">
          {items.map((source) => (
            <li
              key={source.source_id}
              className={
                "rounded-lg border bg-surface p-4 " +
                (source.stale ? "border-warning/40" : "border-border")
              }
              data-testid="playbook-source-row"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-semibold text-text-primary">
                    {source.filename}
                  </h3>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    {source.format?.toUpperCase()} · revision{" "}
                    {source.revision} ·{" "}
                    {source.chunk_count.toLocaleString()} evidence item
                    {source.chunk_count === 1 ? "" : "s"}
                  </p>
                </div>
                <StatusChip tone={source.stale ? "amber" : "green"}>
                  {source.stale ? "Stale" : "Current"}
                </StatusChip>
              </div>

              <div className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
                <Field label="Parser">{source.parser_version || "—"}</Field>
                <Field label="Current parser">
                  {source.current_parser_version || "—"}
                </Field>
                <Field label="Schema">{source.schema_version || "—"}</Field>
                <Field label="Last read">
                  {source.parsed_at ? shortDateTime(source.parsed_at) : "—"}
                </Field>
              </div>

              {source.stale && (
                <div className="mt-3 rounded-md border border-warning/40 bg-surface-warning p-3">
                  <p className="text-xs font-medium text-text-primary">
                    {source.reason_label}
                  </p>
                  {source.improvements.length > 0 && (
                    <ul className="mt-1.5 space-y-1">
                      {source.improvements.map((line, i) => (
                        <li key={i}
                          className="text-[11px] leading-relaxed text-text-secondary">
                          {line}
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-2 text-[11px] text-text-muted">
                    Re-reading uses the file already stored. No upload, no
                    charge, and no document is rewritten by it.
                  </p>
                </div>
              )}

              <div className="mt-3">
                <SmallButton
                  onClick={() => onReread(source)}
                  icon={RefreshCw}
                  disabled={busy === source.source_id}
                  testId="playbook-reread-source"
                >
                  {busy === source.source_id ? "Re-reading…" : "Re-read"}
                </SmallButton>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
