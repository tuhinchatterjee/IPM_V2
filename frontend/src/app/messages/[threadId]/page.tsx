"use client";

import { useParams } from "next/navigation";

import { BackLink } from "@/components/layout/back-link";
import { ThreadView } from "@/components/messages/thread";

/**
 * One conversation.
 *
 * Back goes to Messages rather than to wherever the reader came from: a thread
 * is reached from an inbox, a dashboard tile and a notification, and all three
 * of those readers are on their way back to their mail.
 */
export default function MessageThreadPage() {
  const params = useParams<{ threadId: string }>();
  const threadId = Number(params?.threadId);

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-6">
      <BackLink href="/messages" label="Messages" />
      <div className="mt-4">
        {Number.isFinite(threadId) ? (
          <ThreadView threadId={threadId} />
        ) : (
          <p className="py-10 text-center text-sm text-text-secondary">
            That conversation is not available to you.
          </p>
        )}
      </div>
    </div>
  );
}
