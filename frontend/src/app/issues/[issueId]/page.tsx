"use client";

import { Suspense, use } from "react";

import { IssueDetail } from "@/components/guided/issue-detail";
import { useWideContent } from "@/components/layout/content-width";

export default function IssuePage({ params }: { params: Promise<{ issueId: string }> }) {
  const { issueId } = use(params);
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[90rem] px-4 py-6 sm:px-6 lg:px-10">
      <Suspense fallback={null}>
        <IssueDetail issueId={issueId} />
      </Suspense>
    </main>
  );
}
