"""Which columns a scenario may move, in what units, and where it may not.

Section 3.2 asks for a field dictionary carrying, per field: source table and
column, grain, type, unit, allowed range, missing-value meaning, horizon,
transformation, whether it is mutable in a scenario, its downstream
dependencies, and which methods support it.

Everything here was measured against the published parquet, not read off a
schema comment. Three measurements decide most of the eligibility rules, and
they are worth stating because they are not obvious from the column names:

**The ECL identity.** Published ECL is `ead x pd x lgd`, with the 12-month PD
at Stage 1 and the lifetime PD at Stages 2 and 3. Corporate reconciles to
-0.3343 SAR mn on a 7,075,662 SAR mn book -- zero to four decimal places, pure
rounding. That exactness is what makes proportional Delta sound here: a 20%
PD rise really does raise ECL 20%, because ECL is linear in PD.

**Stage 3 has no PD to shock.** Every Stage 3 row carries `pd_pit_12m = 1.0`
and `pd_lifetime = 1.0` exactly -- 14,836 Corporate rows and 13,295 Retail --
and its ECL is `ead x lgd`. A relative PD shock on a probability that is
already one is not a conservative estimate, it is a meaningless one, so
Stage 3 is reason-coded ineligible for a PD shock rather than silently scaled.

**The Retail write-off floor.** 1,837 written-off Stage 3 accounts carry
`ecl = max(ecl, written_off - recovered)`, which adds 53.04 SAR mn -- 1.97% of
the published Retail book. On those rows ECL is not a function of PD, LGD or
EAD at all, so no proportional shock on any of the three is sound, and they
are ineligible for proportional Delta with that reason attached.

None of these is a defect in the book. They are facts about it that a stress
engine has to know, and section 9.1 is explicit that the alternative --
"silently treat an ineligible record as zero incremental ECL" -- is the thing
not to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario import spec as sp
from backend.cockpit_v4.scenario import units as un
from backend.cockpit_v4.scenario.errors import MAPPING_UNAVAILABLE, raise_for

#: Published in the book, as a real column.
PUBLISHED = "published"

#: Not a column, but recoverable exactly from ones that are. Labelled
#: everywhere it is used; section 3.3 forbids passing a derivation off as a
#: source fact.
DERIVED = "derived"

#: Named by the specification and absent from this book.
ABSENT = "absent"


@dataclass(frozen=True)
class Field:
    """One column a scenario might read or move."""

    field_id: str
    relation: str
    #: PUBLISHED, DERIVED or ABSENT.
    availability: str
    storage: str
    unit: str
    what: str
    #: Inclusive, in the column's own storage. None where unbounded.
    low: Decimal | None = None
    high: Decimal | None = None
    #: May a scenario change it? A key or a label may not.
    mutable: bool = False
    #: Fields whose value depends on this one.
    affects: tuple[str, ...] = ()
    #: Methods that can act on a change to it.
    methods: tuple[str, ...] = (sp.DELTA, sp.USER_DEFINED)
    #: For a PD: which horizon it is. Section 9.2 keeps these distinct.
    horizon: str = ""
    #: What a null means here. Section 3.2: an observed zero is not missing.
    missing_means: str = ""
    #: How a DERIVED field is computed, exactly.
    derivation: str = ""
    #: Why an ABSENT field is absent, and what depends on it.
    absent_note: str = ""


_D = Decimal


def _money(field_id: str, relation: str, what: str, **over) -> Field:
    body = dict(field_id=field_id, relation=relation, availability=PUBLISHED,
                storage=un.MONEY, unit="SAR million", what=what,
                low=_D("0"), missing_means="not published for this row")
    body.update(over)
    return Field(**body)


# ---- Corporate ---------------------------------------------------------

_CORP_FACILITY = "corp_facility_quarter"
_CORP_BORROWER = "corp_borrower_quarter"

CORPORATE_FIELDS: tuple[Field, ...] = (
    # -- the measured outcome --
    _money("ecl_sar_mn", _CORP_FACILITY,
           "reported ECL: the 12-month figure at Stage 1, lifetime at Stages "
           "2 and 3",
           mutable=False,
           missing_means="never null; an observed zero would be a real zero"),
    _money("ecl_12m_sar_mn", _CORP_FACILITY, "12-month ECL, always published"),
    _money("ecl_lifetime_sar_mn", _CORP_FACILITY, "lifetime ECL"),

    # -- the three parameters Delta can move --
    Field("pd_pit_12m", _CORP_FACILITY, PUBLISHED, un.FRACTION,
          "probability", "point-in-time 12-month PD",
          low=_D("0"), high=_D("1"), mutable=True,
          affects=("ecl_sar_mn",), horizon="12 months",
          missing_means="never null; Stage 3 carries exactly 1.0"),
    Field("pd_lifetime", _CORP_FACILITY, PUBLISHED, un.FRACTION,
          "probability", "lifetime PD; the measure ECL uses at Stages 2 and 3",
          low=_D("0"), high=_D("1"), mutable=True,
          affects=("ecl_sar_mn",), horizon="lifetime, length not published",
          missing_means="never null; Stage 3 carries exactly 1.0"),
    Field("lgd_pct", _CORP_FACILITY, PUBLISHED, un.PERCENT, "percent",
          "loss given default; one definition only, no downturn variant",
          low=_D("0"), high=_D("100"), mutable=True,
          affects=("ecl_sar_mn",)),
    _money("ead_sar_mn", _CORP_FACILITY,
           "exposure at default: drawn + undrawn x CCF",
           mutable=True, affects=("ecl_sar_mn", "utilisation_pct")),

    # -- exposure structure --
    _money("drawn_sar_mn", _CORP_FACILITY, "drawn balance",
           mutable=True, affects=("ead_sar_mn", "utilisation_pct")),
    _money("undrawn_sar_mn", _CORP_FACILITY, "undrawn commitment",
           mutable=True, affects=("ead_sar_mn",)),
    _money("limit_sar_mn", _CORP_FACILITY, "approved limit",
           mutable=True, affects=("utilisation_pct",)),
    Field("utilisation_pct", _CORP_FACILITY, PUBLISHED, un.PERCENT, "percent",
          "drawn as a share of limit", low=_D("0"), mutable=False),

    # -- the one field the specification names that must be derived --
    Field("ccf", _CORP_FACILITY, DERIVED, un.FRACTION, "fraction",
          "credit conversion factor",
          low=_D("0"), high=_D("1"), mutable=True, affects=("ead_sar_mn",),
          derivation="(ead_sar_mn - drawn_sar_mn) / undrawn_sar_mn. Verified "
                     "to reconstruct ead to 2.8e-14 over all 384,009 rows. "
                     "Undefined on the 1,308 rows with zero undrawn, which "
                     "therefore have no structural CCF sensitivity "
                     "(section 10.3).",
          missing_means="undefined where undrawn is zero, which is not the "
                        "same as a CCF of zero"),

    # -- classification --
    Field("stage", _CORP_FACILITY, PUBLISHED, un.INDEX, "IFRS 9 stage",
          "1, 2 or 3", low=_D("1"), high=_D("3"), mutable=True,
          affects=("ecl_sar_mn",), methods=(sp.USER_DEFINED,),
          missing_means="never null"),
    Field("rating_current", _CORP_BORROWER, PUBLISHED, un.ORDINAL,
          "rating grade",
          "19 live grades AAA..C best to worst, then D; the order is "
          "published in the release manifest under notes.rating_scale",
          mutable=True, affects=("pd_pit_12m",), methods=(),
          missing_means="an unrated borrower is not a worst-rated one"),
    Field("sector", _CORP_BORROWER, PUBLISHED, un.ORDINAL, "category",
          "14 sectors, 75 sub-sectors", mutable=False),
    Field("default_flag", _CORP_FACILITY, PUBLISHED, un.INDEX, "flag",
          "credit-impaired", low=_D("0"), high=_D("1"), mutable=False),
    _money("write_off_sar_mn", _CORP_FACILITY, "amount written off"),
)


# ---- Retail ------------------------------------------------------------

_RETAIL_ACCOUNT = "retail_account_month"

RETAIL_FIELDS: tuple[Field, ...] = (
    _money("ecl_sar_mn", _RETAIL_ACCOUNT,
           "reported ECL; floored at written-off less recovered on a "
           "charged-off account, which is where the identity stops holding"),
    _money("ecl_12m_sar_mn", _RETAIL_ACCOUNT, "12-month ECL"),
    _money("ecl_lifetime_sar_mn", _RETAIL_ACCOUNT, "lifetime ECL"),

    Field("pd_pit_12m", _RETAIL_ACCOUNT, PUBLISHED, un.FRACTION,
          "probability", "point-in-time 12-month PD, driven by the "
          "behavioural score",
          low=_D("0"), high=_D("1"), mutable=True, affects=("ecl_sar_mn",),
          horizon="12 months",
          missing_means="never null; Stage 3 carries exactly 1.0"),
    Field("pd_lifetime", _RETAIL_ACCOUNT, PUBLISHED, un.FRACTION,
          "probability", "lifetime PD",
          low=_D("0"), high=_D("1"), mutable=True, affects=("ecl_sar_mn",),
          horizon="lifetime, length not published"),
    Field("lgd_pct", _RETAIL_ACCOUNT, PUBLISHED, un.PERCENT, "percent",
          "loss given default", low=_D("0"), high=_D("100"), mutable=True,
          affects=("ecl_sar_mn",)),
    _money("ead_sar_mn", _RETAIL_ACCOUNT,
           "exposure at default. Equal to balance on every product except "
           "Credit Card, where it is balance + max(0, limit - balance) x "
           "0.45 -- a constant in the generator, not a column",
           mutable=True, affects=("ecl_sar_mn",)),
    _money("balance_sar_mn", _RETAIL_ACCOUNT, "outstanding balance",
           mutable=True, affects=("ead_sar_mn",)),
    _money("limit_sar_mn", _RETAIL_ACCOUNT, "approved limit",
           mutable=True, affects=("utilisation_pct",)),

    Field("stage", _RETAIL_ACCOUNT, PUBLISHED, un.INDEX, "IFRS 9 stage",
          "1, 2 or 3", low=_D("1"), high=_D("3"), mutable=True,
          affects=("ecl_sar_mn",), methods=(sp.USER_DEFINED,)),
    Field("behaviour_score", _RETAIL_ACCOUNT, PUBLISHED, un.INDEX, "points",
          "behavioural score, 300 weak to 900 strong, banded A (best) to E",
          low=_D("300"), high=_D("900"), mutable=True,
          affects=("pd_pit_12m",), methods=(),
          missing_means="a missing score is not a zero score"),
    Field("product", _RETAIL_ACCOUNT, PUBLISHED, un.ORDINAL, "category",
          "5 products, 12 sub-products", mutable=False),
    _money("write_off_sar_mn", _RETAIL_ACCOUNT, "amount written off"),

    # -- what the specification names and this book does not have --
    Field("ccf", _RETAIL_ACCOUNT, ABSENT, un.FRACTION, "fraction",
          "credit conversion factor", mutable=False, methods=(),
          absent_note="Not published and not derivable. Every product except "
                      "Credit Card sets ead = balance, so there is no "
                      "conversion to recover; Credit Card uses a constant "
                      "0.45 that lives in the generator. Section 10.1's "
                      "proportional CCF rule has nothing to act on here."),
    Field("application_score", _RETAIL_ACCOUNT, ABSENT, un.INDEX, "points",
          "origination score", mutable=False, methods=(),
          absent_note="Does not exist. The score at origination is an "
                      "internal generator variable and is never published. "
                      "Section 8 is explicit that an application score must "
                      "not be substituted by the behavioural one, so a "
                      "scenario naming it is unsupported rather than "
                      "redirected."),
    Field("sector", _RETAIL_ACCOUNT, ABSENT, un.ORDINAL, "category",
          "employer industry or business activity", mutable=False, methods=(),
          absent_note="Retail carries no sector dimension. Section 3.3: "
                      "product is not a substitute for employer sector, so a "
                      "sector rule in a Retail scenario is unsupported."),
)


BY_DOMAIN: dict[str, tuple[Field, ...]] = {
    dom.CORPORATE: CORPORATE_FIELDS,
    dom.RETAIL: RETAIL_FIELDS,
}


def lookup(domain_id: str, field_id: str) -> Field:
    """The field, or a refusal that says what this book has instead."""
    for entry in BY_DOMAIN.get(domain_id, ()):
        if entry.field_id == field_id:
            return entry
    known = sorted(f.field_id for f in BY_DOMAIN.get(domain_id, ())
                   if f.availability != ABSENT)
    raise_for(MAPPING_UNAVAILABLE,
              f"{field_id!r} is not a field of the {domain_id} book. It "
              f"holds: {', '.join(known)}.",
              field_path=f"shocks.{field_id}", domain_id=domain_id)
    raise AssertionError("unreachable")  # pragma: no cover


def mutable(domain_id: str, field_id: str) -> Field:
    """The field, refusing if a scenario may not move it."""
    entry = lookup(domain_id, field_id)
    if entry.availability == ABSENT:
        raise_for(MAPPING_UNAVAILABLE,
                  f"{field_id} is not in the {domain_id} book. "
                  f"{entry.absent_note}",
                  field_path=f"shocks.{field_id}")
    if not entry.mutable:
        raise_for(MAPPING_UNAVAILABLE,
                  f"{field_id} is not something a scenario changes -- it is "
                  f"{entry.what}. Move what drives it instead.",
                  field_path=f"shocks.{field_id}",
                  affects=list(entry.affects))
    return entry


# ---- eligibility, measured rather than assumed -------------------------

#: A row excluded from a method, and the reason a reader is shown. Section
#: 9.1: "Missing inputs must produce reason-coded ineligibility by method."
STAGE_THREE_PD = (
    "Stage 3 carries a PD of exactly 1.0 and measures ECL as EAD x LGD. A "
    "relative PD shock on a probability that is already one has no meaning, "
    "so these rows are excluded from this shock rather than scaled.")

WRITTEN_OFF_FLOOR = (
    "This account is written off and its ECL is floored at the amount "
    "written off less recovered, so it is not a function of PD, LGD or EAD. "
    "A proportional shock cannot move it correctly.")

NO_UNDRAWN = (
    "This facility has no undrawn commitment, so it has no CCF to convert "
    "and no structural CCF sensitivity.")

ZERO_BASELINE = (
    "The baseline value is zero, so a relative change has no ratio. Section "
    "10.3: this is unsupported rather than divided by an epsilon.")


def sql_ineligibility(domain_id: str, field_id: str) -> tuple[str, str]:
    """A SQL predicate selecting rows this shock cannot move, and why.

    Returned as SQL rather than applied in Python because the calculation
    runs in the database over the full population -- section 9.1 forbids
    sampling for a reported total -- and a predicate the engine evaluates is
    one the governance trace can show.

    An empty predicate means nothing is excluded.
    """
    entry = lookup(domain_id, field_id)
    if entry.availability == ABSENT:
        return "TRUE", entry.absent_note

    if field_id in ("pd_pit_12m", "pd_lifetime"):
        return "stage = 3", STAGE_THREE_PD
    if field_id == "ccf":
        if domain_id == dom.RETAIL:
            return "TRUE", entry.absent_note
        return "undrawn_sar_mn = 0", NO_UNDRAWN
    if domain_id == dom.RETAIL and field_id in ("lgd_pct", "ead_sar_mn",
                                                "balance_sar_mn"):
        # The floor binds only where something was written off.
        return "write_off_sar_mn > 0", WRITTEN_OFF_FLOOR
    return "", ""


def eligibility_note(domain_id: str, field_id: str) -> str:
    """One line for the preview, naming the exclusion or saying there is none."""
    _, reason = sql_ineligibility(domain_id, field_id)
    return reason or "every row in the cohort is eligible for this shock."


def absent(domain_id: str) -> tuple[Field, ...]:
    """What the specification asks for that this book does not have.

    Section 3.2: the inventory is published with its gaps, and section 7.1's
    rule applies more widely -- "Never present missing factors as zero."
    """
    return tuple(f for f in BY_DOMAIN.get(domain_id, ())
                 if f.availability == ABSENT)


def derived(domain_id: str) -> tuple[Field, ...]:
    """Fields recovered from published ones, labelled as such everywhere."""
    return tuple(f for f in BY_DOMAIN.get(domain_id, ())
                 if f.availability == DERIVED)


__all__ = [
    "ABSENT", "BY_DOMAIN", "CORPORATE_FIELDS", "DERIVED", "Field",
    "NO_UNDRAWN", "PUBLISHED", "RETAIL_FIELDS", "STAGE_THREE_PD",
    "WRITTEN_OFF_FLOOR", "ZERO_BASELINE", "absent", "derived",
    "eligibility_note", "lookup", "mutable", "sql_ineligibility",
]
