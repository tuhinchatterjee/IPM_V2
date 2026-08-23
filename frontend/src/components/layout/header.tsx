import Link from "next/link";

import { BackendStatusIndicator } from "@/components/system/backend-status";

/**
 * Application header.
 *
 * Carries the product identity and the live backend status, so whether the
 * system is healthy is visible from every screen rather than only from a
 * settings page.
 */
export function Header() {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-5">
      <Link href="/" className="flex items-baseline gap-2.5">
        <span className="text-base font-semibold tracking-tight text-text-primary">
          IPM
        </span>
        <span className="hidden text-xs text-text-muted sm:inline">
          Credit Portfolio Intelligence &amp; Monitoring
        </span>
      </Link>

      <BackendStatusIndicator />
    </header>
  );
}
