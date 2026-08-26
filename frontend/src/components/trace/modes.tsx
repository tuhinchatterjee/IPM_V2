"use client";

import * as React from "react";
import { GitBranch, Layers, List } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The three ways to read a Trace.
 *
 * One dataset, three shapes — because "how was this produced?" is asked by
 * three different people for three different reasons, and no single view serves
 * all of them.
 *
 *   LINEAGE    an analyst asking how the answer was assembled. A graph, which
 *              is the right shape for structure and dependency.
 *   LANDSCAPE  a CRO asking how far this travelled from the data and where it
 *              struggled. Depth carries that at a glance.
 *   AUDIT      an auditor recording that they checked it. A list, in order,
 *              quotable line by line — and the view that works without sight.
 *
 * Switching is instant and preserves the selection, so following a node from
 * the graph into the ledger keeps it selected in both.
 */

export type TraceMode = "lineage" | "landscape" | "audit";

const MODES: { id: TraceMode; label: string; hint: string; icon: typeof Layers }[] = [
  {
    id: "lineage",
    label: "Lineage",
    hint: "How the answer was assembled, as a graph",
    icon: GitBranch,
  },
  {
    id: "landscape",
    label: "Landscape",
    hint: "How far it travelled from the data, in depth",
    icon: Layers,
  },
  {
    id: "audit",
    label: "Audit",
    hint: "Every step in order, as a list",
    icon: List,
  },
];

const STORAGE_KEY = "creditprobe.trace.mode";

/**
 * The chosen mode, remembered.
 *
 * An auditor who works in Audit mode should not have to choose it on every
 * Trace they open. Read once on mount rather than during render, so the server
 * and the client agree on the first paint.
 */
export function useTraceMode(): [TraceMode, (mode: TraceMode) => void] {
  // The stored choice is external state the server cannot know, so it is read
  // through useSyncExternalStore rather than assigned from an effect: the
  // server renders "lineage", the client swaps to the remembered mode on
  // hydration, and neither ever renders markup the other disagrees with.
  const stored = React.useSyncExternalStore(subscribe, readStored, () => "lineage" as TraceMode);
  const [override, setOverride] = React.useState<TraceMode | null>(null);

  const choose = React.useCallback((next: TraceMode) => {
    setOverride(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
      window.dispatchEvent(new Event(CHANGED));
    } catch {
      // A browser with site data blocked still gets a working Trace; it just
      // opens on Lineage every time. Not remembering is a smaller failure
      // than not switching.
    }
  }, []);

  return [override ?? stored, choose];
}

const CHANGED = "creditprobe:trace-mode";

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function readStored(): TraceMode {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    if (value === "lineage" || value === "landscape" || value === "audit") {
      return value;
    }
  } catch {
    // Fall through to the default.
  }
  return "lineage";
}

export function ModeSwitcher({
  mode,
  onChange,
  className,
}: {
  mode: TraceMode;
  onChange: (mode: TraceMode) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label="How to read this Trace"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-lg border border-border",
        "bg-surface-sunken p-0.5",
        className,
      )}
    >
      {MODES.map(({ id, label, hint, icon: Icon }) => {
        const active = mode === id;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active}
            title={hint}
            onClick={() => onChange(id)}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-2.5 py-1",
              "text-[0.6875rem] font-medium",
              "transition-colors duration-[--duration-instant]",
              active
                ? "bg-surface text-text-primary shadow-[var(--shadow-raised)]"
                : "text-text-muted hover:text-text-secondary",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {label}
          </button>
        );
      })}
    </div>
  );
}
