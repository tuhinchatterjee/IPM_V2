"use client";

import * as React from "react";
import { use } from "react";
import { Download, FileSpreadsheet, FileText, Presentation } from "lucide-react";

import { AnalysisPicker } from "@/components/playbook/analysis-picker";
import { Composer, type Attachment } from "@/components/playbook/composer";
import { MarkdownView } from "@/components/playbook/markdown-view";
import { BackLink } from "@/components/layout/back-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type PbAnalysisCard,
  type PbArtifact,
  type PbCapabilities,
  type PbWorkspace,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import {
  composerState,
  currentVersion,
  formatBytes,
  moduleLabel,
  nextSteps,
  roleLabel,
  sourceStatus,
} from "@/lib/playbook";

const FORMAT_ICON = {
  docx: FileText,
  pdf: FileText,
  pptx: Presentation,
  xlsx: FileSpreadsheet,
} as const;

/**
 * One playbook.
 *
 * A workspace rather than a document: the conversation, the sources, every
 * artifact version and the decisions all reload from the server, so refreshing
 * loses nothing and "the latest report" means something after a reload.
 */
export default function PlaybookThreadPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const workspaceId = Number(id);
  const [refresh, setRefresh] = React.useState(0);
  const workspace = useAsync<PbWorkspace>(
    () => api.playbookWorkspace(workspaceId),
    [workspaceId, refresh],
  );
  const caps = useAsync<PbCapabilities>(() => api.playbookCapabilities(), []);

  const [prompt, setPrompt] = React.useState("");
  const [attachments, setAttachments] = React.useState<Attachment[]>([]);
  const [chosen, setChosen] = React.useState<PbAnalysisCard[]>([]);
  const [pendingFiles, setPendingFiles] = React.useState<File[]>([]);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const { canGenerate, note } = composerState(caps.data ?? null);
  const data = workspace.data;

  const send = async () => {
    if (!data) return;
    setBusy(true);
    setError("");
    try {
      const sourceIds: number[] = [];
      for (const file of pendingFiles) {
        const source = await api.uploadPlaybookSource(data.id, file);
        sourceIds.push(source.id);
      }
      const report = data.artifacts.find((a) => a.kind === "report");
      await api.sendPlaybookMessage(data.id, {
        text: prompt.trim(),
        source_ids: sourceIds,
        export_revision_ids: chosen.map((c) => c.revision_id),
        artifact_id: report?.id ?? null,
        base_version_id: report?.current_version_id ?? null,
        // Derived from the thread's own length, so pressing send twice or
        // refreshing mid-flight resolves to one job rather than two.
        idempotency_key: `ws${data.id}:turn${data.messages.length}`,
      });
      setPrompt("");
      setAttachments([]);
      setChosen([]);
      setPendingFiles([]);
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (workspace.loading) {
    return <Skeleton className="h-80 w-full" />;
  }
  if (workspace.error || !data) {
    return (
      <p className="text-sm text-negative">
        {workspace.error ?? "This playbook could not be opened."}
      </p>
    );
  }

  const steps = nextSteps(data);

  return (
    <div className="space-y-6">
      <BackLink href="/playbook" label="Playbook" />

      <header className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold text-text-primary">
            {data.title}
          </h1>
          {data.demo && <Badge variant="warning">Demo · synthetic</Badge>}
        </div>
        {data.state_summary && (
          <p className="text-sm text-text-muted">{data.state_summary}</p>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-5">
          {data.messages.map((message) => (
            <article key={message.id} className="space-y-2">
              {message.role === "user" ? (
                <div className="rounded-lg border border-border bg-surface-sunken p-3">
                  <p className="meta mb-1">You</p>
                  <p className="prose-user text-sm">
                    {String(message.content.text ?? "")}
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="meta">
                    Playbook
                    {message.origin === "seed_fixture" && (
                      <span className="ml-2 text-warning">
                        Demo · synthetic, not model-written
                      </span>
                    )}
                    {message.model && message.origin === "assistant_live" && (
                      <span className="ml-2 text-text-muted">
                        {message.model}
                      </span>
                    )}
                  </p>
                  {message.content.failed ? (
                    <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative">
                      {String(message.content.text ?? "")}
                    </p>
                  ) : (
                    <MarkdownView
                      source={String(
                        message.content.markdown ?? message.content.text ?? "",
                      )}
                    />
                  )}
                  {Array.isArray(message.content.notes) &&
                    (message.content.notes as string[]).map((n, i) => (
                      <p
                        key={i}
                        className="rounded-md border border-warning/40 bg-surface-warning p-2 text-xs text-text-primary"
                      >
                        {n}
                      </p>
                    ))}
                  {message.content.evidence_complete === false && (
                    <p className="text-xs text-warning">
                      Some attached evidence was not fully read; conclusions
                      here rest only on what was.
                    </p>
                  )}
                </div>
              )}
            </article>
          ))}

          {steps.length > 0 && (
            <ul className="flex flex-wrap gap-2 pt-2">
              {steps
                .filter((s) => s.prompt)
                .map((step) => (
                  <li key={step.id}>
                    <button
                      type="button"
                      onClick={() => setPrompt(step.prompt)}
                      className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-hover"
                    >
                      {step.label}
                    </button>
                  </li>
                ))}
              {steps.some((s) => s.id === "attach") && (
                <li>
                  <button
                    type="button"
                    onClick={() => setPickerOpen(true)}
                    className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-hover"
                  >
                    Attach another exported analysis
                  </button>
                </li>
              )}
            </ul>
          )}

          <div className="sticky bottom-0 bg-canvas pb-4 pt-2">
            <Composer
              value={prompt}
              onChange={setPrompt}
              onSend={send}
              attachments={attachments}
              onRemoveAttachment={(key) => {
                setAttachments((c) => c.filter((a) => a.key !== key));
                if (key.startsWith("analysis:")) {
                  const rid = Number(key.slice("analysis:".length));
                  setChosen((c) => c.filter((x) => x.revision_id !== rid));
                } else {
                  setPendingFiles((c) =>
                    c.filter(
                      (f) =>
                        `file:${f.name}:${f.size}:${f.lastModified}` !== key,
                    ),
                  );
                }
              }}
              onUploadFiles={(files) => {
                const incoming = Array.from(files);
                setPendingFiles((c) => [...c, ...incoming]);
                setAttachments((c) => [
                  ...c,
                  ...incoming.map((f) => ({
                    key: `file:${f.name}:${f.size}:${f.lastModified}`,
                    kind: "source" as const,
                    label: f.name,
                    sizeBytes: f.size,
                  })),
                ]);
              }}
              onAddAnalyses={() => setPickerOpen(true)}
              busy={busy}
              disabledNote={canGenerate ? "" : note}
              placeholder="Ask for a change, a check, or another format…"
            />
            {error && <p className="mt-2 text-xs text-negative">{error}</p>}
          </div>
        </div>

        <aside className="space-y-5">
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Sources
            </h2>
            {data.sources.length === 0 ? (
              <p className="text-xs text-text-muted">Nothing attached yet.</p>
            ) : (
              <ul className="space-y-2">
                {data.sources.map((source) => {
                  const state = sourceStatus(source);
                  return (
                    <li
                      key={source.id}
                      className="rounded-md border border-border p-2.5"
                    >
                      <p className="truncate text-xs font-medium text-text-primary">
                        {source.filename}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <Badge variant="outline">{roleLabel(source.role)}</Badge>
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
                      </div>
                      {state.detail && (
                        <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
                          {state.detail}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Files and versions
            </h2>
            {data.artifacts.length === 0 ? (
              <p className="text-xs text-text-muted">
                Nothing generated yet.
              </p>
            ) : (
              data.artifacts.map((artifact) => (
                <ArtifactCard key={artifact.id} artifact={artifact} />
              ))
            )}
          </section>
        </aside>
      </div>

      <AnalysisPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onAttach={(cards) => {
          setPickerOpen(false);
          setChosen((c) => [
            ...c,
            ...cards.filter(
              (x) => !c.some((y) => y.revision_id === x.revision_id),
            ),
          ]);
          setAttachments((c) => [
            ...c,
            ...cards
              .filter((x) => !c.some((a) => a.key === `analysis:${x.revision_id}`))
              .map((x) => ({
                key: `analysis:${x.revision_id}`,
                kind: "analysis" as const,
                label: x.title,
                detail: moduleLabel(x.source_module),
              })),
          ]);
        }}
        alreadyAttached={chosen.map((c) => c.revision_id)}
      />
    </div>
  );
}

/** Every version of one document, newest first, with its real files. */
function ArtifactCard({ artifact }: { artifact: PbArtifact }) {
  const current = currentVersion(artifact);
  const [showAll, setShowAll] = React.useState(false);
  const versions = [...artifact.versions].reverse();
  const shown = showAll ? versions : versions.slice(0, 1);

  return (
    <Card className="p-3">
      <p className="text-xs font-semibold text-text-primary">{artifact.title}</p>
      <p className="mt-0.5 text-[11px] text-text-muted">
        {artifact.kind} · {artifact.versions.length} version
        {artifact.versions.length === 1 ? "" : "s"}
      </p>
      <ul className="mt-2 space-y-2">
        {shown.map((version) => (
          <li key={version.id} className="rounded-md bg-surface-sunken p-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-text-primary">
                Version {version.version}
                {current?.id === version.id && " · current"}
              </span>
              <span className="text-[11px] text-text-muted">
                {version.created_at.slice(0, 10)}
              </span>
            </div>
            {version.change_summary && (
              <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
                {version.change_summary}
              </p>
            )}
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {version.files.map((file) => {
                const Icon = FORMAT_ICON[file.format] ?? FileText;
                return (
                  <a
                    key={file.id}
                    href={`/api/v1${api.playbookDownloadPath(file.id)}`}
                    className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-text-secondary hover:bg-surface-hover"
                    data-testid={`playbook-download-${file.format}`}
                  >
                    <Icon className="size-3" aria-hidden />
                    {file.format.toUpperCase()}
                    <Download className="size-3" aria-hidden />
                  </a>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
      {versions.length > 1 && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 w-full"
          onClick={() => setShowAll((s) => !s)}
        >
          {showAll ? "Show current only" : `Show all ${versions.length} versions`}
        </Button>
      )}
    </Card>
  );
}
