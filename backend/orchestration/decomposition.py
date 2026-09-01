"""
Where an ECL movement came from, attributed without an arbitrary order. P0.4.

The defect
----------
    "Decompose the change in total ECL over the latest year into changes
    associated with exposure, Stage migration, PD, LGD and portfolio mix. Show
    which sectors and customers contributed most."

CreditProbe answered with an ECL movement BY SECTOR. That is a true table and a
different question: it says where the change landed, not what caused it. The
five drivers the question named were not computed at all, and the customer
attribution was not attempted.

Why ordering matters, and why nobody notices
--------------------------------------------
The naive way to attribute a change in a product is to move one factor at a
time:

    hold PD and LGD at opening, move EAD          -> the exposure effect
    hold LGD at opening, move PD                  -> the PD effect
    move LGD                                      -> the LGD effect

This sums exactly to the total. It is also wrong, and wrong in a way that
survives review, because every interaction term is silently handed to whichever
factor happened to move last. Reverse the order and the same book produces a
different story about what drove the loss. A committee cannot tell, because
each version reconciles.

So the attribution here is SHAPLEY. Each factor's effect is its average
marginal contribution across every order in which the factors could have moved,
which is the unique attribution that is order-neutral, sums exactly to the
total, and gives a factor that never moved an effect of zero.

    phi_i = SUM over S subset of N\\{i} of
                |S|! (n-|S|-1)! / n!  *  [ v(S + i) - v(S) ]

    where v(S) = the ECL computed with the factors in S at their CLOSING
    values and every other factor at its OPENING value.

Because v(N) - v({}) telescopes, sum(phi) = closing - opening exactly, per
account and therefore in total.

The factorisation, and what it does NOT claim
---------------------------------------------
    model_ecl  =  T  *  w  *  R  *  PD12  *  LGD  *  K

    T      total exposure across the population   -- the scale effect
    w      this account's share of it             -- the portfolio-mix effect
    R      PD_used / PD12                         -- the Stage/SICR effect:
                                                     1 in Stage 1, the lifetime
                                                     multiple once SICR moved
                                                     the account to lifetime
    PD12   twelve-month PD                        -- the PD effect
    LGD    loss given default                     -- the LGD effect
    K      model_ecl / (T*w*R*PD12*LGD)           -- everything else the model
                                                     does: discounting, the
                                                     lifetime profile, EIR

K is the honest part. P0.4 says plainly: "Do not pretend PD x LGD x EAD
explains final ECL where overlays / lifetime horizon / discounting make it
incomplete." On this book it does not — the product of EAD, the horizon-correct
PD and LGD comes to roughly seventy per cent of modelled ECL. Rather than
scaling that gap away or hiding it inside the PD effect, K carries it as a
named driver, and the answer says what it is.

Two components are additive rather than multiplicative and are attributed
directly, because inventing a factorisation for them would be dishonest:

    overlay        total_ecl - model_ecl, the management and macro overlay
    new / exited   accounts present on one side only

Same-scope populations
----------------------
The multiplicative attribution is defined on accounts present in BOTH periods.
An account that arrived contributes its whole closing ECL, and one that left
contributes minus its whole opening ECL; neither has a PD effect, because
neither has two PDs. Folding them into the driver effects is the other common
way a decomposition reconciles while lying.
"""

from __future__ import annotations

import itertools
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# The multiplicative drivers, in the order a credit officer reads them.
EXPOSURE = "exposure"
MIX = "portfolio_mix"
STAGE = "stage_migration"
PD = "pd"
LGD = "lgd"
MODEL = "model_residual"

FACTORS: tuple[str, ...] = (EXPOSURE, MIX, STAGE, PD, LGD, MODEL)

# The additive components.
OVERLAY = "overlay"
NEW_ACCOUNTS = "new_accounts"
EXITED_ACCOUNTS = "exited_accounts"

COMPONENTS: tuple[str, ...] = (*FACTORS, OVERLAY, NEW_ACCOUNTS, EXITED_ACCOUNTS)

LABELS: dict[str, str] = {
    EXPOSURE: "Exposure",
    MIX: "Portfolio mix",
    STAGE: "Stage migration (SICR)",
    PD: "Probability of default",
    LGD: "Loss given default",
    MODEL: "Model residual",
    OVERLAY: "Management and macro overlay",
    NEW_ACCOUNTS: "Accounts arriving",
    EXITED_ACCOUNTS: "Accounts leaving",
}

MEANINGS: dict[str, str] = {
    EXPOSURE: ("The book grew or shrank. Holds every other driver at its "
               "opening value and moves total exposure at default only."),
    MIX: ("Exposure moved between accounts without the total changing. This is "
          "the composition effect: the same book, differently distributed."),
    STAGE: ("Accounts moved between a twelve-month and a lifetime horizon. "
            "This is the SICR effect, measured as the change in the lifetime "
            "multiple applied to each account's PD."),
    PD: "Twelve-month probabilities of default changed, at a constant horizon.",
    LGD: "Loss given default changed.",
    MODEL: ("Everything the impairment model does that exposure, PD and LGD do "
            "not describe: discounting, the lifetime loss profile, the "
            "effective interest rate. Reported rather than absorbed, because "
            "the product of EAD, PD and LGD does not equal modelled ECL and "
            "calling it the PD effect would be untrue."),
    OVERLAY: ("The management and macro overlay on top of modelled ECL. Added, "
              "not modelled, so it is attributed directly rather than "
              "factorised."),
    NEW_ACCOUNTS: ("Accounts in the closing population that were not in the "
                   "opening one. Their whole ECL is new; they have no PD "
                   "change because they have only one PD."),
    EXITED_ACCOUNTS: ("Accounts in the opening population that are not in the "
                      "closing one. Their whole opening ECL has gone."),
}

