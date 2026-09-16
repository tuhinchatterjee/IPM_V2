"use client";

import * as React from "react";
import { use } from "react";
import { useRouter } from "next/navigation";

import { DashboardHeader } from "@/components/playbook/status/header";
import { DecisionsTab } from "@/components/playbook/status/decisions-tab";
import { FindingsTab } from "@/components/playbook/status/findings-tab";
import { GovernDialog, type GovernField } from "@/components/playbook/status/govern-dialog";
import { HistoryTab } from "@/components/playbook/status/history-tab";
import { MetricsTab } from "@/components/playbook/status/metrics-tab";
import { PackTab } from "@/components/playbook/status/pack-tab";
import { ReadinessPanel } from "@/components/playbook/status/readiness-panel";
import { SectionsTab } from "@/components/playbook/status/sections-tab";
import { SinceTab } from "@/components/playbook/status/since-tab";
import { SourcesTab } from "@/components/playbook/status/sources-tab";
import { StatusCards } from "@/components/playbook/status/status-cards";
import { TabBoundary } from "@/components/playbook/status/tab-boundary";
import { UpdateReview } from "@/components/playbook/status/update-review";
import { BackLink } from "@/components/layout/back-link";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type PbAction,
  type PbDashboard,
  type PbFinding,
  type PbGovernedDecision,
  type PbHistoryFeed,
  type PbMetric,
  type PbSectionDetail,
  type PbUpdateProposal,
  type PbWorkspace,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { currentVersion } from "@/lib/playbook";
import { readDraft, saveDraft } from "@/lib/playbook-draft";
import { orderSections, resolveTab, tabsFor } from "@/lib/intelligence";
import { cn } from "@/lib/utils";

/**
 * Know the Status — the Document Intelligence dashboard.
 *
 * A route rather than a mode inside the thread, so it is linkable, and so the
 * browser's own Back works. What that costs is React state, which does not
 * survive a route change — so the composer draft, the chosen analyses and the
 * scroll position are carried in session storage and restored by the thread
 * on the way back. §6 requires that round trip to lose nothing.
 *
 * Every number on this page arrives computed. Nothing here derives a status,
 * a percentage or a judgement in the browser: §1 is explicit that status
 * comes from governed state, and a dashboard that did its own arithmetic
 * would be a second opinion nobody asked for.
 */
