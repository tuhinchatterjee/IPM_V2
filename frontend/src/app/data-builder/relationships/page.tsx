"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Loader2, Share2 } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, api, type RelationshipEdge } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

const CARDINALITY_LABEL: Record<string, string> = {
  one_to_one: "1 : 1",
  many_to_one: "many : 1",
  one_to_many: "1 : many",
  many_to_many: "many : many",
};

/**
 * The relationship map.
 *
 * Grouped by the dataset everything hangs off rather than drawn as a free
 * canvas, because the honest shape of a credit book is a hub: the facility
 * position, the customer, and the reporting period, with everything else
 * attached to one of them. A force-directed picture of the same thing looks
 * more impressive and tells a reader less.
 *
 * Every dataset shows its grain. "One row per what" is the question a
 * relationship map is usually being consulted to answer, and two boxes joined
 * by a line whose grain nobody states is a picture rather than a model.
 */
export default function RelationshipMapPage() {
  const [nonce, setNonce] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const canEdit = useCanEditData();
  const map = useAsync(() => api.relationshipMap(), [nonce]);

  const nodes = map.data?.nodes ?? [];
  const edges = map.data?.edges ?? [];
  const byName = new Map(nodes.map((n) => [n.name, n]));

  // Every dataset something joins TO. These are the hubs, and everything else
  // is a spoke off one of them.
  const hubs = Array.from(new Set(edges.map((e) => e.to_dataset))).sort(
    (a, b) =>
      edges.filter((e) => e.to_dataset === b).length -
      edges.filter((e) => e.to_dataset === a).length,
  );

  async function seed() {
    setBusy(true);
    setError("");
    try {
      await api.seedRelationships();
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Relationship Map"
        eyebrow="Data Builder"
        description="Every governed dataset and every declared join between them, with the cardinality that makes a join safe. A relationship is what lets an analysis carry a customer's sector onto its facilities — and getting a cardinality wrong is how a join silently multiplies a book."
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

      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="Governed datasets" value={nodes.length} />
        <Tile label="Declared joins" value={edges.length} />
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
        <Skeleton className="h-64 w-full" />
      ) : map.error ? (
        <Card className="border-negative/40 p-4 text-sm text-negative">{map.error}</Card>
      ) : edges.length === 0 ? (
        <Card className="p-8 text-center text-sm text-text-muted">
          No relationships are declared yet. A steward can declare the shipped joins above, or
          define one by hand from a dataset page.
        </Card>
      ) : (
        <div className="space-y-6">
          {hubs.map((hub) => {
            const spokes = edges.filter((e) => e.to_dataset === hub);
            const node = byName.get(hub);
            return (
              <section key={hub}>
                <div className="mb-2.5 flex flex-wrap items-baseline gap-2">
                  <h2 className="font-mono text-sm font-semibold text-text-primary">{hub}</h2>
                  {node?.grain && (
                    <span className="text-xs text-text-muted">{node.grain}</span>
                  )}
                  {node?.authoritative_for?.length ? (
                    <Badge variant="info">authoritative</Badge>
                  ) : null}
                </div>
                <Card>
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead>Joins from</TableHead>
                        <TableHead>On</TableHead>
                        <TableHead>Cardinality</TableHead>
                        <TableHead>Why</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {spokes.map((edge) => (
                        <Spoke key={edge.id} edge={edge} grain={byName.get(edge.from_dataset)?.grain} />
                      ))}
                    </TableBody>
                  </Table>
                </Card>
              </section>
            );
          })}

          {(map.data?.unconnected.length ?? 0) > 0 && (
            <section>
              <h2 className="meta mb-2.5 text-text-muted">Joined to nothing</h2>
              <Card className="p-4">
                <p className="mb-2 text-xs leading-relaxed text-text-muted">
                  These are readable by name and nothing carries an attribute onto them. That
                  is a legitimate state for a reference table and a gap for anything else.
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
      )}
    </div>
  );
}

function Spoke({ edge, grain }: { edge: RelationshipEdge; grain?: string }) {
  return (
    <TableRow>
      <TableCell className="align-top">
        <span className="block font-mono text-xs text-text-primary">{edge.from_dataset}</span>
        {grain && <span className="mt-0.5 block text-[11px] text-text-muted">{grain}</span>}
      </TableCell>
      <TableCell className="align-top font-mono text-xs text-text-muted">
        {edge.from_field} = {edge.to_field}
      </TableCell>
      <TableCell className="align-top">
        <Badge variant={edge.kind === "reporting_period" ? "outline" : "default"}>
          {CARDINALITY_LABEL[edge.cardinality] ?? edge.cardinality}
        </Badge>
      </TableCell>
      <TableCell className="max-w-xl align-top text-xs text-text-muted">
        {edge.description}
      </TableCell>
    </TableRow>
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
