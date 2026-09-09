"use client";

import * as React from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  GripVertical,
  Loader2,
  Minus,
  Plus,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, type LensPanel, type RenderedLens, type RenderedPanel } from "@/lib/api";

/**
 * Rearranging a lens by hand, on the lens itself.
 *
 * §12–§17. The pencil turns the lens into an editable board: every card takes
 * a handle and a remove control, cards can be dragged into a new order, and a
 * metric can be added through exactly the same builder the creation flow uses.
 *
 * Three decisions worth stating:
 *
 * **The cards are the real cards.** Edit mode does not swap the rendered lens
 * for a list of titles. What is dragged is the tile with its number on it,
 * because the arrangement somebody is judging is the arrangement of the things
 * they can see — a list of names reordered well often looks wrong as tiles.
 *
 * **The wiggle is a state, not decoration.** It says "this is movable and
 * nothing here is saved yet", which is the one thing a person needs to know in
 * this mode. It is suppressed under `prefers-reduced-motion`, where the same
 * fact is carried by the outline and the handle.
 *
 * **Nothing is saved until Save.** Reordering and removing are local until
 * then, so a mis-drag costs nothing and Cancel is honest. The save goes
 * through `PUT /lenses/{id}/layout`, which is the same validated, versioned
 * path a change made by asking goes through — a tile moved by hand is refused
 * for the same reasons and can be put back the same way.
 */

export interface EditState {
  order: RenderedPanel[];
  dirty: boolean;
}

export function LensEditBar({
  editing,
  dirty,
  busy,
  onSave,
  onCancel,
  onAddMetric,
}: {
  editing: boolean;
  dirty: boolean;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
  onAddMetric: () => void;
}) {
  if (!editing) return null;
  return (
    <Card
      className="flex flex-wrap items-center gap-2 border-accent/40 bg-accent/5 p-3"
      data-testid="edit-bar"
    >
      <span className="text-xs font-medium text-text-primary">
        Editing this lens
      </span>
      <span className="text-[11px] text-text-muted">
        Drag a card by its handle to reorder. Nothing is saved until you save.
      </span>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" onClick={onAddMetric}
                data-testid="add-metric">
          <Plus aria-hidden />
          Add new metric
        </Button>
        <Button size="sm" onClick={onSave} disabled={busy || !dirty}
                data-testid="save-layout">
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          <X aria-hidden />
          Cancel
        </Button>
      </div>
    </Card>
  );
}

/**
 * One card in edit mode: the tile itself, plus a handle and a remove control.
 *
 * The remove asks first. A tile removed by a mis-click on a dense board is a
 * tile somebody has to remember the name of to put back, and the confirmation
 * costs one click on a deliberate removal.
 */
