"use client";

/**
 * Corporate / Retail, for the workspaces outside the Cockpit home. The same
 * two books and the same meaning as the Cockpit's own switch: choosing one
 * opens that book's release, never a filter over the other.
 */

import type { DomainId } from "@/lib/workspace/objects";
import { cn } from "@/lib/utils";

export function DomainSwitchPlain({ value, onChange }: { value: DomainId; onChange: (d: DomainId) => void }) {
  return (
    <div role="radiogroup" aria-label="Book" className="inline-flex rounded-lg border border-border p-0.5 text-sm" data-testid="ws-domain-switch" data-domain={value}>
      {(["corporate", "retail"] as const).map((d) => (
        <button
          key={d}
          type="button"
          role="radio"
          aria-checked={value === d}
          onClick={() => onChange(d)}
          className={cn("rounded-md px-3 py-1 capitalize", value === d ? "bg-accent text-accent-contrast" : "text-text-secondary hover:bg-surface-hover")}
          data-testid={`ws-domain-${d}`}
        >
          {d}
        </button>
      ))}
    </div>
  );
}
