"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import * as React from "react";
import {
  ArrowLeft,
  BadgeCheck,
  Download,
  GitBranch,
  Loader2,
  PlayCircle,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { CaseVerdict, LifecycleMark } from "@/components/studio/lifecycle";
import { useCanRunAnalysis, useRole } from "@/components/system/role-switcher";
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
import { Tabs } from "@/components/ui/tabs";
import {
  ApiError,
  api,
  type StudioConcept,
  type StudioMethod,
  type StudioPeriodAlignment,
  type StudioRelationshipNeed,
  type StudioValidationPack,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * One method, and everything the tick rests on.
 *
 * The tabs follow the questions a reviewer asks, in order: what does it
 * measure, how is it computed, what proves it, and who signed it off. The plan
 * is shown as the operations the runtime will execute rather than as prose —
 * "TOP_N over group by sector" is checkable and "ranks the largest sectors" is
 * not.
 */
export default function MethodPage() {
  const params = useParams<{ methodId: string }>();
  const methodId = decodeURIComponent(params.methodId);
  const router = useRouter();
  const { role } = useRole();
  const canRun = useCanRunAnalysis();

  const [tab, setTab] = React.useState("about");
  const [live, setLive] = React.useState<StudioMethod | null>(null);
  const [pack, setPack] = React.useState<StudioValidationPack | null>(null);
  const [busy, setBusy] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");

  const loaded = useAsync(() => api.studioMethod(methodId), [methodId]);
  const method = live ?? loaded.data?.method ?? null;

  async function act(what: string, run: () => Promise<void>) {
    setBusy(what);
    setError("");
    setMessage("");
    try {
      await run();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy("");
    }
  }

  const revalidate = () =>
    act("validate", async () => {
      const body = await api.studioValidate(methodId);
      setLive(body.method);
      setPack(body.validation);
      setTab("proof");
      setMessage(
        body.validation.all_passed
          ? `All ${body.validation.passed} cases agree with the independent calculation.`
          : `${body.validation.failed} case(s) disagree. One of the two is wrong.`,
      );
    });

  const certify = () =>
    act("certify", async () => {
      const body = await api.studioCertify(methodId, role);
      setLive(body.method);
      setMessage("Certified. The version and the person who signed it off are recorded.");
    });

  const fork = () =>
    act("fork", async () => {
      const body = await api.studioFork(methodId, `${method?.name ?? methodId} (bank variant)`);
      router.push(`/studio/${encodeURIComponent(body.method.id)}`);
    });

  if (loaded.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (loaded.error || !method) {
    return <p className="text-sm text-negative">{loaded.error ?? "No such method."}</p>;
  }

  const operations = (method.plan?.operations ?? []) as Record<string, unknown>[];

  return (
    <div className="space-y-6">
      <PageHeader
        title={method.name}
        eyebrow="Analysis Studio"
        description={method.definition}
        status="live"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" asChild>
              <Link href="/studio">
                <ArrowLeft aria-hidden />
                Library
              </Link>
            </Button>
            {method.plan && canRun && (
              <>
                <Button variant="outline" onClick={revalidate} disabled={busy !== ""}>
                  {busy === "validate" ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <PlayCircle aria-hidden />
                  )}
                  Run validation pack
                </Button>
                <Button variant="outline" asChild>
                  <a href={api.studioValidationPackUrl(method.id)}>
                    <Download aria-hidden />
                    Download pack
                  </a>
                </Button>
                <Button variant="outline" onClick={fork} disabled={busy !== ""}>
                  <GitBranch aria-hidden />
                  Fork
                </Button>
              </>
            )}
            {method.can_certify && !method.is_certified && role === "ADMIN" && (
              <Button onClick={certify} disabled={busy !== ""}>
                <BadgeCheck aria-hidden />
                Certify
              </Button>
            )}
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <LifecycleMark lifecycle={method.lifecycle} label={method.lifecycle_label} />
        <Badge variant="outline">{method.category}</Badge>
        <span className="tabular text-xs text-text-muted">v{method.version}</span>
        <span className="text-xs text-text-muted">
          {method.source === "bank" ? "This bank's own method" : "CreditProbe library"}
        </span>
        {method.forked_from && (
          <span className="text-xs text-text-muted">
            Forked from{" "}
            <Link
              href={`/studio/${encodeURIComponent(method.forked_from)}`}
              className="underline"
            >
              {method.forked_from}
            </Link>
          </span>
        )}
      </div>

      {message && <p className="text-sm text-positive">{message}</p>}
      {error && <p className="text-sm text-negative">{error}</p>}

      {!method.is_certified && method.certification_gaps.length > 0 && (
        <Card className="p-4">
          <p className="text-sm font-medium text-text-primary">
            What this method still needs before it can be certified
          </p>
          <ul className="mt-2 list-inside list-disc space-y-1 text-xs text-text-secondary">
            {method.certification_gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </Card>
      )}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "about", label: "What it measures" },
          { id: "data", label: "What it needs" },
          { id: "plan", label: "How it is computed", count: operations.length || undefined },
          { id: "proof", label: "Proof", count: method.test_cases.length || undefined },
          { id: "governance", label: "Governance" },
        ]}
      />

      {tab === "about" && (
        <Card className="space-y-5 p-5">
          <Prose label="Definition" text={method.definition} />
          <Prose label="Purpose" text={method.purpose} />
          <Prose label="Methodology" text={method.methodology} />
          <Prose label="When to use it" text={method.when_to_use} />
          <Prose label="When NOT to use it" text={method.when_not_to_use} />
          <Prose label="How to read the result" text={method.interpretation} />
          <Prose
            label="What it does not tell you"
            text={method.limitations}
            emphasis
          />
        </Card>
      )}

      {tab === "data" && (
        <Card className="space-y-5 p-5">
          <Prose label="Required grain" text={method.required_grain} />
          <Prose label="Required history" text={method.required_history} />
          <Concepts values={method.required_concepts ?? []} />
          <RelationshipNeeds values={method.required_relationships ?? []} />
          <PeriodAlignment alignment={method.period_alignment ?? {}} />
          <Chips label="Governed domains" values={method.required_domains} />
          <Chips label="Governed fields" values={method.required_fields} />
          <Chips label="Weighting options" values={method.weighting_options} />
          <Chips label="Applicable segments" values={method.applicable_segments} />
          <Chips label="Also known as" values={method.aliases} />
        </Card>
      )}

      {tab === "plan" && (
        <Card className="p-5">
          {method.engine_analysis && (
            <p className="mb-4 text-sm text-text-secondary">
              Implemented by the certified engine analysis{" "}
              <Link
                href={`/engine-builder/${method.engine_analysis}`}
                className="font-mono underline"
              >
                {method.engine_analysis}
              </Link>
              .
            </p>
          )}
          {operations.length === 0 ? (
            <p className="text-sm text-text-muted">
              This is a definition. Nobody has built it yet, and the Studio says so rather than
              implying an implementation exists.
            </p>
          ) : (
            <>
              <p className="mb-4 text-xs leading-relaxed text-text-muted">
                The analytical plan, step by step. The runtime compiles this into one
                parameterised statement — every value bound, nothing concatenated — which is why a
                composed analysis is safe to execute.
              </p>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-10">#</TableHead>
                    <TableHead>Step</TableHead>
                    <TableHead>Operation</TableHead>
                    <TableHead>Reads</TableHead>
                    <TableHead>Parameters</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {operations.map((op, index) => (
                    <TableRow key={String(op.id ?? index)}>
                      <TableCell className="tabular text-xs text-text-muted">
                        {index + 1}
                      </TableCell>
                      <TableCell className="font-mono text-xs">{String(op.id ?? "")}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{String(op.op ?? "")}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-text-muted">
                        {((op.inputs as string[]) ?? []).join(", ") || "—"}
                      </TableCell>
                      <TableCell className="max-w-lg break-all font-mono text-[11px] text-text-muted">
                        {JSON.stringify(op.params ?? {})}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}
        </Card>
      )}

      {tab === "proof" && (
        <Card className="p-5">
          {method.test_cases.length === 0 ? (
            <p className="text-sm text-text-muted">
              No test cases. A method nobody has run against anything cannot be certified, whoever
              asks.
            </p>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-center gap-4 text-sm">
                <span className="text-positive">{method.tests_passing} passed</span>
                {method.tests_failing > 0 && (
                  <span className="text-negative">{method.tests_failing} failed</span>
                )}
                <span className="text-text-muted">
                  {method.test_cases.length} cases in total
                </span>
                {pack?.ran_at && (
                  <span className="text-xs text-text-muted">Run at {pack.ran_at}</span>
                )}
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Case</TableHead>
                    <TableHead>Why it is contentious</TableHead>
                    <TableHead>Expected</TableHead>
                    <TableHead>Result</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {method.test_cases.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell className="align-top text-xs font-medium text-text-primary">
                        {c.name}
                      </TableCell>
                      <TableCell className="max-w-md align-top text-xs text-text-muted">
                        {c.purpose}
                      </TableCell>
                      <TableCell className="max-w-xs break-all align-top font-mono text-[11px] text-text-muted">
                        {JSON.stringify(c.expected)}
                      </TableCell>
                      <TableCell className="align-top">
                        <CaseVerdict passed={c.passed} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {pack?.sql && (
                <div className="mt-6">
                  <p className="text-xs font-medium text-text-secondary">
                    The statement the fixture was run through
                  </p>
                  <pre className="mt-2 max-h-72 overflow-auto rounded-md border border-border bg-surface-sunken p-3 font-mono text-[11px] leading-relaxed text-text-secondary">
                    {pack.sql}
                  </pre>
                  <p className="mt-2 text-[11px] text-text-muted">
                    {pack.parameters.length} bound parameter
                    {pack.parameters.length === 1 ? "" : "s"}: {JSON.stringify(pack.parameters)}
                  </p>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {tab === "governance" && (
        <Card className="space-y-5 p-5">
          <Prose label="Owner" text={method.owner} />
          <Prose label="Certified at" text={method.certified_at || "Not certified"} />
          <Prose label="Certified by" text={method.certified_by || "—"} />
          <Prose
            label="Fingerprint"
            text={method.fingerprint}
            hint="A hash of what this method computes — the plan and the governed fields. Renaming a method does not change it, so two methods computing the same thing under different names are visible as such."
          />
          <div>
            <p className="mb-2 text-xs font-medium text-text-secondary">Version history</p>
            {method.versions.length === 0 ? (
              <p className="text-sm text-text-muted">
                Version {method.version} is the first. Editing a certified method starts a new one
                and leaves the signed-off version standing.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Version</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>Change</TableHead>
                    <TableHead>Certified by</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {method.versions.map((v) => (
                    <TableRow key={v.version}>
                      <TableCell className="tabular text-xs">v{v.version}</TableCell>
                      <TableCell>
                        <LifecycleMark lifecycle={v.lifecycle} compact />
                      </TableCell>
                      <TableCell className="max-w-lg text-xs text-text-muted">
                        {v.change_note}
                      </TableCell>
                      <TableCell className="text-xs text-text-muted">
                        {v.certified_by || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

function Prose({
  label,
  text,
  hint,
  emphasis,
}: {
  label: string;
  text: string;
  hint?: string;
  emphasis?: boolean;
}) {
  if (!text) return null;
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary">{label}</p>
      <p
        className={`mt-1 whitespace-pre-line text-sm leading-relaxed ${
          emphasis ? "text-text-primary" : "text-text-secondary"
        }`}
      >
        {text}
      </p>
      {hint && <p className="mt-1 text-[11px] leading-relaxed text-text-muted">{hint}</p>}
    </div>
  );
}

/**
 * What the method measures, in concepts rather than columns.
 *
 * The dataset and field it resolved to are shown as the answer on the day it
 * was saved, not as the definition. A method that stored `ifrs9_staging.ead`
 * breaks the day a bank supplies its own extract under another column name;
 * one that stores "exposure at default" re-resolves against whatever the
 * catalogue declares authoritative when it next runs.
 */
function Concepts({ values }: { values: StudioConcept[] }) {
  if (!values.length) return null;
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary">
        Semantic concepts it measures
      </p>
      <ul className="mt-1.5 space-y-2">
        {values.map((c) => (
          <li key={c.concept}>
            <p className="text-sm text-text-primary">
              {c.label}
              {c.unit && <span className="ml-1.5 text-xs text-text-muted">{c.unit}</span>}
            </p>
            <p className="text-[11px] leading-relaxed text-text-muted">
              Resolved to{" "}
              <code className="font-mono text-text-secondary">
                {c.dataset}.{c.field}
              </code>
              {c.definition && ` — ${c.definition}`}
            </p>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
        Stored as concepts, so the method re-resolves against whatever the
        catalogue declares authoritative when it next runs.
      </p>
    </div>
  );
}

/**
 * The governed joins the method depends on.
 *
 * A steward re-declaring one of these changes what the method means without
 * changing a character of its plan, which is why the version is recorded.
 */
function RelationshipNeeds({ values }: { values: StudioRelationshipNeed[] }) {
  if (!values.length) return null;
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary">
        Governed relationships it walks
      </p>
      <ul className="mt-1.5 space-y-1">
        {values.map((r) => (
          <li key={r.relationship_id} className="text-[11px] leading-relaxed">
            <code className="font-mono text-text-secondary">
              {r.left} → {r.right}
            </code>
            <span className="ml-1.5 text-text-muted">
              {r.cardinality.replace(/_/g, " ")} · {r.join_policy} · v{r.version}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** How periods were reconciled across sources of different frequency. */
function PeriodAlignment({ alignment }: { alignment: StudioPeriodAlignment }) {
  if (!alignment.description) return null;
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary">Period alignment</p>
      <p className="mt-1 text-sm leading-relaxed text-text-secondary">
        {alignment.description}.
      </p>
      {alignment.opening_period && alignment.closing_period && (
        <p className="mt-1 text-[11px] text-text-muted">
          Saved from a run measuring {alignment.opening_period} against{" "}
          {alignment.closing_period}.
        </p>
      )}
    </div>
  );
}

function Chips({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary">{label}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {values.map((v) => (
          <Badge key={v} variant="outline" className="font-mono text-[11px]">
            {v}
          </Badge>
        ))}
      </div>
    </div>
  );
}
