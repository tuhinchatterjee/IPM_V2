"use client";

import * as React from "react";

/**
 * Whether the left navigation is collapsed, shared between the header (which
 * holds the toggle) and the sidebar (which reads it).
 *
 * The preference is remembered in localStorage: a person who works mostly in the
 * Trace canvas or a Lens wants the extra width every session, not just this one.
 * Reading it in an effect rather than during render keeps the server and client
 * markup identical, so there is no hydration mismatch and no visible flicker on
 * the first paint.
 */

const STORAGE_KEY = "creditprobe.nav.collapsed";

interface NavState {
  collapsed: boolean;
  toggle: () => void;
}

const NavContext = React.createContext<NavState>({ collapsed: false, toggle: () => {} });

export function NavProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = React.useState(false);

  React.useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "1");
    } catch {
      /* private browsing, or storage disabled — the default is fine */
    }
  }, []);

  const toggle = React.useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* not worth failing a navigation over */
      }
      return next;
    });
  }, []);

  const value = React.useMemo(() => ({ collapsed, toggle }), [collapsed, toggle]);
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
}

export function useNavState(): NavState {
  return React.useContext(NavContext);
}
