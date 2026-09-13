"use client";

/**
 * One Cockpit conversation, at its own URL.
 *
 * A thread having a real route is what makes it a place rather than a state
 * the page happens to be in. It can be refreshed, linked, reopened from the
 * home page, and walked back to with the browser's own Back button -- none of
 * which was true while the conversation lived inside the landing page's
 * component state.
 *
 * The id is in the path and the authorization is not. A thread is
 * tenant-checked server-side and answers 404 to anyone else, so typing
 * somebody else's id here reveals nothing, including whether it exists.
 */

import { useParams, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { cockpitV4Enabled } from "@/components/cockpit-v4/client";
import { CockpitV4Thread } from "@/components/cockpit-v4/thread-view";
import { NotInThisRuntime } from "@/components/cockpit-v4/not-in-this-runtime";
import { useWideContent } from "@/components/layout/content-width";

export default function CockpitThreadPage() {
  const params = useParams<{ threadId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  // The question the home page handed over, carried in the URL so that a
  // refresh before the first answer does not lose it -- and consumed exactly
  // once, because a reload must never re-ask.
  const question = search.get("q") ?? "";

  // Charts and tables want the workspace, not a centred ribbon.
  useWideContent();

  if (!cockpitV4Enabled()) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16">
        <NotInThisRuntime title="Cockpit" what="The Cockpit conversation" />
      </div>
    );
  }

  const threadId = String(params?.threadId ?? "");
  if (!threadId) return null;

  return (
    <CockpitV4Thread
      threadId={threadId}
      initialQuestion={question}
      onQuestionAsked={() =>
        router.replace(`/cockpit/thread/${encodeURIComponent(threadId)}`)
      }
      onHome={() => router.push("/")}
    />
  );
}
