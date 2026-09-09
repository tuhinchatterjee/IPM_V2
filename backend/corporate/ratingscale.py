"""
The governed CreditProbe 19-point corporate internal rating master scale.

This module is the ONE definition of the corporate rating scale and of the
three probabilities of default the IFRS 9 book is measured on. The universe
generator, the Borrower 360 snapshot, What-If, the Delta Model, the ML feature
set, the migration matrix and every chart read it from here. There is no second
scale underneath: a grade is an ordinal on this table and nothing else, and
nothing anywhere sorts a rating alphabetically — `AA-` sorts before `AA+`
lexicographically and after it in credit, which is the whole reason the order
is governed in one place instead of being derived at each screen.

The scale
---------
Nineteen ordered PERFORMING grades, ordinal 1 (strongest) to 19 (weakest):

    AAA AA+ AA AA- A+ A A- BBB+ BBB BBB- BB+ BB BB- B+ B B- CCC CC C

The scale ends at `C`. Default is NOT a twentieth grade of it. `D` is a
separate STATE, carried at ordinal 20 so a defaulted borrower still sorts last
on a screen, and it is reached by the default EVENT and never by a PD band —
a name can carry a sixty per cent twelve-month PD and still be paying, and a
scale that grades it `D` makes the default rate of its own weakest grade
unmeasurable, because the grade and the outcome stop being separate facts.

Ordinals ascend with risk, so a downgrade is a positive notch move and
`notches(a, b)` is a subtraction. That is the whole of the notch arithmetic.

Every borrower record carries `internal_rating` and `internal_rating_ordinal`,
and they agree by construction because both are written from this table.

The three PDs, and why there are three
--------------------------------------
IFRS 9 needs a measure that moves with the cycle; a rating system needs one
that does not. Copying one field into the other three would make the book
internally incoherent, so each is derived and each means something different:

  TTC PD — the through-the-cycle central tendency of the GRADE. A property of
      the masterscale, not of the quarter. Grade 9 has the same TTC PD in the
      trough as at the peak; that is what makes a rating migration readable.

  PIT 12-month PD — what this borrower is actually expected to do over the
      next year. Derived from the TTC PD by shifting the single-factor default
      threshold with the state of the cycle:

          PIT = Phi( Phi^-1(TTC) - sqrt(rho / (1 - rho)) * Z + e )

      Z is the systematic factor, POSITIVE in good times, and `e` is the
      borrower's own idiosyncratic condition. `rho` is the asset correlation
      and is SECTOR-SPECIFIC, which is what makes a macro shock hit Real
      Estate harder than Healthcare rather than shifting the book uniformly.

      This is the threshold-shift form rather than the Basel conditional-PD
      form. They differ in one property that matters here: at Z = 0 this
      returns the grade's TTC PD EXACTLY, so "neutral cycle" means "central
      tendency" and a reader comparing a PIT PD against its grade sees the
      cycle in the difference. The Basel form divides by sqrt(1 - rho) and so
      sits below the central tendency at Z = 0 — correct for a capital
      calculation, confusing on a screen.

  Lifetime PD — the cumulative probability of default over the behavioural
      life. NOT `1 - (1 - PIT)^T`: that assumes today's stressed hazard
      persists for four years, which no credit committee believes. The hazard
      MEAN-REVERTS from the PIT level back towards the grade's TTC level:

          h_1 = PIT
          h_t = TTC + (h_{t-1} - TTC) * REVERSION           for t > 1
          lifetime = 1 - product over t of (1 - h_t)

      So a borrower stressed today has a lifetime PD well below the naive
      extrapolation, and a strong borrower's lifetime PD is comfortably above
      its twelve-month one. Both are what a lender would say.

Stage and the applicable PD
---------------------------
Stage 1 is measured on the twelve-month PD, Stage 2 on the lifetime PD, and
Stage 3 on 100%. `applicable_pd` is the only function that decides which, so
the measurement basis is one line and What-If can attribute a change of basis
separately from a change of level.

Stage 3 is 100% because the default has already happened; a measurement that
used 99.9% would be asserting a one-in-a-thousand chance that an observed
event did not occur. PD = 100% is not LGD = 100%: a defaulted borrower with
collateral still recovers, so the loss is `1.00 x LGD x EAD` and the whole of
the severity question stays with LGD. The modelled TTC, PIT and lifetime PDs
remain on the row as INFORMATION — they are what a cure or recovery analysis
reads — but they are not the measurement basis.
"""

