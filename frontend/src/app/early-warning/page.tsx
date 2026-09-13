"use client";

/**
 * The single Early Warning Score workspace.
 *
 * There is one left-navigation item and one route. Signals and the model both
 * live inside here — Signals as a view, the model behind the View Model button
 * — so a reader never has to work out which of two Early Warning entries is
 * the product.
 *
 * Everything below reads `/retail/ews/*`, which reads the Early Warning Score
 * domain. No figure on this screen is computed in the browser and none is
 * hard-coded.
 */

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { EWS_DESCRIPTION, EWS_LABEL } from "@/lib/ews";
import { isRetail } from "@/lib/profile";

import { EwsWorkspace } from "./workspace";
import { ForwardRiskSignal } from "./forward-risk";

export default function EarlyWarningScorePage() {
  return (
    <React.Suspense fallback={<Skeleton className="h-96 w-full" />}>
      {isRetail() ? <Retail /> : <ForwardRiskSignal />}
    </React.Suspense>
  );
}

function Retail() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Intelligence"
        title={EWS_LABEL}
        description={EWS_DESCRIPTION}
        // Every figure on this screen reads the registered Early Warning
        // Score domain end to end, which is what `live` means here. The phase
        // below is what a reader has to keep in mind about it: the book it
        // runs on is a demonstration book.
        status="live"
        phase="Governed model on synthetic demonstration data"
      />
      <EwsWorkspace />
    </div>
  );
}
