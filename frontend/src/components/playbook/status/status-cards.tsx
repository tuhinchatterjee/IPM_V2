"use client";

import * as React from "react";

import { StatusChip } from "@/components/playbook/status/chips";
import type { PbDashboard } from "@/lib/api";
import { ragLabel, statusCards } from "@/lib/intelligence";
import { cn } from "@/lib/utils";

/**
 * The summary row. §8.
 *
 * Completion and readiness sit side by side and are never combined: §9 is
 * explicit, and the reason is that a document can be 95% written and
 * nowhere near ready. Each card is a button, because a count nobody can act
 * on is a count nobody reads twice.
 */
export function StatusCards({
  dashboard,
  onOpenTab,
}: {
  dashboard: PbDashboard;
  onOpenTab: (tab: string) => void;
}) {
  const cards = statusCards(dashboard);
  return (
    <ul
      className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4"
      data-testid="playbook-status-cards"
    >
      {cards.map((card) => (
        <li key={card.id}>
          <button
            type="button"
            onClick={() => onOpenTab(card.tab)}
            data-testid={`playbook-card-${card.id}`}
            className={cn(
              "flex h-full w-full flex-col items-start gap-1 rounded-lg border",
              "border-border bg-surface p-3 text-left transition-colors",
              "hover:bg-surface-hover focus-visible:outline-2",
              "focus-visible:outline-offset-2 focus-visible:outline-accent",
            )}
          >
            <span className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
              {card.label}
            </span>
            <span className="text-lg font-semibold leading-none tabular-nums text-text-primary">
              {card.value}
            </span>
            {card.tone === "unknown" ? (
              <span className="text-[11px] leading-snug text-text-muted">
                {card.detail}
              </span>
            ) : (
              <StatusChip tone={card.tone} title={ragLabel(card.tone)}>
                {card.detail}
              </StatusChip>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
