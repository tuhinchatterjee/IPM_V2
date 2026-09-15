/**
 * What the composer was holding when the user went to look at the status.
 *
 * §6 requires that CHAT → KNOW THE STATUS → BACK TO CHAT loses nothing: not
 * the half-typed sentence, not the files waiting to be attached, not the
 * analyses already picked. The dashboard is a separate route, so React state
 * does not survive the trip and something has to carry it.
 *
 * `sessionStorage` carries it. It is the right shape of storage for this:
 * per-tab, per-viewer, gone when the tab closes, and never sent anywhere. A
 * draft is a convenience, not a record — nothing here is governed state, and
 * losing it costs a retype rather than a fact.
 *
 * Every read and write is wrapped, because `sessionStorage` throws in a
 * private window and in a browser with site data blocked, and a status page
 * that will not open because a draft could not be read would be a worse bug
 * than the one this fixes.
 */

export interface PlaybookDraft {
  prompt: string;
  task: { kind: string; scope: string };
  /** Exported-analysis revision ids, in the order they were chosen. */
  analyses: number[];
  /** Where the conversation was scrolled to. */
  scrollY: number;
  /** Which dashboard tab was last open, so returning lands where you left. */
  tab?: string;
}

export const EMPTY: PlaybookDraft = {
  prompt: "",
  task: { kind: "", scope: "" },
  analyses: [],
  scrollY: 0,
};

function key(workspaceId: number): string {
  return `playbook:draft:${workspaceId}`;
}

function store(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveDraft(
  workspaceId: number,
  draft: Partial<PlaybookDraft>,
): void {
  const box = store();
  if (!box) return;
  try {
    box.setItem(key(workspaceId),
      JSON.stringify({ ...EMPTY, ...readDraft(workspaceId), ...draft }));
  } catch {
    // A draft that could not be saved is a retype, not a failure worth
    // surfacing. The alternative — an error toast about session storage —
    // tells the user nothing they can act on.
  }
}

export function readDraft(workspaceId: number): PlaybookDraft {
  const box = store();
  if (!box) return { ...EMPTY };
  try {
    const raw = box.getItem(key(workspaceId));
    if (!raw) return { ...EMPTY };
    const parsed = JSON.parse(raw) as Partial<PlaybookDraft>;
    return {
      prompt: typeof parsed.prompt === "string" ? parsed.prompt : "",
      task: {
        kind: typeof parsed.task?.kind === "string" ? parsed.task.kind : "",
        scope: typeof parsed.task?.scope === "string" ? parsed.task.scope : "",
      },
      analyses: Array.isArray(parsed.analyses)
        ? parsed.analyses.filter((n): n is number => typeof n === "number")
        : [],
      scrollY: typeof parsed.scrollY === "number" ? parsed.scrollY : 0,
      tab: typeof parsed.tab === "string" ? parsed.tab : undefined,
    };
  } catch {
    // Corrupt or unreadable. An empty draft is always safe.
    return { ...EMPTY };
  }
}

export function clearDraft(workspaceId: number): void {
  const box = store();
  if (!box) return;
  try {
    box.removeItem(key(workspaceId));
  } catch {
    /* nothing to do, and nothing worth telling the user */
  }
}

// The hand-over from the dashboard to the chat is NOT here, deliberately.
// It travels in the URL (`?context=finding:786`) and the context itself is
// fetched from the server, so it survives a reload, can be sent to somebody,
// and does not depend on two pages agreeing about when a piece of session
// state is consumed. Carrying it here was tried and was worse.
