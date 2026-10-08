"""
Per-KPI significance thresholds.

Calibrated against the measured null-draw noise floor: the observed total
change for each KPI between month_1_baseline and month_5_baseline_null -- the
only pair of months in this dataset where NOTHING was injected relative to
each other, so any observed movement there is pure sampling noise.

Measured null-draw noise (month_1 vs. month_5, ~30k tickets/month):
    AHT            -0.12%  (relative change in blended AHT)
    TPH            +0.89%  (relative change in blended TPH)
    CSAT_1STAR     -0.71 percentage points (absolute)
    CSAT_5STAR     +0.86 percentage points (absolute)
    TOTAL_SOLVES   +0.15%  (relative change in total resolved tickets)

Thresholds below are set at roughly 3-13x that noise floor -- comfortably
clear of a single noisy sample, while still well below the real injected
signal magnitudes observed in months 2-4 (see docs/step3_summary.md for the
full comparison table). CSAT uses an ABSOLUTE percentage-point threshold
rather than a relative-% one: CSAT_1STAR's baseline is only ~9%, so a
relative-% threshold would be wildly unstable for a metric that small (this
exact instability was already documented in Step 2's validation).

KNOWN LIMITATION: these are calibrated against a SINGLE null-draw sample (n=1).
That's a thin basis for a margin -- it's the best available with 2 "nothing
happened" months. Once more null-ish months of history exist, replace this
fixed-threshold approach with a real statistical control chart (e.g. a
rolling mean/stdev z-score), per the original project roadmap. The structure
below (one threshold record per KPI, with an explicit `metric` type) is meant
to make that swap easy without touching detector.py's call sites.
"""
from __future__ import annotations

from dataclasses import dataclass

# "pct_change": compare abs(total_change_pct) against `value` (threshold in %).
# "pp_change":  compare abs(total_change_abs * 100) against `value` (threshold in
#               percentage points) -- for proportion-type KPIs (CSAT%).
MetricType = str  # "pct_change" | "pp_change"


@dataclass(frozen=True)
class Threshold:
    metric: MetricType
    value: float          # threshold magnitude, in the units implied by `metric`
    null_noise: float     # the measured null-draw noise, same units, for reference/logging
    rationale: str


THRESHOLDS: dict[str, Threshold] = {
    "AHT": Threshold(
        metric="pct_change",
        value=1.5,
        null_noise=0.12,
        rationale="~13x the measured null-draw noise (0.12%); comfortably below the "
        "smallest real injected AHT signal observed (month_3's +3.0%).",
    ),
    "TPH": Threshold(
        metric="pct_change",
        value=4.5,
        null_noise=0.89,
        rationale="~5x the measured null-draw noise (0.89%); separates month_3's "
        "near-zero TPH movement (+0.3%, itself close to noise) from month_2/4's "
        "real ~6-7% moves.",
    ),
    "CSAT_1STAR": Threshold(
        metric="pp_change",
        value=2.0,
        null_noise=0.71,
        rationale="~3x the measured null-draw noise (0.71pp). Note: every scenario's "
        "BLENDED 1-star CSAT movement (0.08-0.58pp) stays under this threshold -- the "
        "per-queue CSAT shifts injected in Step 1 are real but too diluted by queue "
        "weight to surface as a company-wide anomaly. That's a correct, expected "
        "non-detection, not a detector shortcoming -- see docs/step3_summary.md.",
    ),
    "CSAT_5STAR": Threshold(
        metric="pp_change",
        value=2.0,
        null_noise=0.86,
        rationale="~2.3x the measured null-draw noise (0.86pp); same rationale as "
        "CSAT_1STAR.",
    ),
    "TOTAL_SOLVES": Threshold(
        metric="pct_change",
        value=1.5,
        null_noise=0.15,
        rationale="~10x the measured null-draw noise (0.15%); comfortably below the "
        "smallest real injected growth signal observed (month_3's +2.7%).",
    ),
}
