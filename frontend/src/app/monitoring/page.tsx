"use client";

import { Suspense } from "react";

import { useWideContent } from "@/components/layout/content-width";
import { MonitoringCentre } from "@/components/monitoring/monitoring-centre";
import { GuidedOff } from "@/components/scenarios/guided-off";
import { guidedEnabled } from "@/lib/workspace/guided";

export default function MonitoringPage() {
  useWideContent();
  return (
    <main className="mx-auto w-full max-w-[96rem] px-4 py-6 sm:px-6 lg:px-10">
      {guidedEnabled() ? (
        <Suspense fallback={null}>
          <MonitoringCentre />
        </Suspense>
      ) : (
        <GuidedOff what="The Monitoring Centre" />
      )}
    </main>
  );
}
