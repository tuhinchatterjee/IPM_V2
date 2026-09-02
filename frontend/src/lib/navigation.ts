import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  Bot,
  Boxes,
  Brain,
  ClipboardCheck,
  Database,
  FileText,
  FlaskConical,
  Gauge,
  GitBranch,
  Inbox,
  LayoutGrid,
  ListChecks,
  Mail,
  Network,
  Radar,
  Search,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";

/**
 * The CreditProbe AI capability map.
 *
 * One definition of what the product contains — the sidebar, the landing page
 * and every page header read it, so a capability can never appear in one place
 * and not another.
 *
 * The WORK group follows the product hierarchy exactly:
 *
 *     Project        the master workspace
 *       Investigation  a conversational thread
 *         Analysis       one deterministic engine result
 *
 * so Work lists Projects, Investigations, Analyses and Documents in that order.
 * Analysis Studio stays under BUILD because it defines analytical *capabilities*
 * rather than holding executed results. It replaced Engine Builder in the
 * navigation: the registered engine analyses are still there, still certified
 * and still reachable, but they are now one kind of implementation behind a
 * method rather than the whole of what the product can compute. The
 * /engine-builder routes remain for the analyses that link to them.
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

/**
 * The client-demo scope freeze.
 *
 * Distinct from `status`, and the distinction is the point. `status` says how
 * finished a capability is; `demo` says whether it is part of tomorrow's
 * demonstration. A capability can be perfectly finished and still not belong
 * in a twenty-minute walkthrough, and one that is honestly labelled
 * "Placeholder by design" is finished enough to ship and wrong to show.
 *
 *   core     Shown, and must be reliable.
 *   optional Shown only if every check passes; the presenter may skip it.
 *   admin    Reachable by an authorized user, not part of the walkthrough.
 *   hidden   Removed from navigation while Demo Mode is on.
 *
 * `hidden` removes the LINK, not the route. Anyone who types the address
 * still gets the page, because hiding a screen is presentation, never
 * security — the API behind it enforces permission whatever the sidebar
 * shows.
 */
export type DemoScope = "core" | "optional" | "admin" | "hidden";

export const DEMO_SCOPE_LABEL: Record<DemoScope, string> = {
  core: "Core"    ,
  optional: "Optional",
  admin: "Admin preview",
  hidden: "Hidden in Synthetic Data Mode",
};

