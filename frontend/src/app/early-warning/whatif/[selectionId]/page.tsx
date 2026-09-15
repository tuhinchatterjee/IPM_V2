"use client";

import { useParams } from "next/navigation";

import { WhatIfThread } from "@/components/whatif/thread-view";

/**
 * The Early Warning export's deep link, kept working.
 *
 * §8 asks for one thread family behind every door and for the old links to
 * keep resolving. This route is now an adapter: it opens the thread for the
 * exported cohort and renders the same component the standalone page and the
 * guided cards render. A link in somebody's notes from last week still lands
 * on its own selection, with its own baseline.
 */
export default function ImportedWhatIfPage() {
  const params = useParams<{ selectionId: string }>();
  return (
    <WhatIfThread
      selectionId={String(params?.selectionId ?? "")}
      openedFrom="early_warning_export"
    />
  );
}
