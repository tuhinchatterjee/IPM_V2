/**
 * Demo records for the surfaces that have no backend model yet.
 *
 * Deliberately narrow. Anything analytical — every figure, every chart, every
 * table — comes from the engine API; nothing here invents a portfolio number.
 * These are only the *containers* a bank would create around that analysis:
 * project names, investigation titles, blueprint definitions, document
 * placeholders, users and workflow items.
 *
 * Each investigation names the REAL registered analyses it runs, so its
 * workspace executes them rather than displaying a stored picture of them.
 * When projects and investigations become PostgreSQL-backed, only this file is
 * deleted.
 */

export const DEMO_NOTICE =
  "Demo record. Projects, investigations, blueprints and documents are not yet persisted; the analytical results inside them are real.";

// =============================================================== investigations

export interface InvestigationStep {
  /** A registered analysis id — executed for real when the workspace opens. */
  analysisId: string;
  title: string;
  /** Why this step is in the investigation. */
  rationale: string;
  params?: Record<string, unknown>;
  filters?: Record<string, unknown>;
}

export interface Investigation {
  id: string;
  title: string;
  question: string;
  objective: string;
  status: "open" | "in_review" | "closed";
  owner: string;
  project?: string;
  updated: string;
  tags: string[];
  steps: InvestigationStep[];
  followUps: string[];
}

export const INVESTIGATIONS: Investigation[] = [
  {
    id: "stage-2-deterioration",
    title: "Stage 2 Deterioration Review",
    question: "Why has Stage 2 increased?",
    objective:
      "Establish how much exposure moved into Stage 2, where it came from, and which sectors and borrowers drove the movement.",
    status: "open",
    owner: "Head of Credit Risk",
    project: "March 2026 Portfolio Review",
    updated: "2026-03-31",
    tags: ["IFRS 9", "Staging", "Monthly"],
    steps: [
      {
        analysisId: "stage_distribution",
        title: "Current stage split",
        rationale: "Establish the closing position before explaining the movement.",
      },
      {
        analysisId: "stage_migration",
        title: "Stage migration, opening to closing",
        rationale:
          "Measure what actually moved between stages, facility by facility, rather than inferring it from the change in totals.",
        params: { from_period: "previous", to_period: "latest" },
      },
      {
        analysisId: "ecl_movement",
        title: "ECL attribution",
        rationale: "Separate the loss impact of migration from remeasurement and overlay.",
        params: { from_period: "previous", to_period: "latest", group_by: "sector" },
      },
      {
        analysisId: "top_deteriorating_borrowers",
        title: "Borrowers behind the movement",
        rationale: "Identify the names to take to committee.",
        params: { from_period: "previous", to_period: "latest", top_n: 10 },
      },
    ],
    followUps: [
      "Which sectors contributed most to the Stage 2 increase?",
      "How much of the movement is concentrated in the top 10 borrowers?",
      "What would a moderate downturn do to these facilities?",
    ],
  },
  {
    id: "real-estate-deterioration",
    title: "Real Estate Deterioration",
    question: "How exposed are we to Real Estate, and is it getting worse?",
    objective:
      "Quantify Real Estate exposure and concentration, measure its deterioration, and size the loss under a downturn.",
    status: "open",
    owner: "Sector Credit Head",
    project: "Real Estate Deep Dive",
    updated: "2026-03-28",
    tags: ["Sector", "Concentration", "Real Estate"],
    steps: [
      {
        analysisId: "portfolio_summary",
        title: "Real Estate position",
        rationale: "Size the sector before analysing it.",
        filters: { sector: "Real Estate" },
      },
      {
        analysisId: "sector_concentration",
        title: "Concentration across sectors",
        rationale: "Put Real Estate in context and expose single-name risk inside it.",
      },
      {
        analysisId: "stage_migration",
        title: "Real Estate stage migration",
        rationale: "Measure deterioration within the sector specifically.",
        params: { from_period: "previous", to_period: "latest" },
        filters: { sector: "Real Estate" },
      },
      {
        analysisId: "stress_scenario_basic",
        title: "Downturn impact on Real Estate",
        rationale: "Size the incremental loss under a moderate management scenario.",
        params: { scenario: "moderate", sector: "Real Estate" },
      },
    ],
    followUps: [
      "Which Real Estate borrowers deteriorated most?",
      "What is the largest single name inside the sector?",
      "How does Real Estate coverage compare with the rest of the book?",
    ],
  },
  {
    id: "rating-migration-review",
    title: "Rating Migration Review",
    question: "How have internal ratings migrated over the last year?",
    objective:
      "Produce the empirical transition matrix, quantify upgrade and downgrade rates, and identify where downgrades concentrated.",
    status: "in_review",
    owner: "Credit Risk Analytics",
    project: "March 2026 Portfolio Review",
    updated: "2026-03-25",
    tags: ["Ratings", "Migration", "Quarterly"],
    steps: [
      {
        analysisId: "rating_transition_matrix",
        title: "Transition matrix",
        rationale:
          "Empirical transition probabilities, measured by joining the same facility across both periods.",
        params: { from_period: "earliest", to_period: "latest" },
      },
      {
        analysisId: "dpd_migration",
        title: "Delinquency migration",
        rationale: "Cross-check the rating view against observed arrears behaviour.",
        params: { from_period: "earliest", to_period: "latest" },
      },
      {
        analysisId: "top_deteriorating_borrowers",
        title: "Largest downgrades",
        rationale: "Name the facilities behind the downgrade rate.",
        params: { from_period: "earliest", to_period: "latest", top_n: 15 },
      },
    ],
    followUps: [
      "Is the downgrade rate concentrated in one sector?",
      "How does the matrix change over a shorter interval?",
    ],
  },
  {
    id: "ecl-movement-investigation",
    title: "ECL Movement Investigation",
    question: "Why did ECL change this period?",
    objective:
      "Attribute the change in impairment to migration, new Stage 3, overlay, remeasurement, new business and exits, and reconcile it exactly.",
    status: "open",
    owner: "IFRS 9 Reporting",
    project: "IFRS 9 ECL Review",
    updated: "2026-03-30",
    tags: ["IFRS 9", "ECL", "Attribution"],
    steps: [
      {
        analysisId: "ecl_movement",
        title: "ECL bridge",
        rationale:
          "Opening to closing, attributed to its drivers, with every component reconciling exactly.",
        params: { from_period: "previous", to_period: "latest", group_by: "sector" },
      },
      {
        analysisId: "stage_distribution",
        title: "Coverage by stage",
        rationale: "Show where the provision now sits.",
      },
      {
        analysisId: "portfolio_trend",
        title: "Coverage trend",
        rationale: "Place this period's movement in the context of the trend.",
      },
    ],
    followUps: [
      "How much of the ECL increase came from new Stage 3?",
      "Which sector contributed most to the movement?",
    ],
  },
];

