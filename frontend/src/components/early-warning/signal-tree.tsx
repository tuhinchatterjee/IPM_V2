"use client";

import * as React from "react";
import { ChevronRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type {
  EarlyWarningV2BorrowerTree,
  EarlyWarningV2LayerNode,
  EarlyWarningV2SubCategoryNode,
} from "@/lib/api";

/**
 * Layer → sub-category → signal, expand/collapse.
 *
 * Tab 14 of the workbook is explicit about the reading convention: "collapse
 * anything green; open anything amber or rust". So every sub-category starts
 * collapsed except HIGH/VERY_HIGH ones — a reader lands straight on what
 * needs attention rather than having to open eight nodes to find it.
 *
 * This is a strict hierarchy, not a network — a nested list is the right
 * shape, not the heavier React-Flow graph pattern `reasoning-map.tsx` uses
 * for genuine relationship graphs.
 */

const BAND_VARIANT: Record<string, "negative" | "warning" | "info" | "positive" | "default"> = {
  VERY_HIGH: "negative",
  HIGH: "warning",
  MEDIUM: "info",
  LOW: "default",
  VERY_LOW: "positive",
};

const BAND_LABEL: Record<string, string> = {
  VERY_HIGH: "Very High",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  VERY_LOW: "Very Low",
};

const LAYER_LABEL: Record<string, string> = {
  L1: "Layer 1 — Behavioural",
  L2: "Layer 2 — Financial & Structural",
  L3: "Layer 3 — External Intelligence",
  L4: "Layer 4 — Network & Connected Risk",
};

const OPEN_BY_DEFAULT = new Set(["HIGH", "VERY_HIGH"]);

/**
 * Whether a sub-category code is on the Classifier side (L2.1-L2.7, L4.4)
 * rather than the Trigger & Accelerator side (L1.x, L2.T1/T2, L3.x, L4.1-3).
 * A Classifier sub-category is a structural reading from bands and
 * overrides, not something a trigger fires into — the empty state reads
 * differently for the two, or "no signal fired" misreads a classifier
 * reading already in force as a missing observation.
 */
function isClassifierSubCategory(code: string): boolean {
  return /^L2\.\d/.test(code) || code === "L4.4";
}

export function SignalTree({ tree }: { tree: EarlyWarningV2BorrowerTree }) {
  return (
    <div className="space-y-3">
      {tree.tree.map((layer) => (
        <LayerRow key={layer.layer} layer={layer} />
      ))}
      {tree.external_events.length > 0 && (
        <Card className="p-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
            Layer 3 external events this period
          </p>
          <ul className="space-y-1 text-xs">
            {tree.external_events.map((event, i) => (
              <li key={i} className="flex items-center gap-2 text-text-secondary">
                <span className="flex-1 truncate">
                  {String(event.trigger_code ?? "event")}
                </span>
                {event.scenario_status && (
                  <Badge variant="outline" className="shrink-0">
                    synthetic
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function LayerRow({ layer }: { layer: EarlyWarningV2LayerNode }) {
  const [open, setOpen] = React.useState(
    layer.sub_categories.some((s) => OPEN_BY_DEFAULT.has(s.band)),
  );

  return (
    <Card className="overflow-hidden p-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-surface-hover"
      >
        <ChevronRight
          className={cn("size-3.5 shrink-0 text-text-muted transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <span className="flex-1 text-sm font-medium text-text-primary">
          {LAYER_LABEL[layer.layer] ?? layer.layer}
        </span>
        {layer.ta_score !== undefined && (
          <span className="text-xs text-text-secondary">T&amp;A {layer.ta_score.toFixed(1)}</span>
        )}
        {layer.c_score !== undefined && (
          <span className="text-xs text-text-secondary">C {layer.c_score.toFixed(1)}</span>
        )}
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-border p-2.5 pl-7">
          {layer.sub_categories.map((sub) => (
            <SubCategoryRow key={sub.code} sub={sub} />
          ))}
        </div>
      )}
    </Card>
  );
}

function SubCategoryRow({ sub }: { sub: EarlyWarningV2SubCategoryNode }) {
  const [open, setOpen] = React.useState(OPEN_BY_DEFAULT.has(sub.band));

  return (
    <div className="rounded-md border border-border/70 bg-surface-sunken">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
      >
        <ChevronRight
          className={cn("size-3 shrink-0 text-text-muted transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-text-primary">
          {sub.name}
        </span>
        <span className="shrink-0 text-xs tabular text-text-muted">{sub.score.toFixed(1)}</span>
        <Badge variant={BAND_VARIANT[sub.band] ?? "default"} className="shrink-0">
          {BAND_LABEL[sub.band] ?? sub.band}
        </Badge>
      </button>
      {open && (
        <div className="space-y-2 border-t border-border/70 px-2.5 py-2 pl-5">
          <p className="text-xs leading-relaxed text-text-secondary">{sub.reason}</p>
          {sub.signals.length > 0 ? (
            <ul className="space-y-1">
              {sub.signals.map((signal) => (
                <li
                  key={`${signal.signal_key}-${signal.causal_chain_id}`}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <span className="min-w-0 flex-1 truncate text-text-secondary">
                    {signal.signal_key}
                  </span>
                  <span className="shrink-0 tabular text-text-muted">
                    {signal.signal_score.toFixed(1)}
                  </span>
                </li>
              ))}
            </ul>
          ) : isClassifierSubCategory(sub.code) ? (
            <p className="text-xs text-text-muted">
              Structural reading, not a fired trigger — this score comes
              from the classifier&rsquo;s own bands and overrides.
            </p>
          ) : (
            <p className="text-xs text-text-muted">No signal fired here this period.</p>
          )}
        </div>
      )}
    </div>
  );
}
