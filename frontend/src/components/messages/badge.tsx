"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Mail } from "lucide-react";
import * as React from "react";

import { useAttention } from "@/lib/attention";

/**
 * The unread indicator in the header.
 *
 * One icon and, when there is something, one number. Not a panel: the
 * notification centre beside it already opens; a second thing that opens would
 * make the header a place people go rather than a place people glance at.
 *
 * The number comes from the shared attention store, which is the only thing in
 * the product that fetches `/messages/counts`. That is what makes reading a
 * message clear this badge the instant it is read rather than the next time the
 * route changes: the thread view refreshes the store, and the store tells this
 * component. A count nobody is signed in for simply does not render — a "0" for
 * an anonymous caller is a claim about a mailbox that does not exist.
 *
 * The route change is still a refresh, because things happen elsewhere: a
 * colleague sends something while this tab sits on one page all afternoon.
 */
export function UnreadMessages() {
  const pathname = usePathname();
  const { counts, refresh } = useAttention();

  React.useEffect(() => {
    void refresh();
  }, [pathname, refresh]);

  if (counts === null) return null;
  const count = counts.unread + counts.action_required;

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