export function findInvestigation(id: string): Investigation | undefined {
  return INVESTIGATIONS.find((i) => i.id === id);
}

// ===================================================================== projects

export interface Project {
  id: string;
  name: string;
  description: string;
  owner: string;
  team: string;
  status: "active" | "in_review" | "closed";
  updated: string;
  counts: { chats: number; investigations: number; blueprints: number; documents: number };
  investigationIds: string[];
}

export const PROJECTS: Project[] = [
  {
    id: "march-2026-portfolio-review",
    name: "March 2026 Portfolio Review",
    description:
      "Quarter-end review of the wholesale book for the Board Risk Committee: staging, coverage, concentration and the names driving deterioration.",
    owner: "Head of Credit Risk",
    team: "Wholesale Credit",
    status: "active",
    updated: "2026-03-31",
    counts: { chats: 6, investigations: 2, blueprints: 2, documents: 1 },
    investigationIds: ["stage-2-deterioration", "rating-migration-review"],
  },
  {
    id: "real-estate-deep-dive",
    name: "Real Estate Deep Dive",
    description:
      "Standing review of Real Estate exposure, concentration and downturn sensitivity ahead of the sector limit reset.",
    owner: "Sector Credit Head",
    team: "Wholesale Credit",
    status: "active",
    updated: "2026-03-28",
    counts: { chats: 4, investigations: 1, blueprints: 1, documents: 1 },
    investigationIds: ["real-estate-deterioration"],
  },
  {
    id: "ifrs9-ecl-review",
    name: "IFRS 9 ECL Review",
    description:
      "Attribution of the impairment movement and review of overlay usage for the IFRS 9 Committee.",
    owner: "IFRS 9 Reporting",
    team: "Group Finance",
    status: "in_review",
    updated: "2026-03-30",
    counts: { chats: 3, investigations: 1, blueprints: 1, documents: 1 },
    investigationIds: ["ecl-movement-investigation"],
  },
];

