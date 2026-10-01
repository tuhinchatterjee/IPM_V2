"use client";

/**
 * The governance Trace of one workspace object: integrity first (content
 * hashes re-verified, each record's link in the tenant's hash chain), then
 * versions, lineage to the roots, the event log (comments, shares, run
 * decisions, Lens refreshes, alert transitions) and the LLM exchanges behind
 * it. Reading it makes no model call and changes nothing.
 */

import * as React from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, ShieldAlert, ShieldCheck, Upload } from "lucide-react";

import { ExportPackage } from "@/components/workspace/export-package";
import { readTrace, shortHash, verifyLedger, verifyPackage, type LedgerLink, type LedgerReport, type ObjectTrace, type PackageReport } from "@/lib/workspace/trace";

const OPEN_HREF: Record<string, (id: string) => string> = {
  scenario_result: (id) => `/what-if/result/${id}`,
  comparison: (id) => `/what-if/compare/${id}`,
  scenario: (id) => `/scenarios/${id}`,
  lens: (id) => `/lenses/${id}`,
  run: (id) => `/what-if?run=${id}`,
  cohort: (id) => `/what-if?cohort=${id}`,
  alert: (id) => `/monitoring?alert=${id}`,
  metric: (id) => `/metrics?m=${id}`,
};

const when = (t: number | null | undefined) => (t ? new Date(t * 1000).toISOString().replace("T", " ").slice(0, 19) + "Z" : "—");

function Link_({ link }: { link: LedgerLink | null | undefined }) {
  if (!link) return <span className="text-negative">not in ledger</span>;
  const ok = link.links && link.row_matches;
  return (
    <span className={ok ? "text-positive" : "text-negative"} title={`record ${link.record_hash}\nchain ${link.chain_hash}`} data-ledger-ok={String(ok)}>
      #{link.seq} {ok ? "✓" : "✗"}
      {link.backfilled ? " (backfilled)" : ""}
    </span>
  );
}