#: How close the components have to sum to the actual movement. Relative to the
#: movement itself, because an absolute tolerance is either meaningless on a
#: large book or unmeetable on a small one. Floating-point noise over sixteen
#: thousand accounts is many orders of magnitude below this.
TOLERANCE = 1e-6

#: Below this share of the total movement, a component is noise rather than a
#: driver, and listing it invites a reader to explain it.
MATERIAL_SHARE = 0.005


@dataclass
class Component:
    """One driver's effect on the movement."""

    key: str
    label: str
    effect: float
    #: What this component means, and what it does not claim.
    meaning: str = ""

    @property
    def adverse(self) -> bool:
        """Whether this drove the loss up. ECL rising is deterioration."""
        return self.effect > 0

    def share_of(self, movement: float) -> float:
        return (self.effect / movement * 100.0) if movement else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label,
                "effect": round(self.effect, 4), "adverse": self.adverse,
                "meaning": self.meaning}


@dataclass
class Contributor:
    """One sector or customer, and how much of the movement it accounts for."""

    key: str
    name: str
    opening: float
    closing: float
    effect: float
    #: The same driver breakdown, for this contributor alone.
    components: dict[str, float] = field(default_factory=dict)

    @property
    def adverse(self) -> bool:
        return self.effect > 0

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name,
                "opening": round(self.opening, 4),
                "closing": round(self.closing, 4),
                "effect": round(self.effect, 4), "adverse": self.adverse,
                "components": {k: round(v, 4)
                               for k, v in self.components.items()}}


@dataclass
class Decomposition:
    """The whole attribution, and whether it reconciles."""

    opening_period: str = ""
    closing_period: str = ""
    opening_total: float = 0.0
    closing_total: float = 0.0
    components: list[Component] = field(default_factory=list)
    sectors: list[Contributor] = field(default_factory=list)
    customers: list[Contributor] = field(default_factory=list)
    #: Accounts in both periods, in one only, and in the other only.
    matched: int = 0
    arrived: int = 0
    departed: int = 0
    #: Set when the attribution could not be computed.
    unavailable: str = ""

    @property
    def movement(self) -> float:
        return self.closing_total - self.opening_total

    @property
    def attributed(self) -> float:
        return sum(c.effect for c in self.components)

    @property
    def gap(self) -> float:
        return self.attributed - self.movement

    @property
    def reconciles(self) -> bool:
        """Whether the components sum to the movement, within tolerance."""
        scale = max(abs(self.movement), abs(self.opening_total), 1.0)
        return abs(self.gap) <= TOLERANCE * scale

    @property
    def adverse(self) -> list[Component]:
        """What pushed the loss up, largest first."""
        return sorted((c for c in self.components if c.effect > 0),
                      key=lambda c: -c.effect)

    @property
    def favourable(self) -> list[Component]:
        """What pulled it down, largest first."""
        return sorted((c for c in self.components if c.effect < 0),
                      key=lambda c: c.effect)

    @property
    def material(self) -> list[Component]:
        """The components worth putting in front of a reader."""
        floor = abs(self.movement) * MATERIAL_SHARE
        return sorted((c for c in self.components if abs(c.effect) >= floor),
                      key=lambda c: -abs(c.effect))

    def component(self, key: str) -> Component | None:
        return next((c for c in self.components if c.key == key), None)

    def waterfall(self) -> list[dict[str, Any]]:
        """The rows a waterfall draws: opening, each driver, closing.

        A waterfall is the faithful picture of an exact decomposition, and it
        is only faithful because it reconciles — the bars have to land on the
        closing bar or the chart is a lie with a nice shape.
        """
        rows: list[dict[str, Any]] = [
            {"step": f"ECL at {self.opening_period}", "kind": "total",
             "value": round(self.opening_total, 4)}]
        for component in sorted(self.components, key=lambda c: -abs(c.effect)):
            if component.effect == 0.0:
                continue
            rows.append({"step": component.label, "kind": "delta",
                         "value": round(component.effect, 4),
                         "adverse": component.adverse})
        rows.append({"step": f"ECL at {self.closing_period}", "kind": "total",
                     "value": round(self.closing_total, 4)})
        return rows

    def proves(self) -> list[str]:
        """What this decomposition establishes."""
        return [
            "The components sum exactly to the movement in total ECL. Every "
            "unit of the change is attributed to a named driver and none is "
            "left in a balancing figure.",
            "The attribution does not depend on the order the drivers are "
            "considered in. Each effect is the average marginal contribution "
            "across every ordering, so no interaction term has been handed to "
            "whichever factor happened to move last.",
            "Accounts present in only one period are separated from the "
            "drivers, so an arrival is not reported as a rise in PD.",
        ]

    def does_not_prove(self) -> list[str]:
        """What it does not — said before somebody reads it as causation."""
        return [
            "It does not establish cause. A PD effect means the PDs used in "
            "the calculation changed; it does not say why they changed, and "
            "the reason may be a model recalibration rather than the book.",
            "It does not separate the model residual into discounting, the "
            "lifetime loss profile and the effective interest rate. Those move "
            "together here and are reported as one driver.",
            "It attributes the overlay rather than explaining it. An overlay "
            "is a judgement, and a decomposition of a judgement is arithmetic "
            "about somebody's opinion.",
            "It says nothing about accounts outside the governed population "
            "for these two periods.",
        ]

    def sentence(self) -> str:
        largest = self.material[0] if self.material else None
        direction = "rose" if self.movement > 0 else "fell"
        led = (f", led by {largest.label.lower()} at "
               f"{largest.effect:+,.1f}") if largest else ""
        return (f"ECL {direction} by {abs(self.movement):,.1f} between "
                f"{self.opening_period} and {self.closing_period}{led}.")

    def to_dict(self) -> dict[str, Any]:
        # Publish first, then subtract. The movement is the difference of the
        # totals AS PUBLISHED, not the published difference of the unrounded
        # ones: rounding each of the three independently left a row whose two
        # totals did not subtract to its own movement — 12,411.65 less
        # 5,313.07 shown beside a movement of -7,098.57 — and a reader who
        # checks the arithmetic on the screen is right to stop trusting it.
        # `gap` and `reconciles` stay on the unrounded basis, because they are
        # a claim about the METHOD rather than about the presentation.
        opening = round(self.opening_total, 4)
        closing = round(self.closing_total, 4)
        return {
            "opening_period": self.opening_period,
            "closing_period": self.closing_period,
            "opening_total": opening,
            "closing_total": closing,
            "movement": round(closing - opening, 4),
            "attributed": round(self.attributed, 4),
            "gap": round(self.gap, 10),
            "reconciles": self.reconciles,
            "tolerance": TOLERANCE,
            "components": [c.to_dict() for c in self.components],
            "adverse": [c.key for c in self.adverse],
            "favourable": [c.key for c in self.favourable],
            "sectors": [c.to_dict() for c in self.sectors],
            "customers": [c.to_dict() for c in self.customers],
            "population": {"matched": self.matched, "arrived": self.arrived,
                           "departed": self.departed},
            "waterfall": self.waterfall(),
            "proves": self.proves(),
            "does_not_prove": self.does_not_prove(),
            "unavailable": self.unavailable,
        }