export function findProject(id: string): Project | undefined {
  return PROJECTS.find((p) => p.id === id);
}

// =================================================================== blueprints

export interface Blueprint {
  id: string;
  name: string;
  description: string;
  owner: string;
  cadence: string;
  version: string;
  /** The registered analyses this workflow runs, in order. */
  steps: { analysisId: string; title: string }[];
  parameters: { name: string; description: string; default: string }[];
}

export const BLUEPRINTS: Blueprint[] = [
  {
    id: "monthly-deterioration-review",
    name: "Monthly Portfolio Deterioration Review",
    description:
      "The standing month-end deterioration pack: position, what moved between stages, what it did to ECL, and the names behind it. Re-run each period against the same definitions so the results are comparable.",
    owner: "Credit Risk Analytics",
    cadence: "Monthly",
    version: "1.2.0",
    steps: [
      { analysisId: "portfolio_summary", title: "Portfolio position" },
      { analysisId: "stage_migration", title: "Stage migration" },
      { analysisId: "ecl_movement", title: "ECL attribution" },
      { analysisId: "top_deteriorating_borrowers", title: "Deteriorating names" },
    ],
    parameters: [
      { name: "period", description: "Closing reporting period.", default: "latest" },
      { name: "compare_period", description: "Opening period.", default: "previous" },
      { name: "top_n", description: "Number of borrowers to list.", default: "10" },
    ],
  },
  {
    id: "stage-2-investigation",
    name: "Stage 2 Investigation",
    description:
      "Decomposes a Stage 2 movement into its origin, its sector concentration and the facilities responsible. Used whenever the staging ratio moves more than the tolerance.",
    owner: "Head of Credit Risk",
    cadence: "On trigger",
    version: "1.0.0",
    steps: [
      { analysisId: "stage_distribution", title: "Stage split" },
      { analysisId: "stage_migration", title: "What moved" },
      { analysisId: "sector_concentration", title: "Where it concentrated" },
    ],
    parameters: [
      { name: "period", description: "Reporting period.", default: "latest" },
      { name: "basis", description: "Exposure or facility count.", default: "ead" },
    ],
  },
  {
    id: "rating-migration-review-bp",
    name: "Rating Migration Review",
    description:
      "Produces the empirical rating transition matrix over a chosen interval, with upgrade and downgrade rates and a delinquency cross-check.",
    owner: "Credit Risk Analytics",
    cadence: "Quarterly",
    version: "1.1.0",
    steps: [
      { analysisId: "rating_transition_matrix", title: "Transition matrix" },
      { analysisId: "dpd_migration", title: "Delinquency migration" },
    ],
    parameters: [
      { name: "from_period", description: "Opening period.", default: "earliest" },
      { name: "to_period", description: "Closing period.", default: "latest" },
    ],
  },
  {
    id: "sector-concentration-review",
    name: "Sector Concentration Review",
    description:
      "Concentration by sector with the Herfindahl index and the largest single name inside each sector, followed by a downturn scenario on the largest exposures.",
    owner: "Portfolio Management",
    cadence: "Quarterly",
    version: "1.0.0",
    steps: [
      { analysisId: "sector_concentration", title: "Concentration" },
      { analysisId: "stress_scenario_basic", title: "Downturn sensitivity" },
    ],
    parameters: [
      { name: "dimension", description: "Concentration dimension.", default: "sector" },
      { name: "scenario", description: "Stress preset.", default: "moderate" },
    ],
  },
];

export function findBlueprint(id: string): Blueprint | undefined {
  return BLUEPRINTS.find((b) => b.id === id);
}

// ==================================================================== documents

export interface DocumentRecord {
  id: string;
  title: string;
  kind: string;
  owner: string;
  status: "draft" | "in_review" | "approved";
  updated: string;
  project: string;
  sections: string[];
}