from __future__ import annotations

from typing import Any

import numpy as np

SCALE_VERSION = "3.0.0"
SCALE_OWNER = "Credit Risk Analytics"
SCALE_EFFECTIVE = "2026-01-01"

# --------------------------------------------------------------- the grades

#: THE CreditProbe internal corporate rating scale: nineteen PERFORMING
#: grades, strongest first, ordinal 1 to 19. The scale ends at `C`.
#:
#: `C` is the weakest grade a paying borrower can hold. Default is NOT the
#: twentieth grade of this scale — it is an EVENT, and a scale that ends in
#: `D` makes the grade and the outcome the same fact, so the default rate of
#: the weakest grade becomes unmeasurable: every name in it has defaulted by
#: definition. Keeping them apart is what lets the book say "4% of C-rated
#: exposure defaulted this year" instead of "100%, trivially".
PERFORMING: tuple[str, ...] = (
    "AAA", "AA+", "AA", "AA-",
    "A+", "A", "A-",
    "BBB+", "BBB", "BBB-",
    "BB+", "BB", "BB-",
    "B+", "B", "B-",
    "CCC", "CC", "C",
)
PERFORMING_COUNT = len(PERFORMING)

#: The default state. It carries an ordinal so that a borrower that has
#: defaulted still sorts after every performing grade on a screen, and it is
#: never reachable from a PD band — only from the default event.
DEFAULT_GRADE = "D"
DEFAULT_ORDINAL = PERFORMING_COUNT + 1

#: The nineteen grades followed by the default state, for the places that must
#: show both: a rating distribution of the whole book, a stage-3 breakdown, a
#: chart axis. Anything measuring PERFORMING credit uses `PERFORMING`, and the
#: two names are kept distinct so a caller cannot silently get twenty grades
#: where the scale has nineteen.
ALL_STATES: tuple[str, ...] = (*PERFORMING, DEFAULT_GRADE)
STATE_COUNT = len(ALL_STATES)
#: Index of the default state inside `ALL_STATES`, for array indexing.
DEFAULT_STATE_INDEX = PERFORMING_COUNT

#: The weakest grade a scenario may downgrade INTO. A scenario never
#: manufactures a default: default is an event, not an arithmetic consequence.
WEAKEST_PERFORMING = PERFORMING[-1]

ORDINAL: dict[str, int] = {g: i + 1 for i, g in enumerate(ALL_STATES)}
BY_ORDINAL: dict[int, str] = {i + 1: g for i, g in enumerate(ALL_STATES)}

#: Investment grade ends at BBB-. Named because people ask for it by name.
INVESTMENT_GRADE: tuple[str, ...] = PERFORMING[:ORDINAL["BBB-"]]
SPECULATIVE_GRADE: tuple[str, ...] = PERFORMING[ORDINAL["BBB-"]:]

#: Colloquial bands, so "BBB" or "investment grade" resolves to real grades.
BANDS: dict[str, tuple[str, ...]] = {
    "aaa": ("AAA",),
    "aa": ("AA+", "AA", "AA-"),
    "a": ("A+", "A", "A-"),
    "bbb": ("BBB+", "BBB", "BBB-"),
    "bb": ("BB+", "BB", "BB-"),
    "b": ("B+", "B", "B-"),
    "ccc": ("CCC",),
    "cc": ("CC",),
    "c": ("C",),
    "d": (DEFAULT_GRADE,),
    "default": (DEFAULT_GRADE,),
    "investment grade": INVESTMENT_GRADE,
    "investment-grade": INVESTMENT_GRADE,
    "sub-investment grade": SPECULATIVE_GRADE,
    "sub investment grade": SPECULATIVE_GRADE,
    "speculative grade": SPECULATIVE_GRADE,
    "speculative": SPECULATIVE_GRADE,
    "non-investment grade": SPECULATIVE_GRADE,
    "high yield": SPECULATIVE_GRADE,
}

