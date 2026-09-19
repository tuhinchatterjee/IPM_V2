"use client";

/**
 * Lets one page widen the shell's content column, without the shell knowing
 * which pages those are.
 *
 * Every other screen reads well inside `max-w-[1200px]`: a table of
 * borrowers, a form, a settings panel. The Cockpit does not. It is a
 * workspace -- an answer, its evidence, its charts and a live process panel
 * beside each other -- and at 1200px the charts are the thing that gives
 * way, which is the part a credit officer is actually reading.
 *
 * So the width is a property the PAGE declares and the shell honours, rather
 * than a list of route prefixes kept in the shell and forgotten the next
 * time a route moves. `useWideContent()` sets it on mount and puts it back
 * on unmount, so navigating away from the Cockpit restores the ordinary
 * column with no cleanup at the call site.
 *
 * Implemented with a data attribute on `<body>` rather than React state
 * because the shell wraps `{children}` above every page component: a state
 * change here would have to lift into a provider that re-renders the whole
 * shell -- the header, the sidebar and the page -- on every navigation, to
 * move one CSS class. The attribute is read by the stylesheet, so nothing
 * re-renders at all.
 */

import { useEffect } from "react";

/** The attribute the shell's stylesheet keys off. */
export const WIDE_ATTRIBUTE = "data-content-width";
export const WIDE_VALUE = "wide";

/** Widen the content column for as long as this component is mounted. */
export function useWideContent(): void {
  useEffect(() => {
    if (typeof document === "undefined") return;
    const body = document.body;
    // Counted, not set and cleared: two mounted components that both want a
    // wide column must not have the first one to unmount narrow it under
    // the second. React also mounts twice in development strict mode, and a
    // boolean flag would be cleared by the first teardown.
    const depth = Number(body.getAttribute("data-content-width-depth") ?? "0");
    body.setAttribute("data-content-width-depth", String(depth + 1));
    body.setAttribute(WIDE_ATTRIBUTE, WIDE_VALUE);
    return () => {
      const held = Number(
        body.getAttribute("data-content-width-depth") ?? "1",
      );
      const left = Math.max(0, held - 1);
      body.setAttribute("data-content-width-depth", String(left));
      if (left === 0) body.removeAttribute(WIDE_ATTRIBUTE);
    };
  }, []);
}

export default useWideContent;
