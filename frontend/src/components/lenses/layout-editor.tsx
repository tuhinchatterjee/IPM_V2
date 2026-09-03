"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Loader2, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type LensPanel,
  type LensSection,
  type RenderedLens,
} from "@/lib/api";

/**
 * Arranging a lens by hand.
 *
 * The conversational path already existed; this is the same thing without
 * having to describe it. What matters is that it is not a second way in: the
 * layout is submitted whole to `PUT /lenses/{id}/layout`, which runs the same
 * validation and writes the same kind of revision as a change made by asking.
 * A tile moved by hand is refused for the reasons a tile added by asking is,
 * and either can be put back.
 *
 * How a tile is drawn is offered from the metric's own declaration, not from
 * the platform's list of chart types. A ratio rendered as a line of one point
 * looks like a working tile and misleads, so the choices here are the ones the
 * definition says are honest — and the server checks again, because a select
 * element is a convenience and never a control.
 */

/**
 * How an ANALYSIS panel may be drawn.
 *
 * Metric tiles do not use this: each metric declares what it can honestly be
 * shown as, and that declaration is what the select offers. An analysis panel
 * has no such declaration yet, so the platform's list stands in — and the
 * server validates either way.
 */
const ANALYSIS_VISUALS = ["kpi", "table", "bar", "line", "matrix"];

interface Draft {
  key: string;
  kind: LensPanel["kind"];
  analysis_id: string;
  metric_id: string;
  title: string;
  visual: string;
  params: Record<string, unknown>;
  filters: Record<string, unknown>;
  period: string;
  note: string;
  /** How this tile may honestly be drawn. Empty means the platform's list. */
  visuals: string[];
  /** What it is called when the person has not renamed it. */
  fallback: string;
}