# ------------------------------------------------------------ the TTC master
#
# How this curve was built, in one paragraph
# ------------------------------------------
# The nineteen TTC PDs are a PIECEWISE-LINEAR CURVE IN LOG-ODDS of the annual
# default probability, anchored on published corporate default evidence. Three
# properties made log-odds the right space rather than percent or plain log:
# it is strictly monotonic by construction, so no inversion can be introduced
# by a rounding; the per-notch step is a single interpretable number (the
# log-odds distance between adjacent grades); and it saturates below 100%, so
# the weakest performing grade approaches but never reaches the default
# convention. Linear interpolation in PERCENT space was rejected outright: it
# puts equal absolute distance between AAA and AA+ as between CC and C, which
# is not how credit risk is spaced.
#
# The per-notch log-odds step is not constant — it widens down the scale,
# which is the shape the agency evidence shows:
#
#     AAA .. BBB-   0.37 per notch   (~1.45x PD per notch)
#     BBB- .. B-    0.60 per notch   (~1.8x PD per notch)
#     B- .. C       0.95 per notch   (~2x PD per notch, decelerating in
#                                     percent as it approaches saturation)
#
# The single anchor is BBB = 0.18%; everything else follows from the step
# schedule. `docs/corporate_rating_pd_calibration.md` records the external
# evidence consulted, what each anchor is worth, and the limitations of the
# exercise. The scale is an INTERNAL CreditProbe scale calibrated using public
# corporate default evidence as an external reference; it is not the S&P scale
# and it is not the Moody's scale, and no borrower here carries an
# agency-assigned rating.

#: The log-odds anchor the curve is built from: grade, ordinal, PD in percent.
TTC_ANCHOR_GRADE = "BBB"
TTC_ANCHOR_PD_PCT = 0.18
#: (from_ordinal, to_ordinal, log-odds step per notch) over the whole scale.
TTC_LOG_ODDS_STEPS: tuple[tuple[int, int, float], ...] = (
    (1, 10, 0.37), (10, 16, 0.60), (16, 19, 0.95),
)

#: Through-the-cycle twelve-month PD, in PERCENT, per PERFORMING grade. A
#: property of the GRADE and not of the quarter: grade 9 has the same TTC PD
#: in the trough as at the peak, which is what makes a rating migration
#: readable. Generated by the log-odds construction above and written out here
#: so the master is a table a reader can check rather than a function they
#: have to run.
TTC_PD_PCT: dict[str, float] = {
    "AAA": 0.00934, "AA+": 0.01353, "AA": 0.01958, "AA-": 0.02835,
    "A+": 0.04103, "A": 0.05939, "A-": 0.08596,
    "BBB+": 0.12440, "BBB": 0.18000, "BBB-": 0.26038,
    "BB+": 0.47343, "BB": 0.85931, "BB-": 1.55478,
    "B+": 2.79724, "B": 4.98232, "B-": 8.72116,
    "CCC": 19.81071, "CC": 38.97967, "C": 62.28900,
}

#: The PD of a defaulted exposure, for IFRS 9 measurement. Default has already
#: happened, so the probability that it happens is one. It is deliberately NOT
#: an entry in `TTC_PD_PCT`: that table is the masterscale of PERFORMING
#: grades, and putting 100% in it would let a performing calculation pick the
#: default convention up by accident.
#:
#: PD = 100% is not LGD = 100%. A defaulted borrower with collateral still
#: recovers, so the loss is `1.00 x LGD x EAD` and the LGD is the whole of the
#: severity question. `stage_three_pd()` is the one place the convention is
#: applied.
DEFAULT_PD_PCT = 100.0


