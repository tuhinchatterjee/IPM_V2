"use client";

/**
 * The model-comparison LAB page: the lab section above the unchanged
 * Cockpit home. Served only when the lab flag is set, so a normal Cockpit
 * build never shows it. Normal single-model chat stays exactly as it was,
 * underneath.
 */

import * as React from "react";

import { cockpitV4Enabled } from "@/components/cockpit-v4/client";
import { CockpitV4Home } from "@/components/cockpit-v4/cockpit-v4-home";
import { useWideContent } from "@/components/layout/content-width";
import { labEnabled } from "@/components/model-lab/client";
import { ModelComparisonLab } from "@/components/model-lab/model-comparison";

export default function ModelLabPage() {
  useWideContent();
  if (!labEnabled()) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-sm text-text-secondary">
        The model comparison lab is not enabled in this runtime.
      </div>
    );
  }
  return (
    <div className="px-4 py-4">
      <ModelComparisonLab />
      {cockpitV4Enabled() && (
        <React.Suspense fallback={null}>
          <CockpitV4Home />
        </React.Suspense>
      )}
    </div>
  );
}
