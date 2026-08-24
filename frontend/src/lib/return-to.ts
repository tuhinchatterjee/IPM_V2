"use client";

import { useSearchParams } from "next/navigation";
import * as React from "react";

/**
 * Where "Back" actually goes.
 *
 * A product with fifteen screens that link into each other has a real problem:
 * the browser's back button is the only honest answer, and a "Back to
 * Investigations" button that always goes to Investigations is a lie whenever
 * you arrived from a Project.
 *
 * So a link that leaves one screen for another carries where it came from:
 *
 *     href={withReturnTo(`/investigations/${id}`, "/projects/12", "Contracting review")}
 *
 * and the destination reads it back with `useReturnTo()`, showing a Back action
 * that names the place it will return you to. When nothing was carried, the
 * caller's own default is used — so a screen opened directly still has a
 * sensible Back rather than a dead one.
 *
 * Two query parameters, `returnTo` and `returnLabel`, are the whole mechanism.
 * They survive a refresh and a shared link, which `history.state` would not.
 */

export interface ReturnTo {
  /** Where Back goes. */
  href: string;
  /** What the Back action says, e.g. "Contracting review". */
  label: string;
}

/** Add return context to a link. */
export function withReturnTo(href: string, from: string, label: string): string {
  const separator = href.includes("?") ? "&" : "?";
  return (
    `${href}${separator}returnTo=${encodeURIComponent(from)}` +
    `&returnLabel=${encodeURIComponent(label)}`
  );
}

/**
 * The place to go back to, or the caller's default.
 *
 * Only same-origin relative paths are honoured. A `returnTo` is a URL that
 * arrived in a query string, so treating it as trustworthy would let any link
 * anywhere turn a Back button into an off-site redirect.
 */
export function useReturnTo(fallback: ReturnTo): ReturnTo {
  const params = useSearchParams();
  const href = params.get("returnTo");
  const label = params.get("returnLabel");

  return React.useMemo(() => {
    if (!href || !isInternalPath(href)) return fallback;
    return { href, label: label || "Back" };
    // The fallback is an inline object at every call site, so keying the memo on
    // its parts rather than its identity is what stops it recomputing forever.
  }, [href, label, fallback.href, fallback.label]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** A path inside this application: one leading slash, and no scheme or host. */
export function isInternalPath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !value.includes(":");
}
