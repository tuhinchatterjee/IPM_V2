"use client";

import * as React from "react";

import { api, type MessageCounts } from "@/lib/api";

/**
 * One number, everywhere.
 *
 * The header badge, the mailbox tabs, the three summary tiles and the personal
 * workspace card all show counts of the same things. When each of them fetched
 * its own, they drifted: reading a message updated the tab because the list
 * reloaded, and left the header showing the old number until the route changed.
 * A badge that is sometimes wrong is worse than no badge, because the reader
 * cannot tell which time it is.
 *
 * So there is one store. `/messages/counts` is the only place any of it comes
 * from — the backend computes every predicate in a single function — and the
 * only way it changes is `refresh()`, which every action that could move a
 * count calls: sending, reading, archiving, moving a request along.
 *
 * `useSyncExternalStore` rather than a context, deliberately. The subscribers
 * sit in four different parts of the tree, two of them outside any page, and a
 * provider high enough to cover them all would re-render the whole application
 * for a number in the corner.
 */

const EMPTY: MessageCounts = {
  inbox: 0,
  unread: 0,
  archived: 0,
  sent: 0,
  drafts: 0,
  action_required: 0,
  shared_with_me: 0,
};

let current: MessageCounts | null = null;
let loaded = false;
let pending: Promise<MessageCounts | null> | null = null;
const listeners = new Set<() => void>();

function publish(next: MessageCounts | null): void {
  current = next;
  loaded = true;
  for (const fn of listeners) fn();
}

/**
 * Re-read the counts and tell every subscriber.
 *
 * Concurrent calls share one request: reading a thread fires this from the
 * thread view and from the list that reloads underneath it, and two requests
 * would race to publish the same answer.
 */
export function refreshAttention(): Promise<MessageCounts | null> {
  if (pending) return pending;
  pending = api
    .messageCounts()
    .then((counts) => {
      publish(counts);
      return counts;
    })
    .catch(() => {
      // Signed out, or the database is not there. Publishing null keeps every
      // badge hidden rather than showing a zero, which would be a claim about
      // a mailbox nobody is looking at.
      publish(null);
      return null;
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

const snapshot = (): MessageCounts | null => current;
const serverSnapshot = (): MessageCounts | null => null;

/**
 * The counts, and the one way to move them.
 *
 * `counts` is null until the first read completes and whenever nobody is
 * signed in; callers that need a number regardless can use `safe`, which reads
 * zero for every box.
 */
export function useAttention(): {
  counts: MessageCounts | null;
  safe: MessageCounts;
  refresh: () => Promise<MessageCounts | null>;
} {
  const counts = React.useSyncExternalStore(subscribe, snapshot, serverSnapshot);

  React.useEffect(() => {
    if (!loaded) void refreshAttention();
  }, []);

  return { counts, safe: counts ?? EMPTY, refresh: refreshAttention };
}
