"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import { ArrowLeft, Download, FileText, Paperclip } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { WorkDocument, WorkDocumentBody } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * One working paper, open for editing. §19.
 *
 * The layout §19 asks for, and why each side holds what it does
 * ---------------------------------------------------------------
 * Title, version, status and owner above; the section outline on the left;
 * the editable document in the middle; supporting evidence and review
 * controls on the right. That is not decoration — it is the shape of the
 * task. A reviewer navigates by section, reads in the middle, and checks
 * the evidence without losing their place. Putting the evidence below the
 * document means it is read after the conclusions rather than beside them.
 *
 * Autosave, and why it does not fight a manual save
 * --------------------------------------------------
 * Both write through the same call. Autosave is debounced and marks the
 * document dirty until the response lands; the manual button is the same
 * request without the wait, for somebody who wants to know it is safe
 * before they close the tab. There is no separate draft buffer, because two
 * places to hold unsaved text is two places for it to be lost from.
 *
 * What the screen refuses
 * ------------------------
 * An approved revision is not editable here, and the editor says so rather
 * than accepting keystrokes that will be rejected. The route to carrying on
 * is Create revision, which is offered in the same place the disabled
 * editor explains itself.
 */

const STATUS_TONE: Record<string, "positive" | "warning" | "default"> = {
  approved: "positive", in_review: "warning", draft: "default",
  archived: "default",
};

const SAVE_AFTER_MS = 1200;

