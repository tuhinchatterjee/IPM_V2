"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

type Changes = Record<string, string | null | undefined>;

/**
 * Write a page's state into its address.
 *
 * Every write builds on the last address this page asked for while that
 * request is still in flight, not on `window.location`, which lags it. With
 * the lagging location, two quick changes lost one of them: load a scenario
 * then clear it left the scenario in the address; a filter typed while a
 * metric was being opened put the previous metric back. Back or a refresh
 * then restored the wrong state (VAL-DEF-039). A committed navigation (this
 * page's or another's) makes the live address the base again.
 */
export function useAddress(): { replace: (changes: Changes) => void; push: (changes: Changes) => void } {
  const router = useRouter();
  const params = useSearchParams();
  const requested = React.useRef("");
  React.useEffect(() => {
    requested.current = "";
  }, [params]);

  const go = React.useCallback(
    (changes: Changes, mode: "replace" | "push") => {
      const base = requested.current || `${window.location.pathname}${window.location.search}`;
      const url = new URL(base, window.location.origin);
      for (const [k, v] of Object.entries(changes)) {
        if (v === null || v === undefined || v === "") url.searchParams.delete(k);
        else url.searchParams.set(k, v);
      }
      const next = `${url.pathname}${url.search}`;
      if (next === base) return;
      requested.current = next;
      if (mode === "push") router.push(next, { scroll: false });
      else router.replace(next, { scroll: false });
    },
    [router],
  );
  return React.useMemo(
    () => ({ replace: (c: Changes) => go(c, "replace"), push: (c: Changes) => go(c, "push") }),
    [go],
  );
}
