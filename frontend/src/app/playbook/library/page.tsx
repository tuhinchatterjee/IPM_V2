"use client";

import * as React from "react";
import { Search } from "lucide-react";

import { MarkdownView } from "@/components/playbook/markdown-view";
import { BackLink } from "@/components/layout/back-link";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty";
import { Input, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type PbAnalysisPreview, type PbLibrary } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { moduleLabel } from "@/lib/playbook";

/**
 * The whole exported-analysis library.
 *
 * Everything here got here by somebody pressing Export to Playbook. There is no
 * view of "all analyses" because being saved in a module and being exported to
 * Playbook are different states, and only the second belongs in evidence.
 */
export default function PlaybookLibraryPage() {
  const [query, setQuery] = React.useState("");
  const [module, setModule] = React.useState("");
  const [sort, setSort] = React.useState("recent");
  const [previewId, setPreviewId] = React.useState<number | null>(null);
  const [preview, setPreview] = React.useState<PbAnalysisPreview | null>(null);

  const library = useAsync<PbLibrary>(
    () =>
      api.playbookExports({
        q: query,
        modules: module ? [module] : undefined,
        sort,
        limit: 100,
      }),
    [query, module, sort],
  );

  React.useEffect(() => {
    if (previewId === null) return;
    let alive = true;
    api.playbookExportPreview(previewId).then((p) => alive && setPreview(p));
    return () => {
      alive = false;
    };
  }, [previewId]);

  const closePreview = () => {
    setPreviewId(null);
    setPreview(null);
  };

  const counts = library.data?.counts ?? {};

  return (
    <div className="space-y-6">
      <BackLink href="/playbook" label="Playbook" />
      <PageHeader
        title="Exported analyses"
        description="Analyses explicitly exported to Playbook, with everything they found. Nothing appears here until somebody exports it."
        status="live"
        phase=""
      />

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[18rem] flex-1">
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
          {(library.data?.implemented_modules ?? []).map((m) => (
            <option key={m} value={m}>
              {moduleLabel(m)} {counts[m] ? `(${counts[m]})` : ""}
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

      {library.loading ? (
        <Skeleton className="h-40 w-full" />
      ) : (library.data?.analyses.length ?? 0) === 0 ? (
        <EmptyState
          title="No exported analyses match"
          description="Use Export to Playbook on a completed analysis in Cockpit, Early Warning, Scorecard Validation or Lenses."
        />
      ) : (
        <>
          <p className="text-xs text-text-muted">
            {library.data?.total} exported analys
            {library.data?.total === 1 ? "is" : "es"}
          </p>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {library.data?.analyses.map((a) => (
              <Card key={a.revision_id} className="flex h-full flex-col p-4">
                <div className="mb-2 flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline">{moduleLabel(a.source_module)}</Badge>
                  {a.reporting_period && <Badge>{a.reporting_period}</Badge>}
                  {a.demo && <Badge variant="warning">Demo</Badge>}
                </div>
                <h3 className="text-sm font-medium text-text-primary">
                  {a.title}
                </h3>
                <p className="mt-1 flex-1 text-xs leading-relaxed text-text-muted">
                  {a.insight}
                </p>
                <div className="mt-3 flex items-center justify-between border-t border-border pt-2">
                  <span className="text-[11px] text-text-muted">
                    {a.exported_at.slice(0, 10)}
                    {a.revisions > 1 && ` · rev ${a.revision}/${a.revisions}`}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setPreview(null);
                      setPreviewId(a.revision_id);
                    }}
                  >
                    Preview
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}

      <Dialog
        open={previewId !== null}
        onClose={closePreview}
        size="xl"
        title={preview?.title ?? "Exported analysis"}
        description={
          preview
            ? `${moduleLabel(preview.source_module)}${
                preview.reporting_period ? ` · ${preview.reporting_period}` : ""
              }`
            : ""
        }
      >
        {preview ? (
          <div className="space-y-4 text-sm">
            {preview.question && (
              <div>
                <p className="meta">The question asked</p>
                <p className="mt-1">{preview.question}</p>
              </div>
            )}
            <MarkdownView source={preview.narrative} />
            {preview.tables.map((t) => (
              <div key={t.id} className="overflow-x-auto rounded-md border border-border">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="bg-surface-sunken">
                      {t.columns.map((c) => (
                        <th key={c} scope="col" className="border-b border-border px-3 py-2 text-left font-semibold">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {t.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((cell, j) => (
                          <td key={j} className="border-b border-border px-3 py-1.5 tabular">
                            {String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        ) : (
          <Skeleton className="h-40 w-full" />
        )}
      </Dialog>
    </div>
  );
}
