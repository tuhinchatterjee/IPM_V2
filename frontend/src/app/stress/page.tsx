"use client";

/**
 * The old /stress route.
 *
 * The capability is called What-If Analysis now and lives at /what-if. This
 * route is kept because links to it exist — in saved documents, in browser
 * histories, in a route-crawl artefact — and a 404 is a worse answer than a
 * redirect. It renders nothing of its own.
 */

import { useRouter } from "next/navigation";
import * as React from "react";

export default function StressRedirectPage() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace("/what-if");
  }, [router]);
  return (
    <div className="py-16 text-center text-[13px] text-text-muted">
      Stress Testing is now <strong className="text-text-primary">What-If Analysis</strong>.
      Taking you there…
    </div>
  );
}