export interface NavItem {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  status: CapabilityStatus;
  phase: string;
  group: NavGroup;
  /**
   * Which roles see this in the sidebar. Absent means everybody.
   *
   * Hiding a link is COURTESY, not security — §28's Agent Operations is
   * enforced by `principals.require_operate` on every endpoint behind it, and
   * a Viewer who types the URL gets a 403 rather than a screen. What this
   * prevents is a sidebar full of things the reader cannot open.
   */
  roles?: string[];
  /**
   * Where this sits in the client-demo scope freeze. See
   * `docs/DEMO_SCOPE_FREEZE.md` for why each one is classified as it is.
   */
  demo: DemoScope;
  /** Why, in one line, when the answer is not obvious. */
  demoNote?: string;
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
    label: "Cockpit",
    description:
      "Ask a question in plain language. CreditProbe AI plans the investigation, runs certified analyses and explains the result.",
    icon: Sparkles,
    status: "live",
    phase: "",
    group: "Home",
    demo: "core",
  },

  {
    href: "/workspace",
    label: "My workspace",
    description:
      "What is waiting on you: unread messages, reviews you have been asked for, and the investigations and analyses colleagues have shared with you.",
    icon: Inbox,
    status: "live",
    phase: "",
    group: "Home",
    demo: "core",
  },
  {
    href: "/messages",
    label: "Messages",
    description:
      "Send a colleague an investigation, an analysis or a workbook, ask for a review, and read what CreditProbe has told you.",
    icon: Mail,
    status: "live",
    phase: "",
    group: "Home",
    demo: "core",
  },

  // ---- WORK: the product hierarchy, largest container first ----
  {
    href: "/projects",
    label: "Projects",
    description:
      "The master workspace. A Project holds investigations, saved analyses, documents, people and context.",
    icon: Boxes,
    status: "live",
    phase: "",
    group: "Work",
    demo: "core",
  },
  {
    href: "/investigations",
    label: "Investigations",
    description:
      "Conversational threads. An Investigation holds every question, answer, analysis and interpretation in one continuing thread.",
    icon: Search,
    status: "live",
    phase: "",
    group: "Work",
    demo: "core",
  },
  {
    href: "/analyses",
    label: "Analyses",
    description:
      "Executed and saved analytical results, each with the data version, parameters and Trace that produced it.",
    icon: BarChart3,
    status: "live",
    phase: "",
    group: "Work",
    demo: "core",
  },
  {
    href: "/documents",
    label: "Documents",
    description:
      "Board and committee papers authored with live analytical content. Placeholder for this release.",
    icon: FileText,
    status: "preview",
    phase: "Placeholder by design",
    group: "Work",
    demo: "hidden",
    demoNote:
      "Placeholder by design: the cards are fixed sample records, not authored documents. Nothing here is wired to analytical content, so it would be the first dead end a client found.",
  },

  // ---- INTELLIGENCE: standing capability rather than one-off work ----
  {
    href: "/lenses",
    label: "Lenses",
    description:
      "Live dashboards you build by describing them. Each tile is a certified analysis with its own Trace.",
    icon: LayoutGrid,
    status: "live",
    phase: "",
    group: "Intelligence",
    demo: "optional",
    demoNote:
      "Real and seeded with one published Lens. Shown if time allows; not on the twenty-minute path.",
  },
  {
    href: "/early-warning",
    label: "Early Warning",
    description:
      "Forward Risk Signal: a transparent, factor-based estimate of the chance a facility moves to a worse IFRS 9 stage next quarter, for three transitions. Every score decomposes exactly into one number per factor.",
    icon: Radar,
    status: "partial",
    phase: "Prototype signal, fitted on synthetic data. Not a validated model.",
    group: "Intelligence",
    demo: "optional",
    demoNote:
      "Real and honestly labelled a prototype fitted on synthetic data. Show it only if the audience asks about predictive signals, and read the label out.",
  },
  {
    href: "/early-warning/signals",
    label: "Early Warning Signals",
    description:
      "The governed conditions this book is watched for, borrower by borrower. Not one score: 34 named tests across eight families, each with a threshold, an owner and a version, and each traceable to the field it read. Where a test could not be run on a borrower, the screen says so on that signal rather than in a blanket list.",
    icon: ListChecks,
    status: "live",
    phase: "",
    group: "Intelligence",
    demo: "core",
    demoNote:
      "The transparency argument in one screen. Open a borrower and read a condition out: the value, the previous value, the threshold and who owns it.",
  },
  {
    href: "/playbooks",
    label: "Playbooks",
    description:
      "A standing instruction: run these certified analyses over this scope, test these thresholds, and act when one is crossed. A run that finds nothing says so.",
    icon: ClipboardCheck,
    status: "partial",
    phase: "Manual and on-publication triggers run; scheduled ones are not yet wired to a scheduler",
    group: "Intelligence",
    demo: "optional",
    demoNote:
      "Manual and on-publication triggers run. Scheduled ones are not wired to a scheduler, so do not promise scheduling.",
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
    demo: "optional",
  },

  // ---- BUILD: what the product is capable of, and what it may read ----
  {
    href: "/borrower-360",
    label: "Borrower 360",
    description:
      "One corporate borrower and everything the bank knows about it: exposure, ratings, IFRS 9, covenants, collateral and limits, its ownership, control, guarantee and supply relationships, and the quality of the evidence underneath. The six ways of grouping a borrower are shown side by side rather than reconciled into one, because they answer different questions and do not agree.",
    icon: Network,
    status: "live",
    phase: "",
    group: "Intelligence",
    demo: "core",
  },
  {
    href: "/scorecard-validation",
    label: "Scorecard Validation",
    description:
      "Governed monitoring and validation of the retail application and behavioural scorecards: discrimination, calibration, stability, variable diagnostics and implementation, each against an approved limit that says where it came from.",
    icon: Gauge,
    status: "live",
    phase: "",
    group: "Intelligence",
    demo: "core",
  },
  {
    href: "/studio",
    label: "Analysis Studio",
    description:
      "Every credit-risk method CreditProbe knows, what each one measures, and — where one exists — the implementation and the test cases that prove it. Build new methods by describing them; certify them only once their validation pack passes.",
    icon: FlaskConical,
    status: "live",
    phase: "",
    group: "Build",
    demo: "core",
  },
  {
    href: "/data-builder",
    label: "Data Builder",
    description:
      "Domains, dataset families, the data dictionary, relationships, quality and publication.",
    icon: Database,
    status: "live",
    phase: "",
    group: "Build",
    demo: "core",
  },

  // ---- GOVERN ----
  {
    href: "/trace",
    label: "Trace & Lineage",
    description:
      "How an analysis was created: every step from question to chart, inspectable and modifiable.",
    icon: GitBranch,
    status: "live",
    phase: "",
    group: "Govern",
    demo: "core",
  },
  {
    href: "/workflow",
    label: "Workflow",
    description:
      "Share, review and approve the things that carry institutional weight, with an append-only decision history.",
    icon: ClipboardCheck,
    status: "live",
    phase: "",
    group: "Govern",
    demo: "core",
  },

  // ---- ADMIN ----
  {
    href: "/agent-operations",
    label: "Agent Operations",
    description:
      "The governed agentic layer: the twelve specialists and what each may do, every run and what it cost, the schedules, the policies, the approvals waiting for a person, and how the agents score against the evaluation corpus.",
    icon: Bot,
    status: "live",
    phase: "",
    group: "Admin",
    demo: "admin",
    demoNote:
      "Already restricted to ADMIN and DATA_STEWARD. Compelling to a technical audience and irrelevant to a CRO.",
    // §64: "Only authorized roles can access it." §28 places it with
    // Administration rather than in the ordinary Cockpit navigation, because
    // an analyst has no use for a worker heartbeat.
    roles: ["ADMIN", "DATA_STEWARD"],
  },
  {
    href: "/ai-studio",
    label: "AI Intelligence Studio",
    description:
      "What CreditProbe has been taught, how it was validated, how it is performing, what has gone stale and which release is running \u2014 for the ontology, the teaching library, the investigation blueprints, the judgment policies, the visualization grammar and the model routing.",
    icon: Brain,
    status: "live",
    phase: "",
    group: "Admin",
    demo: "admin",
    demoNote:
      "Already restricted to ADMIN and DATA_STEWARD. Holds the Feedback & Learning area, which is worth showing on request rather than by default.",
    // §119: an ordinary Analyst sees only a compact assurance badge on the
    // answer itself. Reading which cases production retrieves is most of the
    // way to knowing how to phrase a question to get a chosen answer, so the
    // Studio needs the standing to change it — and every endpoint behind it
    // enforces that whatever the sidebar shows.
    roles: ["ADMIN", "DATA_STEWARD"],
  },
  {
    href: "/users",
    label: "Users & Teams",
    description: "Users, teams, roles and permissions at capability, object and data level.",
    icon: Users,
    status: "preview",
    phase: "Placeholder records",
    group: "Admin",
    // Restricted here in the release-candidate phase. The route crawl found
    // an ANALYST and a VIEWER seeing this link and getting a 403 from
    // `/api/v1/users` the moment they clicked it — the sidebar was offering
    // a door the API was always going to refuse. The endpoint's permission
    // was right; the invitation was wrong.
    roles: ["ADMIN"],
    demo: "admin",
    demoNote:
      "Real accounts and real permissions, but the screen is labelled Preview and its team management is not complete.",
  },
  {
    href: "/settings",
    label: "Settings",
    description: "Themes, roles, model configuration and administration.",
    icon: Settings,
    status: "partial",
    phase: "",
    group: "Admin",
    demo: "admin",
  },
];

export const STATUS_LABEL: Record<CapabilityStatus, string> = {
  live: "Live",
  partial: "Partial",
  preview: "Preview",
  planned: "Planned",
};

export function itemsInGroup(
  group: NavGroup,
  role?: string,
  demoMode = false,
): NavItem[] {
  return NAV_ITEMS.filter(
    (item) =>
      item.group === group &&
      (!item.roles || !role || item.roles.includes(role)) &&
      // In Demo Mode, `hidden` items leave the navigation. Out of it, every
      // capability is listed with its honest status, which is what a
      // development build and a pilot both want.
      !(demoMode && item.demo === "hidden"),
  );
}

/** Everything in one demo scope, for the scope-freeze document and its test. */
export function itemsInDemoScope(scope: DemoScope): NavItem[] {
  return NAV_ITEMS.filter((item) => item.demo === scope);
}

export function findNavItem(href: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.href === href);
}
