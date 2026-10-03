"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { cockpitV4Enabled } from "@/components/cockpit-v4/client";
import { guidedEnabled } from "@/lib/workspace/guided";

/**
 * True where a legacy V3 page has no backend: the V4 runtime serves the
 * Cockpit and the Guided Workspace, not the V3 analysis-run, Early Warning
 * lab or signals APIs. Those pages then hand over to their governed
 * equivalent instead of rendering empty panels.
 */
export function legacyRedirectActive(): boolean {
  return cockpitV4Enabled() && guidedEnabled();
}

/**
 * Replace the address with the governed route (no extra history entry, so
 * browser Back returns to the page that linked here) and say where the
 * reader is being taken.
 */
export function LegacyRedirect({ to, keepQuery = false, testId, children }: {
  to: string;
  keepQuery?: boolean;
  testId: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  React.useEffect(() => {
    router.replace(`${to}${keepQuery ? window.location.search : ""}`);
  }, [router, to, keepQuery]);
  return (
    <p className="p-6 text-sm text-text-muted" data-testid={testId} data-redirect-to={to}>
      {children}
    </p>
  );
}
