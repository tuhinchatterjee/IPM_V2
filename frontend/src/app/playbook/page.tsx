"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, FileText, Layers } from "lucide-react";

import { AnalysisPicker } from "@/components/playbook/analysis-picker";
import { Composer, type Attachment } from "@/components/playbook/composer";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type PbAnalysisCard, type PbCapabilities, type PbHome } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { composerState, homePrompts, moduleLabel } from "@/lib/playbook";

/**
 * Playbook.
 *
 * The order on this page is fixed by §3 and is rendered in that order:
 * the composer, the quick prompts under it, Recent Playbooks, then Recent
 * Exported Analyses. `lib/playbook.ts` holds the order as data and asserts it,
 * so it cannot drift here without a test failing.
 *
 * This is a different feature from Monitoring Playbooks at /playbooks, which is
 * a standing instruction that runs certified analyses on a trigger. Both exist;
 * neither replaced the other.
 */
export default function PlaybookHomePage() {
  const router = useRouter();
  const home = useAsync<PbHome>(() => api.playbookHome(8), []);
  const caps = useAsync<PbCapabilities>(() => api.playbookCapabilities(), []);

  const [prompt, setPrompt] = React.useState("");
  const [attachments, setAttachments] = React.useState<Attachment[]>([]);
  const [chosen, setChosen] = React.useState<PbAnalysisCard[]>([]);
  const [pickerOpen, setPickerOpen] = React.useState(false);
  const [pendingFiles, setPendingFiles] = React.useState<File[]>([]);
  const [starting, setStarting] = React.useState(false);
  const [error, setError] = React.useState("");

  const { canGenerate, note } = composerState(caps.data ?? null);

  const addFiles = (files: FileList) => {
    const incoming = Array.from(files);
    setPendingFiles((current) => [...current, ...incoming]);
    setAttachments((current) => [
      ...current,
      ...incoming.map((f) => ({
        key: `file:${f.name}:${f.size}:${f.lastModified}`,
        kind: "source" as const,
        label: f.name,
        sizeBytes: f.size,
      })),
    ]);
  };

  const attachAnalyses = (cards: PbAnalysisCard[]) => {
    setPickerOpen(false);
    setChosen((current) => {
      const merged = [...current];
      for (const card of cards) {
        if (!merged.some((c) => c.revision_id === card.revision_id)) {
          merged.push(card);
        }
      }
      return merged;
    });
    setAttachments((current) => [
      ...current,
      ...cards
        .filter((c) => !current.some((a) => a.key === `analysis:${c.revision_id}`))
        .map((c) => ({
          key: `analysis:${c.revision_id}`,
          kind: "analysis" as const,
          label: c.title,
          detail: moduleLabel(c.source_module),
        })),
    ]);
  };

  const removeAttachment = (key: string) => {
    setAttachments((current) => current.filter((a) => a.key !== key));
    if (key.startsWith("analysis:")) {
      const id = Number(key.slice("analysis:".length));
      setChosen((current) => current.filter((c) => c.revision_id !== id));
    } else {
      setPendingFiles((current) =>
        current.filter(
          (f) => `file:${f.name}:${f.size}:${f.lastModified}` !== key,
        ),
      );
    }
  };

  /**
   * Starting a playbook is: make the workspace, put the evidence in it, then
   * send the question. Uploads happen before the send so the request cannot go
   * out referring to a file the backend has not read.
   */
  const start = async () => {
    setStarting(true);
    setError("");
    try {
      const created = await api.createPlaybookWorkspace({
        title: prompt.trim().slice(0, 120) || "New playbook",
      });
      const sourceIds: number[] = [];
      for (const file of pendingFiles) {
        const source = await api.uploadPlaybookSource(created.id, file);
        sourceIds.push(source.id);
      }
      await api.sendPlaybookMessage(created.id, {
        text: prompt.trim(),
        source_ids: sourceIds,
        export_revision_ids: chosen.map((c) => c.revision_id),
        idempotency_key: `start:${created.id}`,
      });
      router.push(`/playbook/${created.id}`);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      setStarting(false);
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader
        title="Playbook"
        description="Create and refine reports, presentations, and other supported files from your documents and exported analyses."
        status="partial"
        phase="Generation needs a configured provider; seeded workspaces and their files are readable without one."
      />

      {/* 1 — the composer */}
      <section aria-label="Ask Playbook" className="space-y-3">
        <Composer
          value={prompt}
          onChange={setPrompt}
          onSend={start}
          attachments={attachments}
          onRemoveAttachment={removeAttachment}
          onUploadFiles={addFiles}
          onAddAnalyses={() => setPickerOpen(true)}
          busy={starting}
          disabledNote={canGenerate ? "" : note}
          autoFocus
        />
        {error && <p className="text-xs text-negative">{error}</p>}

        {/* 2 — the quick prompts, under the composer */}
        <ul className="flex flex-wrap gap-2">
          {homePrompts(5).map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => setPrompt(p.prompt)}
                className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-text-secondary transition-colors hover:bg-surface-hover"
              >
                {p.label}
              </button>
            </li>
          ))}
        </ul>
      </section>

      {/* 3 — recent playbooks */}
      <section aria-labelledby="recent-playbooks" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2
            id="recent-playbooks"
            className="text-xs font-semibold uppercase tracking-wide text-text-muted"
          >
            Recent playbooks
          </h2>
        </div>
        {home.loading ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <Skeleton className="h-28 w-full" />
            <Skeleton className="h-28 w-full" />
          </div>
        ) : home.data?.recent_playbooks.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {home.data.recent_playbooks.map((w) => (
              <Link key={w.id} href={`/playbook/${w.id}`} className="group">
                <Card className="flex h-full flex-col p-4 transition-colors hover:bg-surface-hover">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <FileText className="size-4 shrink-0 text-text-muted" aria-hidden />
                    {w.demo && <Badge variant="warning">Synthetic data</Badge>}
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary">
                    {w.title}
                  </h3>
                  {w.document_family && (
                    <p className="mt-0.5 text-xs text-text-muted">
                      {w.document_family.replace(/_/g, " ")}
                    </p>
                  )}
                  <p className="mt-2 flex-1 text-xs leading-relaxed text-text-muted">
                    {w.state_summary || "No work recorded yet."}
                  </p>
                  <div className="mt-3 flex items-center justify-between border-t border-border pt-2 text-[11px] text-text-muted">
                    <span>{w.last_activity.slice(0, 10)}</span>
                    <span className="inline-flex items-center gap-1 font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
                      Open <ArrowRight className="size-3" aria-hidden />
                    </span>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={FileText}
            title="No playbooks yet"
            description="Attach a document or an exported analysis above and describe what you want."
          />
        )}
      </section>

      {/* 4 — recent exported analyses */}
      <section aria-labelledby="recent-exports" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2
            id="recent-exports"
            className="text-xs font-semibold uppercase tracking-wide text-text-muted"
          >
            Recent exported analyses
          </h2>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/playbook/library">View all</Link>
          </Button>
        </div>
        {home.loading ? (
          <Skeleton className="h-24 w-full" />
        ) : home.data?.recent_exports.length ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {home.data.recent_exports.map((a) => (
              <Card key={a.revision_id} className="flex h-full flex-col p-4">
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline">{moduleLabel(a.source_module)}</Badge>
                  {a.reporting_period && <Badge>{a.reporting_period}</Badge>}
                  {a.demo && <Badge variant="warning">Synthetic data</Badge>}
                </div>
                <h3 className="text-sm font-medium text-text-primary">
                  {a.title}
                </h3>
                <p className="mt-1 flex-1 text-xs leading-relaxed text-text-muted">
                  {a.insight}
                </p>
                <p className="mt-2 border-t border-border pt-2 text-[11px] text-text-muted">
                  Exported {a.exported_at.slice(0, 10)}
                </p>
              </Card>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Layers}
            title="Nothing has been exported to Playbook yet"
            description="Use Export to Playbook on a completed analysis in Cockpit, Early Warning, Scorecard Validation or Lenses."
          />
        )}
      </section>

      <AnalysisPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onAttach={attachAnalyses}
        alreadyAttached={chosen.map((c) => c.revision_id)}
      />
    </div>
  );
}
