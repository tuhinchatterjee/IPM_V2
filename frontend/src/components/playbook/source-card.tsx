"use client";

import * as React from "react";
import { RotateCcw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { api, type PbSource } from "@/lib/api";
import { ROLE_LABEL, formatBytes, roleLabel, sourceStatus } from "@/lib/playbook";

/**
 * One uploaded file: what it is, what was read of it, and what was not.
 *
 * The role is editable because the parser guesses at it, and a methodology
 * document read as "supporting" is evidence the author will weigh wrongly. The
 * correction is recorded as a person's decision rather than another inference,
 * which is why the card says so once a person has made one.
 *
 * A failed parse offers a retry rather than asking for the file again: the
 * bytes are already stored, so uploading it a second time would prove nothing
 * the first upload did not.
 */
export function SourceCard({
  source,
  onChanged,
}: {
  source: PbSource;
  onChanged: () => void;
}) {
  const state = sourceStatus(source);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await work();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="rounded-md border border-border p-2.5">
      <p className="truncate text-xs font-medium text-text-primary">
        {source.filename}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <label className="sr-only" htmlFor={`role-${source.id}`}>
          What kind of document {source.filename} is
        </label>
        <select
          id={`role-${source.id}`}
          value={source.role}
          disabled={busy}
          onChange={(e) =>
            run(() =>
              api.correctPlaybookSource(source.id, {
                source_role: e.target.value,
              }),
            )
          }
          className="rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary disabled:opacity-50"
          data-testid={`playbook-source-role-${source.id}`}
        >
          {Object.keys(ROLE_LABEL).map((role) => (
            <option key={role} value={role}>
              {roleLabel(role)}
            </option>
          ))}
        </select>
        <Badge
          variant={
            state.tone === "positive"
              ? "positive"
              : state.tone === "warning"
                ? "warning"
                : state.tone === "negative"
                  ? "negative"
                  : "default"
          }
        >
          {state.label}
        </Badge>
        <span className="text-[11px] text-text-muted">
          {formatBytes(source.size_bytes)}
        </span>
        {source.reporting_period && (
          <Badge variant="outline">{source.reporting_period}</Badge>
        )}
      </div>
      {source.role_set_by === "user" && (
        <p className="mt-1 text-[11px] text-text-muted">
          You set this, so it will not be re-inferred.
        </p>
      )}
      {state.detail && (
        <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
          {state.detail}
        </p>
      )}
      {(source.status === "failed" || source.status === "partial") && (
        <button
          type="button"
          disabled={busy}
          onClick={() => run(() => api.retryPlaybookSource(source.id))}
          className="mt-1.5 inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary hover:bg-surface-hover disabled:opacity-50"
          data-testid={`playbook-source-retry-${source.id}`}
        >
          <RotateCcw className="size-3" aria-hidden />
          {busy ? "Reading again…" : "Read it again"}
        </button>
      )}
      {error && <p className="mt-1 text-[11px] text-negative">{error}</p>}
    </li>
  );
}
