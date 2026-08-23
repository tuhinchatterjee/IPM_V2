"use client";

import * as React from "react";

import {
  DEFAULT_THEME,
  THEME_STORAGE_KEY,
  type ThemeId,
  isThemeId,
} from "@/lib/themes";

/* -----------------------------------------------------------------------------
   The stored theme is external state — it lives in localStorage, not in React.
   So it is read with useSyncExternalStore rather than copied into state inside an
   effect. That is the correct React 19 idiom for this: no cascading render on
   mount, and a change in another browser tab is picked up automatically.
   -------------------------------------------------------------------------- */

const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  // Keeps two open tabs in agreement.
  window.addEventListener("storage", onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getSnapshot(): ThemeId {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeId(stored) ? stored : DEFAULT_THEME;
  } catch {
    // Private browsing or blocked storage — the default theme is still correct.
    return DEFAULT_THEME;
  }
}

function getServerSnapshot(): ThemeId {
  // The server cannot know the user's choice. ThemeScript applies the real theme
  // before first paint, so this never causes a visible flash.
  return DEFAULT_THEME;
}

interface ThemeContextValue {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  /** False during server render and until hydration completes. */
  ready: boolean;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

/**
 * Applies and remembers the user's theme.
 *
 * The theme is a `data-theme` attribute on <html>; all four palettes are already
 * in the stylesheet, so switching is a single attribute change with no reflow.
 *
 * The choice lives in localStorage for now. When user preferences move to
 * PostgreSQL (the `user_preferences` table already exists), only this file
 * changes — nothing that consumes `useTheme()` has to.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const ready = React.useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );

  const setTheme = React.useCallback((next: ThemeId) => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Not being able to remember the choice must not prevent setting it.
    }
    document.documentElement.setAttribute("data-theme", next);
    emit();
  }, []);

  // Keeps the DOM attribute in step when the value changes somewhere other than
  // setTheme — currently only a change made in another tab. This effect touches
  // the DOM and never sets state, so it introduces no cascading render.
  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const value = React.useMemo(
    () => ({ theme, setTheme, ready }),
    [theme, setTheme, ready],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = React.useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside <ThemeProvider>.");
  }
  return context;
}

/**
 * Applies the stored theme before the page paints.
 *
 * Without this, the browser would render the default theme for one frame and
 * then switch — a visible white flash for anyone using Midnight or Graphite.
 * It has to be a blocking inline script, which is the one legitimate use of
 * dangerouslySetInnerHTML here: the content is a fixed string we author, with no
 * user input anywhere in it.
 */
export function ThemeScript() {
  const script = `
(function () {
  try {
    var stored = localStorage.getItem('${THEME_STORAGE_KEY}');
    var allowed = ['executive-light','midnight','graphite','warm-institutional'];
    document.documentElement.setAttribute(
      'data-theme',
      allowed.indexOf(stored) !== -1 ? stored : '${DEFAULT_THEME}'
    );
  } catch (e) {
    document.documentElement.setAttribute('data-theme', '${DEFAULT_THEME}');
  }
})();`.trim();

  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}