# ---------------------------------------------------------------------------
# The Shapley weights
# ---------------------------------------------------------------------------


def _weights(n: int) -> dict[int, float]:
    """|S|! (n-|S|-1)! / n!, by the size of the coalition."""
    total = math.factorial(n)
    return {size: math.factorial(size) * math.factorial(n - size - 1) / total
            for size in range(n)}


#: Every subset of the six factors, as a frozenset, computed once.
_SUBSETS: tuple[frozenset[int], ...] = tuple(
    frozenset(combination)
    for size in range(len(FACTORS) + 1)
    for combination in itertools.combinations(range(len(FACTORS)), size))

_WEIGHTS = _weights(len(FACTORS))


def shapley(opening: tuple[float, ...],
            closing: tuple[float, ...]) -> tuple[float, ...]:
    """The order-neutral attribution of a change in a PRODUCT of factors.

    `opening` and `closing` hold the same factors at the two dates. The result
    holds one effect per factor, and it sums to
    ``prod(closing) - prod(opening)`` exactly, up to floating point.

    This is the whole of the order-neutrality claim, in eight lines. Everything
    around it is deciding which factors to hand it.
    """
    n = len(opening)
    if n != len(closing):
        raise ValueError("opening and closing must describe the same factors")

    # v(S): the product with the factors in S moved to closing.
    value: dict[frozenset[int], float] = {}
    for subset in _SUBSETS if n == len(FACTORS) else _all_subsets(n):
        product = 1.0
        for index in range(n):
            product *= closing[index] if index in subset else opening[index]
        value[subset] = product

    weights = _WEIGHTS if n == len(FACTORS) else _weights(n)
    effects = [0.0] * n
    for subset, without in value.items():
        for index in range(n):
            if index in subset:
                continue
            gain = value[subset | {index}] - without
            effects[index] += weights[len(subset)] * gain
    return tuple(effects)


def _all_subsets(n: int) -> tuple[frozenset[int], ...]:
    return tuple(frozenset(c) for size in range(n + 1)
                 for c in itertools.combinations(range(n), size))


# ---------------------------------------------------------------------------
# Building the factors from two periods of the book
# ---------------------------------------------------------------------------


