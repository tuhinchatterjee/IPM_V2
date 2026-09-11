"use client";

import * as React from "react";

/**
 * Whether the left navigation is collapsed, shared between the header (which
 * holds the toggle) and the sidebar (which reads it).
 *
 * The preference is remembered in localStorage: a person who works mostly in the
 * Trace canvas or a Lens wants the extra width every session, not just this one.
 *
 * localStorage is EXTERNAL state — the server cannot know it, and reading it
 * during render would make the server and client markup disagree. So it is read
 * through `useSyncExternalStore`, which is the React 19 idiom for exactly this:
 * the server snapshot is the default, the stored value appears on hydration
 * without a cascading render, and a change in another tab arrives through the
 * subscription rather than being missed.
 */

const STORAGE_KEY = "creditprobe.nav.collapsed";

interface NavState {
  collapsed: boolean;
  toggle: () => void;
}

const NavContext = React.createContext<NavState>({
  collapsed: false,
  toggle: () => {},
});

/** Listeners in this tab. `storage` only fires in OTHER tabs, so both are needed. */
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function read(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    // Private browsing, or storage disabled. The default is fine.
    return false;
  }
}

/** The server has no localStorage, so it renders the navigation expanded. */
function readOnServer(): boolean {
  return false;
}

function write(value: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Not worth failing a navigation over.
  }
  listeners.forEach((listener) => listener());
}

/**
 * Below this width the sidebar's 212px is most of the screen.
 *
 * A phone rendering a 375px window was leaving the content area 163px, which
 * is not a layout so much as a column of broken words. The navigation
 * collapses to its icon rail there -- a state the sidebar already renders
 * properly -- and the stored preference is untouched, so a person who
 * expands it on a laptop still finds it expanded when they go back.
 */
const NARROW = "(max-width: 767px)";

function subscribeNarrow(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(NARROW);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function readNarrow(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(NARROW).matches;
}

/** The server has no viewport, so it renders for the wide case. */
function readNarrowOnServer(): boolean {
  return false;
}

export function NavProvider({ children }: { children: React.ReactNode }) {
  const stored = React.useSyncExternalStore(subscribe, read, readOnServer);
  const narrow = React.useSyncExternalStore(
    subscribeNarrow,
    readNarrow,
    readNarrowOnServer,
  );
  const collapsed = stored || narrow;
  const toggle = React.useCallback(() => write(!read()), []);

  const value = React.useMemo(() => ({ collapsed, toggle }), [collapsed, toggle]);
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

export function useNavState(): NavState {
  return React.useContext(NavContext);
}
