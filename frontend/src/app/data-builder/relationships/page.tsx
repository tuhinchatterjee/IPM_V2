"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Loader2, Search, Share2 } from "lucide-react";

import { RelationshipCanvas } from "@/components/data-builder/relationship-canvas";
import { RelationshipInspector } from "@/components/data-builder/relationship-inspector";
import { PageHeader } from "@/components/layout/page-header";
import { useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, type RelationshipEdge } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const CARDINALITY_LABEL: Record<string, string> = {
  one_to_one: "1 : 1",
  many_to_one: "many : 1",
  one_to_many: "1 : many",
  many_to_many: "many : many",
};

/**
 * The relationship map.
 *
 * This is the one place the relationship model is edited and the one place the
 * planner reads from — there is no second relationship system anywhere in the
 * product. A join drawn here is a join an analysis may use; a join that is not
 * ACTIVE here is one the runtime will refuse, and the map says which is which
 * rather than drawing them alike.
 *
 * The canvas answers "what connects to what". The list beside it answers
 * "which join, exactly" — a canvas is bad at being searched and a table is bad
 * at showing shape, so the page does both and keeps one selection between them.
 */
export default function RelationshipMapPage() {
  const [nonce, setNonce] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [selected, setSelected] = React.useState<number | null>(null);
  const [query, setQuery] = React.useState("");
  // A relationship changed by the inspector is patched in place rather than
  // refetched, so validating a join does not rebuild the canvas underneath the
  // steward's cursor.
  const [patched, setPatched] = React.useState<Record<number, RelationshipEdge>>({});
  const canEdit = useCanEditData();
  const map = useAsync(() => api.relationshipMap(), [nonce]);

  const nodes = map.data?.nodes ?? [];
  const edges = React.useMemo(
    () => (map.data?.edges ?? []).map((e) => patched[e.id] ?? e),
    [map.data, patched],
  );
  const chosen = edges.find((e) => e.id === selected) ?? null;

  const matches = React.useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return edges;
    return edges.filter((e) =>
      [e.from_dataset, e.to_dataset, e.from_field, e.to_field, e.semantic, e.description]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [edges, query]);

  async function seed() {
    setBusy(true);
    setError("");
    try {
      await api.seedRelationships();
      setPatched({});
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  const runnable = edges.filter((e) => e.is_runnable).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Relationship Map"
        eyebrow="Data Builder"
        description="Every governed dataset and every declared join between them. This is the model the analytical planner reads: a question that needs two datasets is answered by walking these edges, so a cardinality declared wrongly here is how a book gets silently multiplied there."
        status="live"
        actions={
          <div className="flex gap-2">
            {canEdit && (
              <Button variant="outline" onClick={seed} disabled={busy}>
                {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Share2 aria-hidden />}
                Declare the shipped joins
              </Button>
            )}
            <Button variant="ghost" asChild>
              <Link href="/data-builder">
                <ArrowLeft aria-hidden />
                Data Builder
              </Link>
            </Button>
          </div>
        }
      />

      {error && <p className="text-sm text-negative">{error}</p>}

      <div className="grid gap-3 sm:grid-cols-4">
        <Tile label="Governed datasets" value={nodes.length} />
        <Tile label="Declared joins" value={edges.length} />
        <Tile
          label="The planner may use"
          value={runnable}
          note={
            runnable < edges.length
              ? `${edges.length - runnable} declared but not active.`
              : "Every declared join is active."
          }
        />
        <Tile
          label="Not joined to anything"
          value={map.data?.unconnected.length ?? 0}
          note={
            (map.data?.unconnected.length ?? 0) > 0
              ? "Readable by name, but nothing carries an attribute onto them."
              : undefined
          }
        />
      </div>

      {map.loading && !map.data ? (
        <Skeleton className="h-[560px] w-full" />
      ) : map.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">{map.error}</Card>
      ) : edges.length === 0 ? (
        <Card className="p-8 text-center text-sm text-text-muted">
          No relationships are declared yet. A steward can declare the shipped joins above, or
          define one by hand from a dataset page.
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <Card className="overflow-hidden p-0">
            <RelationshipCanvas
              nodes={nodes}
              edges={edges}
              selectedEdge={selected}
              onSelectEdge={setSelected}
            />
          </Card>

          <div className="min-h-0 lg:h-[560px]">
            {chosen ? (
              <RelationshipInspector
                key={chosen.id}
                edge={chosen}
                canValidate={canEdit}
                canPromote={canEdit}
                onChanged={(updated) =>
                  setPatched((current) => ({ ...current, [updated.id]: updated }))
                }
              />
            ) : (
              <Card className="flex h-full flex-col overflow-hidden">
                <div className="border-b border-border px-3 py-2.5">
                  <label className="flex items-center gap-2">
                    <Search className="size-3.5 shrink-0 text-text-muted" aria-hidden />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Find a join"
                      className="w-full bg-transparent text-xs text-text-primary outline-none placeholder:text-text-muted"
                    />
                  </label>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {matches.length === 0 ? (
                    <p className="p-4 text-xs text-text-muted">
                      Nothing matches &ldquo;{query}&rdquo;.
                    </p>
                  ) : (
                    <ul className="divide-y divide-border">
                      {matches.map((edge) => (
                        <li key={edge.id}>
                          <button
                            type="button"
                            onClick={() => setSelected(edge.id)}
                            className="w-full px-3 py-2 text-left transition-colors hover:bg-surface-hover"
                          >
                            <p className="font-mono text-[11px] leading-snug text-text-primary">
                              {edge.from_dataset}
                              <span className="px-1 text-text-muted">→</span>
                              {edge.to_dataset}
                            </p>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5">
                              <Badge
                                variant={
                                  edge.cardinality === "many_to_many" ? "warning" : "outline"
                                }
                                className="text-[10px]"
                              >
                                {CARDINALITY_LABEL[edge.cardinality] ?? edge.cardinality}
                              </Badge>
                              {edge.join_policy === "asof" && (
                                <Badge variant="info" className="text-[10px]">
                                  as-of
                                </Badge>
                              )}
                              <span
                                className={cn(
                                  "text-[10px]",
                                  edge.is_runnable ? "text-text-muted" : "text-warning",
                                )}
                              >
                                {edge.lifecycle_label || edge.lifecycle}
                              </span>
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <p className="border-t border-border px-3 py-2 text-[10px] leading-relaxed text-text-muted">
                  Click a line on the map or a row here to inspect a join: what it means, what
                  the data says about it, and who moved it to its current state.
                </p>
              </Card>
            )}
          </div>
        </div>
      )}

      {(map.data?.unconnected.length ?? 0) > 0 && (
        <section>
          <h2 className="meta mb-2.5 text-text-muted">Joined to nothing</h2>
          <Card className="p-4">
            <p className="mb-2 text-xs leading-relaxed text-text-muted">
              These are readable by name and nothing carries an attribute onto them. That is a
              legitimate state for a reference table and a gap for anything else.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {map.data?.unconnected.map((name) => (
                <Badge key={name} variant="outline" className="font-mono text-[11px]">
                  {name}
                </Badge>
              ))}
            </div>
          </Card>
        </section>
      )}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: number; note?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-text-muted">{label}</p>
      <p className="tabular mt-1 text-2xl font-semibold text-text-primary">{value}</p>
      {note && <p className="mt-1 text-[11px] leading-snug text-text-muted">{note}</p>}
    </Card>
  );
}
