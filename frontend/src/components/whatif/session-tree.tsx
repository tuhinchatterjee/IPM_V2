"use client";

/**
 * The What-If session as a scenario tree (§30): the original reported
 * baseline at the root, layered scenarios under their parent, method
 * re-runs as variants of the run they re-used, combined definitions marked
 * with their parts. Tick executed nodes to compare them.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { sarDelta } from "@/lib/viz/format";
import { wsGet, wsSend } from "@/lib/workspace/client";
import type { GovernedObject } from "@/lib/workspace/objects";
import { newWhatIfSession, whatIfSession } from "@/lib/workspace/runs";
import { withBack } from "@/lib/workspace/nav";

interface TreeNode {
  id: string;
  kind: "baseline" | "run";
  label: string;
  cohort?: string;
  entities?: number;
  state?: string;
  methods_ran?: string[];
  baseline_mode?: string;
  parent?: string;
  variant_of?: string;
  combined?: boolean;
  combined_from?: string[];
  result_id?: string;
  results?: Record<string, { change: string | null; change_pct: string | null }>;
  created_at?: number;
}

interface Tree {
  nodes: TreeNode[];
  edges: { from: string; to: string; kind: "baseline" | "layered" | "method_variant" }[];
}

export function SessionTree({ domain, refreshKey }: { domain: string; refreshKey: string }) {
  const router = useRouter();
  const [tree, setTree] = React.useState<Tree | null>(null);
  const [session, setSession] = React.useState("");
  const [chosen, setChosen] = React.useState<Set<string>>(new Set());
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    const sid = whatIfSession();
    wsGet<Tree>(`/whatif/tree?session_id=${encodeURIComponent(sid)}&domain=${domain}`)
      .then((t) => {
        setSession(sid);
        setTree(t);
      })
      .catch(() => setTree(null));
  }, [domain, refreshKey]);

  if (!tree || tree.nodes.length <= 1) return null;
  const root = tree.nodes.find((n) => n.id === "baseline")!;
  const toggle = (id: string) =>
    setChosen((p) => {
      const next = new Set(p);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function compare() {
    setError("");
    try {
      const c = await wsSend<GovernedObject>("/whatif/compare", { result_ids: [...chosen] });
      router.push(withBack(`/what-if/compare/${c.object_id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="space-y-2 rounded-xl border border-border bg-surface-raised p-3" data-testid="whatif-tree" data-session-id={session} data-nodes={tree.nodes.length - 1}>
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Scenario tree — this session</h3>
        <span className="text-xs text-text-muted">baseline → scenarios → layered · method variants under the run they re-used</span>
        <button type="button" disabled={chosen.size < 2} onClick={() => void compare()} className="ml-auto rounded-md bg-accent px-2 py-1 text-xs text-accent-contrast disabled:opacity-40" data-testid="tree-compare">
          Compare {chosen.size || ""}
        </button>
        <button
          type="button"
          onClick={() => {
            newWhatIfSession();
            setChosen(new Set());
            setTree(null);
          }}
          className="rounded-md border border-border px-2 py-1 text-xs"
          data-testid="tree-new-session"
          title="Start a new session: the next run is not asked about earlier ones"
        >
          New session
        </button>
      </header>
      {error && (
        <p role="alert" className="text-xs text-negative" data-testid="tree-error">
          {error}
        </p>
      )}
      <ul className="space-y-1">
        <Node n={root} depth={0} tree={tree} chosen={chosen} toggle={toggle} />
      </ul>
    </section>
  );
}

function Node({ n, depth, tree, chosen, toggle }: { n: TreeNode; depth: number; tree: Tree; chosen: Set<string>; toggle: (id: string) => void }) {
const byId = new Map(tree.nodes.map((x) => [x.id, x]));
const children = (id: string, kind?: string) =>
  tree.edges
    .filter((e) => e.from === id && (!kind || e.kind === kind))
    .map((e) => byId.get(e.to))
    .filter((x): x is TreeNode => Boolean(x));
  const variants = children(n.id, "method_variant");
  const layered = children(n.id).filter((c) => !variants.includes(c));
  return (
    <li className="space-y-1" style={{ marginLeft: depth ? 16 : 0 }} data-testid="tree-node" data-node-id={n.id} data-parent={n.parent ?? ""} data-variant-of={n.variant_of ?? ""}>
      {n.kind === "baseline" ? (
        <div className="text-xs font-semibold">{n.label}</div>
      ) : (
        <div className="flex flex-wrap items-center gap-2 rounded border border-border bg-surface p-1.5 text-xs">
          {n.result_id && (
            <input
              type="checkbox"
              checked={chosen.has(n.result_id)}
              onChange={() => toggle(n.result_id!)}
              data-testid="tree-compare-pick"
              data-result-id={n.result_id}
              aria-label={`compare ${n.label}`}
            />
          )}
          <span className="font-medium">{n.label}</span>
          {n.variant_of && <span className="rounded bg-surface-sunken px-1">method variant</span>}
          {n.baseline_mode === "PRIOR_SCENARIO" && <span className="rounded bg-surface-sunken px-1">layered</span>}
          {n.combined && <span className="rounded bg-surface-sunken px-1">combined: {n.combined_from?.join(" + ")}</span>}
          <span className="text-text-muted">
            {n.entities} exposures · {n.state} · {n.methods_ran?.join("+") || "no method yet"}
          </span>
          {Object.entries(n.results ?? {}).map(([m, r]) => (
            <span key={m} className="tabular">
              {m} {r.change ? sarDelta(Number(r.change)) : "—"}
            </span>
          ))}
          {n.result_id ? (
            <Link data-testid="tree-result-link" href={withBack(`/what-if/result/${n.result_id}`)} className="text-accent underline">
              result
            </Link>
          ) : (
            <Link data-testid="tree-open-run" href={withBack(`/what-if?run=${n.id}`)} className="text-accent underline">
              open run
            </Link>
          )}
        </div>
      )}
      {(variants.length > 0 || layered.length > 0) && (
        <ul className="space-y-1">
          {[...variants, ...layered].map((c) => (
            <Node key={c.id} n={c} depth={depth + 1} tree={tree} chosen={chosen} toggle={toggle} />
          ))}
        </ul>
      )}
    </li>
  );
}
