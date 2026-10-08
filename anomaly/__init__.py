"""
Step 3 — Anomaly detection layer.

Given a target month's ticket data, decide which (if any) of the 5 KPIs moved
"significantly" vs. a prior period, using the Step 2 decomposition engine's
output as the source of per-KPI change magnitudes. Thresholds are fixed,
per-KPI percentages/percentage-points calibrated against the measured null-draw
noise floor (month_1 vs. month_5 -- the one pair of months in this dataset with
zero injected effect between them). See docs/step3_summary.md for the full
derivation and known limitations (a single noise draw is a thin calibration
sample; this is deliberately built to be swapped for a real statistical
control-chart method once more months of history exist).
"""