export const DOCUMENTS: DocumentRecord[] = [
  {
    id: "march-2026-cro-review",
    title: "March 2026 CRO Portfolio Review",
    kind: "Board Risk Committee paper",
    owner: "Head of Credit Risk",
    status: "in_review",
    updated: "2026-03-31",
    project: "March 2026 Portfolio Review",
    sections: [
      "Executive summary",
      "Portfolio position",
      "Staging and coverage",
      "Concentration",
      "Deteriorating names",
      "Scenario sensitivity",
      "Recommendations",
    ],
  },
  {
    id: "real-estate-sector-review",
    title: "Real Estate Sector Review",
    kind: "Sector committee paper",
    owner: "Sector Credit Head",
    status: "draft",
    updated: "2026-03-28",
    project: "Real Estate Deep Dive",
    sections: [
      "Sector overview",
      "Exposure and concentration",
      "Deterioration",
      "Collateral and coverage",
      "Limit recommendation",
    ],
  },
  {
    id: "ifrs9-committee-pack",
    title: "IFRS 9 Committee Pack",
    kind: "IFRS 9 Committee pack",
    owner: "IFRS 9 Reporting",
    status: "approved",
    updated: "2026-03-30",
    project: "IFRS 9 ECL Review",
    sections: [
      "ECL movement",
      "Staging",
      "Overlay usage",
      "Model performance",
      "Governance",
    ],
  },
];

export function findDocument(id: string): DocumentRecord | undefined {
  return DOCUMENTS.find((d) => d.id === id);
}

// ======================================================== users, teams, workflow

export interface UserRecord {
  id: string;
  name: string;
  email: string;
  role: "ADMIN" | "DATA_STEWARD" | "ANALYST" | "VIEWER";
  team: string;
  lastActive: string;
  status: "active" | "disabled";
}

export const USERS: UserRecord[] = [
  { id: "u1", name: "A. Rahman", email: "a.rahman@bank.example", role: "ADMIN", team: "Risk Technology", lastActive: "2026-03-31", status: "active" },
  { id: "u2", name: "S. Nair", email: "s.nair@bank.example", role: "DATA_STEWARD", team: "Group Data Office", lastActive: "2026-03-31", status: "active" },
  { id: "u3", name: "M. Haddad", email: "m.haddad@bank.example", role: "ANALYST", team: "Wholesale Credit", lastActive: "2026-03-30", status: "active" },
  { id: "u4", name: "L. Okafor", email: "l.okafor@bank.example", role: "ANALYST", team: "Credit Risk Analytics", lastActive: "2026-03-29", status: "active" },
  { id: "u5", name: "J. Tanaka", email: "j.tanaka@bank.example", role: "VIEWER", team: "Board Risk Committee", lastActive: "2026-03-24", status: "active" },
  { id: "u6", name: "P. Lindqvist", email: "p.lindqvist@bank.example", role: "DATA_STEWARD", team: "Group Finance", lastActive: "2026-03-27", status: "active" },
  { id: "u7", name: "R. Costa", email: "r.costa@bank.example", role: "ANALYST", team: "Wholesale Credit", lastActive: "2026-02-11", status: "disabled" },
];

export interface TeamRecord {
  id: string;
  name: string;
  purpose: string;
  members: number;
  projects: number;
}

export const TEAMS: TeamRecord[] = [
  { id: "t1", name: "Wholesale Credit", purpose: "Corporate and commercial portfolio management.", members: 3, projects: 2 },
  { id: "t2", name: "Credit Risk Analytics", purpose: "Owns the analytical capability and its certification.", members: 1, projects: 1 },
  { id: "t3", name: "Group Data Office", purpose: "Owns data domains, dictionary and publication.", members: 1, projects: 0 },
  { id: "t4", name: "Group Finance", purpose: "IFRS 9 impairment reporting and governance.", members: 1, projects: 1 },
  { id: "t5", name: "Board Risk Committee", purpose: "Read-only oversight of the portfolio.", members: 1, projects: 0 },
];

