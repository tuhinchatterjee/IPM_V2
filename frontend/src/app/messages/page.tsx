"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { MessageCentre } from "@/components/messages/centre";

/**
 * Messages — the internal workflow surface.
 *
 * Deliberately one entry in the navigation rather than five. Inbox, Sent,
 * Drafts, Archived and Action Required are views of the same mail, and a
 * sidebar that listed each of them would spend five slots saying one thing.
 */
export default function MessagesPage() {
  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-6">
      <PageHeader
        title="Messages"
        description="Send colleagues an investigation, an analysis or a workbook — and see what CreditProbe has told you."
      />
      <React.Suspense
        fallback={
          <p className="py-10 text-center text-sm text-text-muted">Loading…</p>
        }
      >
        <MessageCentre />
      </React.Suspense>
    </div>
  );
}
