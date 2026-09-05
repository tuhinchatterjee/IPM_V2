"use client";

import { useSearchParams } from "next/navigation";
import * as React from "react";

import {
  readReturn,
  type ReturnContext,
  type ReturnTo,
} from "./return-context";

/**
 * Where "Back" actually goes — the React side of the return-context contract.
 *
 * The contract itself, and every sanctioned way to build a return href, lives
 * in `return-context.ts`, which is free of React so it can be unit-tested with
 * `node --test`. This file is the two hooks that read it back:
 *
 *   useReturnTo()   the destination for the Back control
 *   useAnchorScroll() lands the reader on the exact turn they left from
 *
 * A link that leaves one screen for another is built like this:
 *
 *     href={linkBack(`/trace/${runId}`, fromInvestigation(id, title, seq))}
 *
 * and the destination reads it back with `useReturnTo()`.
 */

export type { ReturnTo, ReturnContext, SourceType } from "./return-context";
export {
  isInternalPath,
  withReturnTo,
  linkBack,
  turnAnchor,
  analysisAnchor,
  facilityAnchor,
  fromInvestigation,
  fromProject,
  fromSavedAnalysis,
  fromLens,
  fromBorrower,
  fromDataset,
  fromTraceNode,
  fromCockpit,
  INDEX_OF,
} from "./return-context";

/**
 * The place to go back to, or the caller's default.
 *
 * Only same-origin relative paths are honoured; the reasoning is in
 * `readReturn`, which is where the rule is tested.
 */
export function useReturnTo(fallback: ReturnTo): ReturnContext {
  const params = useSearchParams();
  const href = params.get("returnTo");
  const label = params.get("returnLabel");
  const type = params.get("returnType");

  return React.useMemo(
    () => readReturn(href, label, type, fallback),
    // The fallback is an inline object at every call site, so keying the memo on
    // its parts rather than its identity is what stops it recomputing forever.
    [href, label, type, fallback.href, fallback.label], // eslint-disable-line react-hooks/exhaustive-deps
  );
}

/**
 * Land on the anchor the URL names, once the thing it names exists.
 *
 * The App Router restores a hash on a full page load and does not reliably do
 * so after a client-side navigation, and in this product the element being
 * anchored to — turn nine of an investigation — is usually not in the document
 * yet when the navigation completes, because the thread is still being
 * fetched. So the caller passes whatever it is waiting for, and the scroll
 * happens on the render after that arrives.
 *
 * `ready` rather than an effect that polls: a Back that jumps the reader
 * somewhere half a second after they have started reading is worse than one
 * that does not jump at all.
 */
export function useAnchorScroll(ready: boolean): void {
  const done = React.useRef(false);

  React.useEffect(() => {
    if (!ready || done.current) return;
    const hash = window.location.hash.slice(1);
    if (!hash) {
      done.current = true;
      return;
    }
    const target = document.getElementById(hash);
    if (!target) return; // Not rendered yet; try again on the next change.
    done.current = true;
    target.scrollIntoView({ block: "start" });
  }, [ready]);
}
