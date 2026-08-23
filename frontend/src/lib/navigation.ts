import type { LucideIcon } from "lucide-react";
import {
  Boxes,
  ClipboardCheck,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  LayoutGrid,
  Search,
  Settings,
  Sparkles,
  Users,
  Wrench,
} from "lucide-react";

/**
 * The IPM capability map.
 *
 * One definition of what the product contains — the sidebar, the landing page
 * and every page header read it, so a capability can never appear in one place
 * and not another.
 *
 * `status` is part of the model rather than a comment. The product rule is that
 * the UI must never present a placeholder as production functionality, and the
 * only reliable way to honour that is to make every screen carry its own honest
 * status and render it.
 */
export type CapabilityStatus =
  /** Working on real engine or Data Builder results, end to end. */
  | "live"
  /** Real, on a deliberately narrow path, or partly demo-seeded. */
  | "partial"
  /** Designed and structurally real, not yet interactive. */
  | "preview"
  /** Not started; the route exists so navigation is complete. */
  | "planned";

export type NavGroup = "Home" | "Work" | "Intelligence" | "Build" | "Govern" | "Admin";

export interface NavItem {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  status: CapabilityStatus;
  phase: string;
  group: NavGroup;
}

export const NAV_GROUPS: NavGroup[] = [
  "Home",
  "Work",
  "Intelligence",
  "Build",
  "Govern",
  "Admin",
];

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    label: "AI Cockpit",
    description:
      "Ask a question in plain language. IPM plans the investigation, runs approved analyses and explains the result.",
    icon: Sparkles,
    status: "live",
    phase: "",
    group: "Home",
  },

  {
    href: "/projects",
    label: "Projects",
    description:
      "Containers for a body of work — chats, investigations, analyses, traces and scenarios.",
    icon: Boxes,
    status: "preview",
    phase: "Demo records",
    group: "Work",
  },
  {
    href: "/investigations",
    label: "Investigations",
    description:
      "Multi-step root-cause analysis, persisted as a named, shareable investigation.",
    icon: Search,
    status: "live",
    phase: "",
    group: "Work",
  },
  {
    href: "/documents",
    label: "Documents",
    description:
      "Board and committee papers authored with live analytical content. Placeholder for this demo.",
    icon: FileText,
    status: "preview",
    phase: "Placeholder by design",
    group: "Work",
  },

  {
    href: "/lenses",
    label: "Lenses",
    description:
      "Saved executive views — composed tiles with fixed filters, each with its own Trace.",
    icon: LayoutGrid,
    status: "live",
    phase: "",
    group: "Intelligence",
  },
  {
    href: "/stress",
    label: "Stress Testing",
    description:
      "Named, versioned management scenarios applied to the portfolio, with comparison.",
    icon: FlaskConical,
    status: "live",
    phase: "",
    group: "Intelligence",
  },
  {
    href: "/blueprints",
    label: "Blueprints",
    description:
      "Reusable analytical workflows that turn one analyst's proven work into institutional capability.",
    icon: ClipboardCheck,
    status: "preview",
    phase: "Execution next",
    group: "Intelligence",
  },

  {
    href: "/engine-builder",
    label: "Engine Builder",
    description:
      "Define, test, version and certify analytical capability. IPM Certified analyses carry a verification tick.",
    icon: Wrench,
    status: "live",
    phase: "",
    group: "Build",
  },
  {
    href: "/data-builder",
    label: "Data Builder",
    description:
      "Domains, datasets, the data dictionary, relationships, quality and publication.",
    icon: Database,
    status: "live",
    phase: "",
    group: "Build",
  },

  {
    href: "/trace",
    label: "Trace & Lineage",
    description:
      "How an analysis was created: every step from question to chart, inspectable and modifiable.",
    icon: GitBranch,
    status: "live",
    phase: "",
    group: "Govern",
  },

  {
    href: "/users",
    label: "Users & Teams",
    description: "Users, teams, roles and permissions at capability, object and data level.",
    icon: Users,
    status: "preview",
    phase: "Demo records",
    group: "Admin",
  },
  {
    href: "/workflow",
    label: "Workflow",
    description:
      "Review and approval of certifications, dataset publication and document sign-off.",
    icon: ClipboardCheck,
    status: "preview",
    phase: "Demo records",
    group: "Admin",
  },
  {
    href: "/settings",
    label: "Settings",
    description: "Themes, roles, model configuration and administration.",
    icon: Settings,
    status: "partial",
    phase: "",
    group: "Admin",
  },
];

export const STATUS_LABEL: Record<CapabilityStatus, string> = {
  live: "Live",
  partial: "Partial",
  preview: "Preview",
  planned: "Planned",
};

export function itemsInGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((item) => item.group === group);
}

export function findNavItem(href: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.href === href);
}