@dataclass
class Account:
    """One account at one date, as the decomposition needs it."""

    account_id: str
    customer_id: str = ""
    name: str = ""
    sector: str = ""
    ead: float = 0.0
    stage: int = 1
    pd_12m: float = 0.0
    pd_lifetime: float = 0.0
    lgd: float = 0.0
    model_ecl: float = 0.0
    total_ecl: float = 0.0

    @property
    def overlay(self) -> float:
        return self.total_ecl - self.model_ecl

    @property
    def horizon(self) -> float:
        """R: the lifetime multiple this account's stage applies to its PD.

        1.0 in Stage 1, where the twelve-month PD is the one used. Above 1 once
        SICR has moved it to a lifetime horizon. This is what makes stage
        migration a driver rather than a note.
        """
        if self.stage <= 1 or self.pd_12m <= 0:
            return 1.0
        return self.pd_lifetime / self.pd_12m

    def pd_used(self) -> float:
        return self.pd_12m if self.stage <= 1 else self.pd_lifetime


def decompose(opening: list[Account], closing: list[Account], *,
              opening_period: str = "", closing_period: str = "",
              top: int = 10) -> Decomposition:
    """Attribute the movement in total ECL across the governed drivers.

    Never raises: a decomposition that fails must say it is unavailable, not
    take the answer down with it. An unavailable decomposition is a legitimate
    outcome the caller reports; a traceback is not.
    """
    try:
        return _decompose(opening, closing, opening_period=opening_period,
                          closing_period=closing_period, top=top)
    except Exception as e:  # noqa: BLE001 - an attribution must not lose an answer
        logger.exception("Could not decompose the ECL movement: %s", e)
        return Decomposition(opening_period=opening_period,
                             closing_period=closing_period,
                             unavailable=type(e).__name__)


def _decompose(opening: list[Account], closing: list[Account], *,
               opening_period: str, closing_period: str,
               top: int) -> Decomposition:
    before = {a.account_id: a for a in opening}
    after = {a.account_id: a for a in closing}
    both = sorted(before.keys() & after.keys())
    arrived = sorted(after.keys() - before.keys())
    departed = sorted(before.keys() - after.keys())

    out = Decomposition(
        opening_period=opening_period, closing_period=closing_period,
        opening_total=sum(a.total_ecl for a in opening),
        closing_total=sum(a.total_ecl for a in closing),
        matched=len(both), arrived=len(arrived), departed=len(departed))

    if not both:
        out.unavailable = ("no account is present in both periods, so there is "
                           "no movement to attribute to a driver")
        return out

    # T: total exposure over the SAME-SCOPE population, which is what the mix
    # factor takes shares of. Using the whole book here would make the shares
    # of matched accounts move when an unrelated account arrived.
    total_open = sum(before[k].ead for k in both) or 1.0
    total_close = sum(after[k].ead for k in both) or 1.0

    effects = dict.fromkeys(FACTORS, 0.0)
    by_sector: dict[str, list[float]] = {}
    by_customer: dict[str, list[float]] = {}
    names: dict[str, str] = {}

    for key in both:
        a, b = before[key], after[key]
        contribution = shapley(
            _factors(a, total_open), _factors(b, total_close))
        # The residual factor K makes the product equal modelled ECL exactly,
        # so the six effects sum to b.model_ecl - a.model_ecl per account. The
        # overlay is added on top, unfactorised.
        for name, value in zip(FACTORS, contribution, strict=True):
            effects[name] += value
        effects_total = sum(contribution) + (b.overlay - a.overlay)

        sector = b.sector or a.sector or "Unattributed"
        by_sector.setdefault(sector, [0.0, 0.0, 0.0, *([0.0] * len(FACTORS))])
        _accumulate(by_sector[sector], a.total_ecl, b.total_ecl,
                    effects_total, contribution)

        customer = b.customer_id or a.customer_id or key
        names[customer] = b.name or a.name or customer
        by_customer.setdefault(customer,
                               [0.0, 0.0, 0.0, *([0.0] * len(FACTORS))])
        _accumulate(by_customer[customer], a.total_ecl, b.total_ecl,
                    effects_total, contribution)

    overlay = (sum(after[k].overlay for k in both)
               - sum(before[k].overlay for k in both))
    new_ecl = sum(after[k].total_ecl for k in arrived)
    gone_ecl = -sum(before[k].total_ecl for k in departed)

    # An arrival or a departure lands on its sector and customer whole: it has
    # no driver breakdown, because it has no second observation to compare.
    for key in arrived:
        a = after[key]
        _land(by_sector, a.sector or "Unattributed", 0.0, a.total_ecl,
              a.total_ecl)
        names.setdefault(a.customer_id or key, a.name or key)
        _land(by_customer, a.customer_id or key, 0.0, a.total_ecl, a.total_ecl)
    for key in departed:
        a = before[key]
        _land(by_sector, a.sector or "Unattributed", a.total_ecl, 0.0,
              -a.total_ecl)
        names.setdefault(a.customer_id or key, a.name or key)
        _land(by_customer, a.customer_id or key, a.total_ecl, 0.0,
              -a.total_ecl)

    out.components = [
        Component(key=name, label=LABELS[name], effect=effects[name],
                  meaning=MEANINGS[name])
        for name in FACTORS]
    out.components.extend([
        Component(key=OVERLAY, label=LABELS[OVERLAY], effect=overlay,
                  meaning=MEANINGS[OVERLAY]),
        Component(key=NEW_ACCOUNTS, label=LABELS[NEW_ACCOUNTS], effect=new_ecl,
                  meaning=MEANINGS[NEW_ACCOUNTS]),
        Component(key=EXITED_ACCOUNTS, label=LABELS[EXITED_ACCOUNTS],
                  effect=gone_ecl, meaning=MEANINGS[EXITED_ACCOUNTS]),
    ])

    out.sectors = _ranked(by_sector, {}, top)
    out.customers = _ranked(by_customer, names, top)
    return out


