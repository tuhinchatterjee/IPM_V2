"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { MessageSquare, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Investigations: the conversations.
 *
 * An Investigation is a thread — a question, an answer, the follow-ups it led
 * to. This screen is the list of them, most recently spoken in first, showing
 * the last thing CreditProbe said so you can tell them apart without opening
 * each one.
 *
 * Threads filed under a Project also appear on that Project. They are listed
 * here too, because "where did I put that" should have one answer that always
 * works.
 */
export default function InvestigationsPage() {
  const router = useRouter();
  const threads = useAsync(() => api.threads(), []);

  return (
    <div className="space-y-7">
      <PageHeader
        title="Investigations"
        description="Each investigation is a conversation: a question, the answer, and the follow-ups it led to. Every answer keeps the analyses that produced it and the Trace behind each figure."
        status="live"
        actions={
          <Button size="sm" asChild>
            <Link href="/?focus=ask">
              <Sparkles aria-hidden />
              New investigation
            </Link>
          </Button>
        }
      />

      {threads.loading && <Skeleton className="h-52 w-full" />}
      {threads.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {threads.error}
        </Card>
      )}

      {threads.data &&
        (threads.data.investigations.length > 0 ? (
          <Card className="divide-y divide-border">
            {threads.data.investigations.map((thread) => (
              <button
                key={thread.id}
                type="button"
                onClick={() => router.push(`/investigations/${thread.id}`)}
                className="flex w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-surface-hover"
              >
                <MessageSquare
                  className="mt-0.5 size-4 shrink-0 text-text-muted"
                  aria-hidden
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-text-primary">
                    {thread.title}
                  </span>
                  <span className="mt-0.5 line-clamp-1 block text-xs text-text-muted">
                    {thread.last_answer || thread.question}
                  </span>
                </span>
                <span className="hidden shrink-0 items-center gap-3 text-[11px] text-text-muted sm:flex">
                  <span>
                    {thread.message_count}{" "}
                    {thread.message_count === 1 ? "message" : "messages"}
                  </span>
                  <span>{when(thread.last_message_at ?? thread.updated_at)}</span>
                </span>
              </button>
            ))}
          </Card>
        ) : (
          <EmptyState
            icon={MessageSquare}
            title="No investigations yet"
            description="Ask a question in the Cockpit. The question and its answer become an investigation you can keep asking into."
            action={
              <Button size="sm" asChild>
                <Link href="/?focus=ask">Open the Cockpit</Link>
              </Button>
            }
          />
        ))}
    </div>
  );
}

/** A date somebody can read at a glance, rather than a timestamp. */
function when(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