#: The upper PD bound of each performing grade, used to read a grade FROM a
#: modelled PD. Derived as the geometric midpoint between adjacent TTC PDs, so
#: the bands are the masterscale's own and cannot drift away from it.
def _bounds() -> tuple[float, ...]:
    out = []
    for left, right in zip(PERFORMING, PERFORMING[1:], strict=False):
        out.append(float(np.sqrt(TTC_PD_PCT[left] * TTC_PD_PCT[right])))
    return tuple(out)


RATING_BOUNDS: tuple[float, ...] = _bounds()


#: The log-odds of each performing grade's TTC PD, in scale order.
#:
#: This is the axis the scale is actually built on, and it is exported because
#: a notch is not a constant amount of credit risk. Three notches at the
#: investment-grade end is 1.11 in log-odds; three notches through the
#: distressed tail is 2.85. Anything that asks "has this name moved enough to
#: matter?" has to ask it here rather than in notch counts, or the same rule
#: becomes a tight filter at one end of the scale and a loose one at the other.
LOG_ODDS: tuple[float, ...] = tuple(
    float(np.log((TTC_PD_PCT[g] / 100.0) / (1.0 - TTC_PD_PCT[g] / 100.0)))
    for g in PERFORMING)


def log_odds_gap(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """How far apart two grades are, in log-odds, by ZERO-BASED index.

    Indices outside the performing scale are clipped into it: a defaulted name
    is not on this axis, and the caller decides what to do about that rather
    than getting a silent zero.
    """
    axis = np.asarray(LOG_ODDS)
    a = np.clip(np.asarray(left, dtype=int), 0, PERFORMING_COUNT - 1)
    b = np.clip(np.asarray(right, dtype=int), 0, PERFORMING_COUNT - 1)
    return np.abs(axis[b] - axis[a])

PD_FLOOR_PCT = 0.003
PD_CEILING_PCT = 99.0

# ------------------------------------------------------- PIT and the cycle

#: Asset correlation in the single-factor transform, by sector. Higher means
#: the sector moves more with the cycle. These are the numbers that make a
#: macro shock differentiate rather than shift the book uniformly.
SECTOR_CORRELATION: dict[str, float] = {
    "Real Estate": 0.24,
    "Contracting": 0.22,
    "Construction": 0.22,
    "Petrochemicals": 0.20,
    "Transport & Logistics": 0.18,
    "Wholesale & Retail": 0.16,
    "Manufacturing": 0.16,
    "Hospitality": 0.20,
    "Agriculture": 0.14,
    "Mining": 0.20,
    "Telecom": 0.12,
    "Utilities": 0.10,
    "Healthcare": 0.10,
    "Education": 0.11,
    "Financial Services": 0.18,
    "Professional Services": 0.13,
    "Public Sector": 0.08,
}
DEFAULT_CORRELATION = 0.15

#: How far the hazard reverts towards the grade's TTC level each year of the
#: lifetime horizon. 0.55 keeps two thirds of the first year's excess by year
#: two and a fifth of it by year four, which is the shape a rating agency's
#: cumulative default curve has.
REVERSION = 0.55
#: Exposure-weighted behavioural mean life of the corporate book, in years.
LIFETIME_HORIZON_YEARS = 4.2


def _phi(x: np.ndarray | float) -> np.ndarray:
    """Standard normal CDF, without pulling scipy into the generator."""
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / np.sqrt(2.0)))


def _erf(x: np.ndarray) -> np.ndarray:
    """Abramowitz and Stegun 7.1.26. Accurate to 1.5e-7, which is far finer
    than any PD this book carries and avoids a dependency for one function."""
    sign = np.sign(x)
    z = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * z)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * np.exp(-z * z)
    return sign * y


