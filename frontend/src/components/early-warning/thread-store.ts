/**
 * A thread the reader can walk back to.
 *
 * The gap
 * -------
 * The Early Warning thread lived entirely in component state under an id
 * React generated on mount. Open a borrower, press Back, and the thread was
 * gone — not archived, not reopened empty, GONE, with no trace that it had
 * existed. A reader who had asked four questions and drilled into a name to
 * check one of the answers lost all four for looking.
 *
 * So a thread has an id in the address, and its turns are kept against that
 * id. Back returns to it; a link reopens it; "New thread" starts a genuinely
 * new one rather than clearing this one.
 *
 * What this is NOT
 * ----------------
 * Durable storage. `sessionStorage` is per-tab and ends with the tab, which
 * is exactly the right lifetime for "I pressed Back" and the wrong one for
 * "I'll pick this up on Monday". Keeping a thread for Monday is what saving
 * it to Investigations does, deliberately and visibly, and that path already
 * exists. Pretending this one survives a closed browser would be worse than
 * not having it.
 *
 * Every read and write is guarded. `sessionStorage` throws in a private
 * window and returns nothing after a clear, and a chat that cannot render
 * because storage was unavailable is a worse failure than one that forgets.
 */

/** A turn as the thread remembers it: what was asked, and what came back. */
export interface RememberedTurn {
  id: string;
  question: string;
  /** The answer document, opaque here — this module stores, it does not read. */
  answer: unknown;
  progress: unknown;
}

export interface RememberedThread {
  id: string;
  turns: RememberedTurn[];
  /** The server's rolling summary, handed back on the next turn. */
  summary?: Record<string, unknown>;
  /** The dashboard scope the thread was asked in, snapshotted at its start. */
  scope?: { spec?: Record<string, unknown>; label: string };
}

const PREFIX = "ews-thread:";

/** The key the address uses. Short, because a reader sees it. */
export const THREAD_PARAM = "thread";

/** A fresh thread id. Sortable by age, which makes a stale one recognisable. */
export function newThreadId(now: number = Date.now()): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `t${now.toString(36)}${random}`;
}

/** The thread the address names, if it names one. */
export function threadFromQuery(search: string): string {
  const value = new URLSearchParams(search).get(THREAD_PARAM) ?? "";
  // Anything that is not a thread id we generated is ignored rather than
  // used as a storage key: an id out of a URL is somebody else's text.
  return /^[a-z0-9]{6,40}$/i.test(value) ? value : "";
}

/** The address with this thread in it, leaving every other key alone. */
export function queryWithThread(search: string, id: string): string {
  const query = new URLSearchParams(search);
  if (id) query.set(THREAD_PARAM, id);
  else query.delete(THREAD_PARAM);
  return query.toString();
}

export function remember(thread: RememberedThread): void {
  try {
    sessionStorage.setItem(PREFIX + thread.id, JSON.stringify(thread));
  } catch {
    // Out of quota, or a private window. The thread still works; it just
    // will not survive a Back.
  }
}

export function recall(id: string): RememberedThread | null {
  if (!id) return null;
  try {
    const raw = sessionStorage.getItem(PREFIX + id);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as RememberedThread;
    // Stored by this module, but read back as though it were not: a shape
    // that does not match is nothing, not a crash on the next render.
    if (!parsed || typeof parsed !== "object") return null;
    if (!Array.isArray(parsed.turns)) return null;
    return { ...parsed, id };
  } catch {
    return null;
  }
}

export function forget(id: string): void {
  try {
    sessionStorage.removeItem(PREFIX + id);
  } catch {
    /* nothing to do, and nothing worth telling the reader */
  }
}
