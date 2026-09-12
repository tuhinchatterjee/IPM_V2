# V4 display precision policy

The rule in one line: **CreditProbe computes the canonical value, CreditProbe
chooses how many decimals a reader sees, and the analyst may send either the
canonical value or that value correctly rounded — nothing else.**

## Why the policy exists

A live run computed exposure at default by sector correctly and had its
answer refused:

```
asserted   40599.17
canonical  40599.1736630513815
```

`40,599.17` is how a credit officer writes that number. What refused it was a
relative tolerance of 1e-9, introduced with a comment claiming it absorbed a
rounded display value. It does not: rounding five significant digits to two
places moves the figure by **9.02e-8** relative, ninety times that bound.

Widening the tolerance would have been the wrong fix. At 1e-6, a figure wrong
by more than SAR 0.04 million passes on this book, and at 1e-4 one wrong by
SAR 4 million does. Presentation would have been bought with arithmetic.

## Canonical vs display

| | |
| --- | --- |
| **Canonical** | Full precision, computed by CreditProbe from executed evidence. Stored, recomputed against, never rounded away. |
| **Display** | The canonical value quantized to a permitted precision, `ROUND_HALF_UP`. What a reader sees. |

Validation:

```
expected_display = quantize(canonical, allowed_precision)
asserted ∈ { canonical, expected_display }
```

A third number that merely *rounds* to the right answer — `40599.1699` at 2dp
— is refused. Rounding to something correct is not being it.

The published figure is rendered from the canonical verdict, not from the
analyst's string, so what reaches the reader is CreditProbe's rounding of
CreditProbe's arithmetic.

## Precision by unit

Read from the **unit**, never from a claim's name: `total_ead` and
`ead_share` differ by unit, not by spelling.

| Unit class | Permitted | Default | Example |
| --- | --- | --- | --- |
| Money (`SAR million`) | 0, 1, 2, 3 | 2 | `SAR 40,599.17 million` |
| Percent | 0, 1, 2, 3 | 2 | `25.25%` |
| Percentage point | 0, 1, 2, 3 | 2 | `1.31 percentage points` |
| Ratio | 2, 3, 4 | 2 | `0.5714` |
| Count | 0 | 0 | `59` |
| Categorical | 0 | — | Stage 2, BBB+ |

A claim declaring a precision outside its class is refused and told which are
allowed. The first thing this caught was real: a covenant-breach count
declaring two decimal places, which the old validator had no opinion about.

## Currency and scale

The V4 demonstration book is a **Saudi** corporate portfolio.

- Reporting currency: **SAR**
- Canonical amount scale: **million**
- Canonical evidence stays in SAR million. An executive display may scale a
  large total to `SAR 12.5bn`, but the evidence underneath does not move.

Scale is read, never assumed. `SAR million` and `SAR bn` are the same currency
at a thousandfold difference, and the pair is checked together — a rounding
fix must never admit a 1,000× monetary error or a 100× percentage one.
`percent`, `percentage point` and `ratio` are three units, not one.

## Zero and notation

No user-facing value is ever in scientific notation. `0E+12` displays as
`0.00`. Negative zero is normalised: a movement of `-0.001` reads as
`SAR 0.00 million`, never `SAR -0.00 million`, which would read as a loss too
small to name rather than as nothing.

## Tables and charts

A table names an artifact and columns and is served the stored rows, so it
cannot misreport a number; its columns are checked against the artifact. A
chart's columns are checked the same way, and where an answer claims a
ranking and publishes a chart, the charted measure must actually be ordered.

Table, chart and narrative reconcile because all three are formatted from the
same canonical values at the same declared precision.