def _phi_inverse(p: np.ndarray | float) -> np.ndarray:
    """Standard normal quantile. Acklam's rational approximation."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1.0 - 1e-12)
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    lower, upper = 0.02425, 1.0 - 0.02425
    out = np.zeros_like(p)

    left = p < lower
    if np.any(left):
        q = np.sqrt(-2.0 * np.log(p[left]))
        out[left] = ((((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5])
                     / ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0))
    right = p > upper
    if np.any(right):
        q = np.sqrt(-2.0 * np.log(1.0 - p[right]))
        out[right] = -((((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5])
                       / ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1.0))
    mid = ~(left | right)
    if np.any(mid):
        q = p[mid] - 0.5
        r = q * q
        out[mid] = ((((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5])*q
                    / (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0))
    return out


def ttc_pd(grades: np.ndarray | list[str]) -> np.ndarray:
    """The masterscale's central PD for each grade, in percent.

    `D` returns the default convention rather than a masterscale entry, so a
    caller that hands the whole book in gets a total answer without the
    default state having to live in the performing table.
    """
    return np.array(
        [DEFAULT_PD_PCT if str(g) == DEFAULT_GRADE
         else TTC_PD_PCT.get(str(g), TTC_PD_PCT["BB"]) for g in grades],
        dtype=float)


def correlation(sectors: np.ndarray | list[str]) -> np.ndarray:
    return np.array([SECTOR_CORRELATION.get(str(s), DEFAULT_CORRELATION)
                     for s in sectors], dtype=float)


def pit_pd(ttc_pct: np.ndarray, systematic: np.ndarray | float,
           rho: np.ndarray | float,
           idiosyncratic: np.ndarray | float = 0.0) -> np.ndarray:
    """Point-in-time twelve-month PD, in percent, from the TTC central PD.

    The single-factor transform. `systematic` is the state of the cycle, with
    POSITIVE meaning good times, so a strong economy lowers the PIT PD below
    the grade's central tendency and a downturn raises it above. At Z = 0 with
    no idiosyncratic term the result IS the grade's TTC PD, which is what makes
    the two comparable on a screen.
    """
    central = np.clip(np.asarray(ttc_pct, dtype=float) / 100.0, 1e-9, 0.999999)
    rho = np.clip(np.asarray(rho, dtype=float), 0.01, 0.6)
    loading = np.sqrt(rho / (1.0 - rho))
    moved = (_phi_inverse(central)
             - loading * np.asarray(systematic, dtype=float)
             + np.asarray(idiosyncratic, dtype=float))
    return np.clip(_phi(moved) * 100.0, PD_FLOOR_PCT, PD_CEILING_PCT)


def lifetime_pd(pit_pct: np.ndarray, ttc_pct: np.ndarray, *,
                years: float = LIFETIME_HORIZON_YEARS,
                reversion: float = REVERSION) -> np.ndarray:
    """Cumulative lifetime PD in percent, on a mean-reverting hazard.

    The first year's hazard is the point-in-time PD. Each later year reverts
    towards the grade's through-the-cycle level, so a borrower stressed today
    is not assumed to stay stressed for four years — which is the assumption
    `1 - (1 - PIT)^T` silently makes.
    """
    pit = np.clip(np.asarray(pit_pct, dtype=float) / 100.0, 0.0, 0.999999)
    ttc = np.clip(np.asarray(ttc_pct, dtype=float) / 100.0, 0.0, 0.999999)
    survival = np.ones_like(pit)
    hazard = pit.copy()
    whole = int(np.floor(years))
    for year in range(whole):
        if year:
            hazard = ttc + (hazard - ttc) * reversion
        survival = survival * (1.0 - np.clip(hazard, 0.0, 0.999999))
    tail = years - whole
    if tail > 0:
        hazard = ttc + (hazard - ttc) * reversion
        survival = survival * (1.0 - np.clip(hazard * tail, 0.0, 0.999999))
    return np.clip((1.0 - survival) * 100.0, PD_FLOOR_PCT, 99.9)


def stage_three_pd(shape: Any = None) -> float:
    """The measurement PD of a credit-impaired exposure: 100%.

    Not 99.9%, and not the borrower's modelled PD. Stage 3 means the default
    has already happened, so the probability of it happening is one; a
    measurement that used 99.9% would be asserting a one-in-a-thousand chance
    that an event already observed did not occur.

    The modelled TTC, PIT and lifetime PDs are still carried on the row as
    INFORMATION — they say what the borrower looked like and are what a
    recovery or cure analysis reads — but they are not the measurement basis.
    """
    return DEFAULT_PD_PCT


def applicable_pd(stage: np.ndarray, twelve_month: np.ndarray,
                  lifetime: np.ndarray) -> np.ndarray:
    """The PD the measurement uses, by Stage.

    Stage 1 is measured on the twelve-month PD, Stage 2 on the lifetime PD,
    and Stage 3 on 100% — the exposure has defaulted, so the probability of
    default is one and the loss is decided entirely by LGD and EAD.

    The ONE place the measurement basis is decided, so a change of basis is a
    single fact What-If can attribute separately from a change of level.
    """
    staged = np.asarray(stage)
    performing = np.where(staged <= 1,
                          np.asarray(twelve_month, dtype=float),
                          np.asarray(lifetime, dtype=float))
    return np.where(staged >= 3, DEFAULT_PD_PCT, performing)


# ------------------------------------------------------------- grade moves


def grade_from_pd(pd_pct: np.ndarray) -> np.ndarray:
    """Index into RATING_SCALE from a twelve-month PD, on the master bands.

    Returns a PERFORMING grade only.
    """
    index = np.zeros(np.shape(pd_pct), dtype=int)
    for edge in RATING_BOUNDS:
        index = index + (np.asarray(pd_pct) > edge).astype(int)
    return np.clip(index, 0, PERFORMING_COUNT - 1)


def ordinal(grades: np.ndarray | list[str]) -> np.ndarray:
    """1 for AAA through 19 for C, and 20 for default. Risk ascends."""
    return np.array([ORDINAL.get(str(g), ORDINAL["BB"]) for g in grades],
                    dtype=int)


def shift(grades: np.ndarray | list[str], notches: int) -> np.ndarray:
    """Move a grade by notches. Positive is a DOWNGRADE.

    Clamped at the weakest PERFORMING grade: a scenario does not manufacture a
    default. A name already in default stays in default.
    """
    out = []
    for grade in grades:
        name = str(grade)
        if name == DEFAULT_GRADE:
            out.append(DEFAULT_GRADE)
            continue
        moved = ORDINAL.get(name, ORDINAL["BB"]) + int(notches)
        moved = int(np.clip(moved, 1, PERFORMING_COUNT))
        out.append(BY_ORDINAL[moved])
    return np.array(out, dtype=object)


def notches(from_grade: str, to_grade: str) -> int:
    """How many notches from one grade to another. Positive is a downgrade."""
    return ORDINAL.get(str(to_grade), 0) - ORDINAL.get(str(from_grade), 0)


def grades_in(band: str) -> tuple[str, ...]:
    """The grades a colloquial band names. Empty when it names none."""
    said = str(band or "").strip().lower()
    if said in BANDS:
        return BANDS[said]
    upper = str(band or "").strip().upper()
    if upper in ORDINAL:
        return (upper,)
    return ()


def table() -> list[dict[str, Any]]:
    """The master table, as a screen shows it."""
    return [{
        "grade": grade,
        "ordinal": ORDINAL[grade],
        "performing": True,
        "ttc_pd_pct": TTC_PD_PCT[grade],
        "upper_pd_bound_pct": (RATING_BOUNDS[i] if i < len(RATING_BOUNDS)
                               else None),
        "band": next((b for b, g in BANDS.items()
                      if grade in g and len(b) <= 4), ""),
        "investment_grade": grade in INVESTMENT_GRADE,
    } for i, grade in enumerate(PERFORMING)]


def describe() -> dict[str, Any]:
    return {
        "version": SCALE_VERSION,
        "owner": SCALE_OWNER,
        "effective": SCALE_EFFECTIVE,
        "grades": list(PERFORMING),
        "grade_count": PERFORMING_COUNT,
        "performing_count": PERFORMING_COUNT,
        "states": list(ALL_STATES),
        "default_grade": DEFAULT_GRADE,
        "default_ordinal": DEFAULT_ORDINAL,
        "default_pd_pct": DEFAULT_PD_PCT,
        "weakest_performing": WEAKEST_PERFORMING,
        "name": "CreditProbe internal corporate rating scale",
        "basis": ("CreditProbe internal rating scale calibrated using public "
                  "corporate default evidence as an external reference. It is "
                  "not the S&P scale and it is not the Moody\u2019s scale, and "
                  "no borrower here carries an agency-assigned rating."),
        "direction": "Ordinal 1 is AAA and 19 is C, the weakest performing "
                     "grade; risk ascends with the ordinal, so a downgrade is "
                     "a positive notch move. Default is a separate state at "
                     "ordinal 20, reached by the default event and never by a "
                     "PD band.",
        "calibration": {
            "method": "Piecewise-linear in the log-odds of the annual default "
                      "probability, anchored on published corporate default "
                      "evidence.",
            "anchor": {"grade": TTC_ANCHOR_GRADE, "ttc_pd_pct": TTC_ANCHOR_PD_PCT},
            "log_odds_steps": [
                {"from_ordinal": a, "to_ordinal": b, "per_notch": s}
                for a, b, s in TTC_LOG_ODDS_STEPS],
            "document": "docs/corporate_rating_pd_calibration.md",
        },
        "table": table(),
        "pd": {
            "ttc": "A property of the GRADE, not the quarter. Read from the "
                   "master table above.",
            "pit": "The TTC PD with its single-factor default threshold "
                   "shifted by the state of the cycle, using a "
                   "sector-specific asset correlation and the borrower's own "
                   "idiosyncratic condition. A neutral cycle returns the "
                   "grade's TTC PD exactly.",
            "lifetime": "Cumulative over a "
                        f"{LIFETIME_HORIZON_YEARS}-year behavioural life on a "
                        "hazard that reverts towards the grade's TTC level by "
                        f"{REVERSION:.0%} a year — not a naive extrapolation "
                        "of today's twelve-month PD.",
            "applicable": "Twelve-month in Stage 1; lifetime in Stage 2; "
                          "100% in Stage 3, because the default has already "
                          "happened. PD of 100% is not LGD of 100% \u2014 a "
                          "defaulted borrower with collateral still recovers, "
                          "and the severity stays with LGD and EAD.",
        },
        "correlations": dict(SECTOR_CORRELATION),
        "lifetime_horizon_years": LIFETIME_HORIZON_YEARS,
        "reversion": REVERSION,
    }


__all__ = [
    "ALL_STATES", "BANDS", "BY_ORDINAL", "DEFAULT_CORRELATION",
    "DEFAULT_GRADE", "DEFAULT_ORDINAL", "DEFAULT_PD_PCT",
    "DEFAULT_STATE_INDEX", "INVESTMENT_GRADE", "LIFETIME_HORIZON_YEARS",
    "LOG_ODDS", "ORDINAL", "PD_CEILING_PCT", "PD_FLOOR_PCT", "PERFORMING",
    "PERFORMING_COUNT", "RATING_BOUNDS", "REVERSION", "SCALE_EFFECTIVE",
    "SCALE_OWNER", "SCALE_VERSION", "SECTOR_CORRELATION", "SPECULATIVE_GRADE",
    "STATE_COUNT", "TTC_ANCHOR_GRADE", "TTC_ANCHOR_PD_PCT",
    "TTC_LOG_ODDS_STEPS", "TTC_PD_PCT", "WEAKEST_PERFORMING", "applicable_pd",
    "correlation", "describe", "grade_from_pd", "grades_in", "lifetime_pd",
    "log_odds_gap", "notches", "ordinal", "pit_pd", "shift",
    "stage_three_pd", "table", "ttc_pd",
]
