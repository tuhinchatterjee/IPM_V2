"use client";

import { useParams } from "next/navigation";

import { WhatIfThread } from "@/components/whatif/thread-view";

/**
 * The canonical What-If thread route, §8.
 *
 * Every door — the standalone composer, a guided card, an Early Warning
 * export — lands here. The thread carries its own cohort, so this page needs
 * nothing but the id.
 */
export default function WhatIfThreadPage() {
  const params = useParams<{ threadId: string }>();
  return <WhatIfThread threadId={String(params?.threadId ?? "")} />;
}