/** What each role may do. Mirrors backend/api/permissions.py. */
export const ROLE_MATRIX: {
  capability: string;
  ADMIN: boolean;
  DATA_STEWARD: boolean;
  ANALYST: boolean;
  VIEWER: boolean;
}[] = [
  { capability: "View analyses and results", ADMIN: true, DATA_STEWARD: true, ANALYST: true, VIEWER: true },
  { capability: "Run a certified analysis", ADMIN: true, DATA_STEWARD: true, ANALYST: true, VIEWER: false },
  { capability: "Create and edit datasets", ADMIN: true, DATA_STEWARD: true, ANALYST: false, VIEWER: false },
  { capability: "Upload source files", ADMIN: true, DATA_STEWARD: true, ANALYST: false, VIEWER: false },
  { capability: "Edit the data dictionary", ADMIN: true, DATA_STEWARD: true, ANALYST: false, VIEWER: false },
  { capability: "Publish a dataset", ADMIN: true, DATA_STEWARD: true, ANALYST: false, VIEWER: false },
  { capability: "Certify an analysis", ADMIN: true, DATA_STEWARD: false, ANALYST: false, VIEWER: false },
  { capability: "Manage users and roles", ADMIN: true, DATA_STEWARD: false, ANALYST: false, VIEWER: false },
];

export interface WorkflowItem {
  id: string;
  title: string;
  objectType: string;
  state: "submitted" | "in_review" | "approved" | "rejected";
  requestedBy: string;
  assignedTo: string;
  submitted: string;
  due: string;
}

export const WORKFLOW_ITEMS: WorkflowItem[] = [
  { id: "w1", title: "Certify: High Utilisation Watchlist v0.1.0", objectType: "Engine analysis", state: "submitted", requestedBy: "M. Haddad", assignedTo: "A. Rahman", submitted: "2026-03-29", due: "2026-04-05" },
  { id: "w2", title: "Publish: Third-party ECL Extract v2", objectType: "Dataset", state: "in_review", requestedBy: "S. Nair", assignedTo: "P. Lindqvist", submitted: "2026-03-28", due: "2026-04-02" },
  { id: "w3", title: "Approve: March 2026 CRO Portfolio Review", objectType: "Document", state: "in_review", requestedBy: "Head of Credit Risk", assignedTo: "J. Tanaka", submitted: "2026-03-31", due: "2026-04-08" },
  { id: "w4", title: "Approve: Moderate downturn scenario calibration", objectType: "Stress scenario", state: "approved", requestedBy: "L. Okafor", assignedTo: "A. Rahman", submitted: "2026-03-20", due: "2026-03-27" },
  { id: "w5", title: "Certify: Sector Concentration v1.0.0", objectType: "Engine analysis", state: "approved", requestedBy: "Credit Risk Analytics", assignedTo: "A. Rahman", submitted: "2026-03-12", due: "2026-03-19" },
];

// ================================================================ suggestions

/**
 * The suggested questions on the Cockpit.
 *
 * Each maps to a real registered analysis, so pressing one runs governed code
 * rather than producing a scripted answer. When the planner arrives it will
 * choose these same analyses from the same registry.
 */
export interface SuggestedQuestion {
  question: string;
  analysisId: string;
  params?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  note: string;
}

export const SUGGESTED_QUESTIONS: SuggestedQuestion[] = [
  {
    question: "What deteriorated this period?",
    analysisId: "top_deteriorating_borrowers",
    params: { from_period: "previous", to_period: "latest", top_n: 10 },
    note: "Runs Top Deteriorating Borrowers",
  },
  {
    question: "Why has Stage 2 increased?",
    analysisId: "stage_migration",
    params: { from_period: "previous", to_period: "latest" },
    note: "Runs Stage Migration",
  },
  {
    question: "Which sectors deteriorated the most?",
    analysisId: "ecl_movement",
    params: { from_period: "previous", to_period: "latest", group_by: "sector" },
    note: "Runs ECL Movement by sector",
  },
  {
    question: "Show me the rating transition matrix.",
    analysisId: "rating_transition_matrix",
    params: { from_period: "earliest", to_period: "latest" },
    note: "Runs Rating Transition Matrix",
  },
  {
    question: "Show the top deteriorating borrowers.",
    analysisId: "top_deteriorating_borrowers",
    params: { from_period: "earliest", to_period: "latest", top_n: 15 },
    note: "Runs Top Deteriorating Borrowers",
  },
  {
    question: "Stress the Real Estate portfolio.",
    analysisId: "stress_scenario_basic",
    params: { scenario: "moderate", sector: "Real Estate" },
    note: "Runs Basic Management Stress Scenario",
  },
];
