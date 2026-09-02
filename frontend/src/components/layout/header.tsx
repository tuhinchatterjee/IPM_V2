"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { PanelLeft } from "lucide-react";

import { AiPowerControl } from "@/components/system/ai-power";
import { UnreadMessages } from "@/components/messages/badge";
import { NotificationCentre } from "@/components/collaboration/notifications";
import { PersonaliseControl } from "@/components/system/personalisation";
import { BackendStatusIndicator } from "@/components/system/backend-status";
import { DemoBadge } from "@/components/system/demo-mode";
import { RoleSwitcher } from "@/components/system/role-switcher";
import { ThemeMenu } from "@/components/system/theme-menu";

import { useNavState } from "./nav-state";

/**
 * Application header.
 *
 * Deliberately quiet: a navigation toggle, the wordmark, and the three controls
 * that change what you are looking at (theme, acting role, backend status). The
 * old "Ask CreditProbe" button has gone — asking now happens in a composer that
 * is present on the Cockpit, inside every Investigation and under every answer,
 * so a button that jumps you somewhere else to ask was one control too many.
 *
 * The theme switcher stays here, one click from anywhere, because the room a
 * credit committee sits in changes more often than any setting on the Settings
 * page does.
 *
 * The AI POWERED control is here for a different reason: a product that claims
 * to be AI-powered should be able to prove it from wherever the claim is being
 * read, and the proof should be one click away rather than filed under Settings.
 *
 * The notification bell is here for the same reason: work assigned to somebody
 * has to be visible from wherever they are, and each notification opens the
 * exact object rather than the list it lives in.
 */
export function Header() {
  const router = useRouter();
  const { collapsed, toggle } = useNavState();

  // Cmd/Ctrl+K is the expected shortcut for "ask something" in a modern tool,
  // and the Cockpit is where asking starts.
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
    <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-border bg-surface px-3">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={toggle}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
          className="flex size-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
        >
          <PanelLeft className="size-[15px]" aria-hidden />
        </button>
        <Link href="/" className="flex items-baseline gap-2 px-2">
          <span className="text-[14px] font-semibold tracking-[0.02em] text-text-primary">
            CreditProbe
            <span className="ml-1 text-accent">AI</span>
          </span>
        </Link>
      </div>

      <div className="flex items-center gap-1.5">
        <DemoBadge />
        <AiPowerControl />
        {/* §48: reachable from the screen you are on, not from a screen you
            have to go to — and deliberately out of the Cockpit, whose whole
            claim is that it opens on a question rather than on everything. */}
        <UnreadMessages />
        <NotificationCentre />
        <PersonaliseControl />
        <ThemeMenu />
        <RoleSwitcher />
        <BackendStatusIndicator />
      </div>
    </header>
  );
}