function Rendered({ body }: { body: string }) {
  /** A light Markdown read-view: headings, lists, tables and paragraphs. */
  const blocks = React.useMemo(() => {
    const out: React.ReactNode[] = [];
    let table: string[][] = [];
    let list: string[] = [];
    const flushTable = (key: number) => {
      if (!table.length) return;
      const [head, ...rest] = table;
      out.push(
        <div key={`t${key}`} className="my-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                {head.map((c, i) => (
                  <th key={i} className="px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wider text-text-muted">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rest.map((row, i) => (
                <tr key={i} className="border-b border-border/50 last:border-0">
                  {row.map((c, j) => (
                    <td key={j} className="px-2 py-1.5 text-text">{c}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>);
      table = [];
    };
    const flushList = (key: number) => {
      if (!list.length) return;
      out.push(
        <ul key={`l${key}`} className="my-2 space-y-1 pl-4">
          {list.map((one, i) => (
            <li key={i} className="list-disc text-sm leading-relaxed text-text">{one}</li>
          ))}
        </ul>);
      list = [];
    };
    (body || "").split("\n").forEach((line, at) => {
      const cells = /^\s*\|(.+)\|\s*$/.exec(line);
      if (cells) {
        const parts = cells[1].split("|").map((c) => c.trim());
        const divider = parts.every((c) => /^[-: ]+$/.test(c) && c.includes("-"));
        if (!divider) table.push(parts);
        return;
      }
      flushTable(at);
      const head = /^(#{1,4})\s+(.*)$/.exec(line);
      if (head) {
        flushList(at);
        const level = head[1].length;
        const slug = head[2].toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
        out.push(
          <h3 key={at} id={slug}
              className={cn("scroll-mt-20 font-semibold text-text",
                            level === 1 ? "mt-5 text-base" : "mt-4 text-sm")}>
            {head[2]}
          </h3>);
        return;
      }
      const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
      if (bullet) { list.push(bullet[1]); return; }
      flushList(at);
      if (line.trim()) {
        out.push(
          <p key={at} className="my-2 text-sm leading-relaxed text-text">{line}</p>);
      }
    });
    flushTable(9999);
    flushList(9999);
    return out;
  }, [body]);
  return <div>{blocks}</div>;
}

export default function DocumentPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = Number(params.id);
  const [doc, setDoc] = React.useState<WorkDocumentBody | null>(null);
  const [failed, setFailed] = React.useState("");
  const [draft, setDraft] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [dirty, setDirty] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [savedAt, setSavedAt] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  const [history, setHistory] = React.useState<WorkDocument[] | null>(null);
  const [busy, setBusy] = React.useState("");

  const load = React.useCallback(() => {
    if (!Number.isFinite(id)) return;
    api.document(id)
      .then((got) => {
        setDoc(got);
        setDraft(got.body);
        setTitle(got.title);
        setDirty(false);
      })
      .catch((error: Error) => setFailed(error.message));
  }, [id]);

  React.useEffect(() => { load(); }, [load]);

  // Autosave. Debounced, and it writes through the same call the button
  // uses — one place for unsaved text is one place to lose it from.
  React.useEffect(() => {
    if (!dirty || !doc?.can_edit) return;
    const timer = setTimeout(() => { void save(); }, SAVE_AFTER_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, title, dirty, doc?.can_edit]);

  async function save() {
    if (!doc?.can_edit) return;
    setSaving(true);
    try {
      const got = await api.saveDocument(id, { body: draft, title });
      setDoc(got);
      setDirty(false);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function move(to: string) {
    setBusy(to);
    try {
      setDoc(await api.moveDocument(id, to));
      setFailed("");
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function revise() {
    setBusy("revise");
    try {
      const made = await api.reviseDocument(id);
      router.push(`/documents/${made.id}`);
    } catch (error) {
      setFailed((error as Error).message);
      setBusy("");
    }
  }

  async function showHistory() {
    if (history) { setHistory(null); return; }
    try {
      const got = await api.documentRevisions(id);
      setHistory(got.revisions);
    } catch (error) {
      setFailed((error as Error).message);
    }
  }

  if (!doc) {
    return (
      <div className="space-y-4">
        {failed
          ? <Card className="p-4"><p className="text-sm text-negative">{failed}</p></Card>
          : <><Skeleton className="h-20 w-full" /><Skeleton className="h-96 w-full" /></>}
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="document-detail">
      <Link href="/documents"
            className="inline-flex items-center gap-1 text-xs text-text-muted hover:text-text"
            data-testid="document-back">
        <ArrowLeft className="size-3.5" aria-hidden /> Documents
      </Link>

      {/* ------------------------------------------ title, version, status */}
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <input
              value={title}
              disabled={!doc.can_edit}
              onChange={(e) => { setTitle(e.target.value); setDirty(true); }}
              data-testid="document-title"
              className="w-full border-none bg-transparent text-lg font-semibold text-text outline-none disabled:opacity-80"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={STATUS_TONE[doc.status] ?? "default"}>
                {doc.status_label}
              </Badge>
              <Badge variant="outline">{doc.badge}</Badge>
              <span className="text-[11px] text-text-muted">
                {[doc.kind, doc.product.replace(/_/g, " "),
                  doc.as_of && `as of ${doc.as_of}`, doc.owner]
                  .filter(Boolean).join(" · ")}
              </span>
            </div>
            {Object.keys(doc.data_versions).length > 0 && (
              // On the face of the paper. A reader who cannot tell which
              // book the figures came from cannot use them.
              <p className="font-mono text-[10px] text-text-muted">
                {Object.entries(doc.data_versions)
                  .map(([k, v]) => `${k} ${String(v)}`).join(" · ")}
              </p>
            )}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {doc.can_edit && (
              <>
                <button type="button" onClick={() => setEditing((was) => !was)}
                        data-testid="document-edit"
                        className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text">
                  {editing ? "Preview" : "Edit"}
                </button>
                <button type="button" onClick={save} disabled={saving || !dirty}
                        data-testid="document-save"
                        className="rounded border border-border-strong bg-surface-hover px-2.5 py-1 text-[11px] text-text disabled:opacity-50">
                  {saving ? "Saving…" : dirty ? "Save" : "Saved"}
                </button>
              </>
            )}
            <a href={api.documentDocxUrl(doc.id)}
               data-testid="document-docx"
               className="flex items-center gap-1 rounded border border-border px-2.5 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text">
              <Download className="size-3" aria-hidden /> Word
            </a>
            <a href={api.documentBundleUrl(doc.id)}
               data-testid="document-bundle"
               className="flex items-center gap-1 rounded border border-border px-2.5 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text">
              <Paperclip className="size-3" aria-hidden /> Support bundle
            </a>
          </div>
        </div>
        {savedAt && !dirty && (
          <p className="mt-2 text-[10px] text-text-muted">
            Saved at {savedAt}.
          </p>
        )}
        {failed && <p className="mt-2 text-[11px] text-negative">{failed}</p>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[180px_1fr_260px]">
        {/* ------------------------------------------------- the outline */}
        <Card className="h-fit p-3" data-testid="document-outline">
          <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
            Sections
          </h4>
          {doc.outline.length === 0 ? (
            <p className="text-[11px] text-text-muted">
              No headings yet. A line beginning with # becomes one.
            </p>
          ) : (
            <ul className="space-y-1">
              {doc.outline.map((one) => (
                <li key={one.anchor}
                    style={{ paddingLeft: `${(one.level - 1) * 8}px` }}>
                  <a href={`#${one.anchor}`}
                     className="text-[11px] text-text-muted hover:text-text">
                    {one.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* ------------------------------------------------ the document */}
        <Card className="p-5">
          {!doc.can_edit && (
            <p className="mb-3 rounded border border-border bg-surface-hover px-3 py-2 text-[11px] leading-relaxed text-text-muted">
              {doc.why_not_editable}
            </p>
          )}
          {editing && doc.can_edit ? (
            <textarea
              value={draft}
              onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
              data-testid="document-body"
              rows={30}
              className="w-full resize-y rounded border border-border bg-surface-hover px-3 py-2 font-mono text-xs leading-relaxed text-text"
            />
          ) : (
            <Rendered body={draft} />
          )}
        </Card>

        {/* ------------------------------ evidence and the review controls */}
        <div className="space-y-4">
          <Card className="p-3">
            <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              Review
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {doc.transitions.map((one) => (
                <button key={one} type="button" onClick={() => move(one)}
                        disabled={Boolean(busy)}
                        data-testid={`document-to-${one}`}
                        className="rounded border border-border px-2 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text disabled:opacity-50">
                  {doc.statuses.find((s) => s.status === one)?.label ?? one}
                </button>
              ))}
              <button type="button" onClick={revise} disabled={Boolean(busy)}
                      data-testid="document-revise"
                      className="rounded border border-border px-2 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text disabled:opacity-50">
                Create revision
              </button>
              <button type="button" onClick={showHistory}
                      data-testid="document-history"
                      className="rounded border border-border px-2 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text">
                {history ? "Hide history" : "History"}
              </button>
            </div>
            {doc.approved_at && (
              <p className="mt-2 text-[10px] text-text-muted">
                Approved by {doc.approved_by || "unattributed"} on{" "}
                {doc.approved_at.slice(0, 10)}.
              </p>
            )}
            {history && (
              <ol className="mt-2 space-y-1 border-t border-border pt-2">
                {history.map((one) => (
                  <li key={one.id} className="text-[11px]">
                    <Link href={`/documents/${one.id}`}
                          className={cn("hover:text-text",
                                        one.id === doc.id
                                          ? "font-semibold text-text"
                                          : "text-text-muted")}>
                      Revision {one.revision} — {one.status_label}
                      {one.is_current ? " (current)" : ""}
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </Card>

          <Card className="p-3">
            <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              Supporting evidence
            </h4>
            {doc.evidence.length === 0 && doc.attachments.length === 0 ? (
              <p className="text-[11px] leading-relaxed text-text-muted">
                Nothing attached. A paper with conclusions and no evidence is
                a paper a reviewer has to take on trust.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {doc.evidence.map((one, at) => (
                  <li key={`e${at}`} className="text-[11px]">
                    {one.href ? (
                      <Link href={one.href} className="text-text-muted hover:text-text">
                        {one.label ?? one.id}
                      </Link>
                    ) : (
                      <span className="text-text-muted">{one.label ?? one.id}</span>
                    )}
                    <span className="ml-1 text-[10px] text-text-muted">
                      {one.kind}
                    </span>
                  </li>
                ))}
                {doc.attachments.map((one) => (
                  <li key={one.id} className="text-[11px]">
                    <a href={api.documentAttachmentUrl(one.id)}
                       data-testid={`document-file-${one.id}`}
                       className="flex items-center gap-1 text-text-muted hover:text-text">
                      <FileText className="size-3 shrink-0" aria-hidden />
                      {one.label}
                    </a>
                    <span className="ml-4 text-[10px] text-text-muted">
                      {one.role} · {(one.size_bytes / 1024).toFixed(0)} KB
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
