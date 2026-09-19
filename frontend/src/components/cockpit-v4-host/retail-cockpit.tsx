"use client";

/**
 * The Cockpit this deployment serves: the AdvancedCockpit, on Cockpit Data.
 *
 * A WRAPPER, and deliberately a thin one. `CockpitV4Home` is ported verbatim
 * and is not edited here; everything this adds is outside it -- the source
 * badge, and the width the workspace needs.
 *
 * It is also a SIBLING of the legacy Cockpit rather than a branch inside it.
 * React runs every hook a component declares, so a legacy page that merely
 * hid its JSX would still fire its own composer, attention and early-warning
 * requests on every load. The ported browser suite asserts exactly that: it
 * fails if the Cockpit page ever calls `/api/v1/ask/mode`, `/ask/briefing`,
 * `/ask/suggestions`, `/api/v1/investigations` or `/api/v1/agentic/officer`.
 * Not instantiating the component is what makes that true.
 *
 * There is no book switcher. The deployment publishes one book, so
 * `DomainSwitch` suppresses itself when fewer than two are available -- but
 * that test is on the LENGTH of the list, and a corporate entry that was
 * published-but-not-ready would still count. This page does not mount it at
 * all, so the control cannot appear for any reason.
 */

import * as React from "react";

import { CockpitV4Home } from "@/components/cockpit-v4/cockpit-v4-home";
import { CockpitSourceBadge } from "@/components/cockpit-v4-host/source-badge";
import { useWideContent } from "@/components/layout/content-width";

export function RetailAdvancedCockpit() {
  // An answer, its evidence, its charts and the live process panel do not
  // sit side by side in a 1200px reading column.
  useWideContent();

  return (
    <>
      <CockpitSourceBadge />
      <CockpitV4Home />
    </>
  );
}

export default RetailAdvancedCockpit;
