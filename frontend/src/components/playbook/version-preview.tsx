"use client";

import * as React from "react";
import { Download } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Dialog } from "@/components/ui/dialog";
import { MarkdownView } from "@/components/playbook/markdown-view";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type PbVersionPreview } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { formatBytes } from "@/lib/playbook";

/**
 * Read one version without downloading it.
 *
 * The text comes from the content that was persisted, not from the generated
 * file and not from what the model first replied — so this shows what grounding
 * actually left in the document. It is not a substitute for the file: the
 * download stays the authoritative artifact, and it is offered here too. This
 * is how somebody reads version 1 without opening a Word document to find out
 * whether they want it back.
 */
export function VersionPreview({
  artifactId,
  version,
  onClose,
}: {
  artifactId: number;
  version: number;
  onClose: () => void;
}) {
  const preview = useAsync<PbVersionPreview>(
    () => api.playbookVersionPreview(artifactId, version),
    [artifactId, version],
  );
  const data = preview.data;

  return (
    <Dialog
      open
      onClose={onClose}
      title={data ? `${data.artifact_title} — version ${version}` : "Version"}
      description={data?.change_summary || undefined}
      size="xl"
    >
      <div className="space-y-4" data-testid="playbook-version-preview">
        {preview.loading && <Skeleton className="h-64 w-full" />}
        {preview.error && (
          <p className="text-sm text-negative">{preview.error}</p>
        )}
        {data && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={data.is_current ? "positive" : "outline"}>
                {data.is_current ? "Current version" : `Version ${data.version}`}
              </Badge>
              {data.created_at && (
                <span className="text-xs text-text-muted">
                  {data.created_at.slice(0, 10)}
                </span>
              )}
              {data.files.map((file) => (
                <a
                  key={file.id}
                  href={`/api/v1${api.playbookDownloadPath(file.id)}`}
                  className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary hover:bg-surface-hover"
                >
                  {file.format.toUpperCase()} · {formatBytes(file.size_bytes)}
                  <Download className="size-3" aria-hidden />
                </a>
              ))}
            </div>

            {data.markdown ? (
              <MarkdownView source={data.markdown} />
            ) : (
              <p className="text-sm text-text-muted">
                This version has no readable content stored.
              </p>
            )}

            {data.sources.length > 0 && (
              <section className="border-t border-border pt-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                  What this rests on
                </h3>
                <ul className="mt-2 space-y-1">
                  {data.sources.map((locator) => (
                    <li key={locator} className="text-[11px] text-text-muted">
                      <code>{locator}</code>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}
