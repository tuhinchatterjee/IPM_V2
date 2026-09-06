"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { CopilotChat } from "@/components/planner/copilot-chat";
import { DraftBuilder } from "@/components/planner/draft-builder";
import { ImportNewProject } from "@/components/planner/import-panel";
import { Button } from "@/components/ui/button";
import { api, ApiError, type CopilotPerson, type DraftDetail } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Starting a project by describing it.
 *
 * The old page was eleven fields and a Create button, which is a good form and
 * the wrong shape for the job. Nobody starts a project by knowing its
 * reporting cadence; they start by knowing what has to happen and roughly
 * when, and the governance questions are things they answer once somebody
 * asks. So this is a conversation on the left and the plan taking shape on the
 * right, and neither is the primary one: they are two views of one draft, and
 * every change from either goes through the same `apply`.
 *
 * Nothing here exists until Publish. A draft is a private working document —
 * nobody else can see it, nothing is scheduled off it, and the agent does not
 * chase anybody about it. That is what lets somebody think out loud.
 *
 * Uploading a workbook is still here, at the bottom, because a plan that
 * already exists in a spreadsheet should not have to be retyped into a chat.
 */
export default function NewDeliveryProjectPage() {
  const router = useRouter();
  const [key, setKey] = React.useState("");
  const [detail, setDetail] = React.useState<DraftDetail | null>(null);
  const [error, setError] = React.useState("");
  const [showImport, setShowImport] = React.useState(false);

  const directory = useAsync(() => api.planner.copilot.people("", 50), []);
  const people: CopilotPerson[] = directory.data?.people ?? [];

  const load = React.useCallback(async (draftKey: string) => {
    try {
      setDetail(await api.planner.copilot.draft(draftKey));
      setError("");
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "I could not read that plan.",
      );
    }
  }, []);

  const start = React.useCallback(async () => {
    setError("");
    try {
      const made = await api.planner.copilot.start("");
      setKey(made.key);
      await load(made.key);
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "I could not start a plan.",
      );
    }
  }, [load]);

  return (
    <div className="mx-auto w-full max-w-6xl px-6 py-6">
      <PageHeader
        title="Start a project"
        description="Describe what you want to happen. Nothing is created until you publish it."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/delivery">Back to delivery</Link>
          </Button>
        }
      />

      {error && (
        <p role="alert" className="mb-3 rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {error}
        </p>
      )}

      {!key ? (
        <div className="rounded-lg border border-border bg-surface px-5 py-6">
          <p className="text-sm text-text-secondary">
            A plan starts empty and private. You can talk it through, fill the
            panels in directly, or do both — they are the same plan.
          </p>
          <Button className="mt-4" onClick={() => void start()}>
            Start a plan
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[380px_1fr]">
          <div className="lg:sticky lg:top-4 lg:self-start">
            <CopilotChat
              draftKey={key}
              suggestions={[
                "Call it the LGD Model Redevelopment",
                "Add Data Foundation as the first milestone",
                "Under Data Foundation add Data Extraction and Reconciliation",
                "What is still missing?",
              ]}
              onTurn={() => void load(key)}
            />
            {detail && (
              <p className="mt-2 px-1 text-xs text-text-muted">
                Draft {detail.code || "unnamed"} · saved {detail.version} times
                · private to you until you publish.
              </p>
            )}
          </div>

          {detail ? (
            <DraftBuilder
              detail={detail}
              people={people}
              onChanged={() => void load(key)}
              onPublished={(projectId) =>
                router.push(`/delivery/${projectId}`)}
            />
          ) : (
            <p className="text-sm text-text-muted">Opening the plan…</p>
          )}
        </div>
      )}

      <div className="mt-8 border-t border-border pt-5">
        <button
          type="button"
          onClick={() => setShowImport(!showImport)}
          className="text-sm text-text-secondary underline-offset-4 hover:underline"
        >
          {showImport ? "Hide" : "Or upload a plan you already have"}
        </button>
        {showImport && (
          <div className="mt-3">
            <ImportNewProject
              onCreated={(projectId) =>
                router.push(`/delivery/${projectId}`)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
