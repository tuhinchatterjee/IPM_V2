"use client";

import * as React from "react";

/**
 * One governed mutation at a time per control group (VAL-DEF idempotency).
 *
 * A double-click fires two click events before React re-renders a
 * `disabled` button, so a state flag alone lets the second request through
 * and the server mints a second cohort / share / clone. The ref closes that
 * window synchronously; `busy` drives the disabled styling.
 */
export function useSingleFlight() {
  const inFlight = React.useRef(false);
  const [busy, setBusy] = React.useState(false);
  const run = React.useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    if (inFlight.current) return undefined;
    inFlight.current = true;
    setBusy(true);
    try {
      return await fn();
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, []);
  return { busy, run };
}
