"use client";

import { Suspense } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { WhatIfWorkspace } from "@/components/whatif/whatif-workspace";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function WhatIfPage() {
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? (
        <Suspense fallback={null}>
          <WhatIfWorkspace />
        </Suspense>
      ) : (
        <GuidedOff what="What-If Analysis" />
      )}
    </main>
  );
}