export function EditableCard({
  panel,
  index,
  onRemove,
  onDragStart,
  onDragOver,
  onDrop,
  onMove,
  first,
  last,
  dragging,
  children,
}: {
  panel: RenderedPanel;
  index: number;
  onRemove: () => void;
  onDragStart: () => void;
  onDragOver: (event: React.DragEvent) => void;
  onDrop: () => void;
  /** Move this card one place earlier (-1) or later (+1) in the order. */
  onMove: (step: -1 | 1) => void;
  first: boolean;
  last: boolean;
  dragging: boolean;
  children: React.ReactNode;
}) {
  const [confirming, setConfirming] = React.useState(false);
  const title = panel.title || panel.metric_id || panel.analysis_id;

  return (
    /*
      Two elements, and the split is not cosmetic. The draggable element is
      the outer one and it never moves: a browser will not begin a drag on an
      element whose own transform is animating, so a card that wiggled and
      was draggable in the same box was a card nobody could pick up. The
      wiggle lives one level in, on a wrapper that carries the whole visible
      card — outline, handle, tile — so what a person sees is unchanged and
      what the pointer grabs is a box that holds still.
    */
    <div
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      data-testid="editable-card"
      data-metric={panel.metric_id}
      data-position={index}
      className="relative"
    >
      <div
        className={`group relative block rounded-lg outline outline-2 outline-offset-2 transition-[outline-color] ${
          dragging ? "outline-accent opacity-50" : "outline-accent/30"
        } lens-wiggle`}
        /* Offset by position rather than by DOM index: the wiggling element
           is an only child now, so a nth-child rule would put every card in
           lockstep, which reads as one big shudder instead of a board of
           loose cards. */
        style={{ animationDelay: `-${((index % 3) * 0.14).toFixed(2)}s` }}
      >
        {/*
          The handle, and either side of it the same move as a button.
          Dragging is the fast way to rearrange and it is the only way if the
          handle is all there is — which leaves anybody working from a
          keyboard, or on a touch screen where a drag fights the scroll,
          unable to do the one thing this mode exists for.
        */}
        <div className="pointer-events-none absolute -left-2 -top-2 z-10 flex gap-1">
          <span
            aria-hidden
            className="pointer-events-auto flex size-6 cursor-grab items-center justify-center rounded-full border border-border bg-surface text-text-muted shadow-sm active:cursor-grabbing"
          >
            <GripVertical className="size-3.5" />
          </span>
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={first}
            aria-label={`Move ${title} earlier`}
            data-testid="move-earlier"
            className="pointer-events-auto flex size-6 items-center justify-center rounded-full border border-border bg-surface text-text-muted shadow-sm transition-colors hover:bg-surface-hover disabled:opacity-40"
          >
            <ChevronLeft className="size-3.5" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={last}
            aria-label={`Move ${title} later`}
            data-testid="move-later"
            className="pointer-events-auto flex size-6 items-center justify-center rounded-full border border-border bg-surface text-text-muted shadow-sm transition-colors hover:bg-surface-hover disabled:opacity-40"
          >
            <ChevronRight className="size-3.5" aria-hidden />
          </button>
        </div>
        <div className="absolute -right-2 -top-2 z-10">
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label={`Remove ${title}`}
            data-testid="remove-card"
            className="flex size-6 items-center justify-center rounded-full border border-negative/50 bg-surface text-negative shadow-sm transition-colors hover:bg-negative hover:text-white"
          >
            <Minus className="size-3.5" aria-hidden />
          </button>
        </div>

        {confirming && (
          <div
            className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 rounded-lg bg-surface/95 p-3 text-center"
            data-testid="remove-confirm"
          >
            <p className="text-xs text-text-primary">
              Remove {title} from this lens?
            </p>
            <p className="text-[11px] text-text-muted">
              It stays in the metric library and can be added again.
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setConfirming(false);
                  onRemove();
                }}
                data-testid="remove-confirm-yes"
              >
                Remove
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                Keep it
              </Button>
            </div>
          </div>
        )}

        {children}
      </div>
    </div>
  );
}

/** Turn rendered panels back into the tile shape the layout route takes. */
export function asTiles(panels: RenderedPanel[]): LensPanel[] {
  return panels.map((panel) => ({
    kind: panel.kind,
    analysis_id: panel.analysis_id,
    metric_id: panel.metric_id,
    title: panel.title,
    visual: panel.visual,
    params: panel.params,
    filters: panel.filters,
    period: panel.period,
    note: panel.note,
  }));
}

/**
 * Save an arrangement.
 *
 * Sections are deliberately not sent. A reorder that crosses a band boundary
 * has no correct band mapping to send — the tile is somewhere new — so the
 * lens keeps its tiles and loses its banding rather than being given a banding
 * nobody chose. The service re-sections on the next conversational change.
 */
export async function saveLayout(
  lensId: number,
  panels: RenderedPanel[],
  summary: string,
) {
  return api.setLensLayout(lensId, {
    tiles: asTiles(panels),
    change_summary: summary,
  });
}

export function describeChange(
  before: RenderedLens,
  after: RenderedPanel[],
): string {
  const was = before.panels.map((p) => p.metric_id || p.analysis_id);
  const now = after.map((p) => p.metric_id || p.analysis_id);
  const removed = was.filter((m) => !now.includes(m));
  const added = now.filter((m) => !was.includes(m));
  const parts: string[] = [];
  if (added.length) parts.push(`added ${added.join(", ")}`);
  if (removed.length) parts.push(`removed ${removed.join(", ")}`);
  if (!parts.length) return "Rearranged the cards by hand.";
  return `Edited by hand: ${parts.join("; ")}.`;
}
