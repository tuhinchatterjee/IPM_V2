"""
High-precision standard-normal CDF and inverse CDF.

This is the one numerical-parity risk point between the workbook and the engine:
every stressed PD is NORMSDIST(NORMSINV(PD_0) + shift), so any drift in the
inverse normal propagates into all 280 cells. Both functions here are accurate to
roughly machine epsilon, which is tighter than Excel's own NORMSINV/NORMSDIST, so
agreement is limited only by Excel's precision (~1e-15 relative).

  norm_ppf  Wichura (1988) AS241 PPND16 — the same rational-approximation family
            Excel uses, with full double precision over the whole (0, 1) range.
  norm_cdf  0.5 * erfc(-x / sqrt(2)) via the C library's erfc, which is correct
            to <1 ulp and does not lose precision in the far left tail.
"""

import math

__all__ = ["norm_cdf", "norm_ppf"]

# --- AS241 PPND16 coefficients (Wichura 1988, Applied Statistics 37(3), 477-484)

_A = (3.3871328727963666080e0, 1.3314166789178437745e2, 1.9715909503065514427e3,
      1.3731693765509461125e4, 4.5921953931549871457e4, 6.7265770927008700853e4,
      3.3430575583588128105e4, 2.5090809287301226727e3)
_B = (1.0, 4.2313330701600911252e1, 6.8718700749205790830e2, 5.3941960214247511077e3,
      2.1213794301586595867e4, 3.9307895800092710610e4, 2.8729085735721942674e4,
      5.2264952788528545610e3)
_C = (1.42343711074968357734e0, 4.63033784615654529590e0, 5.76949722146069140550e0,
      3.64784832476320460504e0, 1.27045825245236838258e0, 2.41780725177450611770e-1,
      2.27238449892691845833e-2, 7.74545014278341407640e-4)
_D = (1.0, 2.05319162663775882187e0, 1.67638483018380384940e0, 6.89767334985100004550e-1,
      1.48103976427480074590e-1, 1.51986665636164571966e-2, 5.47593808499534494600e-4,
      1.05075007164441684324e-9)
_E = (6.65790464350110377720e0, 5.46378491116411436990e0, 1.78482653991729133580e0,
      2.96560571828504891230e-1, 2.65321895265761230930e-2, 1.24266094738807843860e-3,
      2.71155556874348757815e-5, 2.01033439929228813265e-7)
_F = (1.0, 5.99832206555887937690e-1, 1.36929880922735805310e-1, 1.48753612908506148525e-2,
      7.86869131145613259100e-4, 1.84631831751005468180e-5, 1.42151175831644588870e-7,
      2.04426310338993978564e-15)

_SPLIT1 = 0.425
_SPLIT2 = 5.0
_CONST1 = 0.180625
_CONST2 = 1.6


def _poly(coeffs, x):
    """Horner evaluation. AS241 publishes its coefficients in ASCENDING order
    (constant term first), so Horner runs from the end of the array."""
    total = coeffs[-1]
    for c in reversed(coeffs[:-1]):
        total = total * x + c
    return total


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Excel NORMSINV / NORM.S.INV).

    Raises ValueError outside (0, 1): a PD of exactly 0 or 1 has no finite probit
    and silently returning +-inf would poison an entire grid row.
    """
    p = float(p)
    if not (0.0 < p < 1.0):
        raise ValueError(f"norm_ppf requires 0 < p < 1, got {p!r}")

    q = p - 0.5
    if abs(q) <= _SPLIT1:
        r = _CONST1 - q * q
        return q * _poly(_A, r) / _poly(_B, r)

    r = p if q < 0.0 else 1.0 - p
    r = math.sqrt(-math.log(r))
    if r <= _SPLIT2:
        r -= _CONST2
        value = _poly(_C, r) / _poly(_D, r)
    else:
        r -= _SPLIT2
        value = _poly(_E, r) / _poly(_F, r)
    return -value if q < 0.0 else value


def norm_cdf(x: float) -> float:
    """Standard-normal CDF (Excel NORMSDIST / NORM.S.DIST(x, TRUE))."""
    return 0.5 * math.erfc(-float(x) / math.sqrt(2.0))
