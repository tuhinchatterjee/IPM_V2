"use client";

import Link from "next/link";
import * as React from "react";
import { FileText, Plus } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { WorkDocument, WorkDocumentFacets } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Work → Documents. §19.
 *
 * What this replaced
 * -------------------
 * A hard-coded array of three objects in `frontend/src/lib/demo.ts`, rendered
 * as cards. Nothing was stored, nothing could be edited, nothing could be
 * downloaded, and every installation showed the same three titles with the
 * same dates whatever the book underneath had done. The page carried a badge
 * reading "Placeholder by design", which was at least honest.
 *
 * What a documents list has to say
 * ----------------------------------
 * §19 names the columns, and each one is there because a reader's first
 * question about a paper is one of them: is this the current version, what
 * period is it about, which book were its figures computed on, who owns it,
 * and is anybody waiting on a review. A list of titles and dates answers
 * none of those, and the version question is the one that matters most —
 * a paper about a 19,745-facility book sitting beside one about a 59,449
 * facility book, both captioned "August 2026", is the exact confusion §24
 * exists to prevent.
 */

const STATUS_TONE: Record<string, "positive" | "warning" | "default"> = {
  approved: "positive",
  in_review: "warning",
  draft: "default",
  archived: "default",
};

function Filter({ label, value, options, onPick }: {
  label: string; value: string; options: { value: string; label: string }[];
  onPick: (next: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onPick(e.target.value)}
        className="rounded border border-border bg-surface px-1.5 py-1 text-[11px] text-text"
      >
        <option value="">any</option>
        {options.map((one) => (
          <option key={one.value} value={one.value}>{one.label}</option>
        ))}
      </select>
    </label>
  );
}

export default function DocumentsPage() {
  const [rows, setRows] = React.useState<WorkDocument[] | null>(null);
  const [facets, setFacets] = React.useState<WorkDocumentFacets | null>(null);
  const [failed, setFailed] = React.useState("");
  const [product, setProduct] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [kind, setKind] = React.useState("");
  const [owner, setOwner] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [historical, setHistorical] = React.useState(false);
  const [making, setMaking] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    api.documents({ product, status, kind, owner, search,
                    includeHistorical: historical })
      .then((got) => {
        if (!alive) return;
        setRows(got.documents);
        setFacets(got.facets);
      })
      .catch((error: Error) => alive && setFailed(error.message));
    return () => { alive = false; };
  }, [product, status, kind, owner, search, historical]);

  async function startOne() {
    setMaking(true);
    try {
      const made = await api.createDocument({
        title: "Untitled paper",
        body: "# Purpose\n\n",
        kind: "Working paper",
      });
      window.location.href = `/documents/${made.id}`;
    } catch (error) {
      setFailed((error as Error).message);
      setMaking(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Documents"
        description={
          "The papers people write: committee notes, review packs, "
          + "remediation plans and validation write-ups. Each one carries "
          + "the period it is about and the data version its figures were "
          + "computed on, because a paper about last quarter's book and a "
          + "paper about this one read identically without them."
        }
        actions={
          <button
            type="button"
            onClick={startOne}
            disabled={making}
            data-testid="documents-new"
            className="flex items-center gap-1.5 rounded-md border border-border-strong bg-surface-hover px-3 py-1.5 text-xs font-medium text-text disabled:opacity-50"
          >
            <Plus className="size-3.5" aria-hidden />
            {making ? "Creating…" : "New document"}
          </button>
        }
      />

      <Card className="flex flex-wrap items-center gap-3 p-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search titles, summaries and body text"
          data-testid="documents-search"
          className="min-w-52 flex-1 rounded border border-border bg-surface px-2.5 py-1.5 text-xs text-text"
        />
        <Filter label="Product" value={product} onPick={setProduct}
                options={(facets?.products ?? []).map((one) => ({
                  value: one, label: one.replace(/_/g, " ") }))} />
        <Filter label="Type" value={kind} onPick={setKind}
                options={(facets?.kinds ?? []).map((one) => ({
                  value: one, label: one }))} />
        <Filter label="Status" value={status} onPick={setStatus}
                options={(facets?.statuses ?? []).map((one) => ({
                  value: one.status, label: one.label }))} />
        <Filter label="Owner" value={owner} onPick={setOwner}
                options={(facets?.owners ?? []).map((one) => ({
                  value: one, label: one }))} />
        <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
          <input type="checkbox" checked={historical}
                 onChange={(e) => setHistorical(e.target.checked)} />
          Show superseded revisions
        </label>
      </Card>

      {failed && (
        <Card className="p-4">
          <p className="text-sm text-negative">{failed}</p>
        </Card>
      )}

      {rows === null ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : rows.length === 0 ? (
        <Card className="p-6">
          <p className="max-w-2xl text-sm leading-relaxed text-text-muted">
            No document matches these filters. Clear them, or start a new
            paper — a document begins empty and that is fine; it is a working
            draft until somebody sends it for review.
          </p>
        </Card>
      ) : (
        <div className="space-y-2" data-testid="documents-list">
          {rows.map((one) => (
            <Link key={one.id} href={`/documents/${one.id}`}
                  className="block" data-testid={`document-${one.id}`}>
              <Card className={cn(
                "p-4 transition-colors hover:bg-surface-hover",
                !one.is_current && "opacity-75")}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <FileText className="size-4 shrink-0 text-text-muted"
                                aria-hidden />
                      <h3 className="text-sm font-semibold text-text">
                        {one.title}
                      </h3>
                      <Badge variant={STATUS_TONE[one.status] ?? "default"}>
                        {one.status_label}
                      </Badge>
                      {/* Current or superseded, said on the row rather than
                          inferred from a date. */}
                      <Badge variant="outline">{one.badge}</Badge>
                      {one.open_comments > 0 && (
                        <Badge variant="warning">
                          {one.open_comments} open
                        </Badge>
                      )}
                    </div>
                    {one.summary && (
                      <p className="max-w-3xl text-xs leading-relaxed text-text-muted">
                        {one.summary}
                      </p>
                    )}
                    <p className="text-[11px] text-text-muted">
                      {[one.kind, one.product.replace(/_/g, " "),
                        one.as_of && `as of ${one.as_of}`,
                        one.owner, `${one.sections} sections`,
                        `${one.words.toLocaleString()} words`,
                        one.attachment_count
                          && `${one.attachment_count} supporting files`,
                      ].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-[11px] text-text-muted">
                      updated {one.updated_at.slice(0, 10)}
                    </p>
                    {Object.entries(one.data_versions).slice(0, 2).map(
                      ([key, value]) => (
                        <p key={key}
                           className="font-mono text-[10px] text-text-muted">
                          {key} {String(value).slice(0, 14)}
                        </p>
                      ))}
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
