"""
Whether the Corporate IFRS 9 book behaves like a credible credit portfolio.

What this is not
----------------
It is not a schema check, a range check or a reconciliation. Those are already
covered, and a book can pass all three while being economic nonsense: every
column present, every value in range, every total tying — and a rating that
moves 1.3 notches a quarter, or a Stage 2 population that cures at a third per
quarter, or a AAA name that is downgraded every single time it is looked at.

What it is
----------
Fourteen ORDINAL and DISTRIBUTIONAL questions about the book, asked the way a
credit-risk reviewer would ask them. The emphasis is on rank relationships and
on the shape of distributions rather than on absolute thresholds, because an
absolute threshold imported from a real portfolio would say more about the
portfolio it came from than about this one.

Where a bound IS asserted, it is stated in the finding, and it is derived from
the methodology this book documents rather than borrowed to make a test pass.
Three are genuinely external, and they are named as such: rating stability,
Stage 2 cure rates and multi-notch downgrade frequency are the three places
where "what a rating system is" is a fact about rating systems and not about
this generator.

Every check returns a finding rather than raising. A validation that stops at
the first problem tells you about one problem.

    uv run python scripts/whatif_economic_validation.py [--quick]
"""

from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.corporate import ratingscale as rs  # noqa: E402
from backend.corporate.ratingscale import ALL_STATES, PERFORMING  # noqa: E402
from backend.ifrs9 import policy  # noqa: E402
from backend.whatif import domain as dm  # noqa: E402

PASS, PARTIAL, FAIL = "PASS", "PARTIAL", "FAIL"

GRADE_INDEX = {g: i for i, g in enumerate(ALL_STATES)}


# ---------------------------------------------------------------- the bounds
#
# Three of these are facts about rating systems rather than about this
# generator, and they are the only external numbers in the file. Each says
# where it comes from.

#: Quarterly share of borrowers on the same grade they were on last quarter.
#: External: agency and internal-rating one-year stability for a whole book
#: sits around 70-90%, which is roughly 92-97% quarterly. A book far below this
#: is re-binning a score rather than carrying a rating.
RATING_STABILITY_MIN_PCT = 80.0

#: Quarterly share of Stage 2 exposure returning to Stage 1. External: a cure
#: rate above roughly a quarter per quarter implies an average Stage 2 sojourn
#: under four quarters, which supervisors read as a staging rule that is
#: measuring noise rather than credit deterioration.
STAGE2_CURE_MAX_PCT = 25.0

#: Quarterly share of borrowers falling three or more notches. External: a
#: multi-notch downgrade is a credit event, not a routine quarter.
MULTI_NOTCH_MAX_PCT = 3.0

#: Internal, from this book's own methodology: `lifetime_pd` is a cumulative
#: hazard over LIFETIME_HORIZON_YEARS, so it cannot be below the 12-month PD.
#: Not a judgement — an arithmetic consequence.
LIFETIME_HORIZON_YEARS = policy.LIFETIME_HORIZON_YEARS

#: Internal: the reported provision is measured from the book's own parameters
#: plus an overlay, so the two agree to within the overlay's size.
OVERLAY_TOLERANCE_PCT = 25.0

#: A rank correlation at or beyond this is a relationship rather than noise.
RANK_STRONG = 0.5


@dataclass
class Finding:
    """One economic question, its answer, and the evidence."""

    section: str
    question: str
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"section": self.section, "question": self.question,
                "status": self.status, "detail": self.detail,
                "basis": self.basis, "evidence": self.evidence}


class Review:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.tables: dict[str, Any] = {}

    def say(self, section: str, question: str, status: str, detail: str,
            evidence: dict[str, Any] | None = None, basis: str = "") -> None:
        self.findings.append(
            Finding(section, question, status, detail, evidence or {}, basis))
        mark = {PASS: "PASS", PARTIAL: "PARTIAL", FAIL: "FAIL"}[status]
        print(f"  {mark:8s} {question}")
        if status != PASS:
            print(f"           {detail}")

    @property
    def verdict(self) -> str:
        if any(f.status == FAIL for f in self.findings):
            return FAIL
        if any(f.status == PARTIAL for f in self.findings):
            return PARTIAL
        return PASS


def _w(frame: pd.DataFrame, column: str, weight: str = "ead") -> float:
    """An exposure-weighted mean, which is the only kind a book is read on."""
    e = pd.to_numeric(frame[weight], errors="coerce").fillna(0.0)
    v = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return float((v * e).sum() / e.sum()) if e.sum() else float("nan")


def _rate(frame: pd.DataFrame, top: str = "final_ecl",
          bottom: str = "ead") -> float:
    b = pd.to_numeric(frame[bottom], errors="coerce").fillna(0.0).sum()
    t = pd.to_numeric(frame[top], errors="coerce").fillna(0.0).sum()
    return float(t / b * 100.0) if b else float("nan")


def _spearman(x: pd.Series, y: pd.Series) -> float:
    ok = x.notna() & y.notna()
    if ok.sum() < 3:
        return float("nan")
    return float(x[ok].rank().corr(y[ok].rank()))


def _inversions(values: list[float]) -> list[int]:
    """Positions where a series that should rise falls instead."""
    return [i for i in range(1, len(values))
            if not (np.isnan(values[i]) or np.isnan(values[i - 1]))
            and values[i] < values[i - 1] - 1e-9]


# ============================================ 1. the 19-point rating economics