def _factors(account: Account, total_ead: float) -> tuple[float, ...]:
    """The six multiplicative factors for one account at one date.

    K is defined as whatever makes the product equal modelled ECL. That is not
    a fudge — it is the point. The five named factors are what a credit officer
    asked about; K is the honest size of what they do not explain, and giving
    it a name is what stops it being silently distributed over the other five.
    """
    ead = float(account.ead)
    share = ead / total_ead if total_ead else 0.0
    horizon = account.horizon
    pd_12m = float(account.pd_12m) / 100.0
    lgd = float(account.lgd) / 100.0

    product = total_ead * share * horizon * pd_12m * lgd
    residual = (account.model_ecl / product) if product else 0.0
    if not product and account.model_ecl:
        # Nothing multiplicative can produce a loss out of a zero factor. Carry
        # the whole modelled figure on the residual and say so there, rather
        # than dropping the account out of the reconciliation.
        return (1.0, 1.0, 1.0, 1.0, 1.0, account.model_ecl)
    return (total_ead, share, horizon, pd_12m, lgd, residual)


def _accumulate(row: list[float], opening: float, closing: float,
                effect: float, contribution: tuple[float, ...]) -> None:
    row[0] += opening
    row[1] += closing
    row[2] += effect
    for index, value in enumerate(contribution):
        row[3 + index] += value


def _land(bucket: dict[str, list[float]], key: str, opening: float,
          closing: float, effect: float) -> None:
    """An arrival or departure, which has no driver breakdown."""
    bucket.setdefault(key, [0.0, 0.0, 0.0, *([0.0] * len(FACTORS))])
    bucket[key][0] += opening
    bucket[key][1] += closing
    bucket[key][2] += effect


def _ranked(bucket: dict[str, list[float]], names: dict[str, str],
            top: int) -> list[Contributor]:
    """The largest contributors by ABSOLUTE effect, adverse and favourable.

    By absolute size because a decomposition has two interesting tails: the
    thing that drove the loss up and the thing that held it down. Ranking by
    signed value would show a reader ten improvements and no deteriorations on
    a book that improved.
    """
    out = [
        Contributor(key=key, name=names.get(key, key), opening=row[0],
                    closing=row[1], effect=row[2],
                    components=dict(zip(FACTORS, row[3:], strict=True)))
        for key, row in bucket.items()]
    out.sort(key=lambda c: -abs(c.effect))
    return out[:max(0, top)]



# ---------------------------------------------------------------------------
# Reading the book, and recognising the question
# ---------------------------------------------------------------------------

#: The dataset the drivers live in. IFRS 9 staging is the only governed source
#: carrying EAD, stage, both PDs, LGD, modelled ECL and the overlay together,
#: and a decomposition assembled from several sources would attribute a join
#: rather than a book.
DATASET = "ifrs9_staging"

#: The fields it needs, named so the read is a governed projection rather than
#: "everything".
FIELDS: tuple[str, ...] = (
    "account_id", "customer_id", "sector", "segment", "ifrs9_stage", "ead",
    "pd_12m_pct", "pd_lifetime_pct", "lgd_pct", "model_ecl", "total_ecl",
)

#: The verb has to be a decomposition verb AND the subject an ECL movement.
#: Either alone is a different question: "what drove the increase in DPD" is not
#: this method, and "show ECL by driver of the business" is not a question.
_ASKS = re.compile(
    r"\b(?:decompos\w*|attribut\w*|bridge|walk|waterfall|break\s*down|"
    r"breakdown|what\s+drove|drivers?\s+of|explain\s+the\s+(?:change|"
    r"movement|increase|decrease)|contribution\s+(?:of|to))\b", re.I)

_ABOUT = re.compile(
    r"\b(?:ecl|expected\s+credit\s+loss|impairment|provision(?:ing|s)?)\b",
    re.I)

_MOVED = re.compile(
    # "bridge", "walk" and "waterfall" are themselves names for a change
    # decomposition — an ECL waterfall is not a picture of a position — so
    # they satisfy this on their own.
    r"\b(?:change|movement|moved|increase|decrease|rose|fell|grew|"
    r"deterioration|improvement|delta|variance|bridge|walk|waterfall)\b", re.I)

#: The drivers, named. A question that lists two or more of these is asking for
#: this method whichever verb it used.
_DRIVERS = re.compile(
    r"\b(?:exposure|ead|stage|sicr|migration|\bpd\b|probability\s+of\s+default|"
    r"\blgd\b|loss\s+given\s+default|mix|composition|overlay|scenario)\b", re.I)

