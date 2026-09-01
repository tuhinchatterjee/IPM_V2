# Scorecard Model Registry

Ten tables, a lifecycle, and the operations they exist to refuse.

---

## 1. Why a registry when the equation is already on disk

`build.py` writes the binning specification and the fitted coefficients beside
the Parquet lake. That is enough to compute a score and not enough to govern
one.

A finding raised in March against version 1.0.0 has to still mean something in
September — by which time 1.1.0 may be active and the demonstration universe
has been rebuilt twice, because `build.py` deletes and regenerates. The
registry is the part that does not get regenerated: **what was registered, who
approved it, what was found against it, and what was reported to whom.**

---

## 2. The tables

| Table | Holds |
|---|---|
| `scorecard_models` | One registered version. §35's candidates are rows here with status `CANDIDATE` |
| `scorecard_model_variables` | Active and candidate variables, with role, IV and scoreability |
| `scorecard_binning_specs` | Versioned WoE bins, whole, never edited in place |
| `scorecard_policy_limits` | Every limit with its source |
| `scorecard_validation_runs` | One validation of one model over one period, carrying maturity |
| `scorecard_findings` | A finding with the evidence and runs behind it |
| `scorecard_model_approvals` | Append-only status transitions |
| `scorecard_dashboard_pins` | What a user chose to watch |
| `scorecard_reports` | A generated report, storing the disclaimer it was issued with |
| `scorecard_report_evidence` | Every figure a report printed, and where it came from |

Migration `0028`. Upgrades and downgrades cleanly; alembic reports no drift
against the models.

No scored rows live here. Twelve to nineteen thousand a month belong in the
lake — this is the filing cabinet, not the warehouse.

---

## 3. The lifecycle

```
DEVELOPMENT ──> CANDIDATE ──> APPROVED ──> ACTIVE ──> RETIRED
     │              │             │                     ▲
     └──────────────┴─────────────┴─────────────────────┘
                (refusal and withdrawal)
```

**`ACTIVE` has exactly one predecessor, and it is `APPROVED`.** A test asserts
this stays true: a second route to `ACTIVE` would make the narrower approval
permission a formality somebody could route around.

**Activation retires by scorecard type, not by model id.** A challenger is
registered under its own id, so retiring only same-id versions would leave the
incumbent scoring the same applications alongside the challenger that replaced
it. Application and Behavioral both stay live — different populations,
different points in the account lifecycle.

Every transition writes an approval row. The model row says where a version
is; the trail says how it got there, which is the question an audit asks and
the one a mutable column cannot answer.

---

## 4. What the registry refuses

- **Editing an ACTIVE model's equation.** Re-registering the same version with
  the same equation is a reseed and is fine. Re-registering it with a
  different one is not an update — it is a different model wearing the
  approved version's number.
- **A model with no score mapping.** §13 says the registry defines the sign
  convention, and a model registered without one leaves every discrimination
  statistic ambiguous.
- **A variable the dictionary does not define.** `variables.get` raises, and
  the exception is allowed through: registering an unknown name with blank
  metadata is exactly how a hidden predictor gets into a registry and stays
  there.
- **A candidate reusing the version it modifies.** A proposal indistinguishable
  from the model it changes cannot be reviewed.
- **A limit whose provenance is not one of the five.** The source is what tells
  a reader whether a number is a convention or a requirement.
- **A breach with no limit source.** A breach of an unattributed limit cannot
  be defended.
- **A report with no disclaimer.** The copy somebody was handed has to be
  recoverable.

---

## 5. The seeded state

Six models: three per scorecard (`INCUMBENT`, `CHALLENGER`, `RECALIBRATED`).
One `ACTIVE` per type — the incumbent — and the other two `CANDIDATE`. Fifteen
`DEMO POLICY` limits.

Seeding is opt-in behind `--register`.

Information value is read from the **binning specification**, not the fit: it
is a property of how a variable separates under the approved bins, and the
same variable has a different IV under a different spec.

---

## 6. Permissions

| Permission | Roles |
|---|---|
| `SCORECARD_VIEW`, `SCORECARD_ANALYSE` | Administrator, Data Steward, Analyst |
| `SCORECARD_VALIDATE`, `SCORECARD_MODEL_EDIT_CANDIDATE` | Administrator, Data Steward |
| `SCORECARD_REPORT_GENERATE`, `SCORECARD_FINDING_CREATE` | Administrator, Data Steward |
| `SCORECARD_MODEL_APPROVE`, `SCORECARD_FINDING_APPROVE`, `SCORECARD_ADMIN` | Administrator |

Approving is a strict subset of proposing. A test asserts the containment
rather than the membership, so the separation of duties cannot be widened by
adding a role to one set.