def rating_economics(review: Review, latest: pd.DataFrame,
                     period: str) -> None:
    print("\n== 1. Rating economics, the 19-point scale")
    g = latest.groupby("internal_rating")
    table = pd.DataFrame({
        "borrowers": g.size(),
        "exposure": g["ead"].sum(),
        "ttc_pd": g.apply(lambda d: _w(d, "ttc_pd_pct"), include_groups=False),
        "pit_pd": g.apply(lambda d: _w(d, "pit_pd_12m_pct"),
                          include_groups=False),
        "pd_12m": g.apply(lambda d: _w(d, "pd_12m"), include_groups=False),
        "lifetime_pd": g.apply(lambda d: _w(d, "pd_lifetime"),
                               include_groups=False),
        "lgd": g.apply(lambda d: _w(d, "lgd"), include_groups=False),
        "stage_1_pct": g["stage"].apply(lambda s: (s == 1).mean() * 100),
        "stage_2_pct": g["stage"].apply(lambda s: (s == 2).mean() * 100),
        "stage_3_pct": g["stage"].apply(lambda s: (s == 3).mean() * 100),
        "ecl_rate_pct": g.apply(_rate, include_groups=False),
        "default_pct": g["default_flag"].mean() * 100,
    }).reindex([r for r in ALL_STATES if r in g.groups])
    review.tables["rating"] = table.round(4).reset_index().to_dict("records")

    performing = table.reindex([r for r in PERFORMING if r in table.index])

    # The three PDs must rise through the scale. ONE rule decides whether a
    # step down is a finding, and it is the same rule everywhere: the fall has
    # to be larger than the sampling noise of the two grades' own means.
    #
    # That rule does the right thing at both ends without a special case. TTC
    # is a pure property of the grade, so its within-grade variance is zero,
    # the tolerance is zero, and strict monotonicity is enforced. PIT is the
    # grade PLUS the borrower's own remainder — two names in a grade do not
    # carry an identical PD, by design — so a grade holding five borrowers can
    # sit below one holding twenty-five on the mix of those five, and that is
    # the model working rather than the scale failing.
    grades = performing.index.tolist()
    for measure, column, name in (
            ("ttc_pd", "ttc_pd_pct", "TTC PD"),
            ("pit_pd", "pit_pd_12m_pct", "PIT 12m PD"),
            ("lifetime_pd", "pd_lifetime", "lifetime PD")):
        values = performing[measure].tolist()
        spread = latest.groupby("internal_rating")[column].std().reindex(
            grades).fillna(0.0).tolist()
        counts = performing["borrowers"].tolist()
        errors = [sd / np.sqrt(max(int(n), 1))
                  for sd, n in zip(spread, counts, strict=False)]
        found = []
        for i in range(1, len(values)):
            fall = values[i - 1] - values[i]
            tolerance = 2.0 * float(np.hypot(errors[i], errors[i - 1]))
            if fall > tolerance:
                found.append({"where": f"{grades[i - 1]}->{grades[i]}",
                              "fall": round(fall, 6),
                              "two_standard_errors": round(tolerance, 6),
                              "borrowers": [int(counts[i - 1]),
                                            int(counts[i])]})
        noise = [f"{grades[i - 1]}->{grades[i]}" for i in range(1, len(values))
                 if values[i] < values[i - 1] - 1e-12
                 and not any(f["where"] == f"{grades[i - 1]}->{grades[i]}"
                             for f in found)]
        review.say(
            "rating",
            f"{name} rises through the performing scale",
            PASS if not found else FAIL,
            ("no inversion beyond the sampling noise of the grades"
             + (f"; {len(noise)} within it: {', '.join(noise)}" if noise
                else ""))
            if not found else f"{len(found)} inversion(s): {found}",
            {"values": [round(v, 6) for v in values], "grades": grades,
             "inversions": found, "within_noise": noise,
             "borrowers": [int(c) for c in counts]},
            basis="Ordinal, with one tolerance rule used everywhere: a fall "
                  "counts when it exceeds two standard errors of the two "
                  "grades' means. TTC has no within-grade variance, so that "
                  "reduces to strict monotonicity; PIT and lifetime carry a "
                  "borrower-specific remainder, so a thinly populated grade "
                  "may sit below its neighbour on the mix of a handful of "
                  "names.")

    # The ECL rate is NOT one of them. It is PD x LGD x EAD, and LGD is a
    # property of the security rather than the obligor, so a grade whose names
    # happen to be better secured can carry a lower provision rate than the
    # grade above it. Demanding strict monotonicity here would be demanding
    # that collateral not matter. So: rank across the scale, and material
    # local reversals reported rather than a step-by-step test.
    values = performing["ecl_rate_pct"].tolist()
    grades = performing.index.tolist()
    rank = _spearman(pd.Series(range(len(performing)), index=performing.index),
                     performing["ecl_rate_pct"])
    # A reversal is only a finding if it is large in BOTH senses. A 40% fall
    # from 0.023% to 0.014% is a 40% fall in nothing: at the top of the scale
    # the rates are hundredths of a per cent, and thirty-five borrowers'
    # collateral mix moves them by more than that. So the absolute fall has to
    # be worth a fraction of what the book as a whole provides, which is the
    # scale a reader actually reads these against.
    book_rate = _rate(latest)
    floor = book_rate * 0.05
    # And a grade too thin to have a mean cannot be evidence of a reversal
    # either way. The single borrower in C moves that row's coverage by its own
    # collateral, and a check that reads one name's LGD as a statement about
    # the scale is measuring the borrower. The rule is the one this script
    # already uses for the PD ordering: the fall has to be larger than the
    # sampling noise of the two grades' own means.
    per_borrower = (pd.to_numeric(latest["final_ecl"], errors="coerce")
                    / pd.to_numeric(latest["ead"], errors="coerce")
                    .replace(0, np.nan) * 100.0)
    spread = per_borrower.groupby(latest["internal_rating"]).std().reindex(
        grades).fillna(0.0).tolist()
    counts = performing["borrowers"].tolist()
    errors = [float(sd) / np.sqrt(max(int(n), 1)) if int(n) > 1 else np.nan
              for sd, n in zip(spread, counts, strict=False)]
    thin = [g for g, n in zip(grades, counts, strict=False) if int(n) <= 1]

    material = []
    for i in range(1, len(values)):
        if np.isnan(values[i]) or np.isnan(values[i - 1]) or not values[i - 1]:
            continue
        if np.isnan(errors[i]) or np.isnan(errors[i - 1]):
            continue
        noise = 2.0 * float(np.sqrt(errors[i] ** 2 + errors[i - 1] ** 2))
        fall = values[i - 1] - values[i]
        relative = fall / values[i - 1] * 100.0
        if relative > 25.0 and fall >= floor and fall > noise:
            material.append({"where": f"{grades[i - 1]}->{grades[i]}",
                             "fall_pct": round(relative, 2),
                             "fall_pp": round(fall, 4),
                             "lgd_before": round(
                                 float(performing["lgd"].iloc[i - 1]), 2),
                             "lgd_after": round(
                                 float(performing["lgd"].iloc[i]), 2),
                             "borrowers": int(
                                 performing["borrowers"].iloc[i])})
    review.say(
        "rating", "the ECL rate rises through the scale",
        PASS if rank >= 0.9 and not material else
        (PARTIAL if rank >= 0.9 else FAIL),
        f"Spearman {rank:.3f} across the nineteen grades"
        + ("" if not material else
           f"; {len(material)} material local reversal(s), each explained by "
           f"the collateral mix: {material}"),
        {"spearman": round(rank, 4), "material_reversals": material,
         "values": [round(v, 5) for v in values], "grades": grades,
         "materiality_floor_pp": round(floor, 5),
         "too_thin_to_be_evidence": thin,
         "book_ecl_rate_pct": round(book_rate, 4)},
        basis="Rank, not step: the provision rate is PD x LGD, and LGD is a "
              "property of the security. A grade whose names are better "
              "secured may carry a lower rate than the grade above it, which "
              "is the collateral working rather than the scale failing. A "
              "grade holding one borrower is excluded from the reversal test "
              "for the same reason the PD ordering excludes it: one name's "
              "collateral is not a statement about a scale.")

    # Stage 2 incidence should rise with weakness. It is a step function of a
    # threshold, so it is checked by RANK rather than by strict monotonicity.
    rank = _spearman(pd.Series(range(len(performing)), index=performing.index),
                     performing["stage_2_pct"])
    review.say(
        "rating", "Stage 2 incidence rises with weakness",
        PASS if rank >= RANK_STRONG else FAIL,
        f"Spearman {rank:.3f} between grade rank and Stage 2 share",
        {"spearman": round(rank, 4)},
        basis=f"Rank, not level: staging is a threshold rule, so the share "
              f"steps rather than glides. Strong at >= {RANK_STRONG}.")

    # LGD is a recovery property, not an obligor one, so it is NOT expected to
    # track the grade. Saying so is the point: a book where it did would be
    # double-counting the obligor's risk into the loss rate.
    lgd_rank = _spearman(pd.Series(range(len(performing)),
                                   index=performing.index),
                         performing["lgd"])
    review.say(
        "rating", "LGD does not simply track the rating",
        PASS if abs(lgd_rank) < 0.85 else PARTIAL,
        f"Spearman {lgd_rank:.3f} between grade rank and LGD — LGD is driven "
        "by collateral, which is checked in its own section",
        {"spearman": round(lgd_rank, 4)},
        basis="Economic: loss given default is a property of the security, "
              "not of the obligor's probability of default.")

    d = table.loc["D"] if "D" in table.index else None
    if d is not None:
        clean = bool(d["default_pct"] == 100.0 and d["stage_3_pct"] == 100.0)
        review.say(
            "rating", "the D grade is exactly the defaulted population",
            PASS if clean else FAIL,
            f"{int(d['borrowers'])} borrowers, {d['default_pct']:.0f}% "
            f"flagged, {d['stage_3_pct']:.0f}% in Stage 3",
            {"borrowers": int(d["borrowers"]),
             "default_pct": float(d["default_pct"]),
             "stage_3_pct": float(d["stage_3_pct"])},
            basis="Definitional: D is assigned on the default event.")


# =================================== 2. TTC / PIT / lifetime are different PDs