#: How many named drivers make a question a decomposition request on their own.
MIN_DRIVERS = 3


def wants(question: str) -> bool:
    """Whether this question is asking for an ECL change decomposition.

    Deliberately narrow. This method reads the whole book at row level and
    produces a nine-component attribution; running it for "how did ECL change"
    would answer a simple question with a committee paper. It fires when the
    question is about an ECL MOVEMENT and either uses a decomposition verb or
    names several of the drivers.
    """
    text = str(question or "")
    if not (_ABOUT.search(text) and _MOVED.search(text)):
        return False
    if _ASKS.search(text):
        return True
    named = {m.group(0).lower() for m in _DRIVERS.finditer(text)}
    return len(named) >= MIN_DRIVERS


def read_book(period: str, *, context: Any = None,
              user_id: int | None = None) -> list[Account]:
    """The accounts in one period, through the governed data layer.

    Row level, because the attribution is per account and an aggregate cannot
    tell a stage migration from a change in mix. The projection is named rather
    than "select *": a decomposition needs eleven fields and reading the rest
    would put borrower detail through a path that has no use for it.
    """
    from backend.data_access import get_data_source
    from backend.data_access.context import AnalysisContext

    scope = context or AnalysisContext(period=period, user_id=user_id)
    if getattr(scope, "period", None) != period:
        scope = AnalysisContext(period=period,
                                filters=dict(getattr(scope, "filters", {}) or {}),
                                user_id=getattr(scope, "user_id", None))

    frame = get_data_source().fetch(DATASET, context=scope,
                                    fields=list(FIELDS), period=period)
    return [account_from(row) for row in frame.to_dict("records")]


def account_from(row: dict[str, Any]) -> Account:
    """One governed row as an Account, reading defensively.

    Public because the registered engine analysis builds accounts from its own
    governed read, and two functions turning the same row into the same object
    would be two places for a field name to drift.
    """
    def number(name: str) -> float:
        value = row.get(name)
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    stage = row.get("ifrs9_stage")
    try:
        stage_number = int(stage) if stage is not None else 1
    except (TypeError, ValueError):
        stage_number = 1

    return Account(
        account_id=str(row.get("account_id") or ""),
        customer_id=str(row.get("customer_id") or ""),
        name=str(row.get("borrower_name") or row.get("customer_id") or ""),
        sector=str(row.get("sector") or ""),
        ead=number("ead"), stage=stage_number,
        pd_12m=number("pd_12m_pct"), pd_lifetime=number("pd_lifetime_pct"),
        lgd=number("lgd_pct"), model_ecl=number("model_ecl"),
        total_ecl=number("total_ecl"))


def name_customers(found: Decomposition, period: str,
                   context: Any = None) -> None:
    """Put borrower names on the customer contributors.

    IFRS 9 staging carries the drivers and not the names; the facility book
    carries the names. Read separately and only for the customers that actually
    reach the answer, because pulling every borrower name to label ten rows is
    a join nobody asked for.
    """
    wanted = {c.key for c in found.customers}
    if not wanted:
        return
    try:
        from backend.data_access import get_data_source
        from backend.data_access.context import AnalysisContext

        scope = context if getattr(context, "period", None) == period else \
            AnalysisContext(period=period)
        frame = get_data_source().fetch(
            "portfolio_facility", context=scope,
            fields=["customer_id", "borrower_name"], period=period)
        names = {str(r.get("customer_id")): str(r.get("borrower_name") or "")
                 for r in frame.to_dict("records")}
    except Exception as e:  # noqa: BLE001 - a label must not lose an answer
        logger.warning("Could not read borrower names: %s", e)
        return
    for contributor in found.customers:
        contributor.name = names.get(contributor.key) or contributor.name



# ---------------------------------------------------------------------------
# Answering the question
# ---------------------------------------------------------------------------


