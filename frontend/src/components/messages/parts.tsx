"use client";

import Link from "next/link";
import * as React from "react";

import {
  api,
  type AttachmentType,
  type MessageAction,
  type MessageAttachment,
  type MessageSender,
  type RequestStatus,
  type RequestType,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The pieces every messaging surface shares.
 *
 * They live together because the inbox row, the thread and the workspace
 * dashboard all have to describe the same message the same way. A sender
 * rendered one way in a list and another way in a thread is how a reader
 * stops being sure which of the two is the product speaking.
 */

/**
 * Who sent it.
 *
 * A human is named with their job title, because the title is what tells a
 * reader whether the person who sent them a shipping question owns the
 * shipping book. CreditProbe is marked differently on purpose — both live in
 * one inbox, and the reader must never have to work out which they are looking
 * at.
 */
export function Sender({ sender, className }: {
  sender: MessageSender;
  className?: string;
}) {
  if (sender.type === "SYSTEM") {
    return (
      <span className={cn("inline-flex items-center gap-1.5", className)}>
        <span
          aria-hidden
          className="size-1.5 rounded-full bg-accent"
        />
        <span className="font-medium text-accent">{sender.name}</span>
      </span>
    );
  }
  const title = sender.user?.job_title ?? "";
  return (
    <span className={cn("inline-flex items-baseline gap-1.5", className)}>
      <span className="font-medium text-text-primary">{sender.name}</span>
      {title && (
        <span className="text-text-muted">· {title}</span>
      )}
    </span>
  );
}

/** What a request is asking for, if it is asking for anything. */
export const REQUEST_LABEL: Record<RequestType, string> = {
  fyi: "For information",
  review: "Review requested",
  action: "Action required",
};

export const STATUS_LABEL: Record<RequestStatus, string> = {
  open: "Open",
  in_review: "In review",
  responded: "Responded",
  closed: "Closed",
};

/**
 * The badge on an inbox row.
 *
 * Only for a message that asks for something. A "For information" chip on
 * every other row would make the two that need attention invisible.
 */
export function RequestBadge({ type, status }: {
  type: RequestType;
  status: RequestStatus | null;
}) {
  if (type === "fyi") return null;
  const closed = status === "closed";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.06em]",
        closed
          ? "bg-surface-sunken text-text-muted"
          : type === "action"
            ? "bg-negative/10 text-negative"
            : "bg-accent/10 text-accent",
      )}
    >
      {closed
        ? STATUS_LABEL.closed
        : status && status !== "open"
          ? STATUS_LABEL[status]
          : REQUEST_LABEL[type]}
    </span>
  );
}

const ATTACHMENT_LABEL: Record<AttachmentType, string> = {
  investigation: "Investigation",
  analysis: "Analysis",
  report: "Report",
  file: "File",
};

/** What is attached, said in the vocabulary of the product rather than "3 files". */
export function AttachmentChips({ types }: { types: AttachmentType[] }) {
  if (types.length === 0) return null;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {types.map((t) => (
        <span
          key={t}
          className="rounded border border-border bg-surface-sunken px-1.5 py-0.5 text-[10px] text-text-secondary"
        >
          {ATTACHMENT_LABEL[t]}
        </span>
      ))}
    </span>
  );
}

/**
 * One attachment, as a card that says what the thing IS.
 *
 * The metadata is the snapshot taken when it was sent, not a fresh read: a
 * renamed investigation must not rewrite the history of what somebody was
 * asked to look at. A governed object links to the object; a file downloads
 * through the authorized endpoint, which checks the reader's participation in
 * this thread on every request.
 */
export function AttachmentCard({ attachment }: {
  attachment: MessageAttachment;
}) {
  const meta = attachment.meta ?? {};
  const detail = [
    typeof meta.period === "string" && meta.period ? meta.period : "",
    typeof meta.owner === "string" && meta.owner ? meta.owner : "",
    typeof meta.certification === "string" && meta.certification
      ? meta.certification
      : "",
    typeof meta.size_bytes === "number"
      ? `${Math.max(1, Math.round(meta.size_bytes / 1024))} KB`
      : "",
  ].filter(Boolean);

  const inner = (
    <>
      <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {ATTACHMENT_LABEL[attachment.type]}
      </span>
      <span className="mt-0.5 block truncate text-sm font-medium text-text-primary">
        {attachment.label}
      </span>
      {detail.length > 0 && (
        <span className="mt-0.5 block truncate text-xs text-text-secondary">
          {detail.join(" · ")}
        </span>
      )}
    </>
  );

  const shell =
    "block min-w-0 rounded-lg border border-border bg-surface px-3 py-2 transition-colors hover:border-accent";

  if (attachment.type === "investigation") {
    return (
      <Link href={`/investigations/${attachment.object_id}`} className={shell}>
        {inner}
      </Link>
    );
  }
  if (attachment.type === "analysis") {
    return (
      <Link href={`/analyses/${attachment.object_id}`} className={shell}>
        {inner}
      </Link>
    );
  }
  if (attachment.file) {
    return (
      <a
        href={api.attachmentUrl(attachment.file.artifact_id)}
        className={shell}
        download={attachment.file.filename}
      >
        {inner}
      </a>
    );
  }
  return <span className={shell}>{inner}</span>;
}

/**
 * What a system message offers the reader to do next.
 *
 * Only actions the backend recorded, and the backend only records the ones the
 * product can honour: a "Compare with the previous quarter" button appears
 * because a previous quarter is known, not because the layout has room for a
 * third button.
 */
export function SystemActions({ actions }: { actions: MessageAction[] }) {
  if (!actions?.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {actions.map((a) => (
        <Link
          key={a.action}
          href={a.href}
          className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-accent hover:text-accent"
        >
          {a.label}
        </Link>
      ))}
    </div>
  );
}

/**
 * A time a person can read.
 *
 * Today is a clock time, this week is a weekday, anything older is a date. An
 * inbox in which every row says the full timestamp makes the one from this
 * morning as hard to spot as the one from March.
 */
export function when(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const now = new Date();
  const sameDay = at.toDateString() === now.toDateString();
  if (sameDay) {
    return at.toLocaleTimeString(undefined, { hour: "numeric",
                                              minute: "2-digit" });
  }
  const days = Math.floor((now.getTime() - at.getTime()) / 86_400_000);
  if (days === 1) return "Yesterday";
  if (days < 7) return at.toLocaleDateString(undefined, { weekday: "long" });
  return at.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * Message text, as text.
 *
 * The body is sanitised server-side and rendered here as plain paragraphs.
 * Nothing in this feature interprets markup: the one input in the product that
 * one user writes and another user's browser displays is the last place to
 * start.
 */
export function Body({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-sm leading-[1.6] text-text-primary">
      {text.split("\n").map((line, i) =>
        line.trim() ? (
          <p key={i}>{line}</p>
        ) : (
          <div key={i} className="h-1.5" aria-hidden />
        ),
      )}
    </div>
  );
}

/** A number that must reconcile to real rows, or not be shown at all. */
export function Stat({ label, value, href }: {
  label: string;
  value: number;
  href?: string;
}) {
  const inner = (
    <>
      <span className="block text-2xl font-semibold tabular-nums text-text-primary">
        {value.toLocaleString()}
      </span>
      <span className="mt-0.5 block text-xs text-text-secondary">{label}</span>
    </>
  );
  const shell =
    "block rounded-lg border border-border bg-surface px-4 py-3 transition-colors";
  return href ? (
    <Link href={href} className={cn(shell, "hover:border-accent")}>
      {inner}
    </Link>
  ) : (
    <div className={shell}>{inner}</div>
  );
}
