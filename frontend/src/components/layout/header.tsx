"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Sparkles } from "lucide-react";

import { BackendStatusIndicator } from "@/components/system/backend-status";
import { RoleSwitcher } from "@/components/system/role-switcher";
import { ThemeMenu } from "@/components/system/theme-menu";
import { Button } from "@/components/ui/button";

/**
 * Application header.
 *
 * Left: the product identity, set as a wordmark rather than a logo lockup.
 * Right, in order of how often it is touched: Ask IPM, the theme switcher, the
 * acting role, and the live backend status.
 *
 * The theme switcher lives here, one click from anywhere, because the room a
 * credit committee sits in changes more often than any setting on the Settings
 * page does.
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
      <Link href="/" className="group flex items-baseline gap-3">
        <span className="text-[15px] font-semibold tracking-[0.14em] text-text-primary">
          IPM
        </span>
        <span className="hidden text-[11px] uppercase tracking-[0.16em] text-text-muted lg:inline">
          Credit Portfolio Intelligence
        </span>
      </Link>

      <div className="flex items-center gap-2.5">
        <Button variant="outline" size="sm" asChild>
          <Link href="/?focus=ask" title="Ask IPM a question (Ctrl+K)">
            <Sparkles aria-hidden />
            Ask IPM
            <kbd className="ml-1 hidden rounded border border-border px-1 text-[10px] text-text-muted sm:inline">
              ⌘K
            </kbd>
          </Link>
        </Button>
        <ThemeMenu />
        <RoleSwitcher />
        <BackendStatusIndicator />
      </div>
    </header>
  );
}
