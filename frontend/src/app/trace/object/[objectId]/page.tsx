"use client";

import { use } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { ObjectTraceView } from "@/components/trace/object-trace";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function ObjectTracePage({ params }: { params: Promise<{ objectId: string }> }) {
  const { objectId } = use(params);
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? <ObjectTraceView objectId={objectId} /> : <GuidedOff what="The governance Trace" />}
    </main>
  );
}
