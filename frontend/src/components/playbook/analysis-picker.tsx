"use client";

import * as React from "react";
import { ArrowLeft, Check, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type PbAnalysisCard, type PbAnalysisPreview } from "@/lib/api";
import { matching, moduleLabel, previewSummary } from "@/lib/playbook";

/**
 * Choosing exported analyses.
 *
 * The behaviour §4 asks for and the reason each part exists:
 *
 * **Only exports.** The list comes from the export library endpoint, which
 * contains nothing that was not explicitly exported. There is no "all analyses"
 * option because there is no such thing here.
 *
 * **Preview without losing your place.** Opening an analysis replaces the list
 * in the same dialog and Back returns to it with the search text, the filters,
 * the scroll position and — most importantly — the selection all intact. A
 * picker that clears the selection when you inspect the third item is one
 * people stop inspecting anything in.
 *
 * **A visible tray.** The count and the chosen titles stay on screen, so
 * multi-selection is something you can see rather than something you have to
 * remember.
 */
export function AnalysisPicker({
  open,
  onClose,
  onAttach,
  alreadyAttached = [],
}: {
  open: boolean;
  onClose: () => void;
  onAttach: (chosen: PbAnalysisCard[]) => void;
  alreadyAttached?: number[];
}) {
  const [query, setQuery] = React.useState("");
  const [module, setModule] = React.useState("");
  const [sort, setSort] = React.useState("recent");
  const [cards, setCards] = React.useState<PbAnalysisCard[] | null>(null);
  const [modules, setModules] = React.useState<string[]>([]);
  const [error, setError] = React.useState("");
  const [selected, setSelected] = React.useState<number[]>([]);
  const [previewing, setPreviewing] = React.useState<PbAnalysisCard | null>(null);
  const [preview, setPreview] = React.useState<PbAnalysisPreview | null>(null);
  const listScroll = React.useRef(0);
  const listRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    let alive = true;
    api
      .playbookExports({
        q: query,
        modules: module ? [module] : undefined,
        sort,
        limit: 100,
      })
      .then((body) => {
        if (!alive) return;
        setCards(body.analyses);
        setModules(body.implemented_modules);
        setError("");
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [open, query, module, sort]);

  // Restore the scroll position when coming back from a preview, so Back
  // returns you to where you were rather than to the top of the library.
  React.useEffect(() => {
    if (!previewing && listRef.current) {
      listRef.current.scrollTop = listScroll.current;
    }
  }, [previewing]);

  const openPreview = (card: PbAnalysisCard) => {
    listScroll.current = listRef.current?.scrollTop ?? 0;
    setPreviewing(card);
    setPreview(null);
    api
      .playbookExportPreview(card.revision_id)
      .then(setPreview)
      .catch((e: Error) => setError(e.message));
  };

  const toggle = (revisionId: number) =>
    setSelected((current) =>
      current.includes(revisionId)
        ? current.filter((id) => id !== revisionId)
        : [...current, revisionId],
    );

  const visible = matching(cards ?? [], "", selected);
  const chosen = (cards ?? []).filter((c) => selected.includes(c.revision_id));

  const footer = (
    <>
      <span className="mr-auto text-xs text-text-muted">
        {selected.length === 0
          ? "Nothing selected yet"
          : `${selected.length} selected`}
      </span>
      <Button variant="ghost" size="sm" onClick={onClose}>
        Cancel
      </Button>
      <Button
        size="sm"
        disabled={selected.length === 0}
        onClick={() => {
          onAttach(chosen);
          setSelected([]);
          setPreviewing(null);
        }}
      >
        Attach {selected.length > 0 ? `${selected.length} ` : ""}analysis
        {selected.length === 1 ? "" : "es"}
      </Button>
    </>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="xl"
      title={previewing ? previewing.title : "Add exported analyses"}
      description={
        previewing
          ? previewSummary(preview ?? ({ source_module: previewing.source_module,
              reporting_period: previewing.reporting_period,
              tables: [] } as unknown as PbAnalysisPreview))
          : "Only analyses that were explicitly exported to Playbook appear here."
      }
      footer={footer}
    >
      {previewing ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPreviewing(null)}
            >
              <ArrowLeft aria-hidden />
              Back to the list
            </Button>
            <Button
              size="sm"
              variant={selected.includes(previewing.revision_id) ? "default" : "outline"}
              onClick={() => toggle(previewing.revision_id)}
            >
              {selected.includes(previewing.revision_id) ? (
                <>
                  <Check aria-hidden /> Selected
                </>
              ) : (
                "Select this analysis"
              )}
            </Button>
          </div>
          {preview ? <PreviewBody preview={preview} /> : <Skeleton className="h-48 w-full" />}
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[16rem] flex-1">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-muted"
                aria-hidden
              />
              <Input
                aria-label="Search exported analyses"
                placeholder="Search by title or finding"
                className="pl-8"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <Select
              aria-label="Filter by module"
              value={module}
              onChange={(e) => setModule(e.target.value)}
            >
              <option value="">Every module</option>
              {modules.map((m) => (
                <option key={m} value={m}>
                  {moduleLabel(m)}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Sort"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="recent">Most recent</option>
              <option value="oldest">Oldest</option>
              <option value="title">Title</option>
              <option value="module">Module</option>
            </Select>
          </div>

          {chosen.length > 0 && (
            <div className="flex flex-wrap gap-1.5 rounded-md border border-border bg-surface-sunken p-2">
              {chosen.map((c) => (
                <button
                  key={c.revision_id}
                  type="button"
                  onClick={() => toggle(c.revision_id)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent-muted px-2.5 py-1 text-xs text-text-primary"
                >
                  <Check className="size-3" aria-hidden />
                  <span className="max-w-[18rem] truncate">{c.title}</span>
                </button>
              ))}
            </div>
          )}

          {error && <p className="text-xs text-negative">{error}</p>}

          <div ref={listRef} className="max-h-[46vh] space-y-2 overflow-y-auto pr-1">
            {cards === null ? (
              <>
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </>
            ) : visible.length === 0 ? (
              <EmptyState
                title="No exported analyses match"
                description="Only analyses explicitly exported to Playbook appear here. Export one from Cockpit, Early Warning, Scorecard Validation or Lenses."
              />
            ) : (
              visible.map((card) => {
                const isSelected = selected.includes(card.revision_id);
                const attached = alreadyAttached.includes(card.revision_id);
                return (
                  <div
                    key={card.revision_id}
                    className="flex items-start gap-3 rounded-lg border border-border p-3"
                  >
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={isSelected}
                      aria-label={`Select ${card.title}`}
                      onChange={() => toggle(card.revision_id)}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-medium text-text-primary">
                          {card.title}
                        </p>
                        <Badge variant="outline">
                          {moduleLabel(card.source_module)}
                        </Badge>
                        {card.reporting_period && (
                          <Badge variant="default">{card.reporting_period}</Badge>
                        )}
                        {card.demo && <Badge variant="warning">Synthetic data</Badge>}
                        {attached && <Badge variant="info">Already attached</Badge>}
                      </div>
                      {card.insight && (
                        <p className="mt-1 text-xs leading-relaxed text-text-muted">
                          {card.insight}
                        </p>
                      )}
                      <p className="mt-1 text-[11px] text-text-muted">
                        Exported {card.exported_at.slice(0, 10)}
                        {card.revisions > 1 && ` · revision ${card.revision} of ${card.revisions}`}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openPreview(card)}
                    >
                      Preview
                    </Button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

/** The whole analysis, not a summary of it. */
function PreviewBody({ preview }: { preview: PbAnalysisPreview }) {
  return (
    <div className="space-y-4 text-sm">
      {preview.newer_revision_available !== null && (
        <p className="rounded-md border border-warning/40 bg-surface-warning p-2 text-xs text-text-primary">
          A newer snapshot of this analysis exists (revision{" "}
          {preview.newer_revision_available}). This one is shown as it was
          exported; choose the newer one explicitly if you want it.
        </p>
      )}
      {preview.question && (
        <div>
          <p className="meta">The question asked</p>
          <p className="mt-1 text-text-primary">{preview.question}</p>
        </div>
      )}
      {preview.narrative && (
        <div>
          <p className="meta">What it found</p>
          <p className="mt-1 whitespace-pre-line leading-relaxed text-text-secondary">
            {preview.narrative}
          </p>
        </div>
      )}
      {preview.tables.map((table) => (
        <div key={table.id}>
          <p className="meta">{table.title || "Result table"}</p>
          <div className="mt-1 overflow-x-auto rounded-md border border-border">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="bg-surface-sunken">
                  {table.columns.map((c) => (
                    <th
                      key={c}
                      scope="col"
                      className="border-b border-border px-3 py-2 text-left font-semibold"
                    >
                      {c}
                      {table.units?.[c] ? (
                        <span className="ml-1 font-normal text-text-muted">
                          ({table.units[c]})
                        </span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td
                        key={j}
                        className="border-b border-border px-3 py-1.5 tabular"
                      >
                        {String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {Object.keys(preview.scope ?? {}).length > 0 && (
        <div>
          <p className="meta">Scope</p>
          <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {Object.entries(preview.scope).map(([k, v]) => (
              <React.Fragment key={k}>
                <dt className="text-text-muted">{k.replace(/_/g, " ")}</dt>
                <dd className="text-text-primary">{String(v)}</dd>
              </React.Fragment>
            ))}
          </dl>
        </div>
      )}
      {(["assumptions", "limitations", "caveats"] as const).map((field) =>
        preview[field]?.length ? (
          <div key={field}>
            <p className="meta capitalize">{field}</p>
            <ul className="mt-1 ml-4 list-disc space-y-0.5 text-xs text-text-secondary">
              {preview[field].map((item, i) => (
                <li key={i}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
      <p className="mono text-[11px] text-text-muted">
        {preview.content_hash.slice(0, 16)} · revision {preview.revision}
      </p>
    </div>
  );
}
