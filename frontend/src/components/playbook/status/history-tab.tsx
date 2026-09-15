"use client";

import * as React from "react";
import {
  FileClock,
  FileText,
  GitBranch,
  Link2,
  ListChecks,
  ScrollText,
  Upload,
} from "lucide-react";

import { StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import type { PbArtifact, PbHistoryFeed } from "@/lib/api";
import { actorLabel, shortDateTime } from "@/lib/intelligence";
import { api } from "@/lib/api";

const ICON: Record<string, typeof FileText> = {
  version: GitBranch,
  source: Upload,
  parse: FileClock,
  binding: Link2,
  section: FileText,
  finding: ScrollText,
  decision: ListChecks,
  action: ListChecks,
};

/**
 * The chronological record. §20.
 *
 * Assembled by the backend from the trails the rows already keep, so it
 * cannot disagree with what it describes. Deleting a finding takes its
 * entries with it, which is the property that makes assembling better than
 * storing a second log beside the first.
 */
export function HistoryTab({
  feed,
  artifacts,
  loading,
  filter,
  onFilter,
  onRestore,
  restoring,
  error,
}: {
  feed: PbHistoryFeed | null;
  artifacts: PbArtifact[];
  loading: boolean;
  filter: string;
  onFilter: (kind: string) => void;
  onRestore: (artifactId: number, version: number) => void;
  restoring: number;
  error: string;
}) {
  return (
    <div className="space-y-5" data-testid="playbook-history-tab">
      <section>
        <h2 className="mb-2 text-sm font-semibold text-text-primary">
          Versions
        </h2>
        {artifacts.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
            Nothing has been generated yet.
          </p>
        ) : (
          <ul className="space-y-3">
            {artifacts.map((artifact) => (
              <li key={artifact.id}
                className="rounded-lg border border-border bg-surface">
                <p className="border-b border-border px-4 py-2 text-xs font-semibold text-text-primary">
                  {artifact.title}
                  <span className="ml-2 font-normal text-text-muted">
                    {artifact.kind}
                  </span>
                </p>
                <ul>
                  {[...artifact.versions].reverse().map((version) => (
                    <li key={version.id}
                      className="flex flex-wrap items-start gap-3 border-b border-border px-4 py-2.5 last:border-b-0"
                      data-testid="playbook-version-row">
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-text-primary">
                          Version {version.version}
                          {artifact.current_version_id === version.id && (
                            <span className="ml-2 text-[10px] uppercase tracking-wide text-accent">
                              current
                            </span>
                          )}
                        </p>
                        {version.change_summary && (
                          <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                            {version.change_summary}
                          </p>
                        )}
                        <p className="mt-0.5 text-[10px] text-text-muted">
                          {shortDateTime(version.created_at)}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {version.files.map((file) => (
                          <a
                            key={file.id}
                            href={`/api/v1${api.playbookDownloadPath(file.id)}`}
                            className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary hover:bg-surface-hover"
                          >
                            {file.format.toUpperCase()}
                          </a>
                        ))}
                        {artifact.current_version_id !== version.id && (
                          <SmallButton
                            onClick={() =>
                              onRestore(artifact.id, version.version)}
                            disabled={restoring === version.version}
                            testId="playbook-history-restore"
                          >
                            {restoring === version.version
                              ? "Restoring…"
                              : "Restore"}
                          </SmallButton>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-text-primary">
            Everything that happened
          </h2>
          {feed && (
            <div className="ml-auto flex flex-wrap gap-1">
              <FilterChip active={filter === ""} onClick={() => onFilter("")}>
                All ({feed.total})
              </FilterChip>
              {feed.kinds
                .filter((k) => k.count > 0)
                .map((kind) => (
                  <FilterChip
                    key={kind.kind}
                    active={filter === kind.kind}
                    onClick={() => onFilter(kind.kind)}
                  >
                    {kind.label} ({kind.count})
                  </FilterChip>
                ))}
            </div>
          )}
        </div>

        {error && (
          <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative">
            {error}
          </p>
        )}

        {loading ? (
          <p className="text-sm text-text-muted">Reading the record…</p>
        ) : !feed || feed.events.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
            Nothing has been recorded against this document yet.
          </p>
        ) : (
          <ol className="space-y-0 rounded-lg border border-border bg-surface">
            {feed.events.map((event, i) => {
              const Icon = ICON[event.kind] ?? FileText;
              return (
                <li key={`${event.at}:${i}`}
                  className="flex gap-3 border-b border-border px-4 py-2.5 last:border-b-0"
                  data-testid="playbook-history-event">
                  <Icon className="mt-0.5 size-3.5 shrink-0 text-text-muted"
                    aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-text-primary">{event.title}</p>
                    {event.detail && (
                      <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                        {event.detail}
                      </p>
                    )}
                    <p className="mt-0.5 text-[10px] text-text-muted">
                      {event.at ? shortDateTime(event.at) : "time not recorded"}
                      {event.actor && ` · ${actorLabel(event.actor)}`}
                    </p>
                  </div>
                  <StatusChip tone="unknown">{event.kind_label}</StatusChip>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid="playbook-history-filter"
      className={
        "rounded-full border px-2 py-0.5 text-[11px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent " +
        (active
          ? "border-accent/40 bg-accent-muted text-accent"
          : "border-border bg-surface text-text-secondary hover:bg-surface-hover")
      }
    >
      {children}
    </button>
  );
}