export default function PlaybookStatusPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const workspaceId = Number(id);
  const router = useRouter();

  const [refresh, setRefresh] = React.useState(0);
  const dashboard = useAsync<PbDashboard>(
    () => api.playbookDashboard(workspaceId),
    [workspaceId, refresh],
  );
  const workspace = useAsync<PbWorkspace>(
    () => api.playbookWorkspace(workspaceId),
    [workspaceId, refresh],
  );

  const data = dashboard.data;
  const committee = Boolean(data?.committee_report);
  const tabs = tabsFor(committee);

  // The tab the user was last on, remembered per document. Chosen is what
  // they clicked; the stored one is where they left off. Both are checked
  // against the agenda this document actually has, because a committee
  // document and a working paper do not have the same tabs and a remembered
  // "decisions" must not survive onto a document that has no such tab.
  const [chosenTab, setChosenTab] = React.useState("");
  const storedTab = React.useMemo(
    () => (typeof window === "undefined" ? "" : readDraft(workspaceId).tab),
    [workspaceId],
  );
  const known = (id: string) =>
    Boolean(id) && tabs.some((t) => t.id === id);
  const tab = known(chosenTab)
    ? chosenTab
    : known(storedTab ?? "")
      ? (storedTab as string)
      : "pack";

  const openTab = React.useCallback(
    (next: string) => {
      const resolved = resolveTab(next, committee);
      setChosenTab(resolved);
      saveDraft(workspaceId, { tab: resolved });
    },
    [committee, workspaceId],
  );

  // --- section detail ----------------------------------------------------
  // Which section is open. Derived rather than synchronised: until the user
  // picks one it is simply the first, which is a fact about the data and not
  // a piece of state that has to be kept in step with it.
  const [chosenSection, setChosenSection] = React.useState("");
  const sectionKey =
    chosenSection || orderSections(data?.sections ?? [])[0]?.section_key || "";
  const [sectionRefresh, setSectionRefresh] = React.useState(0);
  const section = useAsync<PbSectionDetail | null>(
    () =>
      sectionKey
        ? api.playbookSection(workspaceId, sectionKey)
        : Promise.resolve(null),
    [workspaceId, sectionKey, sectionRefresh],
  );

  // --- history -----------------------------------------------------------
  const [historyFilter, setHistoryFilter] = React.useState("");
  const history = useAsync<PbHistoryFeed>(
    () => api.playbookHistory(workspaceId, historyFilter),
    [workspaceId, historyFilter, refresh],
  );

  // --- transient state ---------------------------------------------------
  const [busy, setBusy] = React.useState(0);
  const [error, setError] = React.useState("");
  const [restoring, setRestoring] = React.useState(0);
  const [rereadingAll, setRereadingAll] = React.useState(false);
  const [checking, setChecking] = React.useState(false);
  const [proposal, setProposal] = React.useState<PbUpdateProposal | null>(null);
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [dialog, setDialog] = React.useState<DialogSpec | null>(null);

  const reload = () => setRefresh((n) => n + 1);

  /** Run one governed act: clear the error, mark busy, reload on success. */
  const act = async (id: number, run: () => Promise<unknown>) => {
    setBusy(id);
    setError("");
    try {
      await run();
      reload();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(0);
    }
  };

  /**
   * Take a dashboard object into the chat. §22.
   *
   * What travels is the OBJECT, in the URL: `?context=finding:786`. The
   * thread then asks the server for the context itself, which is the right
   * division — the server decides what is governed and what is only
   * suggested, and that judgement should not be made once and then carried
   * around in the browser.
   *
   * A link rather than storage, so the hand-over survives a reload, can be
   * sent to somebody, and does not depend on two pages agreeing about when a
   * piece of session state is consumed.
   */
  const bridge = (kind: string, target: string) => {
    const reference = target ? `${kind}:${target}` : kind;
    router.push(
      `/playbook/${workspaceId}?context=${encodeURIComponent(reference)}`,
    );
  };

  const checkForUpdates = async () => {
    setChecking(true);
    setError("");
    try {
      setProposal(await api.playbookCheckForUpdates(workspaceId));
      setReviewOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  };

  if (dashboard.loading || workspace.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (dashboard.error || !data) {
    return (
      <div className="space-y-4">
        <BackLink href={`/playbook/${workspaceId}`} label="Back to chat" />
        <p className="rounded-md border border-negative/40 bg-negative-muted p-4 text-sm text-negative">
          {dashboard.error ?? "This document has no status to show."}
        </p>
      </div>
    );
  }

  if (!data.available) {
    return (
      <div className="space-y-4">
        <BackLink href={`/playbook/${workspaceId}`} label="Back to chat" />
        <div className="rounded-lg border border-border bg-surface p-6">
          <h1 className="text-base font-semibold text-text-primary">
            {data.title}
          </h1>
          {/* §5: no zero-state statistics. A column of noughts describes a
              document that does not exist yet as though it were failing. */}
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-text-secondary">
            There is nothing to report yet. A status appears once this Playbook
            has a document, a tracked metric or a finding — the conversation is
            where the first of those gets made.
          </p>
        </div>
      </div>
    );
  }

  const artifacts = workspace.data?.artifacts ?? [];
  const report = artifacts.find((a) => a.kind === "report") ?? artifacts[0];
  const version = report ? currentVersion(report) : null;
  const file = version?.files.find((f) => f.format === "pdf")
    ?? version?.files[0]
    ?? null;

  return (
    <div className="space-y-5" data-testid="playbook-status-page">
      <BackLink href={`/playbook/${workspaceId}`} label="Back to chat" />

      {workspace.data?.demo && <Badge variant="warning">Synthetic data</Badge>}

      <DashboardHeader
        dashboard={data}
        workspaceId={workspaceId}
        onBack={() => router.push(`/playbook/${workspaceId}`)}
        onCheckForUpdates={checkForUpdates}
        checking={checking}
        latestDownload={
          file
            ? { href: `/api/v1${api.playbookDownloadPath(file.id)}`,
                format: file.format }
            : null
        }
      />

      <StatusCards dashboard={data} onOpenTab={openTab} />

      {error && (
        <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative"
          data-testid="playbook-dashboard-error">
          {error}
        </p>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <nav className="flex flex-wrap gap-1 border-b border-border"
            aria-label="Document intelligence" role="tablist">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                onClick={() => openTab(t.id)}
                data-testid={`playbook-tab-${t.id}`}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors",
                  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
                  tab === t.id
                    ? "border-accent text-accent"
                    : "border-transparent text-text-muted hover:text-text-secondary",
                )}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <TabBoundary name={tab}>
          {tab === "pack" && (
            <PackTab
              dashboard={data}
              onAsk={bridge}
              onUpdateSection={(key) => bridge("section", key)}
              onOpenSection={(key) => {
                setChosenSection(key);
                openTab("sections");
              }}
            />
          )}

          {tab === "findings" && (
            <FindingsTab
              findings={data.findings}
              busy={busy}
              error={error}
              onAsk={(findingId) => bridge("finding", String(findingId))}
              onAnswer={(finding) => setDialog(answerDialog(finding))}
              onMove={(finding, status) => setDialog(
                moveFindingDialog(finding, status))}
              onAssign={(finding) => setDialog(assignDialog(finding))}
              onAttachEvidence={(finding) => setDialog(evidenceDialog(finding))}
              onSetBlocking={(finding, blocking) =>
                setDialog(blockingDialog(finding, blocking))}
            />
          )}

          {tab === "decisions" && (
            <DecisionsTab
              decisions={data.decisions}
              actions={data.actions}
              findings={data.findings.items}
              busy={busy}
              error={error}
              onAsk={(decisionId) => bridge("decision", String(decisionId))}
              onMoveDecision={(decision, status) =>
                act(decision.id, () =>
                  api.playbookMoveDecision(workspaceId, decision.id,
                    { status }))}
              onRecord={(decision) => setDialog(recordDialog(decision))}
              onCreateActions={(decision) => setDialog(actionDialog(decision))}
              onMoveAction={(action, status) =>
                status === "completed"
                  ? setDialog(completeDialog(action))
                  : act(action.id, () =>
                      api.playbookMoveAction(workspaceId, action.id,
                        { status }))}
              onUpdateAction={(action) => setDialog(updateActionDialog(action))}
              onExportAction={(action) => setDialog(exportDialog(action))}
            />
          )}

          {tab === "since" && (
            <>
              <SinceTab
                since={data.since_last_time}
                onAsk={(metricId) => {
                  const match = data.metrics.inventory.find(
                    (m) => m.metric_id === metricId,
                  );
                  bridge("metric", String(match?.id ?? ""));
                }}
                onAskAll={() => bridge("since_last_time", "")}
              />
              <MetricsTab
                metrics={data.metrics}
                busy={busy}
                error={error}
                onConfirm={(metric) =>
                  act(metric.id, () =>
                    api.playbookDecideMetric(workspaceId, metric.id,
                      { action: "confirm" }))}
                onChange={(metric) => setDialog(mappingDialog(metric))}
                onIgnore={(metric) =>
                  act(metric.id, () =>
                    api.playbookDecideMetric(workspaceId, metric.id,
                      { action: "ignore" }))}
                onConfirmHighConfidence={() =>
                  act(-1, () =>
                    api.playbookConfirmMetrics(workspaceId,
                      { confidence: "high" }))}
                onConfirmSelected={(ids) =>
                  act(-1, () =>
                    api.playbookConfirmMetrics(workspaceId,
                      { binding_ids: ids }))}
                onAsk={(metric) => bridge("metric", String(metric.id))}
              />
            </>
          )}

          {tab === "sections" && (
            <>
              <SectionsTab
                dashboard={data}
                selected={sectionKey}
                detail={section.data ?? null}
                loading={section.loading}
                busy={busy !== 0}
                error={error}
                onSelect={setChosenSection}
                onAsk={(key) => bridge("section", key)}
                onUpdate={(key) => bridge("section", key)}
                onTransition={(key, status) =>
                  setDialog(sectionStatusDialog(key, status))}
                onAssignReviewer={(key) => setDialog(reviewerDialog(key))}
              />
              {committee && (
                <SourcesTab
                  sources={data.sources}
                  busy={busy}
                  error={error}
                  rereadingAll={rereadingAll}
                  onReread={(source) =>
                    act(source.source_id, () =>
                      api.playbookRereadSource(source.source_id))}
                  onRereadAll={async () => {
                    setRereadingAll(true);
                    await act(-1, () =>
                      api.playbookRereadStaleSources(workspaceId));
                    setRereadingAll(false);
                  }}
                />
              )}
            </>
          )}

          {tab === "sources" && (
            <SourcesTab
              sources={data.sources}
              busy={busy}
              error={error}
              rereadingAll={rereadingAll}
              onReread={(source) =>
                act(source.source_id, () =>
                  api.playbookRereadSource(source.source_id))}
              onRereadAll={async () => {
                setRereadingAll(true);
                await act(-1, () =>
                  api.playbookRereadStaleSources(workspaceId));
                setRereadingAll(false);
              }}
            />
          )}

          {tab === "history" && (
            <HistoryTab
              feed={history.data ?? null}
              artifacts={artifacts}
              loading={history.loading}
              filter={historyFilter}
              onFilter={setHistoryFilter}
              restoring={restoring}
              error={history.error ?? ""}
              onRestore={async (artifactId, v) => {
                setRestoring(v);
                await act(-1, () =>
                  api.restorePlaybookVersion(artifactId, v));
                setRestoring(0);
              }}
            />
          )}
          </TabBoundary>
        </div>

        <ReadinessPanel
          dashboard={data}
          onOpenTab={openTab}
          className="xl:sticky xl:top-4 xl:self-start"
        />
      </div>

      <UpdateReview
        open={reviewOpen}
        proposal={proposal}
        loading={checking}
        onClose={() => setReviewOpen(false)}
        onReviewChanges={(t) => {
          setReviewOpen(false);
          openTab(t);
        }}
        onRefreshSections={() => {
          setReviewOpen(false);
          bridge("stale_metrics", "");
        }}
        onRereadSources={async () => {
          setReviewOpen(false);
          setRereadingAll(true);
          await act(-1, () => api.playbookRereadStaleSources(workspaceId));
          setRereadingAll(false);
        }}
      />

      {dialog && (
        <GovernDialog
          open
          title={dialog.title}
          description={dialog.description}
          note={dialog.note}
          fields={dialog.fields}
          submitLabel={dialog.submitLabel}
          busy={busy !== 0}
          error={error}
          onClose={() => {
            setDialog(null);
            setError("");
          }}
          onSubmit={async (values) => {
            const ok = await act(dialog.id, () => dialog.submit(values));
            if (ok) {
              setDialog(null);
              if (dialog.reloadSection) setSectionRefresh((n) => n + 1);
            }
          }}
        />
      )}
    </div>
  );

  // -- dialog specifications ---------------------------------------------
  //
  // Each says what act it is, what it needs written down, and what the person
  // performing it is being told. They are defined here rather than inside the
  // tabs so that every governance act in the dashboard goes through one
  // component, with one discipline about required text.

  function answerDialog(finding: PbFinding): DialogSpec {
    return {
      id: finding.id,
      title: `Answer ${finding.reference || "this finding"}`,
      description: finding.title,
      note: "An answer is not a disposal. The finding stays open until somebody accepts, closes or defers it.",
      submitLabel: "Record the answer",
      fields: [{ name: "answer", label: "Answer", multiline: true,
        required: true, value: finding.answer }],
      submit: (v) =>
        api.playbookMoveFinding(workspaceId, finding.id,
          { status: "answered", answer: v.answer }),
    };
  }

  function moveFindingDialog(finding: PbFinding, status: string): DialogSpec {
    const verb = { accepted: "Accept", closed: "Close",
      deferred: "Defer" }[status] ?? "Move";
    return {
      id: finding.id,
      title: `${verb} ${finding.reference || "this finding"}`,
      description: finding.title,
      note: "This is recorded against your name, with the reason you give.",
      submitLabel: verb,
      fields: [{ name: "reason", label: "Reason", multiline: true,
        required: true,
        placeholder: "Why this finding can be disposed of" }],
      submit: (v) =>
        api.playbookMoveFinding(workspaceId, finding.id,
          { status, reason: v.reason }),
    };
  }

  function assignDialog(finding: PbFinding): DialogSpec {
    return {
      id: finding.id,
      title: "Assign an owner",
      description: finding.title,
      submitLabel: "Assign",
      fields: [{ name: "owner", label: "Owner", required: true,
        value: finding.owner,
        placeholder: "The person or team answerable for it" }],
      submit: (v) =>
        api.playbookAssignFinding(workspaceId, finding.id,
          { owner: v.owner }),
    };
  }

  function blockingDialog(finding: PbFinding, blocking: boolean): DialogSpec {
    return {
      id: finding.id,
      title: blocking ? "Make this finding blocking"
        : "Stop this finding blocking",
      description: finding.title,
      note: blocking
        ? "A blocking finding stops the pack being ready for approval until it is disposed of."
        : "The finding stays open; it will no longer stop approval.",
      submitLabel: blocking ? "Make blocking" : "Stop blocking",
      fields: [{ name: "reason", label: "Reason", multiline: true,
        required: true }],
      submit: (v) =>
        api.playbookSetFindingBlocking(workspaceId, finding.id,
          { blocking, reason: v.reason }),
    };
  }

  function evidenceDialog(finding: PbFinding): DialogSpec {
    return {
      id: finding.id,
      title: "Attach evidence",
      description: finding.title,
      note: "Recorded as you read them. Nothing here is recomputed, so the finding still reads correctly after the data moves on.",
      submitLabel: "Attach",
      fields: [
        { name: "locator", label: "Source locator",
          placeholder: "xlsx://Coverage!B12",
          value: "" },
        { name: "previous_value", label: "Previous value" },
        { name: "current_value", label: "Current value" },
        { name: "delta", label: "Change" },
        { name: "note", label: "Note", multiline: true },
      ],
      submit: (v) =>
        api.playbookAttachFindingEvidence(workspaceId, finding.id, v),
    };
  }

  function recordDialog(decision: PbGovernedDecision): DialogSpec {
    return {
      id: decision.id,
      title: `Record decision ${decision.reference}`,
      description: decision.question,
      note: "A committee decision is recorded against a person, with a time and a rationale. CreditProbe may draft the recommendation; it may not record this.",
      submitLabel: "Record the decision",
      fields: [
        { name: "outcome", label: "Outcome",
          options: (decision.options?.length
            ? decision.options
            : ["approve", "reject", "modify", "defer"]
          ).map((o) => ({ value: o,
            label: o[0].toUpperCase() + o.slice(1) })) },
        { name: "rationale", label: "Rationale", multiline: true,
          required: true },
        { name: "meeting", label: "Meeting",
          placeholder: "Credit Risk Committee, 20 September 2026" },
      ],
      submit: (v) =>
        api.playbookRecordDecision(workspaceId, decision.id, {
          outcome: v.outcome, rationale: v.rationale, meeting: v.meeting,
        }),
    };
  }

  function actionDialog(decision: PbGovernedDecision): DialogSpec {
    return {
      id: decision.id,
      title: "Add an action",
      description: decision.question,
      submitLabel: "Create",
      fields: [
        { name: "title", label: "What has to be done", required: true },
        { name: "description", label: "Detail", multiline: true },
        { name: "owner", label: "Owner" },
        { name: "due_date", label: "Due date", placeholder: "2026-12-31" },
      ],
      submit: (v) =>
        api.playbookCreateDecisionActions(workspaceId, decision.id, {
          actions: [{ title: v.title, description: v.description,
            owner: v.owner, due_date: v.due_date || null }],
        }),
    };
  }

  function completeDialog(action: PbAction): DialogSpec {
    return {
      id: action.id,
      title: "Complete this action",
      description: action.title,
      note: "Recorded against your name. CreditProbe may never mark an action done.",
      submitLabel: "Mark complete",
      fields: [{ name: "reason", label: "What was done", multiline: true,
        required: true }],
      submit: (v) =>
        api.playbookMoveAction(workspaceId, action.id,
          { status: "completed", reason: v.reason }),
    };
  }

  function updateActionDialog(action: PbAction): DialogSpec {
    return {
      id: action.id,
      title: "Add an update",
      description: action.title,
      note: "An update says where the action stands. It does not move it.",
      submitLabel: "Add",
      fields: [{ name: "note", label: "Update", multiline: true,
        required: true }],
      submit: (v) =>
        api.playbookUpdateAction(workspaceId, action.id, { note: v.note }),
    };
  }

  function exportDialog(action: PbAction): DialogSpec {
    return {
      id: action.id,
      title: "Hand this action to a planner",
      description: action.title,
      note: "Records where the action also lives. What that system says is kept in its own column and never moves the status here.",
      submitLabel: "Record the handover",
      fields: [
        { name: "system", label: "System", value: "project_planner" },
        { name: "external_ref", label: "Reference there", required: true,
          placeholder: "PP-4417" },
      ],
      submit: (v) =>
        fetch(
          `/api/v1/playbook/workspaces/${workspaceId}/intelligence/actions/` +
            `${action.id}/export`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(v),
          },
        ).then((r) => {
          if (!r.ok) throw new Error("The handover was not recorded.");
          return r.json();
        }),
    };
  }

  function mappingDialog(metric: PbMetric): DialogSpec {
    return {
      id: metric.id,
      title: "Change the mapping",
      description: metric.document_label || metric.label,
      note: "Choosing a metric confirms the link in one act, against your name.",
      submitLabel: "Confirm this mapping",
      fields: [{ name: "metric_id", label: "Governed metric", required: true,
        value: metric.metric_id,
        placeholder: "retail.default_rate" }],
      submit: (v) =>
        api.playbookDecideMetric(workspaceId, metric.id,
          { action: "confirm", metric_id: v.metric_id }),
    };
  }

  function sectionStatusDialog(key: string, status: string): DialogSpec {
    return {
      id: -2,
      title: "Move this section",
      description: `To ${status.replace(/_/g, " ")}`,
      note: "Review states are a person's act and are recorded against your name.",
      submitLabel: "Move it",
      reloadSection: true,
      fields: [{ name: "reason", label: "Reason", multiline: true }],
      submit: (v) =>
        api.playbookSetSectionStatus(workspaceId, key,
          { status, reason: v.reason }),
    };
  }

  function reviewerDialog(key: string): DialogSpec {
    return {
      id: -2,
      title: "Assign a reviewer",
      submitLabel: "Assign",
      reloadSection: true,
      fields: [{ name: "reviewer", label: "Reviewer", required: true }],
      submit: (v) =>
        api.playbookAssignSectionReviewer(workspaceId, key,
          { reviewer: v.reviewer }),
    };
  }
}

interface DialogSpec {
  id: number;
  title: string;
  description?: string;
  note?: string;
  submitLabel: string;
  fields: GovernField[];
  submit: (values: Record<string, string>) => Promise<unknown>;
  reloadSection?: boolean;
}