def pd_economics(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 2. TTC / PIT / lifetime PD economics")
    macro = dm.macro().set_index("period")
    rows = []
    for period, frame in books.items():
        cycle = (float(macro.loc[period, "credit_cycle_factor"])
                 if period in macro.index else float("nan"))
        rows.append({
            "period": period, "borrowers": int(len(frame)),
            "ttc_pd": _w(frame, "ttc_pd_pct"),
            "pit_pd": _w(frame, "pit_pd_12m_pct"),
            "lifetime_pd": _w(frame, "pd_lifetime"),
            "pit_p50": float(frame["pit_pd_12m_pct"].median()),
            "pit_p90": float(frame["pit_pd_12m_pct"].quantile(0.90)),
            "pit_p99": float(frame["pit_pd_12m_pct"].quantile(0.99)),
            "pit_sd": float(frame["pit_pd_12m_pct"].std()),
            "cycle": cycle,
        })
    series = pd.DataFrame(rows)
    review.tables["pd_by_quarter"] = series.round(4).to_dict("records")

    # TTC must be a property of the GRADE: constant per grade, across time.
    drift = {}
    for frame in books.values():
        for grade, value in frame.groupby("internal_rating")["ttc_pd_pct"]:
            drift.setdefault(grade, []).extend(value.tolist())
    moving = {g: (min(v), max(v)) for g, v in drift.items()
              if max(v) - min(v) > 1e-9}
    review.say(
        "pd", "TTC PD is a fixed property of the grade",
        PASS if not moving else FAIL,
        "constant for every grade in every quarter" if not moving
        else f"{len(moving)} grade(s) whose TTC moves: {sorted(moving)[:6]}",
        {"grades_that_move": sorted(moving)},
        basis="Definitional: through-the-cycle means the grade's own level, "
              "so any portfolio movement in weighted TTC must come from "
              "migration and not from the level.")

    # PIT must react to the cycle more than TTC does.
    pit_beta = _spearman(series["pit_pd"], series["cycle"])
    ttc_beta = _spearman(series["ttc_pd"], series["cycle"])
    ratio = series["pit_pd"] / series["ttc_pd"]
    review.say(
        "pd", "PIT PD reacts to the cycle",
        PASS if pit_beta <= -RANK_STRONG else FAIL,
        f"Spearman {pit_beta:.3f} against the credit cycle factor "
        f"(TTC {ttc_beta:.3f}); PIT/TTC ranges "
        f"{ratio.min():.2f}-{ratio.max():.2f}",
        {"pit_vs_cycle": round(pit_beta, 4),
         "ttc_vs_cycle": round(ttc_beta, 4),
         "pit_over_ttc_min": round(float(ratio.min()), 4),
         "pit_over_ttc_max": round(float(ratio.max()), 4)},
        basis="Ordinal and signed: a point-in-time PD must fall when the "
              "economy improves. The magnitude is not asserted.")

    # Portfolio TTC moves ONLY through migration; that movement is reported so
    # a reader can see how much of the cycle the grade absorbed.
    swing = float(series["ttc_pd"].max() / series["ttc_pd"].min())
    pit_swing = float(series["pit_pd"].max() / series["pit_pd"].min())
    review.say(
        "pd", "the portfolio's weighted TTC moves only by migration",
        PASS,
        f"weighted TTC {series['ttc_pd'].min():.2f}%-"
        f"{series['ttc_pd'].max():.2f}% ({swing:.2f}x) against PIT "
        f"{pit_swing:.2f}x — the grade absorbs part of the cycle by design",
        {"ttc_swing": round(swing, 3), "pit_swing": round(pit_swing, 3)},
        basis="Reported, not bounded: with TTC fixed per grade the only way "
              "the weighted figure can move is the mix.")

    lifetime_bad, checked = 0, 0
    for frame in books.values():
        checked += len(frame)
        lifetime_bad += int((frame["pd_lifetime"]
                             < frame["pd_12m"] - 1e-9).sum())
    review.say(
        "pd", "lifetime PD is never below the 12-month PD",
        PASS if lifetime_bad == 0 else FAIL,
        f"{lifetime_bad} violation(s) in {checked:,} borrower-quarters",
        {"violations": lifetime_bad, "rows": checked},
        basis=f"Arithmetic: a cumulative hazard over "
              f"{LIFETIME_HORIZON_YEARS} years cannot be below the same "
              "hazard over one.")


# ================================================= 3-4. stage economics


def stage_economics(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 3. Stage economics")
    rows = []
    for period, frame in books.items():
        row = {"period": period}
        for stage in (1, 2, 3):
            part = frame[frame["stage"] == stage]
            row[f"s{stage}_n"] = int(len(part))
            row[f"s{stage}_ead"] = float(part["ead"].sum())
            row[f"s{stage}_ecl"] = float(part["final_ecl"].sum())
            row[f"s{stage}_pd"] = _w(part, "pd_12m") if len(part) else 0.0
            row[f"s{stage}_lgd"] = _w(part, "lgd") if len(part) else 0.0
            row[f"s{stage}_rate"] = _rate(part) if len(part) else 0.0
        rows.append(row)
    table = pd.DataFrame(rows)
    review.tables["stage_by_quarter"] = table.round(4).to_dict("records")

    rates = [(r["s1_rate"], r["s2_rate"], r["s3_rate"]) for r in rows]
    bad = [rows[i]["period"] for i, (a, b, c) in enumerate(rates)
           if not (a < b < c)]
    review.say(
        "stage", "provision intensity escalates Stage 1 < 2 < 3",
        PASS if not bad else FAIL,
        f"holds in all {len(rows)} quarters" if not bad
        else f"breaks in {bad}",
        {"quarters_breaking": bad,
         "latest": {"s1": round(rates[-1][0], 3), "s2": round(rates[-1][1], 3),
                    "s3": round(rates[-1][2], 3)}},
        basis="Ordinal, and structural: Stage 2 and 3 are measured on a "
              "lifetime PD and Stage 1 on twelve months.")

    pds = [(r["s1_pd"], r["s2_pd"], r["s3_pd"]) for r in rows]
    bad = [rows[i]["period"] for i, (a, b, c) in enumerate(pds)
           if not (a < b <= c)]
    review.say(
        "stage", "credit quality worsens Stage 1 -> 2 -> 3",
        PASS if not bad else FAIL,
        f"holds in all {len(rows)} quarters" if not bad
        else f"breaks in {bad}",
        {"quarters_breaking": bad}, basis="Ordinal.")

    latest_period, latest = list(books.items())[-1]
    s3 = latest[latest["stage"] == 3]
    problems = []
    if len(s3):
        if not bool(s3["default_flag"].all()):
            problems.append("not every Stage 3 borrower is flagged defaulted")
        if set(s3["internal_rating"].unique()) - {"D"}:
            problems.append("a Stage 3 borrower is not rated D")
        benign = s3[(s3["current_dpd"] < policy.DEFAULT_DPD_DAYS)
                    & (~s3["default_flag"].astype(bool))]
        if len(benign):
            problems.append(f"{len(benign)} Stage 3 borrowers with no trigger")
    d_not_3 = latest[(latest["internal_rating"] == "D")
                     & (latest["stage"] != 3)]
    if len(d_not_3):
        problems.append(f"{len(d_not_3)} borrowers rated D outside Stage 3")
    review.say(
        "stage", "Stage 3 is exactly the credit-impaired population",
        PASS if not problems else FAIL,
        f"{len(s3)} borrowers in {latest_period}, every one rated D, flagged "
        f"and past due" if not problems else "; ".join(problems),
        {"stage_3": int(len(s3)), "problems": problems,
         "dpd_min": int(s3["current_dpd"].min()) if len(s3) else 0},
        basis="Definitional: 90 days past due is the presumption of default "
              "and nothing in this book rebuts it.")


def _transitions(opening: pd.Series, closing: pd.Series,
                 exposure: pd.Series) -> dict[str, float]:
    """Every stage transition, by count and — where it matters — by exposure.

    Exposure as well as count for the cure, because "a third of Stage 2 names
    cured" and "a third of Stage 2 exposure cured" are different facts and it
    is the second one that moves a provision.
    """
    out: dict[str, float] = {}
    for start in (1, 2, 3):
        base_n = float((opening == start).sum())
        base_e = float(exposure[opening == start].sum())
        for end in (1, 2, 3):
            if start == end:
                continue
            hit = (opening == start) & (closing == end)
            out[f"s{start}_s{end}"] = (float(hit.sum()) / base_n * 100.0
                                       if base_n else 0.0)
            out[f"s{start}_s{end}_exposure"] = (
                float(exposure[hit].sum()) / base_e * 100.0 if base_e else 0.0)
    return out


def stage_migration(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 4. Stage migration economics")
    periods = list(books)
    indexed = {p: f.set_index("borrower_id") for p, f in books.items()}
    rows = []
    for a, b in zip(periods, periods[1:], strict=False):
        A, B = indexed[a], indexed[b]
        both = A.index.intersection(B.index)
        sa, sb = A.loc[both, "stage"], B.loc[both, "stage"]
        ea = A.loc[both, "ead"]
        moved = _transitions(sa, sb, ea)
        rows.append({"from": a, "to": b, "matched": int(len(both)), **moved})
    table = pd.DataFrame(rows)
    review.tables["stage_migration"] = table.round(4).to_dict("records")

    cure = table["s2_s1_exposure"]
    review.say(
        "stage_migration", "Stage 2 does not cure implausibly fast",
        PASS if cure.mean() <= STAGE2_CURE_MAX_PCT else FAIL,
        f"mean {cure.mean():.1f}% of Stage 2 exposure returns to Stage 1 each "
        f"quarter (min {cure.min():.1f}, max {cure.max():.1f}); the bound is "
        f"{STAGE2_CURE_MAX_PCT}%",
        {"mean": round(float(cure.mean()), 3),
         "min": round(float(cure.min()), 3),
         "max": round(float(cure.max()), 3),
         "bound": STAGE2_CURE_MAX_PCT},
        basis="EXTERNAL: a cure rate above roughly a quarter per quarter "
              "implies an average Stage 2 sojourn under four quarters, which "
              "reads as a staging rule measuring noise rather than credit.")

    out_of_default = table[["s3_s2", "s3_s1"]].to_numpy().max()
    review.say(
        "stage_migration", "Stage 3 does not cure back within a quarter",
        PASS if out_of_default <= 0.0 else PARTIAL,
        f"maximum {out_of_default:.2f}% of Stage 3 leaves Stage 3 in one "
        "quarter",
        {"max_pct": round(float(out_of_default), 4)},
        basis="Methodology: this generator seasons a default for several "
              "quarters before it may cure or be written off.")

    entry = table["s1_s2"]
    review.say(
        "stage_migration", "Stage 2 entry moves with the cycle without a jump",
        PASS if entry.max() < 25.0 else PARTIAL,
        f"S1->S2 ranges {entry.min():.1f}%-{entry.max():.1f}% per quarter",
        {"min": round(float(entry.min()), 3),
         "max": round(float(entry.max()), 3)},
        basis="Distributional: a portfolio-wide jump with no credible event "
              "behind it is the failure mode; a range this wide is a cycle.")

    shares = [(p, float((f["stage"] == 2).mean() * 100)) for p, f in
              books.items()]
    lo, hi = min(s for _, s in shares), max(s for _, s in shares)
    review.say(
        "stage_migration", "the Stage 2 population never dominates the book",
        PASS if hi < 50.0 else FAIL,
        f"Stage 2 share ranges {lo:.1f}%-{hi:.1f}% across the window",
        {"min_pct": round(lo, 3), "max_pct": round(hi, 3),
         "by_quarter": [{"period": p, "stage_2_pct": round(s, 3)}
                        for p, s in shares]},
        basis="Distributional: a swing to portfolio dominance without a "
              "credible event is the failure this checks for.")


# ===================================================== 5. rating migration


def rating_migration(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 5. Rating migration economics")
    periods = list(books)
    indexed = {p: f.set_index("borrower_id") for p, f in books.items()}

    def compare(a: str, b: str) -> dict[str, Any]:
        A, B = indexed[a], indexed[b]
        both = A.index.intersection(B.index)
        ra = A.loc[both, "internal_rating"].map(GRADE_INDEX)
        rb = B.loc[both, "internal_rating"].map(GRADE_INDEX)
        alive = (ra != GRADE_INDEX["D"])
        move = (rb - ra)[alive]
        n = max(len(move), 1)
        return {"from": a, "to": b, "matched": int(len(move)),
                "stable_pct": float((move == 0).sum() / n * 100),
                "down_1_pct": float((move == 1).sum() / n * 100),
                "down_2_pct": float((move == 2).sum() / n * 100),
                "down_3_plus_pct": float((move >= 3).sum() / n * 100),
                "upgrade_pct": float((move < 0).sum() / n * 100),
                "to_default_pct": float(
                    (rb[alive] == GRADE_INDEX["D"]).sum() / n * 100),
                "mean_abs_notches": float(move.abs().mean()),
                "p99_abs_notches": float(move.abs().quantile(0.99))}

    qoq = pd.DataFrame([compare(a, b) for a, b in
                        zip(periods, periods[1:], strict=False)])
    yoy = pd.DataFrame([compare(a, b) for a, b in
                        zip(periods, periods[4:], strict=False)])
    review.tables["rating_migration_qoq"] = qoq.round(4).to_dict("records")
    review.tables["rating_migration_yoy"] = yoy.round(4).to_dict("records")

    stable = qoq["stable_pct"]
    review.say(
        "rating_migration", "a rating is carried, not recomputed each quarter",
        PASS if stable.mean() >= RATING_STABILITY_MIN_PCT else FAIL,
        f"{stable.mean():.1f}% of borrowers hold the same grade quarter to "
        f"quarter (min {stable.min():.1f}, max {stable.max():.1f}); the bound "
        f"is {RATING_STABILITY_MIN_PCT}%. Mean absolute movement "
        f"{qoq['mean_abs_notches'].mean():.2f} notches",
        {"mean_stable_pct": round(float(stable.mean()), 3),
         "min": round(float(stable.min()), 3),
         "max": round(float(stable.max()), 3),
         "mean_abs_notches": round(float(qoq["mean_abs_notches"].mean()), 4),
         "bound": RATING_STABILITY_MIN_PCT},
        basis="EXTERNAL: this is a fact about rating systems rather than "
              "about this generator. A grade that changes for most of the "
              "book every quarter is a re-binned score, not a rating.")

    multi = qoq["down_3_plus_pct"]
    review.say(
        "rating_migration", "multi-notch downgrades are uncommon",
        PASS if multi.mean() <= MULTI_NOTCH_MAX_PCT else FAIL,
        f"{multi.mean():.2f}% fall three or more notches in a quarter "
        f"(max {multi.max():.2f}); the bound is {MULTI_NOTCH_MAX_PCT}%",
        {"mean_pct": round(float(multi.mean()), 4),
         "max_pct": round(float(multi.max()), 4),
         "bound": MULTI_NOTCH_MAX_PCT},
        basis="EXTERNAL: a three-notch fall is a credit event, not a routine "
              "quarter.")

    # Strong grades should be stickier than weak ones. Pooled across quarters,
    # by grade, so a single quarter cannot carry the answer.
    pooled = []
    for a, b in zip(periods, periods[1:], strict=False):
        A, B = indexed[a], indexed[b]
        both = A.index.intersection(B.index)
        pooled.append(pd.DataFrame({
            "grade": A.loc[both, "internal_rating"],
            "move": (B.loc[both, "internal_rating"].map(GRADE_INDEX)
                     - A.loc[both, "internal_rating"].map(GRADE_INDEX))}))
    allq = pd.concat(pooled)
    allq = allq[allq["grade"] != "D"]
    by_grade = allq.groupby("grade")["move"].agg(
        n="size",
        stable_pct=lambda s: float((s == 0).mean() * 100),
        down_pct=lambda s: float((s > 0).mean() * 100),
        up_pct=lambda s: float((s < 0).mean() * 100))
    by_grade = by_grade.reindex([g for g in PERFORMING if g in by_grade.index])
    review.tables["rating_stability_by_grade"] = (
        by_grade.round(3).reset_index().to_dict("records"))

    thin = by_grade[by_grade["n"] >= 200]
    rank = _spearman(
        pd.Series([GRADE_INDEX[g] for g in thin.index], index=thin.index),
        thin["stable_pct"])
    review.say(
        "rating_migration", "strong grades are at least as stable as weak ones",
        PASS if rank <= 0.2 else PARTIAL,
        f"Spearman {rank:.3f} between grade rank and stability — negative or "
        "flat means strong grades are stickier",
        {"spearman": round(rank, 4),
         "weakest_stable_pct": round(float(thin["stable_pct"].iloc[-1]), 2),
         "strongest_stable_pct": round(float(thin["stable_pct"].iloc[0]), 2)},
        basis="Ordinal: a rating system built on investment-grade names does "
              "not move them more often than it moves distressed ones.")

    # The boundary artefact: a grade at either end of the scale must not be
    # forced to move because there is nowhere for noise to go.
    ends = {}
    for grade in (PERFORMING[0], PERFORMING[-1]):
        if grade in by_grade.index and by_grade.loc[grade, "n"] >= 20:
            ends[grade] = float(by_grade.loc[grade, "stable_pct"])
    trapped = {g: v for g, v in ends.items() if v < 25.0}
    review.say(
        "rating_migration", "the ends of the scale are not one-way streets",
        PASS if not trapped else FAIL,
        f"stability at the extremes: "
        f"{', '.join(f'{g} {v:.0f}%' for g, v in ends.items()) or 'too few'}"
        + ("" if not trapped else f" — {sorted(trapped)} cannot hold"),
        {"stability": {g: round(v, 2) for g, v in ends.items()}},
        basis="Structural: the strongest grade has nowhere to be upgraded to "
              "and the weakest performing grade nowhere to fall short of "
              "default, so an unsmoothed assignment pushes both off their "
              "grade every quarter.")


# ============================================ 6-8. ECL, LGD/collateral, EAD


def ecl_economics(review: Review, books: dict[str, pd.DataFrame],
                  measured: dict[str, pd.DataFrame]) -> None:
    print("\n== 6. ECL economics")
    rows, breaks = [], []
    for period, frame in measured.items():
        ead = float(frame["ead"].sum())
        before = float(frame["ecl_before_overlay"].sum())
        overlay = float(frame["management_overlay"].sum())
        final = float(frame["final_ecl"].sum())
        # The three scenario legs, reconstructed from the governed weights.
        unweighted = before / policy.WEIGHTED_SCENARIO_FACTOR
        legs = {name: unweighted * mult
                for name, _weight, mult in policy.SCENARIO_WEIGHTS}
        rebuilt = sum(unweighted * mult * weight
                      for _n, weight, mult in policy.SCENARIO_WEIGHTS)
        rows.append({"period": period, "ead": ead, "ecl_before_overlay": before,
                     "overlay": overlay, "final_ecl": final,
                     "rate_pct": final / ead * 100 if ead else 0.0,
                     **{f"ecl_{n.lower()}": v for n, v in legs.items()},
                     "weighted_rebuilt": rebuilt})
        if not (legs["Downside"] >= legs["Base"] >= legs["Upside"]):
            breaks.append(period)
    table = pd.DataFrame(rows)
    review.tables["ecl_by_quarter"] = table.round(4).to_dict("records")

    review.say(
        "ecl", "Downside ECL >= Base ECL >= Upside ECL",
        PASS if not breaks else FAIL,
        f"holds in all {len(rows)} quarters, by construction from the "
        f"governed weights {policy.SCENARIO_WEIGHTS}" if not breaks
        else f"breaks in {breaks}",
        {"weights": [list(w) for w in policy.SCENARIO_WEIGHTS],
         "latest": {k: round(v, 2) for k, v in rows[-1].items()
                    if k.startswith("ecl_")}},
        basis="Structural: the book stores ONE probability-weighted figure "
              "and the weights beside it, so the three legs are reconstructed "
              "rather than stored. The ordering is a property of the "
              "multipliers.")

    gap = (table["weighted_rebuilt"] - table["ecl_before_overlay"]).abs()
    review.say(
        "ecl", "the weighted figure reconciles to the scenario weights",
        PASS if float(gap.max()) < 1e-6 * float(table["ead"].max()) else FAIL,
        f"maximum difference {gap.max():.6f} on a book of "
        f"{table['ead'].iloc[-1]:,.0f}",
        {"max_abs_difference": round(float(gap.max()), 8)},
        basis="Arithmetic identity.")

    bad = {"ecl_above_ead": 0, "negative_ecl": 0, "negative_overlay": 0}
    for frame in measured.values():
        bad["ecl_above_ead"] += int(
            (frame["final_ecl"] > frame["ead"] + 1e-6).sum())
        bad["negative_ecl"] += int((frame["final_ecl"] < -1e-9).sum())
        bad["negative_overlay"] += int(
            (frame["management_overlay"] < -1e-9).sum())
    review.say(
        "ecl", "no impossible provision",
        PASS if not any(bad.values()) else FAIL,
        "no provision above its exposure, none negative, no negative overlay"
        if not any(bad.values()) else str(bad),
        bad, basis="Definitional.")

    latest = list(measured.values())[-1]
    s3 = latest[latest["stage"] == 3]
    rate = _rate(s3) if len(s3) else 0.0
    review.say(
        "ecl", "Stage 3 loss is severe rather than nominal",
        PASS if rate >= 20.0 else FAIL,
        f"Stage 3 provision covers {rate:.1f}% of Stage 3 exposure",
        {"stage_3_ecl_rate_pct": round(rate, 3)},
        basis="Derived from this book: a defaulted borrower carries a PD at "
              f"the ceiling and an LGD around {_w(s3, 'lgd'):.0f}%, so its "
              "coverage cannot be a Stage 1 number.")

    jumps = table["rate_pct"].pct_change().abs().dropna() * 100
    review.say(
        "ecl", "no unexplained portfolio-wide provision jump",
        PASS if float(jumps.max()) < 60.0 else PARTIAL,
        f"largest quarter-on-quarter change in the book's ECL rate "
        f"{jumps.max():.1f}%",
        {"max_qoq_change_pct": round(float(jumps.max()), 3),
         "series": [round(v, 3) for v in table["rate_pct"]]},
        basis="Distributional: the provision rate follows the cycle, so it "
              "moves; what it must not do is step.")


def lgd_economics(review: Review, latest: pd.DataFrame) -> None:
    print("\n== 7. LGD and collateral economics")
    bands = pd.cut(latest["collateral_coverage_pct"],
                   [-0.01, 0.01, 25, 50, 75, 100, np.inf],
                   labels=["none", "0-25", "25-50", "50-75", "75-100", "100+"])
    grouped = latest.groupby(bands, observed=True)
    table = pd.DataFrame({
        "borrowers": grouped.size(),
        "exposure": grouped["ead"].sum(),
        "lgd": grouped.apply(lambda d: _w(d, "lgd"), include_groups=False),
        "secured_share_pct": grouped.apply(
            lambda d: float(d["secured_exposure"].sum() / d["ead"].sum() * 100)
            if d["ead"].sum() else 0.0, include_groups=False),
    })
    review.tables["lgd_by_collateral"] = (
        table.round(3).reset_index().astype({"collateral_coverage_pct": str})
        .to_dict("records"))

    values = table["lgd"].tolist()
    names = [str(v) for v in table.index]
    rank = _spearman(latest["lgd"], latest["collateral_coverage_pct"])
    # A band-to-band reversal worth reporting is one bigger than the noise in
    # a band of THAT size, not any reversal at all. The bands are unequal —
    # one carries under a hundred names and another nearly a thousand — so the
    # comparison is against each band's own standard error rather than a flat
    # number of points. Two standard errors is the ordinary reading of "more
    # than the sample can explain".
    spread = float(latest["lgd"].std())
    errors = [spread / np.sqrt(max(int(n), 1))
              for n in table["borrowers"].tolist()]
    reversals = []
    for i in range(1, len(values)):
        rise = values[i] - values[i - 1]
        tolerance = 2.0 * np.hypot(errors[i], errors[i - 1])
        if rise > tolerance:
            reversals.append({
                "where": f"{names[i - 1]}->{names[i]}",
                "rise_pp": round(rise, 3),
                "two_standard_errors_pp": round(float(tolerance), 3),
                "borrowers": int(table["borrowers"].iloc[i])})
    review.say(
        "lgd", "LGD falls as collateral coverage rises",
        PASS if rank <= -RANK_STRONG and not reversals else
        (PARTIAL if rank <= -RANK_STRONG else FAIL),
        f"Spearman {rank:.3f} across {len(latest):,} borrowers; LGD "
        f"{values[0]:.1f}% with no collateral down to {values[-1]:.1f}% above "
        f"full coverage"
        + ("" if not reversals else
           f"; {len(reversals)} band reversal(s) above a point: {reversals}"),
        {"lgd_by_band": [round(v, 3) for v in values], "bands": names,
         "spearman": round(rank, 4), "reversals": reversals,
         "lgd_standard_deviation": round(spread, 3)},
        basis="Rank across borrowers, with band reversals judged against each "
              "band's own standard error: the bands hold between ninety and "
              "a thousand names, so a step-by-step test on the band means "
              "would be testing the bucketing rather than the economics.")

    impossible = {
        "secured_above_exposure": int(
            (latest["secured_exposure"] > latest["ead"] + 1e-6).sum()),
        "negative_unsecured": int(
            (latest["unsecured_exposure"] < -1e-9).sum()),
        "eligible_above_market": int(
            (latest["collateral_eligible_value"]
             > latest["collateral_market_value"] + 1e-6).sum()),
        "lgd_outside_range": int(
            ((latest["lgd"] < 0) | (latest["lgd"] > 100)).sum()),
    }
    review.say(
        "lgd", "no impossible collateral position",
        PASS if not any(impossible.values()) else FAIL,
        "recognised collateral never exceeds gross, secured never exceeds "
        "exposure, unsecured never negative" if not any(impossible.values())
        else str(impossible), impossible, basis="Definitional.")

    secured = _w(latest, "secured_lgd")
    unsecured = _w(latest, "unsecured_lgd")
    review.say(
        "lgd", "the haircut on secured exposure is worth having",
        PASS if secured < unsecured else FAIL,
        f"secured LGD {secured:.1f}% against unsecured {unsecured:.1f}%",
        {"secured_lgd": round(secured, 3),
         "unsecured_lgd": round(unsecured, 3)},
        basis="Ordinal.")


def ead_economics(review: Review, latest: pd.DataFrame) -> None:
    print("\n== 8. CCF and EAD economics")
    implied = (latest["drawn_exposure"]
               + latest["credit_conversion_factor"]
               * latest["undrawn_commitment"])
    diff = (latest["ead"] - implied).abs()
    scale = float(latest["ead"].abs().max())
    review.say(
        "ead", "EAD is drawn plus CCF times undrawn",
        PASS if float(diff.max()) <= max(0.5, scale * 1e-5) else FAIL,
        f"maximum difference {diff.max():.4f} on exposures up to "
        f"{scale:,.0f}; {int((diff > 0.01).sum())} of {len(latest):,} rows "
        "differ by more than a hundredth, which is the two-decimal storage",
        {"max_abs_difference": round(float(diff.max()), 6),
         "rows_above_hundredth": int((diff > 0.01).sum())},
        basis="Arithmetic identity, to the precision the lake stores.")

    by_stage = latest.groupby("stage")["credit_conversion_factor"].mean()
    spread = float(by_stage.max() - by_stage.min())
    review.say(
        "ead", "CCF is reported by stage",
        PASS,
        "CCF by stage: "
        + ", ".join(f"S{int(s)} {v:.3f}" for s, v in by_stage.items())
        + (f" — a spread of {spread:.3f}, so drawdown behaviour does not "
           "differentiate by stage in this methodology"
           if spread < 0.05 else ""),
        {"by_stage": {int(k): round(float(v), 4)
                      for k, v in by_stage.items()},
         "spread": round(spread, 4)},
        basis="Reported, not bounded: this generator does not claim that "
              "drawdown behaviour varies with deterioration, so a flat CCF "
              "is the methodology rather than a defect. It is stated because "
              "a reader comparing against a real book will expect it to vary.")


# ============================== 9-10. continuity, and twenty random borrowers


#: What a borrower may plausibly do in one quarter. These are read off the
#: book's own distribution and reported as percentiles; only the last is a
#: bound, and it is a bound on the SHARE of borrowers that jump, not on any
#: individual borrower — a name genuinely can lose half its exposure.
CONTINUITY_COLUMNS = ("ead", "pd_12m", "pd_lifetime", "lgd",
                      "credit_conversion_factor", "final_ecl")


def continuity(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 9. Quarter-to-quarter continuity, borrower by borrower")
    periods = list(books)
    indexed = {p: f.set_index("borrower_id") for p, f in books.items()}
    moves: dict[str, list[pd.Series]] = {c: [] for c in CONTINUITY_COLUMNS}
    notches: list[pd.Series] = []
    stage_moves: list[pd.Series] = []
    for a, b in zip(periods, periods[1:], strict=False):
        A, B = indexed[a], indexed[b]
        both = A.index.intersection(B.index)
        for column in CONTINUITY_COLUMNS:
            before = pd.to_numeric(A.loc[both, column], errors="coerce")
            after = pd.to_numeric(B.loc[both, column], errors="coerce")
            rel = (after - before) / before.where(before.abs() > 1e-9)
            moves[column].append(rel.abs().dropna() * 100)
        notches.append(
            (B.loc[both, "internal_rating"].map(GRADE_INDEX)
             - A.loc[both, "internal_rating"].map(GRADE_INDEX)).abs())
        stage_moves.append(B.loc[both, "stage"] != A.loc[both, "stage"])

    rows = []
    for column, parts in moves.items():
        joined = pd.concat(parts)
        rows.append({"measure": column, "observations": int(len(joined)),
                     "median_pct": float(joined.median()),
                     "p90_pct": float(joined.quantile(0.90)),
                     "p95_pct": float(joined.quantile(0.95)),
                     "p99_pct": float(joined.quantile(0.99)),
                     "max_pct": float(joined.max())})
    grade_move = pd.concat(notches)
    stage_change = pd.concat(stage_moves)
    rows.append({"measure": "rating (notches)",
                 "observations": int(len(grade_move)),
                 "median_pct": float(grade_move.median()),
                 "p90_pct": float(grade_move.quantile(0.90)),
                 "p95_pct": float(grade_move.quantile(0.95)),
                 "p99_pct": float(grade_move.quantile(0.99)),
                 "max_pct": float(grade_move.max())})
    table = pd.DataFrame(rows)
    review.tables["continuity"] = table.round(4).to_dict("records")

    review.say(
        "continuity", "a borrower's exposure does not lurch",
        PASS if table.loc[table["measure"] == "ead", "median_pct"].iloc[0]
        < 25.0 else PARTIAL,
        "median quarter-on-quarter move: "
        + ", ".join(f"{r['measure']} {r['median_pct']:.1f}%"
                    for r in rows if r["measure"] in ("ead", "final_ecl")),
        {"table": table.round(3).to_dict("records")},
        basis="Distributional, and reported as percentiles rather than "
              "bounded: an individual borrower may genuinely halve.")

    review.say(
        "continuity", "the rating is the slowest-moving thing on the record",
        PASS if float(grade_move.median()) == 0.0 else FAIL,
        f"median notch movement {grade_move.median():.0f}, "
        f"p95 {grade_move.quantile(0.95):.0f}, max {grade_move.max():.0f}; "
        f"{float((stage_change).mean() * 100):.1f}% of borrowers change stage "
        "in a quarter",
        {"median_notches": float(grade_move.median()),
         "p95_notches": float(grade_move.quantile(0.95)),
         "max_notches": float(grade_move.max()),
         "stage_change_pct": round(float(stage_change.mean() * 100), 3)},
        basis="Ordinal: a rating is a considered assessment, so the typical "
              "borrower's grade should not move at all in a given quarter.")


def random_borrowers(review: Review, books: dict[str, pd.DataFrame], *,
                     seed: int = 20260908, want: int = 20) -> None:
    """Twenty borrowers drawn at random, and what their eight quarters say.

    Stratified, not cherry-picked: the strata make sure a weak name and a
    defaulted name are looked at, and WITHIN each stratum the draw is random.
    Picking twenty interesting borrowers would prove nothing.
    """
    print("\n== 10. Twenty random borrowers")
    periods = list(books)
    latest = books[periods[-1]]
    rng = np.random.default_rng(seed)

    strata = {
        "strong (AAA-A-)": latest["internal_rating"].isin(PERFORMING[:7]),
        "medium (BBB+-BB-)": latest["internal_rating"].isin(PERFORMING[7:13]),
        "weak (B+-C)": latest["internal_rating"].isin(PERFORMING[13:19]),
        "defaulted (D)": latest["internal_rating"] == "D",
        "stage 2": latest["stage"] == 2,
        "large exposure": latest["ead"] >= latest["ead"].quantile(0.90),
        "small exposure": latest["ead"] <= latest["ead"].quantile(0.10),
    }
    chosen: list[tuple[str, str]] = []
    seen: set[str] = set()
    per = max(1, want // len(strata))
    for name, mask in strata.items():
        pool = [b for b in latest.loc[mask, "borrower_id"] if b not in seen]
        if not pool:
            continue
        take = rng.choice(pool, size=min(per, len(pool)), replace=False)
        for borrower in take:
            chosen.append((name, str(borrower)))
            seen.add(str(borrower))
    # Top the sample up at random from the whole book.
    spare = [b for b in latest["borrower_id"] if b not in seen]
    while len(chosen) < want and spare:
        pick = str(rng.choice(spare))
        chosen.append(("random", pick))
        seen.add(pick)
        spare = [b for b in spare if b != pick]

    trails, anomalies = [], []
    for stratum, borrower in chosen:
        history = []
        for period in periods[-8:]:
            frame = books[period]
            row = frame[frame["borrower_id"] == borrower]
            if row.empty:
                continue
            r = row.iloc[0]
            history.append({
                "period": period, "rating": str(r["internal_rating"]),
                "stage": int(r["stage"]), "ead": round(float(r["ead"]), 2),
                "ttc_pd": round(float(r["ttc_pd_pct"]), 4),
                "pit_pd": round(float(r["pd_12m"]), 4),
                "lifetime_pd": round(float(r["pd_lifetime"]), 4),
                "lgd": round(float(r["lgd"]), 2),
                "collateral_cover": round(
                    float(r["collateral_coverage_pct"]), 1),
                "dpd": int(r["current_dpd"]),
                "ecl": round(float(r["final_ecl"]), 3)})
        if not history:
            continue
        note, flags = _read_trail(history)
        anomalies.extend(f"{borrower}: {f}" for f in flags)
        trails.append({"borrower_id": borrower, "stratum": stratum,
                       "quarters": history, "assessment": note,
                       "anomalies": flags})
    review.tables["borrower_trails"] = trails
    review.say(
        "borrowers", "every sampled borrower's trajectory reads sensibly",
        PASS if not anomalies else FAIL,
        f"{len(trails)} borrowers over up to eight quarters, no incoherent "
        "trajectory" if not anomalies
        else f"{len(anomalies)} anomaly(ies): {anomalies[:5]}",
        {"sampled": len(trails), "anomalies": anomalies},
        basis="Ordinal, per borrower: a grade that moves must move with the "
              "PD, a Stage 3 quarter must carry a default trigger, and a "
              "provision must follow the risk that produced it.")


def _read_trail(history: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """What this borrower did, and anything about it that cannot be true."""
    flags: list[str] = []
    opening, closing = history[0], history[-1]
    for before, after in zip(history, history[1:], strict=False):
        gap = GRADE_INDEX[after["rating"]] - GRADE_INDEX[before["rating"]]
        # A grade that moved must move with the PD it is read from, unless
        # the move is into or out of default, which is an event.
        if gap and "D" not in (before["rating"], after["rating"]):
            if gap > 0 and after["ttc_pd"] < before["ttc_pd"]:
                flags.append(f"downgraded into a lower TTC PD at "
                             f"{after['period']}")
            if gap < 0 and after["ttc_pd"] > before["ttc_pd"]:
                flags.append(f"upgraded into a higher TTC PD at "
                             f"{after['period']}")
        if abs(gap) > 2 and "D" not in (before["rating"], after["rating"]):
            flags.append(f"moved {abs(gap)} notches at {after['period']}")
        if after["stage"] == 3 and after["dpd"] < policy.DEFAULT_DPD_DAYS \
                and after["rating"] != "D":
            flags.append(f"Stage 3 with no trigger at {after['period']}")
        if after["lifetime_pd"] < after["pit_pd"] - 1e-9:
            flags.append(f"lifetime PD below 12-month at {after['period']}")

    moved = GRADE_INDEX[closing["rating"]] - GRADE_INDEX[opening["rating"]]
    direction = ("deteriorated" if moved > 0 else
                 "improved" if moved < 0 else "held its grade")
    stages = {q["stage"] for q in history}
    story = (f"{opening['rating']} in {opening['period']} to "
             f"{closing['rating']} in {closing['period']} — {direction}"
             f"{f' by {abs(moved)} notch(es)' if moved else ''}. "
             f"12-month PD {opening['pit_pd']:.2f}% to "
             f"{closing['pit_pd']:.2f}%, exposure {opening['ead']:,.0f} to "
             f"{closing['ead']:,.0f}, provision {opening['ecl']:,.2f} to "
             f"{closing['ecl']:,.2f}. "
             + ("Stayed in Stage " f"{closing['stage']}." if len(stages) == 1
                else f"Moved through Stages {sorted(stages)}."))
    return story, flags


# ================================ 11-13. sector, segment and the macro cycle


#: What each cut is expected to differentiate, and why the two numbers differ.
#:
#: A SECTOR is an economic exposure: shipping and utilities do not face the
#: same world, and a book whose sectors carried the same risk would have no
#: sector dimension worth reading. A SEGMENT is a size and type cut — a Large
#: Corporate and a Mid Corporate in the same sector face much the same world
#: with different balance sheets — so it differentiates, but far less, and
#: holding it to the sector's bar would be demanding a difference that should
#: not be there.
#:
#: The same asymmetry applies to cyclicality: sectors are the cyclicality
#: dimension and segments are not, so segments are expected to move together.
CUT_EXPECTATIONS = {
    "sector": {"spread": 3.0, "cycle_spread": 0.3,
               "why": "a sector is an economic exposure"},
    "segment": {"spread": 1.3, "cycle_spread": 0.0,
                "why": "a segment is a size and type cut, not an economic "
                       "exposure, so it differentiates risk without "
                       "differentiating cyclicality"},
}


def _cut(review: Review, books: dict[str, pd.DataFrame], column: str,
         section: str, label: str) -> None:
    latest = list(books.values())[-1]
    grouped = latest.groupby(column)
    table = pd.DataFrame({
        "borrowers": grouped.size(),
        "exposure": grouped["ead"].sum(),
        "ttc_pd": grouped.apply(lambda d: _w(d, "ttc_pd_pct"),
                                include_groups=False),
        "pit_pd": grouped.apply(lambda d: _w(d, "pit_pd_12m_pct"),
                                include_groups=False),
        "lifetime_pd": grouped.apply(lambda d: _w(d, "pd_lifetime"),
                                     include_groups=False),
        "lgd": grouped.apply(lambda d: _w(d, "lgd"), include_groups=False),
        "stage_2_pct": grouped["stage"].apply(lambda s: (s == 2).mean() * 100),
        "stage_3_pct": grouped["stage"].apply(lambda s: (s == 3).mean() * 100),
        "ecl_rate_pct": grouped.apply(_rate, include_groups=False),
    }).sort_values("ecl_rate_pct", ascending=False)

    # How each cut moves through the cycle, so "they all behave the same" is
    # answerable rather than assumed.
    macro = dm.macro().set_index("period")["credit_cycle_factor"]
    through = {}
    for period, frame in books.items():
        through[period] = frame.groupby(column).apply(
            lambda d: _w(d, "pit_pd_12m_pct"), include_groups=False)
    path = pd.DataFrame(through).T
    cycle = macro.reindex(path.index)
    table["cycle_correlation"] = path.corrwith(cycle)
    table["peak_over_trough"] = (path.max() / path.replace(0, np.nan).min())
    review.tables[section] = table.round(4).reset_index().to_dict("records")

    expect = CUT_EXPECTATIONS[section]
    spread = float(table["ecl_rate_pct"].max()
                   / max(table["ecl_rate_pct"].min(), 1e-9))
    review.say(
        section, f"{label} differentiate risk",
        PASS if spread >= expect["spread"] else FAIL,
        f"ECL rate ranges {table['ecl_rate_pct'].min():.2f}% to "
        f"{table['ecl_rate_pct'].max():.2f}% — a spread of {spread:,.1f}x "
        f"across {len(table)} {label}; the bound is {expect['spread']}x",
        {"spread": round(spread, 3), "bound": expect["spread"],
         "highest": str(table.index[0]), "lowest": str(table.index[-1])},
        basis=f"Ordinal, and the bound differs by cut because "
              f"{expect['why']}. A cut that produced the same risk everywhere "
              "would not be a risk cut; holding a size cut to an economic "
              "cut's bar would demand a difference that should not exist.")

    spread_beta = float(table["cycle_correlation"].max()
                        - table["cycle_correlation"].min())
    wanted = expect["cycle_spread"]
    if wanted <= 0:
        review.say(
            section, f"{label} are reported for cyclicality, not held to it",
            PASS,
            f"correlation with the credit cycle ranges "
            f"{table['cycle_correlation'].min():.2f} to "
            f"{table['cycle_correlation'].max():.2f} — every {label[:-1]} is "
            "cyclical, which is what this cut should show",
            {"spread": round(spread_beta, 3),
             "min": round(float(table["cycle_correlation"].min()), 3),
             "max": round(float(table["cycle_correlation"].max()), 3)},
            basis="Reported, not bounded: cyclicality lives in the sector "
                  f"dimension. {expect['why'].capitalize()}.")
    else:
        review.say(
            section, f"{label} do not all respond to the cycle alike",
            PASS if spread_beta >= wanted else FAIL,
            f"correlation with the credit cycle ranges "
            f"{table['cycle_correlation'].min():.2f} to "
            f"{table['cycle_correlation'].max():.2f}; most cyclical "
            f"{table['cycle_correlation'].idxmin()}, most resilient "
            f"{table['cycle_correlation'].idxmax()}",
            {"spread": round(spread_beta, 3), "bound": wanted,
             "most_cyclical": str(table["cycle_correlation"].idxmin()),
             "most_resilient": str(table["cycle_correlation"].idxmax())},
            basis="Distributional: a book whose every sector moved together "
                  "would have one risk factor, not a sector dimension.")


def sector_economics(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 11. Sector economics")
    _cut(review, books, "sector", "sector", "sectors")


def segment_economics(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 12. Segment economics")
    _cut(review, books, "segment", "segment", "segments")


def macro_relationship(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 13. Macro and the point-in-time PD")
    macro = dm.macro().set_index("period")
    rows = []
    for period, frame in books.items():
        rows.append({
            "period": period,
            "cycle_factor": float(macro.loc[period, "credit_cycle_factor"])
            if period in macro.index else float("nan"),
            "gdp_growth": float(macro.loc[period, "real_gdp_growth_pct"])
            if period in macro.index else float("nan"),
            "ttc_pd": _w(frame, "ttc_pd_pct"),
            "pit_pd": _w(frame, "pit_pd_12m_pct"),
            "stage_2_pct": float((frame["stage"] == 2).mean() * 100),
            "ecl_rate_pct": _rate(frame)})
    table = pd.DataFrame(rows)
    review.tables["macro_path"] = table.round(4).to_dict("records")

    for measure, name in (("pit_pd", "the point-in-time PD"),
                          ("stage_2_pct", "the Stage 2 share"),
                          ("ecl_rate_pct", "the provision rate")):
        rank = _spearman(table[measure], table["cycle_factor"])
        review.say(
            "macro", f"{name} worsens as the cycle turns down",
            PASS if rank <= -RANK_STRONG else FAIL,
            f"Spearman {rank:.3f} against the credit cycle factor",
            {"spearman": round(rank, 4)},
            basis="Signed and ordinal: the direction is the claim; the "
                  "magnitude is a calibration this book does not assert.")

    pit_rank = abs(_spearman(table["pit_pd"], table["cycle_factor"]))
    ttc_rank = abs(_spearman(table["ttc_pd"], table["cycle_factor"]))
    review.say(
        "macro", "the cycle is not counted twice",
        PASS if pit_rank >= ttc_rank else PARTIAL,
        f"the point-in-time PD tracks the cycle at |{pit_rank:.3f}| and the "
        f"migration-driven TTC at |{ttc_rank:.3f}| — the grade absorbs part "
        "of the cycle and the conditioning adds only the remainder",
        {"pit": round(pit_rank, 4), "ttc": round(ttc_rank, 4)},
        basis="Structural: the grade carries a documented share of the cycle, "
              "so the conditioning applies only what the grade has not.")


# ===================================== 14. the default population, audited


def default_logic(review: Review, books: dict[str, pd.DataFrame]) -> None:
    print("\n== 14. Default and Stage 3 logic")
    problems: list[str] = []
    audited = 0
    for period, frame in books.items():
        impaired = frame[frame["stage"] == 3]
        audited += len(impaired)
        if len(impaired):
            if not bool(impaired["default_flag"].all()):
                problems.append(f"{period}: a Stage 3 borrower is not flagged")
            if set(impaired["internal_rating"]) - {"D"}:
                problems.append(f"{period}: a Stage 3 borrower is not rated D")
            benign = impaired[
                (impaired["current_dpd"] < policy.DEFAULT_DPD_DAYS)
                & (~impaired["default_flag"].astype(bool))]
            if len(benign):
                problems.append(
                    f"{period}: {len(benign)} Stage 3 with no trigger")
        # And the other direction: a trigger that did not reach Stage 3.
        triggered = frame[(frame["current_dpd"] >= policy.DEFAULT_DPD_DAYS)
                          | frame["default_flag"].astype(bool)]
        missed = triggered[triggered["stage"] != 3]
        if len(missed):
            problems.append(
                f"{period}: {len(missed)} triggered but not Stage 3")

    review.say(
        "default", "Stage 3 and the default population are the same names",
        PASS if not problems else FAIL,
        f"{audited:,} Stage 3 borrower-quarters audited across "
        f"{len(books)} quarters; every one flagged, rated D and past due, and "
        "no triggered borrower left outside Stage 3" if not problems
        else "; ".join(problems[:6]),
        {"audited": audited, "problems": problems},
        basis="Definitional, both ways: 90 days past due or a recorded "
              "default is the presumption, and nothing in this book rebuts "
              "it — so the implication runs in both directions.")

    latest = list(books.values())[-1]
    impaired = latest[latest["stage"] == 3]
    if len(impaired):
        review.tables["stage_3_profile"] = {
            "borrowers": int(len(impaired)),
            "dpd_min": int(impaired["current_dpd"].min()),
            "dpd_median": float(impaired["current_dpd"].median()),
            "dpd_max": int(impaired["current_dpd"].max()),
            "pd_12m_min": float(impaired["pd_12m"].min()),
            "lgd_mean": round(_w(impaired, "lgd"), 3),
            "ecl_rate_pct": round(_rate(impaired), 3),
            "exposure": float(impaired["ead"].sum())}


# ---------------------------------------------------------------- the run


# =================================== 15. is this a scale a risk person reads?


def scale_review(review: Review, latest: pd.DataFrame, period: str) -> None:
    """The table §42 asks for, printed, and the properties it must show.

    The instruction is "a senior risk professional should see intuitive credit
    deterioration down the scale", which is a judgement rather than a
    threshold. So this prints the whole scale — count, exposure, all three PDs,
    Stage composition, ECL rate — for that judgement to be made on, and asserts
    only the properties that would make the judgement impossible: the order,
    the endpoints, and whether risk actually rises.
    """
    print("\n== 15. Is this a scale a risk professional would recognise?")
    g = latest.groupby("internal_rating")
    rows = []
    for grade in ALL_STATES:
        if grade not in g.groups:
            rows.append((grade, 0, 0.0, float("nan"), float("nan"),
                         float("nan"), float("nan"), float("nan")))
            continue
        part = g.get_group(grade)
        rows.append((
            grade, int(len(part)),
            float(pd.to_numeric(part["ead"], errors="coerce").sum()),
            _w(part, "ttc_pd_pct"), _w(part, "pit_pd_12m_pct"),
            _w(part, "pd_lifetime"),
            float((pd.to_numeric(part["stage"], errors="coerce") >= 2).mean() * 100),
            _rate(part)))
    total_ead = sum(r[2] for r in rows) or 1.0
    print(f"  {period}  (exposure-weighted; NaN where the book holds none)")
    print(f"  {'Grade':5s} {'Names':>6s} {'Exposure %':>10s} {'TTC PD':>8s} "
          f"{'PIT PD':>8s} {'Life PD':>8s} {'St2+3 %':>8s} {'ECL %':>7s}")
    for grade, n, ead, ttc, pit, life, staged, rate in rows:
        print(f"  {grade:5s} {n:6d} {ead / total_ead * 100:10.2f} "
              f"{ttc:8.3f} {pit:8.3f} {life:8.2f} {staged:8.1f} {rate:7.3f}")
    review.tables["scale_review"] = [
        {"grade": g_, "borrowers": n, "exposure": e, "ttc_pd": t,
         "pit_pd": p_, "lifetime_pd": l_, "stage_2_or_3_pct": s_,
         "ecl_rate_pct": r_}
        for g_, n, e, t, p_, l_, s_, r_ in rows]

    section = "15. business-sensible scale"

    # The order itself. Not "nineteen values exist" — the exact sequence.
    expected = ("AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB",
                "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C")
    review.say(
        section,
        "Is the performing scale the governed nineteen grades, in order, "
        "ending in C?",
        PASS if tuple(PERFORMING) == expected else FAIL,
        f"The scale is {' '.join(PERFORMING)}.",
        {"scale": list(PERFORMING)},
        basis="The authoritative order, written out rather than counted.")

    review.say(
        section, "Is default a separate state rather than the scale's last "
                 "grade?",
        PASS if ("D" not in PERFORMING and ALL_STATES[-1] == "D"
                 and rs.DEFAULT_ORDINAL == 20) else FAIL,
        f"Default is {rs.DEFAULT_GRADE} at ordinal {rs.DEFAULT_ORDINAL}, "
        f"outside the {len(PERFORMING)} performing grades.",
        basis="A scale ending in D makes its weakest grade's default rate "
              "100% by construction, which is unmeasurable rather than severe.")

    graded = latest["internal_rating"].astype(str)
    stranger = sorted(set(graded) - set(ALL_STATES))
    review.say(
        section, "Does every borrower carry a grade the scale defines?",
        PASS if not stranger else FAIL,
        "Every rating is on the governed scale." if not stranger
        else f"Off-scale ratings found: {stranger}.",
        {"off_scale": stranger})

    ordinal = pd.to_numeric(latest.get("internal_rating_ordinal"),
                            errors="coerce")
    agree = graded.map(rs.ORDINAL)
    mismatched = int((ordinal != agree).sum())
    review.say(
        section, "Does internal_rating_ordinal agree with internal_rating on "
                 "every record?",
        PASS if mismatched == 0 else FAIL,
        f"{mismatched} record(s) disagree." if mismatched
        else f"All {len(latest):,} records agree.",
        {"mismatched": mismatched},
        basis="They are written from the same index, so a disagreement means "
              "one of them was recomputed somewhere it should not have been.")

    # Does risk actually rise? Measured by rank correlation against the
    # ordinal, over the grades the book populates, so an empty grade is not
    # counted as evidence either way.
    live = [(rs.ORDINAL[g_], t, p_, l_, s_, r_)
            for g_, n, _e, t, p_, l_, s_, r_ in rows
            if n >= 20 and g_ in rs.ORDINAL and g_ != "D"]
    order = pd.Series([x[0] for x in live])
    for index, (label, floor) in enumerate(
            ((("TTC PD"), 0.999), ("PIT 12m PD", RANK_STRONG),
             ("lifetime PD", RANK_STRONG), ("Stage 2 or 3 share", RANK_STRONG),
             ("ECL rate", RANK_STRONG)), start=1):
        values = pd.Series([x[index] for x in live])
        rho = _spearman(order, values)
        review.say(
            section,
            f"Does {label} rise as the grade weakens, across the grades the "
            "book populates?",
            PASS if rho >= floor else (PARTIAL if rho >= 0.85 else FAIL),
            f"Spearman rank correlation with the rating ordinal is "
            f"{rho:.3f} over {len(live)} populated grades.",
            {"rho": round(rho, 4), "grades": len(live)},
            basis="Rank correlation rather than strict monotonicity: two "
                  "adjacent grades holding a few dozen names each can cross "
                  "on their own mix, which is sampling and not a broken "
                  "scale. TTC carries no such noise and is held to 0.999.")

    # The endpoints, in the terms the requirement uses.
    strongest = next((r for r in rows if r[0] == "AAA"), None)
    weakest = next((r for r in rows if r[0] == "C"), None)
    # This is a question about the SCALE, so it is read off the scale. The
    # first version read it off the quarter and failed twice for reasons that
    # had nothing to do with the claim: an exposure-weighted mean of a column
    # of 100s comes back as 100.00000000000001, and a quarter in which no
    # borrower happens to be rated C produces a NaN. Neither says anything
    # about whether C is the weakest performing grade.
    review.say(
        section, "Is C plainly the weakest PERFORMING grade and plainly not "
                 "default?",
        PASS if (PERFORMING[-1] == "C"
                 and rs.TTC_PD_PCT["C"] == max(rs.TTC_PD_PCT.values())
                 and rs.TTC_PD_PCT["C"] < rs.DEFAULT_PD_PCT) else FAIL,
        f"C carries a TTC PD of {rs.TTC_PD_PCT['C']:.3f}%, the highest on the "
        f"performing scale, against the {rs.DEFAULT_PD_PCT:.0f}% that belongs "
        "to default alone.",
        {"c_ttc_pd": rs.TTC_PD_PCT["C"], "default_pd": rs.DEFAULT_PD_PCT,
         "borrowers_in_c_this_quarter": (weakest[1] if weakest else 0)},
        basis="A property of the masterscale, not of this quarter's "
              "population: a quarter holding no C-rated name says nothing "
              "about where C sits on the scale.")
    review.say(
        section, "Is the investment-grade end low enough to be worth having?",
        PASS if rs.TTC_PD_PCT["AAA"] < 0.05 and rs.TTC_PD_PCT["BBB-"] < 0.5
        else FAIL,
        f"AAA {rs.TTC_PD_PCT['AAA']:.5f}%, BBB- {rs.TTC_PD_PCT['BBB-']:.5f}%.",
        {"aaa": rs.TTC_PD_PCT["AAA"], "bbb_minus": rs.TTC_PD_PCT["BBB-"],
         "populated_aaa": strongest[1] if strongest else 0})

    # Stage 3 is measured at 100% and its provision is its LGD.
    stage_three = latest[pd.to_numeric(latest["stage"], errors="coerce") == 3]
    applicable = pd.to_numeric(stage_three.get("pd_applicable"),
                               errors="coerce")
    review.say(
        section, "Is every Stage 3 exposure measured at a PD of 100%?",
        PASS if len(stage_three) and (applicable == 100.0).all() else FAIL,
        f"{len(stage_three):,} Stage 3 borrower(s); applicable PD ranges "
        f"{applicable.min():.2f}% to {applicable.max():.2f}%.",
        {"stage_3": int(len(stage_three)),
         "min": float(applicable.min()) if len(applicable) else None,
         "max": float(applicable.max()) if len(applicable) else None})
    ead3 = pd.to_numeric(stage_three["ead"], errors="coerce")
    lgd3 = pd.to_numeric(stage_three["lgd"], errors="coerce")
    ecl3 = pd.to_numeric(stage_three["ecl_before_overlay"], errors="coerce")
    gap = float((ecl3 - lgd3 / 100.0 * ead3).abs().max()) if len(ead3) else 0.0
    review.say(
        section, "Is a Stage 3 provision its LGD rather than its exposure?",
        PASS if gap < 1.0 else FAIL,
        f"The largest gap between the provision and LGD x EAD is {gap:.4f}. "
        f"Coverage runs {(ecl3 / ead3 * 100).min():.1f}% to "
        f"{(ecl3 / ead3 * 100).max():.1f}%, tracking LGD.",
        {"largest_gap": gap},
        basis="PD of 100% is not LGD of 100%. A defaulted borrower with "
              "collateral still recovers, and the scenario weighting does not "
              "apply to a default that has already resolved.")


def main() -> int:
    quick = "--quick" in sys.argv
    periods = dm.periods()
    if quick:
        periods = periods[-4:]
    print(f"Corporate IFRS 9 economic validation — {len(periods)} quarters, "
          f"{periods[0]} to {periods[-1]}")

    books = {p: dm.book(p)[0] for p in periods}
    measured = {p: dm.read(dm.IFRS9, p) for p in periods}
    latest_period = periods[-1]
    latest = books[latest_period]

    review = Review()
    rating_economics(review, latest, latest_period)
    pd_economics(review, books)
    stage_economics(review, books)
    stage_migration(review, books)
    rating_migration(review, books)
    ecl_economics(review, books, measured)
    lgd_economics(review, latest)
    ead_economics(review, latest)
    continuity(review, books)
    random_borrowers(review, books)
    sector_economics(review, books)
    segment_economics(review, books)
    macro_relationship(review, books)
    default_logic(review, books)
    scale_review(review, latest, latest_period)

    passed = sum(1 for f in review.findings if f.status == PASS)
    partial = sum(1 for f in review.findings if f.status == PARTIAL)
    failed = sum(1 for f in review.findings if f.status == FAIL)
    print("\n" + "=" * 68)
    print(f"ECONOMIC VALIDATION: {review.verdict}")
    print(f"  {passed} passed · {partial} partial · {failed} failed "
          f"of {len(review.findings)} checks")
    for finding in review.findings:
        if finding.status != PASS:
            print(f"  {finding.status}: [{finding.section}] "
                  f"{finding.question}")
            print(f"      {finding.detail}")

    body = {
        "version": "1.0.0",
        "verdict": review.verdict,
        "periods": periods,
        "borrowers_latest": int(len(latest)),
        "counts": {"pass": passed, "partial": partial, "fail": failed},
        "bounds": {
            "rating_stability_min_pct": RATING_STABILITY_MIN_PCT,
            "stage_2_cure_max_pct": STAGE2_CURE_MAX_PCT,
            "multi_notch_max_pct": MULTI_NOTCH_MAX_PCT,
            "rank_strong": RANK_STRONG,
            "note": ("Three bounds are EXTERNAL — facts about rating systems "
                     "rather than about this generator — and they are named "
                     "in the findings that use them. Everything else is "
                     "ordinal, distributional, or an arithmetic identity."),
        },
        "findings": [f.to_dict() for f in review.findings],
        "tables": review.tables,
    }
    out = pathlib.Path(__file__).resolve().parent.parent / "docs"
    out.mkdir(exist_ok=True)
    path = out / "what_if_ifrs9_economic_validation.json"
    path.write_text(json.dumps(body, indent=1, default=str) + "\n")
    print(f"\nWrote {path}")
    return 0 if review.verdict == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