def answer(question: str, reading: Any, *, context: Any = None,
           period: tuple[str, str] | None = None,
           user_id: int | None = None, top: int = 10) -> Any:
    """The whole method, as an answer the product can render.

    Reads two periods of the governed book, attributes the movement, and
    returns the components, the two contributor rankings and the waterfall —
    plus what the decomposition proves and does not prove, because a reader
    who takes an attribution for a cause has been misled by a correct table.
    """
    from backend.orchestration import handlers
    from backend.orchestration import periods as pd
    from backend.orchestration.handlers import HandlerResult

    available = _available_periods()
    opening, closing = _window(question, period, available)
    if not opening or not closing:
        return HandlerResult(
            answer=("This decomposition needs two published periods to compare "
                    "and CreditProbe cannot find them. Naming both — \"between "
                    "Q2 2025 and Q2 2026\" — resolves it."),
            warnings=[pd.unavailable(question, available)] if available else [])

    found = decompose(read_book(opening, context=context, user_id=user_id),
                      read_book(closing, context=context, user_id=user_id),
                      opening_period=opening, closing_period=closing, top=top)
    if found.unavailable:
        return HandlerResult(
            answer=("CreditProbe could not attribute this movement: "
                    f"{found.unavailable}."),
            detail={"decomposition": found.to_dict()})
    name_customers(found, closing, context)

    warnings: list[str] = []
    if not found.reconciles:
        # Said out loud rather than shown quietly. A decomposition that does not
        # reconcile is not a decomposition, and a waterfall drawn from one is a
        # picture whose bars do not reach the closing bar.
        warnings.append(
            f"The components do not reconcile to the movement: they sum to "
            f"{found.attributed:,.4f} against a movement of "
            f"{found.movement:,.4f}. The attribution is NOT shown as complete.")

    return HandlerResult(
        answer=found.sentence(),
        rows=_rows(found), columns=_columns(),
        values={"opening_total": round(found.opening_total, 4),
                "closing_total": round(found.closing_total, 4),
                "movement": round(found.movement, 4),
                "attributed": round(found.attributed, 4),
                "reconciles": found.reconciles},
        detail={"decomposition": found.to_dict(),
                "method": METHOD_ID,
                "formulas": formulas()},
        # A waterfall, and only because the decomposition reconciles. The bars
        # land on the closing total by construction; drawn from an attribution
        # that did not reconcile it would be a picture whose steps stop short
        # of the figure they claim to explain, so the fallback is the table.
        chart=({"chart": "waterfall", "x": "component", "y": ["effect"],
                "chart_first": True, "alternatives": ["table"],
                "steps": found.waterfall(),
                "reason": ("an exact decomposition of a movement between two "
                           "totals reads as a waterfall")}
               if found.reconciles else {}),
        execution="computed",
        execution_label="Governed calculation",
        graph=_trace(question, reading, found, handlers),
        follow_ups=[
            f"Which customers drove the {found.material[0].label.lower()} "
            f"effect?" if found.material else "Which customers drove this?",
            "Show the same decomposition for one sector only",
            "How does this compare with the previous year?",
        ],
        warnings=warnings)


def _rows(found: Decomposition) -> list[dict[str, Any]]:
    """One row per component, in waterfall order — which is also the order a
    reader wants: largest driver first."""
    movement = found.movement
    return [{"component": c.label,
             "effect": round(c.effect, 4),
             "share_pct": round(c.share_of(movement), 2),
             "direction": "adverse" if c.adverse else "favourable",
             "meaning": c.meaning}
            for c in sorted(found.components, key=lambda x: -abs(x.effect))]


def _columns() -> list[dict[str, Any]]:
    from backend.orchestration import presentation as pr

    return [
        {"name": "component", "label": "Driver", "semantic": pr.TEXT,
         "rank": pr.RANK_SUBJECT},
        {"name": "effect", "label": "Effect on ECL", "semantic": pr.MONEY,
         "unit": "SAR mn", "decimals": 1, "rank": pr.RANK_PRIMARY},
        {"name": "share_pct", "label": "Share of movement",
         "semantic": pr.PERCENT, "unit": "%", "decimals": 1,
         "rank": pr.RANK_DERIVED},
        {"name": "direction", "label": "Direction", "semantic": pr.TEXT,
         "rank": pr.RANK_CONTEXT},
        {"name": "meaning", "label": "What it means", "semantic": pr.TEXT,
         "rank": pr.RANK_CONTEXT, "hidden": True},
    ]


def _available_periods() -> list[str]:
    try:
        from backend.data_access import get_data_source

        return list(get_data_source().periods(DATASET))
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read the published periods: %s", e)
        return []


def _window(question: str, period: tuple[str, str] | None,
            available: list[str]) -> tuple[str, str]:
    """The two periods to compare.

    An explicit pair wins; then whatever the question said about time; then the
    governed default. Never a silent "latest two": "over the latest year" means
    four quarters, and answering it with one quarter would be a different
    question with the same shape.
    """
    from backend.orchestration import periods as pd

    if period and len(period) == 2 and all(period):
        return str(period[0]), str(period[1])
    if not available:
        return "", ""
    intent = pd.read_period_intent(question, available)
    if not intent.specified or not intent.from_period or not intent.to_period:
        intent = pd.governed_default(available)
    return str(intent.from_period or ""), str(intent.to_period or "")


