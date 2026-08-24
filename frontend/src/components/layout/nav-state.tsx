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

export function NavProvider({ children }: { children: React.ReactNode }) {
  const collapsed = React.useSyncExternalStore(subscribe, read, readOnServer);
  const toggle = React.useCallback(() => write(!read()), []);

  const value = React.useMemo(() => ({ collapsed, toggle }), [collapsed, toggle]);
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

export function useNavState(): NavState {
  return React.useContext(NavContext);
}
