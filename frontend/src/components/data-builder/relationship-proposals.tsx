"use client";

import * as React from "react";
import { Check, Loader2, Sparkles, TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ApiError,
  api,
  type RelationshipProposal,
  type RelationshipProposals,
} from "@/lib/api";

/**
 * Proposed joins for one dataset.
 *
 * The assistant searches for columns that could be a key and measures how much
 * of the left-hand book actually finds a match on the right. It never declares
 * anything: accepting a proposal creates a DRAFT, and a steward still has to
 * measure it and activate it before the planner will join on it.
 *
 * That separation is the whole point. Coverage says two columns line up.
 * Whether `account_id` in a bank's own extract means the same thing as
 * `account_id` in the facility book is a question about the bank's systems, and
 * a product that answers it on the bank's behalf is guessing with their book.
 */

const CARDINALITY_LABEL: Record<string, string> = {
  one_to_one: "1 : 1",
  many_to_one: "many : 1",
  one_to_many: "1 : many",
  many_to_many: "many : many",
};

export function RelationshipProposalsPanel({
  datasets,
  onAccepted,
}: {
  datasets: string[];
  onAccepted: () => void;
}) {
  const [dataset, setDataset] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [found, setFound] = React.useState<RelationshipProposals | null>(null);
  const [accepted, setAccepted] = React.useState<Set<string>>(new Set());

  const key = (p: RelationshipProposal) =>
    `${p.from_dataset}.${p.from_field}->${p.to_dataset}.${p.to_field}`;

  async function search(name: string) {
    setDataset(name);
    setFound(null);
    setAccepted(new Set());
    setError("");
    if (!name) return;
    setBusy("search");
    try {
      setFound(await api.proposeRelationships(name));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  async function accept(proposal: RelationshipProposal) {
    setBusy(key(proposal));
    setError("");
    try {
      await api.acceptRelationshipProposal(proposal);
      setAccepted((current) => new Set(current).add(key(proposal)));
      onAccepted();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That did not work.");
    } finally {
      setBusy("");
    }
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
          <Sparkles className="size-3.5" aria-hidden />
          Find joins for a dataset
        </p>
        <select
          value={dataset}
          onChange={(e) => search(e.target.value)}
          aria-label="Dataset to find joins for"
          className="h-8 rounded-md border border-border bg-surface px-2 text-xs text-text-primary"
        >
          <option value="">Choose a dataset…</option>
          {datasets.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        {busy === "search" && (
          <Loader2 className="size-3.5 animate-spin text-text-muted" aria-hidden />
        )}
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
        CreditProbe looks for columns that could be a key and measures how much of
        the book each one actually matches. It proposes; it does not declare.
        Accepting one creates a draft that still has to be measured and activated
        before the planner will join on it.
      </p>

      {error && <p className="mt-2 text-xs text-negative">{error}</p>}

      {found && found.candidates.length === 0 && (
        <p className="mt-3 text-xs text-text-muted">
          Nothing in {found.dataset} matches another governed dataset well enough
          to propose — either everything it joins to is already declared, or no
          shared column covers at least{" "}
          {(found.minimum_coverage * 100).toFixed(0)}% of its rows.
        </p>
      )}

      {found && found.candidates.length > 0 && (
        <ul className="mt-3 space-y-2">
          {found.candidates.map((proposal) => {
            const id = key(proposal);
            const done = accepted.has(id);
            return (
              <li
                key={id}
                className="rounded-md border border-border p-2.5"
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <code className="font-mono text-[11px] text-text-primary">
                    {proposal.from_dataset}.{proposal.from_field}
                    <span className="px-1 text-text-muted">→</span>
                    {proposal.to_dataset}.{proposal.to_field}
                  </code>
                  <Badge
                    variant={proposal.safe_to_join ? "outline" : "warning"}
                    className="text-[10px]"
                  >
                    {CARDINALITY_LABEL[proposal.cardinality] ?? proposal.cardinality}
                  </Badge>
                  <span className="tabular text-[10px] text-text-muted">
                    {(proposal.match_rate * 100).toFixed(1)}% matched
                  </span>
                  {done ? (
                    <span className="ml-auto flex items-center gap-1 text-[11px] text-positive">
                      <Check className="size-3" aria-hidden />
                      saved as a draft
                    </span>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="ml-auto"
                      onClick={() => accept(proposal)}
                      disabled={busy !== ""}
                    >
                      {busy === id && <Loader2 className="animate-spin" aria-hidden />}
                      Accept as a draft
                    </Button>
                  )}
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
                  {!proposal.safe_to_join && (
                    <TriangleAlert
                      className="mr-1 inline size-3 align-[-2px] text-warning"
                      aria-hidden
                    />
                  )}
                  {proposal.why}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