def formulas() -> list[dict[str, str]]:
    """The arithmetic, written out. P0.4 asks for formulas, and a method whose
    formulas are not on the screen is a method nobody can check."""
    return [
        {"name": "Factorisation",
         "formula": "model_ecl = T x w x R x PD12 x LGD x K",
         "note": ("T total exposure over the same-scope population, w the "
                  "account's share of it, R the lifetime multiple its stage "
                  "applies, PD12 the twelve-month PD, LGD loss given default, "
                  "and K whatever remains — discounting, the lifetime loss "
                  "profile, the effective interest rate.")},
        {"name": "Stage/SICR factor",
         "formula": "R = 1 in Stage 1, otherwise pd_lifetime / pd_12m",
         "note": ("Which horizon the account is on. A migration changes R "
                  "without changing PD12, which is why a stage move is not "
                  "reported as a rise in PD.")},
        {"name": "Model residual",
         "formula": "K = model_ecl / (T x w x R x PD12 x LGD)",
         "note": ("Defined as whatever makes the product exact. Named rather "
                  "than distributed over the other five, because EAD x PD x "
                  "LGD does not equal modelled ECL and pretending otherwise "
                  "would put the difference in the PD effect.")},
        {"name": "Attribution (Shapley)",
         "formula": ("phi_i = SUM over S in N\\{i} of "
                     "|S|!(n-|S|-1)!/n! x [v(S+i) - v(S)]"),
         "note": ("v(S) is the ECL with the factors in S at closing and the "
                  "rest at opening. Each effect is the average marginal "
                  "contribution over every ordering, so no interaction term "
                  "is handed to whichever factor moved last.")},
        {"name": "Overlay",
         "formula": "overlay effect = SUM(total_ecl - model_ecl) closing "
                    "- SUM(total_ecl - model_ecl) opening",
         "note": "Additive, so attributed directly rather than factorised."},
        {"name": "Reconciliation",
         "formula": "SUM(components) = closing ECL - opening ECL",
         "note": (f"Exact by construction and asserted to within "
                  f"{TOLERANCE:g} of the movement. A decomposition that does "
                  "not reconcile is reported as not reconciling, never shown "
                  "as complete.")},
    ]


METHOD_ID = "ecl_change_decomposition"


def _trace(question: str, reading: Any, found: Decomposition,
           handlers: Any) -> Any:
    """The Trace for a decomposition: a real calculation, said to be one.

    Not the metadata graph the other handlers use. This method reads two
    periods of the book at row level and computes an attribution, and a Trace
    that described it as a catalogue lookup would be the contradiction P0.9
    exists to prevent.
    """
    from backend.trace.model import NodeType, TraceGraph, TraceNode

    try:
        graph = TraceGraph()
        graph.add_node(TraceNode(
            id="question", type=NodeType.USER_PROMPT, label="Question asked",
            config={"question": question}))
        intent = graph.add_node(TraceNode(
            id="intent", type=NodeType.CAPABILITY,
            label="Read as: ECL change decomposition",
            config={"objective": getattr(reading, "objective", ""),
                    "method": METHOD_ID,
                    "computation_required": True,
                    "rule": ("An order-neutral attribution of the movement in "
                             "total ECL across governed drivers.")}))
        intent.mark_ok()
        graph.connect("question", "intent")

        source = graph.add_node(TraceNode(
            id="population", type=NodeType.DATASET,
            label=f"{DATASET} at {found.opening_period} and "
                  f"{found.closing_period}",
            config={"dataset": DATASET, "fields": list(FIELDS),
                    "matched": found.matched, "arrived": found.arrived,
                    "departed": found.departed,
                    "rule": ("The attribution is defined on accounts present "
                             "in both periods. Arrivals and departures are "
                             "separate components, because an account with one "
                             "PD has no PD change.")}))
        source.mark_ok(rows_out=found.matched)
        graph.connect("intent", "population")

        method = graph.add_node(TraceNode(
            id="attribution", type=NodeType.CALCULATION,
            label="Shapley attribution across six factors",
            config={"factors": list(FACTORS), "formulas": formulas(),
                    "components": [c.to_dict() for c in found.components]}))
        method.mark_ok(rows_out=len(found.components))
        graph.connect("population", "attribution")

        check = graph.add_node(TraceNode(
            id="reconciliation", type=NodeType.RECONCILIATION,
            label=("Components reconcile to the movement" if found.reconciles
                   else "Components do NOT reconcile"),
            config={"movement": round(found.movement, 6),
                    "attributed": round(found.attributed, 6),
                    "gap": round(found.gap, 12),
                    "tolerance": TOLERANCE,
                    "rule": ("sum(component effects) = closing ECL - opening "
                             "ECL. Exact by construction; asserted anyway, "
                             "because a decomposition that silently stops "
                             "reconciling is a decomposition nobody can "
                             "trust.")}))
        if found.reconciles:
            check.mark_ok()
        else:
            check.mark_failed(f"gap of {found.gap:,.6f}")
        graph.connect("attribution", "reconciliation")

        result = graph.add_node(TraceNode(
            id="result", type=NodeType.RESULT, label="Attribution",
            config={"proves": found.proves(),
                    "does_not_prove": found.does_not_prove()}))
        result.mark_ok(rows_out=len(found.components))
        graph.connect("reconciliation", "result")
        graph.compute_hashes()
        return graph
    except Exception as e:  # noqa: BLE001 - a Trace must not lose an answer
        logger.warning("Could not build the decomposition Trace: %s", e)
        return None


__all__ = [
    "COMPONENTS",
    "DATASET",
    "METHOD_ID",
    "FIELDS",
    "EXITED_ACCOUNTS",
    "EXPOSURE",
    "FACTORS",
    "LABELS",
    "LGD",
    "MATERIAL_SHARE",
    "MEANINGS",
    "MIX",
    "MODEL",
    "NEW_ACCOUNTS",
    "OVERLAY",
    "PD",
    "STAGE",
    "TOLERANCE",
    "Account",
    "account_from",
    "Component",
    "Contributor",
    "Decomposition",
    "answer",
    "decompose",
    "formulas",
    "name_customers",
    "read_book",
    "shapley",
    "wants",
]
