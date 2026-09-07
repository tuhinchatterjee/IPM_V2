"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { ImportNewProject } from "@/components/planner/import-panel";
import { ProjectWizard } from "@/components/planner/wizard";
import { Button } from "@/components/ui/button";
import { api, ApiError, type CopilotPerson, type DraftDetail } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Creating a project: a form, in steps, and nothing else.
 *
 * The page this replaces opened a conversation and a plan side by side, which
 * gave the product two ways to create the same thing and left a person who
 * wanted a form staring at a chat box. UAT was unambiguous about it. So the
 * form is now the only way in, and it is stepped rather than laid out all at
 * once — §3 to §13.
 *
 * A draft is private until Publish. Nothing is scheduled off it, nobody else
 * can see it, and the agent does not chase anybody about it. `?draft=<key>`
 * resumes one from the Draft projects list.
 *
 * Uploading a workbook is still here, at the bottom of step one, because a
 * plan that already exists in a spreadsheet should not have to be retyped.
 */
export default function NewDeliveryProjectPage() {
  const router = useRouter();
  const params = useSearchParams();
  const resuming = params.get("draft") ?? "";

  const [key, setKey] = React.useState(resuming);
  const [error, setError] = React.useState("");
  const [saved, setSaved] = React.useState("");
  const [showImport, setShowImport] = React.useState(
    params.get("import") === "1");

  const directory = useAsync(() => api.planner.plan.people("", 200), []);
  const people: CopilotPerson[] = directory.data?.people ?? [];

  // The draft is fetched from the key rather than pushed into state after
  // every write: `reload()` re-reads what the server stored, so the form
  // always shows the plan as it actually is rather than as the last response
  // said it would be.
  const draft = useAsync(
    () => api.planner.plan.draft(key), [key], { enabled: Boolean(key) });
  const detail: DraftDetail | null = draft.data;

  const start = React.useCallback(async () => {
    setError("");
    try {
      const made = await api.planner.plan.start("");
      setKey(made.key);
    } catch (failure) {
      setError(failure instanceof ApiError
        ? failure.message : "I could not start a plan.");
    }
  }, []);

  const discard = React.useCallback(async () => {
    if (!key) return;
    try {
      await api.planner.plan.discard(key);
      router.push("/delivery");
    } catch (failure) {
      setError(failure instanceof ApiError
        ? failure.message : "I could not discard that draft.");
    }
  }, [key, router]);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-6">
      <PageHeader
        title="Create new project"
        description="Eight steps. Nothing is created until the last one."
        actions={
          <div className="flex gap-2">
            {key && (
              <Button variant="ghost" size="sm" onClick={() => void discard()}>
                Discard draft
              </Button>
            )}
            <Button asChild variant="outline" size="sm">
              <Link href="/delivery">Back to Project Planner</Link>
            </Button>
          </div>
        }
      />

      {(error || draft.error) && (
        <p role="alert"
           className="mb-3 rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {error || draft.error}
        </p>
      )}
      {saved && (
        <p role="status"
           className="mb-3 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-secondary">
          {saved}
        </p>
      )}

      {!key ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-surface px-5 py-6">
            <p className="text-sm text-text-secondary">
              You will be asked for the project and its dates, who is
              answerable, how the Agentic AI should chase people, the
              milestones, the tasks under them, and what waits for what. You
              can save and come back at any point.
            </p>
            <Button className="mt-4" onClick={() => void start()}>
              Start the setup
            </Button>
          </div>

          <div className="rounded-lg border border-border bg-surface px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-text-primary">
                  Already have the plan in a spreadsheet?
                </p>
                <p className="mt-0.5 text-xs text-text-secondary">
                  Upload the workbook instead of retyping it. You still see
                  everything before it is created.
                </p>
              </div>
              <Button variant="outline" size="sm"
                      onClick={() => setShowImport(!showImport)}>
                {showImport ? "Hide import" : "Import project"}
              </Button>
            </div>
            {showImport && (
              <div className="mt-4">
                <ImportNewProject
                  onCreated={(projectId) =>
                    router.push(`/delivery/${projectId}`)}
                />
              </div>
            )}
          </div>
        </div>
      ) : detail ? (
        <ProjectWizard
          detail={detail}
          people={people}
          onChanged={() => draft.reload()}
          onSaved={() => {
            setSaved("Draft saved. It is under Draft projects on the "
                     + "Project Planner until you publish it.");
            draft.reload();
          }}
          onPublished={(projectId) => router.push(`/delivery/${projectId}`)}
        />
      ) : (
        <p className="text-sm text-text-muted">Opening the plan…</p>
      )}
    </div>
  );
}
