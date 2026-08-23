"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Sparkles } from "lucide-react";

import { BackendStatusIndicator } from "@/components/system/backend-status";
import { RoleSwitcher } from "@/components/system/role-switcher";
import { Button } from "@/components/ui/button";

/**
 * Application header.
 *
 * Carries the product identity, the Ask IPM launcher (reachable from every
 * screen, as the product's primary way in), the acting role, and the live
 * backend status.
 */
export function Header() {
  const router = useRouter();

  // Cmd/Ctrl+K is the expected shortcut for "ask something" in a modern tool,
  // and the Cockpit is where asking happens.
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        router.push("/?focus=ask");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-5">
      <Link href="/" className="flex items-baseline gap-2.5">
        <span className="text-base font-semibold tracking-tight text-text-primary">IPM</span>
        <span className="hidden text-xs text-text-muted lg:inline">
          Credit Portfolio Intelligence &amp; Monitoring
        </span>
      </Link>

      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link href="/?focus=ask" title="Ask IPM a question (Ctrl+K)">
            <Sparkles aria-hidden />
            Ask IPM
            <kbd className="ml-1 hidden rounded border border-border px-1 text-[10px] text-text-muted sm:inline">
              ⌘K
            </kbd>
          </Link>
        </Button>
        <RoleSwitcher />
        <BackendStatusIndicator />
      </div>
    </header>
  );
}
