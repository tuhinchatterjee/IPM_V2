"use client";

import * as React from "react";
import { FileText, Paperclip, Plus, Send, Upload, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatBytes, roleLabel } from "@/lib/playbook";

/** One thing riding along with the next message. */
export interface Attachment {
  key: string;
  kind: "source" | "analysis";
  label: string;
  detail?: string;
  sizeBytes?: number;
  /** Set while a local file is still uploading and parsing. */
  pending?: boolean;
  /** Set when it failed; a failed attachment must never travel silently. */
  error?: string;
}

const MAX_HEIGHT = 220;

/**
 * The composer.
 *
 * The plus button is inside the box on its lower left, not on a separate upload
 * screen — §4 is specific about that, and it matters because attaching evidence
 * is part of writing the request rather than a detour before it.
 *
 * Two behaviours are worth naming. Enter sends and Shift+Enter adds a newline,
 * matching `components/ask/composer.tsx` so the product has one convention. And
 * a send is refused while any attachment is still uploading or has failed,
 * because a request that quietly goes without its evidence produces a confident
 * answer based on less than the user thinks.
 */
export function Composer({
  value,
  onChange,
  onSend,
  attachments,
  onRemoveAttachment,
  onUploadFiles,
  onAddAnalyses,
  busy = false,
  disabledNote = "",
  placeholder = "What would you like to create, check, or improve?",
  autoFocus = false,
}: {
  value: string;
  onChange: (next: string) => void;
  onSend: () => void;
  attachments: Attachment[];
  onRemoveAttachment: (key: string) => void;
  onUploadFiles: (files: FileList) => void;
  onAddAnalyses: () => void;
  busy?: boolean;
  disabledNote?: string;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [dragging, setDragging] = React.useState(false);
  const textarea = React.useRef<HTMLTextAreaElement>(null);
  const fileInput = React.useRef<HTMLInputElement>(null);
  const menu = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const node = textarea.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  React.useEffect(() => {
    if (!menuOpen) return;
    const close = (event: MouseEvent) => {
      if (!menu.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [menuOpen]);

  const uploading = attachments.some((a) => a.pending);
  const broken = attachments.filter((a) => a.error);
  const blocked = Boolean(disabledNote);
  const canSend =
    !busy && !blocked && !uploading && broken.length === 0 && value.trim().length > 0;

  const send = () => {
    if (!canSend) return;
    onSend();
  };

  return (
    <div className="space-y-2">
      <div
        className={cn(
          "rounded-xl border bg-surface shadow-raised transition-colors",
          dragging ? "border-accent" : "border-border",
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files?.length) onUploadFiles(e.dataTransfer.files);
        }}
      >
        <label htmlFor="playbook-composer" className="sr-only">
          Describe what you would like Playbook to create, check or improve
        </label>
        <textarea
          id="playbook-composer"
          ref={textarea}
          rows={1}
          value={value}
          autoFocus={autoFocus}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          className="w-full resize-none bg-transparent px-4 pt-3.5 text-sm leading-relaxed text-text-primary outline-none placeholder:text-text-muted"
        />

        {attachments.length > 0 && (
          <ul className="flex flex-wrap gap-1.5 px-3 pb-1">
            {attachments.map((a) => (
              <li key={a.key}>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
                    a.error
                      ? "border-negative/40 bg-negative-muted text-negative"
                      : "border-border bg-surface-sunken text-text-secondary",
                  )}
                >
                  {a.kind === "analysis" ? (
                    <FileText className="size-3" aria-hidden />
                  ) : (
                    <Paperclip className="size-3" aria-hidden />
                  )}
                  <span className="max-w-[16rem] truncate">{a.label}</span>
                  {a.pending && (
                    <span className="text-text-muted">· reading…</span>
                  )}
                  {a.sizeBytes ? (
                    <span className="text-text-muted">
                      · {formatBytes(a.sizeBytes)}
                    </span>
                  ) : null}
                  {a.detail && !a.error && (
                    <span className="text-text-muted">· {a.detail}</span>
                  )}
                  {a.error && <span>· {a.error}</span>}
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(a.key)}
                    aria-label={`Remove ${a.label}`}
                    className="ml-0.5 rounded-full p-0.5 hover:bg-surface-hover"
                  >
                    <X className="size-3" aria-hidden />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center justify-between gap-2 px-3 pb-3 pt-1">
          <div className="relative" ref={menu}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label="Add sources"
              onClick={() => setMenuOpen((o) => !o)}
            >
              <Plus aria-hidden />
            </Button>
            {menuOpen && (
              <div
                role="menu"
                className="absolute bottom-11 left-0 z-20 w-64 overflow-hidden rounded-lg border border-border bg-surface-raised shadow-overlay"
              >
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-surface-hover"
                  onClick={() => {
                    setMenuOpen(false);
                    fileInput.current?.click();
                  }}
                >
                  <Upload className="mt-0.5 size-4 text-text-muted" aria-hidden />
                  <span>
                    <span className="block text-sm text-text-primary">
                      Upload from computer
                    </span>
                    <span className="block text-xs text-text-muted">
                      Reports, workbooks, methodologies, templates
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  className="flex w-full items-start gap-2.5 border-t border-border px-3 py-2.5 text-left hover:bg-surface-hover"
                  onClick={() => {
                    setMenuOpen(false);
                    onAddAnalyses();
                  }}
                >
                  <FileText className="mt-0.5 size-4 text-text-muted" aria-hidden />
                  <span>
                    <span className="block text-sm text-text-primary">
                      Add exported analyses
                    </span>
                    <span className="block text-xs text-text-muted">
                      Only analyses exported to Playbook
                    </span>
                  </span>
                </button>
              </div>
            )}
            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              accept=".docx,.pdf,.xlsx,.pptx,.csv,.txt,.md"
              onChange={(e) => {
                if (e.target.files?.length) onUploadFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          <div className="flex items-center gap-2">
            {uploading && (
              <span className="text-xs text-text-muted">
                Waiting for attachments to finish reading
              </span>
            )}
            <Button type="button" size="sm" onClick={send} disabled={!canSend}>
              <Send aria-hidden />
              {busy ? "Working…" : "Send"}
            </Button>
          </div>
        </div>
      </div>

      {blocked && (
        <p className="text-xs leading-relaxed text-warning">{disabledNote}</p>
      )}
      {broken.length > 0 && (
        <p className="text-xs leading-relaxed text-negative">
          {broken.length} attachment(s) could not be read. Remove or retry them
          before sending — a request must not go without evidence it appears to
          have.
        </p>
      )}
    </div>
  );
}

/** A source chip's role, shown where a user can correct it. */
export function RoleBadge({ role }: { role: string }) {
  return <Badge variant="outline">{roleLabel(role)}</Badge>;
}