export function ObjectTraceView({ objectId }: { objectId: string }) {
  const [trace, setTrace] = React.useState<ObjectTrace | null>(null);
  const [error, setError] = React.useState("");
  const [ledger, setLedger] = React.useState<LedgerReport | null>(null);
  const [pkg, setPkg] = React.useState<PackageReport | null>(null);
  const [busy, setBusy] = React.useState("");

  React.useEffect(() => {
    let live = true;
    readTrace(objectId)
      .then((t) => live && setTrace(t))
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [objectId]);

  if (error) return <p role="alert" className="text-sm text-negative">{error}</p>;
  if (!trace)
    return (
      <p className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Reading the Trace…
      </p>
    );
  const open = OPEN_HREF[trace.kind]?.(trace.object_id);
  const ok = trace.integrity.ok;
  return (
    <div className="space-y-5" data-testid="object-trace" data-kind={trace.kind} data-integrity={String(ok)}>
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-text-muted">Trace · {trace.kind.replace(/_/g, " ")}</p>
        <h1 className="text-xl font-semibold text-text-primary">{trace.title || trace.object_id}</h1>
        <p className="text-xs text-text-muted">
          {trace.object_id} v{trace.version} · owner {trace.owner_id} · {trace.release_id || "no release"}
          {trace.period ? ` · ${trace.period}` : ""} · {trace.status || "—"} {trace.seeded ? "· SYNTHETIC DEMO" : ""}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {open && (
            <Link href={open} className="rounded-md bg-accent px-2 py-1 text-xs text-accent-contrast" data-testid="trace-open-object">
              Open
            </Link>
          )}
          <ExportPackage objectId={trace.object_id} testId="trace-export" />
        </div>
      </header>

      <section className={`rounded-xl border p-3 text-sm ${ok ? "border-positive" : "border-negative"}`} data-testid="trace-integrity">
        <p className="flex items-center gap-2 font-semibold">
          {ok ? <ShieldCheck className="h-4 w-4 text-positive" /> : <ShieldAlert className="h-4 w-4 text-negative" />}
          {ok ? "Integrity verified" : "Integrity problem"}
        </p>
        <p className="mt-1 text-xs text-text-secondary">
          {trace.integrity.content_hashes_verified} version(s) re-hashed on read · {trace.integrity.ledger_links} record(s) linked in the tenant ledger
          {trace.integrity.unledgered ? ` · ${trace.integrity.unledgered} not in the ledger` : ""}
          {trace.integrity.broken ? ` · ${trace.integrity.broken} broken` : ""}. {trace.integrity.note}
        </p>
        {Object.keys(trace.digests).length > 0 && (
          <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
            {Object.entries(trace.digests).map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="text-text-muted">{k.replace(/_/g, " ")}</dt>
                <dd className="font-mono" title={v}>
                  {shortHash(v)}
                </dd>
              </div>
            ))}
          </dl>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            disabled={busy === "ledger"}
            onClick={() => {
              setBusy("ledger");
              verifyLedger()
                .then(setLedger)
                .catch((e: unknown) => setError(String(e)))
                .finally(() => setBusy(""));
            }}
            className="rounded-md border border-border px-2 py-1"
            data-testid="trace-verify-ledger"
          >
            Verify the whole tenant ledger
          </button>
          {ledger && (
            <span className={ledger.ok ? "text-positive" : "text-negative"} data-testid="trace-ledger-result" data-ok={String(ledger.ok)}>
              {ledger.ok ? <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" /> : null}
              {ledger.entries} entries, chain head {shortHash(ledger.chain_head)}
              {ledger.problem_count ? ` · ${ledger.problem_count} problem(s): ${ledger.problems.slice(0, 3).map((p) => `${p.problem} ${p.record_id}`).join("; ")}` : " · no problems"}
            </span>
          )}
          <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border px-2 py-1">
            <Upload className="h-3.5 w-3.5" /> Verify a package…
            <input
              type="file"
              accept=".zip,application/zip"
              className="sr-only"
              data-testid="trace-verify-package"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                setBusy("package");
                verifyPackage(f)
                  .then(setPkg)
                  .catch((err: unknown) => setError(String(err)))
                  .finally(() => setBusy(""));
              }}
            />
          </label>
          {pkg && (
            <span className={pkg.ok ? "text-positive" : "text-negative"} data-testid="trace-package-result" data-ok={String(pkg.ok)}>
              Package {pkg.ok ? "verified" : "NOT verified"}: {pkg.files_checked} files, {pkg.objects_checked} objects checked against the store
              {pkg.problems.length ? ` · ${pkg.problems.slice(0, 3).map((p) => `${p.problem} ${p.path}`).join("; ")}` : ""}
            </span>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">Versions</h2>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs" data-testid="trace-versions">
            <thead className="bg-surface-sunken text-left text-text-secondary">
              <tr>
                <th className="px-2 py-1.5">v</th>
                <th className="px-2 py-1.5">Status</th>
                <th className="px-2 py-1.5">Why</th>
                <th className="px-2 py-1.5">Content hash</th>
                <th className="px-2 py-1.5">Ledger</th>
                <th className="px-2 py-1.5">By</th>
                <th className="px-2 py-1.5">When</th>
              </tr>
            </thead>
            <tbody>
              {trace.versions.map((v) => (
                <tr key={v.version} className="border-t border-border" data-testid="trace-version">
                  <td className="px-2 py-1">{v.version}</td>
                  <td className="px-2 py-1">{v.status || "—"}</td>
                  <td className="px-2 py-1">{v.reason || v.operation || "—"}</td>
                  <td className="px-2 py-1 font-mono" title={v.content_hash}>
                    {shortHash(v.content_hash)}
                  </td>
                  <td className="px-2 py-1">
                    <Link_ link={v.ledger} />
                  </td>
                  <td className="px-2 py-1">{v.created_by}</td>
                  <td className="px-2 py-1 tabular">{when(v.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div>
          <h2 className="mb-2 text-sm font-semibold">Built from (to the roots)</h2>
          {trace.lineage.ancestors.length === 0 ? (
            <p className="text-xs text-text-muted">An original object: nothing it was derived from.</p>
          ) : (
            <ul className="space-y-1 text-xs" data-testid="trace-ancestors">
              {trace.lineage.ancestors.map((a) => (
                <li key={`${a.object_id}@${a.version}`} style={{ paddingLeft: `${(a.depth - 1) * 12}px` }}>
                  {a.readable ? (
                    <Link href={`/trace/object/${encodeURIComponent(a.object_id)}`} className="text-accent underline" data-testid="trace-ancestor">
                      {a.kind} · {a.title}
                    </Link>
                  ) : (
                    <span className="text-text-muted">{a.object_id} (not available to you)</span>
                  )}{" "}
                  <span className="text-text-muted">
                    v{a.version} {a.operation ? `· ${a.operation}` : ""} <span className="font-mono">{shortHash(a.content_hash)}</span>
                  </span>
                </li>
              ))}
              {trace.lineage.truncated && <li className="text-warning">Stopped at depth {trace.lineage.max_depth}.</li>}
            </ul>
          )}
        </div>
        <div>
          <h2 className="mb-2 text-sm font-semibold">Derived from this</h2>
          {trace.lineage.descendants.length === 0 ? (
            <p className="text-xs text-text-muted">Nothing has been derived from it yet.</p>
          ) : (
            <ul className="space-y-1 text-xs" data-testid="trace-descendants">
              {trace.lineage.descendants.map((d) => (
                <li key={`${d.object_id}@${d.version}`}>
                  <Link href={`/trace/object/${encodeURIComponent(d.object_id)}`} className="text-accent underline">
                    {d.kind} · {d.title}
                  </Link>{" "}
                  <span className="text-text-muted">
                    v{d.version} · {d.operation}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">What happened ({trace.events.length})</h2>
        {trace.events.length === 0 ? (
          <p className="text-xs text-text-muted">No comments, shares or state changes recorded.</p>
        ) : (
          <ol className="space-y-1 text-xs" data-testid="trace-events">
            {trace.events.map((e, i) => (
              <li key={i} className="flex flex-wrap gap-2 border-l-2 border-border pl-2" data-testid="trace-event" data-type={e.type}>
                <span className="tabular text-text-muted">{when(e.at)}</span>
                <span className="font-medium">{e.type.replace(/_/g, " ")}</span>
                <span>{e.detail}</span>
                <span className="text-text-muted">by {e.actor}</span>
                {"ledger" in e && <Link_ link={e.ledger} />}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">LLM exchanges behind it</h2>
        {trace.llm_exchange.threads.length === 0 ? (
          <p className="text-xs text-text-muted" data-testid="trace-llm-none">
            Not produced in a Cockpit conversation: no model call is behind this object.
          </p>
        ) : !trace.llm_exchange.visible ? (
          <p className="text-xs text-text-muted" data-testid="trace-llm-restricted">
            From Cockpit thread(s) {trace.llm_exchange.threads.join(", ")}. {trace.llm_exchange.note}
          </p>
        ) : (
          <table className="w-full text-xs" data-testid="trace-llm-calls">
            <thead className="text-left text-text-secondary">
              <tr>
                <th className="py-1">Run · call</th>
                <th>Purpose</th>
                <th>Model</th>
                <th>Status</th>
                <th>Canonical request hash</th>
              </tr>
            </thead>
            <tbody>
              {trace.llm_exchange.calls.map((c) => (
                <tr key={c.exchange_id} className="border-t border-border">
                  <td className="py-1">
                    <Link href={`/trace/llm-exchange/${c.run_id}`} className="text-accent underline">
                      {c.run_id.slice(0, 12)} · #{c.seq}
                    </Link>
                  </td>
                  <td>{c.purpose}</td>
                  <td>{c.model}</td>
                  <td>{c.status}</td>
                  <td className="font-mono" title={c.hashes.canonical_request}>
                    {shortHash(c.hashes.canonical_request)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <p className="text-[11px] text-text-muted">Opening this Trace made no model call and changed nothing.</p>
    </div>
  );
}