export function LayoutEditor({
  lensId,
  rendered,
  onSaved,
  onCancel,
}: {
  lensId: number;
  rendered: RenderedLens;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [tiles, setTiles] = React.useState<Draft[]>(() =>
    rendered.panels.map((panel, index) => ({
      key: `${panel.kind}:${panel.metric_id || panel.analysis_id}:${index}`,
      kind: panel.kind,
      analysis_id: panel.analysis_id,
      metric_id: panel.metric_id,
      title: panel.title,
      visual: panel.visual,
      params: panel.params,
      filters: panel.filters,
      period: panel.period,
      note: panel.note,
      visuals: panel.metric?.visuals ?? [],
      fallback: panel.metric?.name || panel.analysis_id || panel.metric_id,
    })),
  );
  const [bands, setBands] = React.useState<LensSection[]>(() =>
    (rendered.sections ?? []).map((section) => ({ ...section })),
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // A band holds positions, so moving one tile has to move the positions the
  // bands hold with it — otherwise a reorder silently re-bands its neighbour.
  function reband(size: number, moved: Map<number, number>) {
    setBands((current) =>
      current.map((band) => ({
        ...band,
        panels: band.panels
          .map((index) => (moved.has(index) ? moved.get(index)! : index))
          .filter((index) => index >= 0 && index < size)
          .sort((a, b) => a - b),
      })),
    );
  }

  function move(index: number, by: number) {
    const to = index + by;
    if (to < 0 || to >= tiles.length) return;
    const next = [...tiles];
    [next[index], next[to]] = [next[to], next[index]];
    setTiles(next);
    reband(next.length, new Map([[index, to], [to, index]]));
  }

  function remove(index: number) {
    const next = tiles.filter((_, i) => i !== index);
    const moved = new Map<number, number>([[index, -1]]);
    for (let i = index + 1; i < tiles.length; i += 1) moved.set(i, i - 1);
    setTiles(next);
    reband(next.length, moved);
  }

  function update(index: number, patch: Partial<Draft>) {
    setTiles(tiles.map((tile, i) => (i === index ? { ...tile, ...patch } : tile)));
  }

  function putInBand(index: number, band: number) {
    setBands(
      bands.map((existing, i) => ({
        ...existing,
        panels:
          i === band
            ? [...existing.panels.filter((p) => p !== index), index].sort(
                (a, b) => a - b,
              )
            : existing.panels.filter((p) => p !== index),
      })),
    );
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.setLensLayout(lensId, {
        tiles: tiles.map((tile) => ({
          kind: tile.kind,
          analysis_id: tile.analysis_id,
          metric_id: tile.metric_id,
          title: tile.title,
          visual: tile.visual,
          params: tile.params,
          filters: tile.filters,
          period: tile.period,
          note: tile.note,
        })),
        // A band that has lost every tile is dropped rather than saved empty:
        // an untitled band with nothing in it renders as a gap on the lens.
        sections: bands.filter((band) => band.panels.length > 0),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const bandOf = (index: number) =>
    bands.findIndex((band) => band.panels.includes(index));

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-text-primary">
          Arrange this lens
        </h2>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-muted">
          Reorder the tiles, band them, rename them, choose how each is drawn.
          Saving writes a new version with a note saying what changed, and the
          one before it stays where it is.
        </p>
      </div>

      <ol className="divide-y divide-border rounded-md border border-border">
        {tiles.map((tile, index) => (
          <li key={tile.key} className="space-y-2 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-6 text-xs tabular text-text-muted">
                {index + 1}
              </span>
              <input
                value={tile.title}
                onChange={(e) => update(index, { title: e.target.value })}
                placeholder={tile.fallback}
                aria-label={`Title for ${tile.fallback}`}
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface px-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <Badge variant="outline">
                {tile.kind === "metric" ? "Metric" : "Analysis"}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => move(index, -1)}
                disabled={index === 0}
                aria-label={`Move ${tile.fallback} up`}
              >
                <ArrowUp aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => move(index, 1)}
                disabled={index === tiles.length - 1}
                aria-label={`Move ${tile.fallback} down`}
              >
                <ArrowDown aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => remove(index)}
                aria-label={`Remove ${tile.fallback}`}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-3 pl-8">
              <label className="text-[11px] text-text-muted">
                Drawn as
                <select
                  value={tile.visual}
                  onChange={(e) => update(index, { visual: e.target.value })}
                  aria-label={`How ${tile.fallback} is drawn`}
                  className="ml-1.5 h-7 rounded-md border border-border bg-surface px-1.5 text-xs text-text-primary focus:border-accent focus:outline-none"
                >
                  <option value="auto">auto</option>
                  {(tile.visuals.length ? tile.visuals : ANALYSIS_VISUALS)
                    .filter((visual) => visual !== "auto")
                    .map((visual) => (
                      <option key={visual} value={visual}>
                        {visual}
                      </option>
                    ))}
                </select>
              </label>

              {bands.length > 0 && (
                <label className="text-[11px] text-text-muted">
                  In band
                  <select
                    value={bandOf(index)}
                    onChange={(e) => putInBand(index, Number(e.target.value))}
                    aria-label={`Which band ${tile.fallback} is in`}
                    className="ml-1.5 h-7 rounded-md border border-border bg-surface px-1.5 text-xs text-text-primary focus:border-accent focus:outline-none"
                  >
                    <option value={-1}>—</option>
                    {bands.map((band, i) => (
                      <option key={band.title || i} value={i}>
                        {band.title || `Band ${i + 1}`}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {tile.visuals.length === 1 && (
                <span className="text-[11px] text-text-muted">
                  Only honest as a {tile.visuals[0]}.
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>

      {tiles.length === 0 && (
        <p className="text-xs text-warning">
          A lens needs at least one tile. Nothing will save while it is empty.
        </p>
      )}

      {error && (
        <p className="whitespace-pre-line text-xs text-negative">{error}</p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button size="sm" onClick={save} disabled={busy || tiles.length === 0}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          Save this arrangement
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}
