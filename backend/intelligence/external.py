"""
External intelligence. §21, §31.

What people wrote down about a borrower, as opposed to what the borrower's
accounts did.

The whole value of this source is that it is early: a credit memo saying the
finance director left and debtor days have stretched can precede anything the
behavioural data shows by two quarters. The whole danger of it is that it is
somebody's opinion, written in prose, and prose reads as more certain than it
is.

So three things hold here.

**It is evidence, never a conclusion.** A memo with negative sentiment is
recorded as "a memo with negative sentiment exists", not as "this borrower is
deteriorating". The concerns the memo flagged are named individually - a
liquidity concern and a management change are different facts and lumping them
into a sentiment score loses both.

**Nothing is inferred from silence.** No memo means no memo. It does not mean
nothing is happening; relationship managers write memos when they have a
reason to, and a quiet file is at least as likely to be an unattended one.

**The text is quoted, never paraphrased.** A summary of somebody's judgement,
generated and shown next to their name, is a claim they did not make. Extracts
appear verbatim and are labelled as extracts.
"""

from __future__ import annotations

from typing import Any

from backend.intelligence import (
    CONCERN,
    EXTERNAL,
    SEVERE,
    WATCH,
    Finding,
    Missing,
    Reading,
    and_list,
    number,
    truthy,
)
from backend.intelligence import reader as rd

DATASET = "credit_memo_signals"

#: The concerns a memo can flag, and what each of them actually asserts. Read
#: individually rather than summed: the count of concerns is a worse signal
#: than which ones they are.
CONCERNS: tuple[tuple[str, str, str, str], ...] = (
    ("going_concern_mentioned", "Going concern raised",
     "Somebody has written down a doubt about the borrower continuing to "
     "trade. This is the most serious thing a memo can record and it is "
     "never inferred - it is present only when a memo says it.", SEVERE),
    ("covenant_breach_mentioned", "Covenant breach discussed",
     "A memo refers to a covenant breach. Whether the covenant dataset also "
     "records one is a separate question and worth asking: the two "
     "disagreeing is itself a finding.", CONCERN),
    ("liquidity_concern_mentioned", "Liquidity concern raised",
     "A memo refers to pressure on the borrower's ability to fund itself.",
     CONCERN),
    ("management_change_mentioned", "Management change noted",
     "A memo records a change in the borrower's senior management. Not "
     "adverse in itself, and frequently early.", WATCH),
    ("receivables_stretch_mentioned", "Receivables stretch noted",
     "A memo records debtors taking longer to pay. Often visible in the "
     "prose a quarter or two before it reaches the ratios.", CONCERN),
    ("sector_headwind_mentioned", "Sector headwind noted",
     "A memo attributes pressure to the borrower's sector rather than to "
     "the borrower. Worth separating: a sector problem and a borrower "
     "problem call for different responses.", WATCH),
)

#: Sentiments that are worth a finding on their own.
ADVERSE_SENTIMENT = frozenset({"negative", "very negative", "adverse"})


