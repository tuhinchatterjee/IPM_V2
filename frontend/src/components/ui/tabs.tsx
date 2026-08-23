"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Underline tabs.
 *
 * Deliberately not pill-shaped buttons: an underline reads as navigation within
 * a page, which is what these are, and it keeps the surface calm on a screen
 * that already carries a lot of numbers.
 */
interface TabsProps {
  tabs: { id: string; label: string; count?: number }[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, active, onChange, className }: TabsProps) {
  return (
    <div className={cn("flex gap-1 overflow-x-auto border-b border-border", className)} role="tablist">
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.id)}
            className={cn(
              "relative whitespace-nowrap px-3 py-2.5 text-sm font-medium transition-colors",
              isActive
                ? "text-text-primary"
                : "text-text-muted hover:text-text-secondary",
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-1.5 text-xs text-text-muted tabular">{tab.count}</span>
            )}
            {isActive && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />
            )}
          </button>
        );
      })}
    </div>
  );
}
