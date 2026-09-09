# Where the evidence sits — CBUAE MMS / MMG and the validation tests

## What this document is, and what it is not

This is a map. It says, for each supervisory expectation the Scorecard
Validation Intelligence module addresses, which validation tests produce the
evidence a reader would look for.

**It is not a compliance assessment, and it must not be presented as one.**
CreditProbe has no standing to determine whether a model complies with any
regulation. A supervisor decides that, on a submission, after reading the
evidence and asking questions software was never asked.

That is not a disclaimer bolted onto a document. It is enforced in the code:

- The status vocabulary in `backend/scorecard/validation/regulatory.py` has
  no word for "compliant". A reference is EVIDENCED, PARTIALLY EVIDENCED,
  NOT EVIDENCED or NOT APPLICABLE, and every one of those is a statement
  about *this engine's own output* on one run.
- `DISCLAIMER` travels on every response the module produces, because a
  coverage table separated from its disclaimer becomes a compliance claim
  the moment it is pasted into a slide.
- `tests/scorecard/test_validation_regulatory.py` asserts both, including
  that no status string contains "COMPLIAN" or "APPROVED".

The article summaries below are **this engine's reading** of what each
reference asks for. They are not quotations. The published text governs.

## The two questions a coverage table must keep apart

**"Was it tested?"** and **"did it pass?"** are different questions, and a
table that conflates them reports a well-evidenced failing model as a
coverage gap — which is precisely backwards. A reference evidenced entirely
by breaches is still EVIDENCED: the validation did its job and the answer
was bad.

So each row carries both: the coverage status, and separately the list of
mapped tests whose results were adverse.

## The map

References are recorded on the test registry, not here. A test knows what it
evidences; a second list in this document would be a second opinion about
the same thing, and the first time a reference changed only one of them
would be updated. `Requirement.tests()` reads the registry.

| Reference | Title | Kind | Tests | What it asks for (engine's reading) |
|---|---|---|---:|---|
| MMS 4.9 | Model documentation | Documentary | 1 | That development, assumptions, limitations and intended use are documented well enough that a competent reviewer who was not involved in building the model can follow what was done and why. |
| MMS 9.4 | Ongoing monitoring | Quantitative | 7 | That a model in use is monitored between validations, on measures that would detect deterioration before an annual cycle would, with thresholds attached rather than a chart somebody looks at. |
| MMS 10.3 | Conceptual soundness | Documentary | 5 | That purpose, target definition, observation and performance windows and sign conventions are recorded and internally consistent — before any question about performance. |
| MMS 10.4 | Outcomes analysis | Quantitative | 36 | That realised performance is measured against predictions on data with a closed outcome window: discrimination, calibration, stability, characteristic behaviour, and whether the production implementation is the approved one. |
| MMG 2.8 | Model purpose and design | Documentary | 5 | That the model was designed for the use it is being put to, and that the design choices are recorded rather than inferred from the code. |
| MMG 2.9 | Use test | Quantitative | 3 | That the model is used the way its approval describes — including at the cut-off, where a policy routinely departed from is not the policy in force. |
| MMG 2.10 | Overrides and departures | Quantitative | 3 | That departures from the model's output are recorded, attributed, reasoned, and measured against their outcomes. |
| MMG 2.11 | Independent validation | Quantitative | 22 | That validation is performed independently of development, reproduces the model's numbers rather than accepting them, and states what it could not test. |
| MMG 3.9 | Calibration and probability estimates | Quantitative | 5 | That where a model produces probabilities rather than only an ordering, those probabilities are compared against realised outcomes at the level decisions are taken. |

Every one of the 48 registered tests maps to at least one reference —
`test_every_test_maps_to_a_reference_in_the_catalogue` fails the build
otherwise, because a test that evidences something nobody can look up is a
test whose result nobody can place.

## How a finding cites a reference

Findings do not carry article numbers of their own. `findings._cite` derives
each finding's references from the tests it names as evidence, so a citation
always resolves to a registry entry and from there to a requirement.

This was a real defect, fixed rather than designed: the patterns originally
carried hand-written references — MMS 10.5, 10.6, 10.8, 10.9, 10.10, MMG
2.13, 2.14 — that appeared in no registry entry and no requirement. Each was
a citation that led nowhere.

## What the gaps look like

The gaps are the useful half of the report. A reference reported as
PARTIALLY EVIDENCED names each test that did not produce a result and quotes
the test's own explanation — "the performance window for this cohort has not
closed", "the model has no score-to-PD mapping", "fewer events than the
engine's minimum". A validator can act on that. The same reference reported
as "78% covered" is not actionable by anyone.

One case is deliberately not a gap: a test that is NOT APPLICABLE to the
model. A scorecard with no challenger has no champion-challenger evidence to
be missing, and counting its absence against coverage would push every
single-model scorecard toward a worse-looking report for a reason that has
nothing to do with its validation.

## Where this sits in the product

- `backend/scorecard/validation/regulatory.py` — the map and the coverage
  report.
- `GET /api/v1/scorecard-validation/regulatory` — the catalogue, nothing run.
- The coverage report travels with a run's results, for the same reason the
  findings do: returning them separately invites a client to pair a fresh
  set with a stale one.
