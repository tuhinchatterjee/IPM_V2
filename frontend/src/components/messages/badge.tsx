"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Mail } from "lucide-react";
import * as React from "react";

import { api } from "@/lib/api";

/**
 * The unread indicator in the header.
 *
 * One icon and, when there is something, one number. Not a panel: the
 * notification centre beside it already opens; a second thing that opens would
 * make the header a place people go rather than a place people glance at.
 *
 * The count is refetched when the route changes, so opening a thread updates it
 * on the way back without a poll running behind every screen in the product.
 * A count nobody is signed in for simply does not render — a "0" for an
 * anonymous caller is a claim about a mailbox that does not exist.
 */
export function UnreadMessages() {
  const pathname = usePathname();
  const [count, setCount] = React.useState<number | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    api
      .messageCounts()
      .then((c) => {
        if (!cancelled) setCount(c.unread + c.action_required);
      })
      .catch(() => {
        // Signed out, or the database is not there. Either way the honest
        // rendering is no badge rather than a zero.
        if (!cancelled) setCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);

  if (count === null) return null;

  return (
    <Link
      href="/messages"
      title={count > 0 ? `${count} waiting` : "Messages"}
      aria-label={count > 0 ? `Messages, ${count} waiting` : "Messages"}
      className="relative flex size-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
    >
      <Mail className="size-[15px]" aria-hidden />
      {count > 0 && (
        <span className="absolute -right-0.5 -top-0.5 min-w-[15px] rounded-full bg-accent px-1 text-center text-[9px] font-semibold leading-[15px] text-white">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
