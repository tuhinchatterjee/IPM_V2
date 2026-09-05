"use client";

import * as React from "react";

import {
  Empty,
  Problem,
  SectionCard,
  formatWhen,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import { fileSize } from "@/lib/playbook-format";
import type { PlaybookPack } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Everything that has happened to this pack, and through which door.
 *
 * `source` is the column that matters. A pack whose history says a figure was
 * changed, without saying whether a person or an assistant changed it, cannot
 * answer the only question an auditor asks. UI, API, AI, AI_CHAT, IMPORT and
 * SYSTEM are distinguished here because the service records them distinctly —
 * and the source is decided by which code path executed, never read from a
 * request body.
 */
export function HistoryPanel({ pack }: { pack: PlaybookPack }) {
  const history = useAsync(
    () => api.playbook.history(pack.id), [pack.id, pack.version]);
  const events = history.data?.events ?? [];

  return (
    <div className="space-y-4">
      <Unavailable state={history} what="this pack's history" />
      <SectionCard
        title="History"
        description="Append-only. Nothing here is edited or removed."
      >
        {history.loading ? (
          <Empty>Loading…</Empty>
        ) : events.length === 0 ? (
          <Empty>Nothing has happened to this pack yet.</Empty>
        ) : (
          <ul className="divide-y divide-border">
            {events.map((event) => (
              <li key={event.id} className="px-4 py-2.5">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm text-text-primary">
                    {event.narrative ||
                      `${event.entity_type} ${event.action}`.replace(/_/g, " ")}
                  </span>
                  <Badge
                    variant={
                      event.source === "AI" || event.source === "AI_CHAT"
                        ? "accent"
                        : event.source === "IMPORT"
                          ? "warning"
                          : "outline"
                    }
                    title={
                      event.source === "AI" || event.source === "AI_CHAT"
                        ? "This change arrived through the assistant."
                        : event.source === "IMPORT"
                          ? "This came out of an uploaded document."
                          : `Recorded through the ${event.source.toLowerCase()}.`
                    }
                  >
                    {event.source.toLowerCase()}
                  </Badge>
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {formatWhen(event.at)}
                  {event.at_version !== null &&
                    ` · pack version ${event.at_version}`}
                  {event.entity_ref && ` · ${event.entity_ref}`}
                </p>
                {Object.keys(event.changes ?? {}).length > 0 && (
                  <Changes changes={event.changes} />
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

/** What actually changed, from and to, rather than "updated". */
function Changes({ changes }: { changes: Record<string, unknown> }) {
  const [open, setOpen] = React.useState(false);
  const entries = Object.entries(changes);
  return (
    <div className="mt-1">
      <button
        type="button"
        className="text-[11px] text-accent hover:underline"
        onClick={() => setOpen((was) => !was)}
      >
        {open ? "Hide" : `${entries.length} field${entries.length === 1 ? "" : "s"} changed`}
      </button>
      {open && (
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
          {entries.map(([field, pair]) => {
            const [before, after] = Array.isArray(pair)
              ? pair
              : [null, pair];
            return (
              <React.Fragment key={field}>
                <dt className="text-text-muted">{field}</dt>
                <dd className="break-words text-text-secondary">
                  <span className="line-through opacity-60">
                    {format(before)}
                  </span>{" "}
                  → {format(after)}
                </dd>
              </React.Fragment>
            );
          })}
        </dl>
      )}
    </div>
  );
}

function format(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value || "—";
  return JSON.stringify(value);
}

/**
 * What has moved since the pack this one follows.
 *
 * Ordered with REDEFINITIONS first, deliberately. A metric whose formula
 * changed between two packs has a movement that is not a movement in the
 * business at all, and a committee shown that at the bottom of a list of real
 * changes will read it as one.
 */
export function ComparisonPanel({ pack }: { pack: PlaybookPack }) {
  const compare = useAsync(
    () => api.playbook.compare(pack.id), [pack.id, pack.version]);
  const data = compare.data;

  return (
    <div className="space-y-4">
      <Unavailable state={compare} what="the comparison with the last pack" />
      <SectionCard
        title="Since last time"
        description={data?.summary || undefined}
      >
        {compare.loading ? (
          <Empty>Loading…</Empty>
        ) : !data || data.previous_pack_id === null ? (
          <Empty>
            {data?.summary ??
              "There is no previous approved pack to compare this one against."}
          </Empty>
        ) : data.differences.length === 0 ? (
          <Empty>Nothing measurable has changed since {data.previous_pack_code}.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
                <th className="px-4 py-2 font-medium">Metric</th>
                <th className="px-4 py-2 font-medium">Then</th>
                <th className="px-4 py-2 font-medium">Now</th>
                <th className="px-4 py-2 font-medium">Change</th>
                <th className="px-4 py-2 font-medium">What kind</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.differences.map((diff) => (
                <tr key={`${diff.metric_id}-${diff.kind}`}>
                  <td className="px-4 py-2.5">
                    <span className="text-text-primary">{diff.name}</span>
                    <p className="font-mono text-[11px] text-text-muted">
                      {diff.metric_id}
                    </p>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-text-secondary">
                    {diff.then_display}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-text-primary">
                    {diff.now_display}
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={
                        diff.better === true
                          ? "text-positive tabular-nums"
                          : diff.better === false
                            ? "text-negative tabular-nums"
                            : "text-text-secondary tabular-nums"
                      }
                    >
                      {diff.change_display}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge
                      variant={diff.kind === "REDEFINED" ? "warning" : "outline"}
                      title={diff.caveat || undefined}
                    >
                      {diff.kind.replace(/_/g, " ").toLowerCase()}
                    </Badge>
                    {diff.caveat && (
                      <p className="mt-0.5 max-w-xs text-[11px] text-warning">
                        {diff.caveat}
                      </p>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
      {(data?.notes.length ?? 0) > 0 && (
        <SectionCard title="What changed about the pack itself">
          <ul className="space-y-1 px-4 py-3">
            {(data?.notes ?? []).map((note, index) => (
              <li key={index} className="text-sm text-text-secondary">
                {note}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  );
}

/**
 * The documents attached to this pack, and what came out of them.
 *
 * An upload is evidence, not truth. Every file kept here is stored under a
 * path derived from its checksum — never its filename, which is what an
 * attacker controls — and everything read out of it is labelled as theirs.
 */
export function SourcesPanel({
  pack,
  onChanged,
}: {
  pack: PlaybookPack;
  onChanged: () => void;
}) {
  const sources = useAsync(
    () => api.playbook.sources(pack.id), [pack.id, pack.version]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [outcome, setOutcome] = React.useState<string>("");
  const input = React.useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setOutcome("");
    try {
      const result = await api.playbook.import(pack.id, file);
      setOutcome(result.summary);
      sources.reload();
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="space-y-4">
      <Unavailable state={sources} what="the documents on this pack" />
      <SectionCard
        title="Documents"
        description="Word, Excel and PowerPoint are read into labelled content. A PDF is kept as supporting evidence."
        action={
          pack.editable && (
            <>
              <input
                ref={input}
                type="file"
                className="hidden"
                accept=".docx,.xlsx,.pptx,.pdf,.csv,.png,.jpg,.jpeg,.msg,.eml"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                }}
              />
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => input.current?.click()}
              >
                {busy ? "Reading…" : "Add a document"}
              </Button>
            </>
          )
        }
      >
        {error != null && (
          <div className="px-4 pt-3">
            <Problem error={error} />
          </div>
        )}
        {outcome && (
          <p className="mx-4 mt-3 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
            {outcome}
          </p>
        )}
        {sources.loading ? (
          <Empty>Loading…</Empty>
        ) : (sources.data?.sources.length ?? 0) === 0 ? (
          <Empty>
            Nothing has been attached to this pack. Everything on it was
            calculated or written here.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {(sources.data?.sources ?? []).map((source) => (
              <li key={source.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">
                    {source.filename || source.label}
                  </span>
                  <Badge variant="outline">
                    {source.import_class.replace(/_/g, " ").toLowerCase()}
                  </Badge>
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {fileSize(source.byte_size)} ·{" "}
                  {formatWhen(source.created_at)} · checksum{" "}
                  <code className="font-mono">
                    {source.checksum.slice(0, 12)}…
                  </code>
                </p>
                {source.warnings.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {source.warnings.map((warning, index) => (
                      <li key={index} className="text-[11px] text-warning">
                        {warning}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}
