# Known limitations — client demonstration

Written to be shown to a client. Everything here is true and everything here
is sayable out loud. A limitation stated before it is discovered is a mark of
seriousness; the same limitation discovered by the audience is not.

---

## 1. What you are looking at

**Synthetic data.** A Saudi corporate credit book generated for
demonstration — borrowers, facilities, ratings, IFRS 9 staging, delinquency,
covenants and collateral across ten quarterly snapshots. No client data is
present, and the header says so on every screen.

**A local demonstration.** One laptop, Docker Desktop, everything on it. This
is not a deployed system and no claim is made about deployment readiness.

**A release candidate.** This build is prepared for a demonstration. It has
not been through the deployment, security review and operational readiness
work a production installation requires.

---

## 2. What is shown, and what is not

**Shown and real:** the Cockpit, Projects, Investigations, Analyses, Analysis
Studio, Data Builder, Trace and Lineage, Workflow, the Excel exports,
Requires Attention, Assurance and the feedback prompt.

**Available but not on the walkthrough:** Lenses, Stress Testing, Early
Warning, Playbooks, Agent Operations, the AI Intelligence Studio, Users &
Teams and Settings. All real; ask and they can be shown.

**Backend only — no screen in this build:**

| Capability | State |
|---|---|
| Regulatory circular knowledge | The full pipeline exists and is tested — ingestion in six formats, SME review, releases, as-of retrieval, citations and five critical Assurance gates. It is reachable at the API and has no screen. |
| Teaching corpus import (500+ Q&A) | The template, the four-outcome preview and the import all work at the API. No screen. |

**Not built:**

* The governed **Project Plan** — a Project holds context, threads, analyses
  and people, but not a structured operating plan.
* **Arabic and right-to-left** — out of scope for this release.
* **Document authoring** — the Documents screen is a placeholder and is hidden
  during the demonstration rather than shown as though it worked.
* **Shadow Mode.**
* **Scheduled Playbooks** — manual and on-publication triggers run; scheduled
  ones are not wired to a scheduler.
* **A Project risk summary** — asked "review unresolved risks in this
  Project", CreditProbe asks which figure to measure rather than summarising
  the Project's open Risk Cases. The clarification is correct behaviour for a
  sentence that names no measure; the summary capability itself does not
  exist.

---

## 2a. Three things to know before you click

**A Viewer cannot open a Lens.** Every tile on a Lens runs an analysis, and
running one requires an Analyst. A Viewer sees the Lenses link and gets a
dashboard of refusals. Sign in as the Analyst or the Administrator to show
Lenses. The permission is deliberate; the invitation is a rough edge and is
recorded rather than papered over.

**Opening an analysis definition directly logs a console 404.** It asks for an
Assurance record, and Assurance records belong to Investigations rather than
to a bare engine run. The page renders correctly. The walkthrough reaches
analyses through Analyses and Trace, where this does not arise.

**Requires Attention shows counts for what actually moved.** At Q2 2026 that
is one Segment case and four Borrower cases; Portfolio and Data are empty
because nothing moved at portfolio level and no dataset is missing. Nothing is
invented to fill a filter.

---

## 3. Accuracy — said plainly

**There is no 99.99% accuracy claim, and there will not be one today.**

Three reasons, and all three hold independently:

1. The measurement — a certification run over the sealed holdout — has not
   been made on this build.
2. Establishing one error in ten thousand with any confidence needs a holdout
   on the order of 10⁵ independently adjudicated cases. The sealed holdout is
   nowhere near that size, so no run of it could distinguish 99.99% from
   99.9%.
3. User feedback does not contribute to an accuracy figure and is forbidden
   by name from doing so. A satisfaction figure is not a precision figure.

**Operational Assurance is not accuracy.** The Assurance panel reports whether
the process held — the right dataset, the right period, the right grain, the
invariants, the grounding. It is never labelled accuracy and the product
refuses to present it as one.

What can be said: on the measured probes, officer selection and outcome
accuracy are 100%, invariants passed on 100% of executed analyses, and there
were no critical failures. That is conformance on a small sample, and it is
offered as nothing more.

---

## 4. The AI, said plainly

**The model never calculates.** It reads the question, plans the analysis and
explains the result. Every figure comes from the deterministic engine, and the
Trace shows the query that produced it.

**Model configuration.** Anthropic, with roles configured per stage — routing,
planning, complex planning, interpretation and repair. Which model serves each
role is configuration, not code, and the AI panel reports it.

**Live verification is a state, not a promise.** The panel shows whether *this
exact build* has been verified against the live model, and shows STALE when
the code or the model configuration has moved on since. If it says the build
has not been verified, it has not been.

**When the provider is unavailable** CreditProbe says so. Deterministic
questions — the catalogue, and analyses that need no planning — still work.
Complex ones state that live AI is unavailable rather than answering anyway.

---

## 5. Feedback and learning

**Raw feedback changes nothing automatically.** A rating is evidence. It
becomes a candidate only with consent and a correction; a candidate becomes
usable only when a human approves it; an approved candidate reaches production
only inside a release that passed five gates and was activated by a named
approver who was not the sole reviewer.

**This does not retrain Anthropic's foundation model.** No weights are read,
written or influenced, and no training data is sent to Anthropic. Local
improvement means reviewed teaching cases, prompt and routing policy, and
small local classifiers that choose between options the deterministic layer
already offers.

---

## 6. Regulatory

**No regulatory advice is offered, and no circular is loaded.**

Asked what a circular or a regulation says, CreditProbe refuses: it answers
such questions only from an approved Regulatory Knowledge Release, none is
active on this deployment, and it will not answer from the analytical data
instead. That refusal is deliberate and is worth demonstrating.

Once a bank loads its own circulars and a regulatory SME approves them, the
same question is answered with a citation and an effective date, and an
uncited regulatory claim is blocked by a critical Assurance gate.

---

## 7. Governance

**Material actions require a person.** Publishing an Investigation globally,
activating any release, certifying a method and approving a candidate all
require a named approver, and an approver may not be the only reviewer.

**Permissions are enforced at the API**, not by hiding links. A Viewer who
types an administrative address gets a refusal, not a screen.

---

## 8. Performance

The demonstration runs on one laptop. A live model call takes as long as it
takes and the working indicator shows real stages rather than a fake
percentage. Deterministic answers are fast. The four-condition question in the
deep path is the slowest in the set and coordinates four specialists.

---

## 9. What has not been verified in this environment

Stated so nothing here is taken for more than it is:

| Not verified | Why |
|---|---|
| The Docker stack built and run | The development sandbox has no Docker daemon. The compose file is valid; nothing was built or started there. |
| Any mode that spends credit | Live provider calls are forbidden in that environment. The presenter runs them on their own key. |
| The two workbook downloads through a browser | The sandbox browser cannot accept a file download. The workbooks are covered by tests; the click is not. |
| The Windows PowerShell scripts executed on Windows | They are parsed and checked for 5.1 and 7 compatibility and ASCII safety; they were not run on a Windows host. |
