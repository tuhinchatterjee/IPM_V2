"use client";

import Link from "next/link";
import * as React from "react";
import { Bell, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, type NotificationRow } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { linkBack } from "@/lib/return-to";
import { cn } from "@/lib/utils";

/**
 * The notification centre. §48.
 *
 * In the header, because it has to be reachable from the screen you are on
 * rather than from a screen you have to go to — and out of the Cockpit, because
 * the Cockpit's whole claim is that it opens on a question rather than on a
 * dashboard of everything.
 *
 * The thing that makes it worth having is the DEEP LINK. A notification that
 * says "Layla commented on Contracting deterioration" and then drops you on a
 * list of investigations has told you something and then made you find it. Each
 * one here opens the exact object, carrying a Back that returns you to whatever
 * you were doing when you looked.
 *
 * Not polled. A count that refreshes every ten seconds costs a request every
 * ten seconds for a number that changes twice a day; it is read when the panel
 * is opened and after anything that would change it.
 */
export function NotificationCentre() {
  const [open, setOpen] = React.useState(false);
  const [nonce, setNonce] = React.useState(0);
  const feed = useAsync(() => api.notifications(), [nonce]);
  const unread = feed.data?.unread ?? 0;

  // Close on Escape and on a click outside: a panel that only closes by
  // clicking the button that opened it is a panel people leave open.
  const panel = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (panel.current && !panel.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setNonce((n) => n + 1);
        }}
        aria-label={
          unread > 0 ? `Notifications, ${unread} unread` : "Notifications"
        }
        aria-expanded={open}
        className="relative flex size-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
      >
        <Bell className="size-[15px]" aria-hidden />
        {unread > 0 && (
          <span
            className="absolute -right-0.5 -top-0.5 flex min-w-[15px] items-center justify-center rounded-full bg-accent px-1 text-[9px] font-semibold leading-[15px] text-accent-contrast"
            aria-hidden
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-[22rem] overflow-hidden rounded-lg border border-border bg-surface shadow-xl">
          <header className="flex items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
            <p className="meta text-text-muted">Notifications</p>
            {unread > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={async () => {
                  await api.markNotificationsRead();
                  setNonce((n) => n + 1);
                }}
              >
                <Check aria-hidden />
                Mark all read
              </Button>
            )}
          </header>

          <div className="max-h-[24rem] overflow-y-auto">
            {feed.loading && (
              <p className="px-3.5 py-6 text-center text-xs text-text-muted">
                Loading…
              </p>
            )}
            {feed.data?.notifications.length === 0 && (
              <p className="px-3.5 py-6 text-center text-xs text-text-muted">
                Nothing needs you.
              </p>
            )}
            {(feed.data?.notifications ?? []).slice(0, 20).map((note) => (
              <NotificationLine
                key={note.id}
                note={note}
                onOpened={() => {
                  setOpen(false);
                  void api.markNotificationsRead(note.id).then(() =>
                    setNonce((n) => n + 1),
                  );
                }}
              />
            ))}
          </div>

          <footer className="border-t border-border px-3.5 py-2">
            <Link
              href="/reviews"
              onClick={() => setOpen(false)}
              className="text-[11px] text-accent hover:underline"
            >
              Open the Workflow inbox
            </Link>
          </footer>
        </div>
      )}
    </div>
  );
}

function NotificationLine({
  note,
  onOpened,
}: {
  note: NotificationRow;
  onOpened: () => void;
}) {
  const href = deepLink(note);

  const body = (
    <>
      <span
        className={cn(
          "mt-1.5 size-1.5 shrink-0 rounded-full",
          note.read ? "bg-border-strong" : "bg-accent",
        )}
        aria-hidden
      />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-text-primary">
          {note.title}
        </span>
        {note.body && (
          <span className="mt-0.5 line-clamp-2 block text-[11px] text-text-muted">
            {note.body}
          </span>
        )}
      </span>
      <span className="shrink-0 text-[10px] text-text-muted">{when(note.created_at)}</span>
    </>
  );

  if (!href) {
    return (
      <div className="flex items-start gap-2.5 px-3.5 py-2.5">{body}</div>
    );
  }
  return (
    <Link
      href={href}
      onClick={onOpened}
      className="flex items-start gap-2.5 px-3.5 py-2.5 transition-colors hover:bg-surface-hover"
    >
      {body}
    </Link>
  );
}

/**
 * Where a notification actually goes. §48: "deep-links to the exact object".
 *
 * The object type is what the backend stamped when it raised the notification,
 * so this is a lookup rather than a guess. A type with no page returns null and
 * the line renders as text — a link that lands on a 404 is worse than no link,
 * because the reader concludes the product is broken rather than that there is
 * nothing to open.
 *
 * The Back carries the Workflow inbox, which is where somebody following a
 * notification is conceptually standing even if they clicked from the header.
 */
export function deepLink(note: NotificationRow): string | null {
  const from = { href: "/reviews", label: "My reviews", type: "workflow" as const };
  const id = note.object_id;
  if (!id) return null;

  switch (note.object_type) {
    case "investigation":
      return linkBack(`/investigations/${id}`, from);
    case "project":
      return linkBack(`/projects/${id}`, from);
    case "analysis":
      return linkBack(`/engine-builder/${id}`, from);
    case "dataset":
      return linkBack(`/data-builder/dataset/${encodeURIComponent(id)}`, from);
    case "run":
      return linkBack(`/trace/${id}`, from);
    case "playbook":
      return "/playbooks";
    case "scenario":
      return "/stress";
    case "document":
      return `/documents/${id}`;
    default:
      return null;
  }
}

function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.round((Date.now() - date.getTime()) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