def read(customer_id: str, period: str = "") -> Reading:
    """What the file says about one borrower, in the file's own words."""
    frame = rd.load(DATASET)
    if frame is None:
        return Reading(domain=EXTERNAL, borrower_id=customer_id, period=period,
                       missing=[Missing(
                           "Credit memos",
                           "This deployment does not carry the credit memo "
                           "dataset, so nothing written about borrowers can "
                           "be read.")])

    chosen, prior = rd.resolve(frame, period)
    if not chosen:
        return Reading(domain=EXTERNAL, borrower_id=customer_id, period=period,
                       missing=[Missing(
                           "Credit memos",
                           f"{period or 'That period'} is not a reporting "
                           "date this dataset holds.")])

    rows = rd.rows_for(frame, customer_id, chosen, key="customer_id")
    if not rows:
        return Reading(domain=EXTERNAL, borrower_id=customer_id, period=chosen,
                       missing=[Missing(
                           "Credit memos",
                           f"No memo was written about {customer_id} in "
                           f"{chosen}. Nothing follows from that. Memos are "
                           "written when somebody has a reason to write one, "
                           "so a quiet file is as likely to be unattended as "
                           "untroubled.")])

    reading = Reading(domain=EXTERNAL, borrower_id=customer_id, period=chosen)
    reading.measured = _measured(rows, prior)

    for field_name, label, means, severity in CONCERNS:
        flagged = [r for r in rows if truthy(r.get(field_name))]
        if not flagged:
            continue
        reading.findings.append(Finding(
            key=field_name,
            label=label + (f" in {len(flagged)} memos" if len(flagged) > 1
                           else ""),
            means=means, severity=severity, value=len(flagged), threshold=1,
            test="mentioned in at least one memo this period",
            dataset=DATASET, field_name=field_name, period=chosen))

    adverse = [r for r in rows
               if str(r.get("sentiment") or "").lower() in ADVERSE_SENTIMENT]
    if adverse:
        authors = and_list(sorted({str(r.get("author_role") or "")
                                   for r in adverse} - {""}))
        reading.findings.append(Finding(
            key="adverse_sentiment",
            label=f"{len(adverse)} memo{'s' if len(adverse) > 1 else ''} "
                  "written in adverse terms",
            means=(f"Recorded by {authors or 'the credit file'}. This is a "
                   "statement that somebody wrote in these terms, not a "
                   "measurement of the borrower."),
            severity=CONCERN, value=len(adverse), threshold=1,
            test="sentiment is adverse", dataset=DATASET,
            field_name="sentiment", period=chosen))

    return reading


def extracts(customer_id: str, period: str = "",
             limit: int = 5) -> list[dict[str, Any]]:
    """The memo text itself, verbatim.

    Kept out of `read` and out of ``Finding`` because a finding is a claim
    this product makes and an extract is a claim somebody else made. Mixing
    them is how a paraphrase ends up attributed to a named author.
    """
    frame = rd.load(DATASET)
    chosen, _ = rd.resolve(frame, period)
    rows = rd.rows_for(frame, customer_id, chosen, key="customer_id")
    return [
        {
            "memo_id": str(row.get("memo_id") or ""),
            "period": chosen,
            "memo_type": str(row.get("memo_type") or ""),
            "author_role": str(row.get("author_role") or ""),
            "sentiment": str(row.get("sentiment") or ""),
            "recommendation": str(row.get("recommendation") or ""),
            "extract": str(row.get("extract") or ""),
            "quoted_verbatim": True,
            "synthetic_text": truthy(row.get("is_synthetic_text")),
        }
        for row in sorted(rows, key=lambda r: str(r.get("memo_id") or ""))
        [:max(1, min(int(limit), 50))]
    ]


def _measured(rows: list[dict[str, Any]], prior: str) -> dict[str, Any]:
    strengths = [s for s in (number(r.get("signal_strength_pct"))
                             for r in rows) if s is not None]
    return {
        "memos": len(rows),
        "memo_types": sorted({str(r.get("memo_type") or "") for r in rows}
                             - {""}),
        "authors": sorted({str(r.get("author_role") or "") for r in rows}
                          - {""}),
        "sentiments": sorted({str(r.get("sentiment") or "") for r in rows}
                             - {""}),
        "recommendations": sorted({str(r.get("recommendation") or "")
                                   for r in rows} - {""}),
        "concerns_raised": sum(int(number(r.get("concerns_raised")) or 0)
                               for r in rows),
        "strongest_signal_pct": max(strengths) if strengths else None,
        "prior_period": prior,
        "means": {
            "memos": "How many memos were written this period. Zero means no "
                     "memo, and nothing more than that.",
            "concerns_raised": "A count of flags across memos. Which concerns "
                               "they are matters more than how many.",
        },
    }


__all__ = ["ADVERSE_SENTIMENT", "CONCERNS", "DATASET", "extracts", "read"]
