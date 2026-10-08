# Step 3 — Anomaly Detection Layer: Summary

Status: **Validation passed.** Safe to proceed to Step 4 (LLM agent orchestration).

## What was built

```
generator/scenarios.py     + a 5th scenario: month_5_baseline_null -- a second control
                           month (same physics as month_1, fresh random draw, zero
                           injected effect). Exists purely so Step 3 has one clean
                           "nothing happened" comparison to measure noise against.
engine/data.py              + CANONICAL_MONTH_ORDER and two small helpers
                           (months_before, immediately_preceding_month) so anomaly
                           detection can auto-derive comparisons without hardcoding
                           month-specific logic.
anomaly/
  thresholds.py             Per-KPI significance thresholds, calibrated against the
                           measured null-draw noise floor (month_1 vs. month_5).
  detector.py                 Core detection logic: wraps Step 2's engine output,
                           classifies each KPI as anomalous or not, both comparison
                           types merged ("flagged" if either crosses threshold).
  run_detection.py              CLI: auto mode (--month, derives comparisons from the
                           canonical sequence) or explicit mode (--baseline/--current/
                           --comparison-type, same shape as engine.run_decomposition).
validate_detector.py        3-tier validation: stability check, false-positive check,
                           informational auto-mode demo.
```

Run it:
```
python -m generator.generate              # regenerates all 5 months, incl. the new null month
python -m anomaly.run_detection --month month_4_scenario_mixed
python -m anomaly.run_detection --baseline month_1_baseline --current month_5_baseline_null \
    --comparison-type prior_month
python validate_detector.py               # the hard gate
```

Regenerating months 1-4 after adding month 5 produced byte-identical files (confirmed via
`git diff --stat` showing zero changes to existing CSVs/JSONs) — the generator's per-month
seeding (`world.random_seed + month_index`) is exactly as deterministic as intended.

## Why a 5th month was needed

Steps 1-2 only ever compared a scenario month against month_1. That's fine for validating
the decomposition math (there's a known injected answer to check against), but it's useless
for testing an anomaly detector's **false-positive rate** — every available month pair has
*something* injected between them. `month_5_baseline_null` fixes that: it's built from the
exact same config as month_1, with no mix-shift, no genuine change, no overall growth, just
a different random seed. Month_1 vs. month_5 isolates pure sampling noise with zero
confounding signal — the one legitimate "nothing happened" test in this dataset.

## Threshold design

Per-KPI, not uniform — because Step 2 already showed these KPIs have very different natural
volatility (CSAT% proportions are much noisier than AHT). Measured null-draw noise (month_1
vs. month_5, nothing injected):

| KPI | Null-draw noise | Threshold | Margin |
|---|---|---|---|
| AHT | 0.12% (relative) | 1.5% | ~13x |
| TPH | 0.89% (relative) | 4.5% | ~5x |
| CSAT 1★ | 0.71 pp (absolute) | 2.0 pp | ~3x |
| CSAT 5★ | 0.86 pp (absolute) | 2.0 pp | ~2.3x |
| Total Solves | 0.15% (relative) | 1.5% | ~10x |

CSAT uses an **absolute percentage-point** threshold rather than relative-%, deliberately:
CSAT 1★'s baseline is only ~9%, so a relative-% threshold is unstable for a metric that
small — this is the exact ratio-instability problem Step 2's validation already surfaced.

**Known limitation, stated plainly:** every margin above is calibrated against a single
noise draw (n=1 — we only have 2 "nothing happened" months). That's a thin statistical
basis, but it's what's available with 5 total months. The code is structured (one
`Threshold` record per KPI, with an explicit `metric` type) so this fixed-threshold approach
can be swapped for a real rolling-mean/stdev control chart once more null-ish months exist,
without touching `detector.py`'s call sites — exactly the "threshold-based to start, could
later be statistical" framing from the original roadmap.

## Validation results

**Tier 1 — stability check** (15/15 passed): for each scenario (month 2/3/4) vs. month_1,
compares the detector's real-data verdict against the verdict you'd get applying the exact
same threshold to ground_truth.json's clean, noise-free analytical value. All 15 (3
scenarios × 5 KPIs) agree. This validates something more useful than "did it flag the
injected effect" — it validates that **sampling noise never flips the significance call**.

A real and interesting result buried in there: **CSAT 1★/5★ are correctly never flagged, in
any scenario.** Every scenario's blended CSAT movement (0.08–0.65 pp) stays below the
2pp threshold — even month_3, which deliberately injected a real per-queue CSAT shift. The
per-queue effect is genuine, but Technical/App Support is only ~6.8% of total ticket volume,
so it dilutes to a sub-noise-floor blip at the company-wide level. **That's a correct
non-detection, not a detector miss** — it's exactly the kind of judgment call a real
anomaly detector needs to make (a real problem in one small queue isn't automatically a
company-wide anomaly), and it's good material for Step 4's exec-summary layer to eventually
articulate ("CSAT dipped in Technical Support specifically, but didn't move company-wide").

**A magnitude mismatch worth flagging explicitly (verdict still correct, numbers aren't
close):** TPH's analytical-vs-recovered values disagree substantially in places — e.g.
month_2: analytical −15.6% vs. recovered −6.8%; month_3: analytical −2.8% vs. recovered
**+0.3%** (opposite sign). Both land on the same anomaly/normal verdict in every case purely
because neither gets close to the 4.5% boundary, but the magnitudes themselves don't agree.
This is the **same root cause Step 2 already documented**: Step 1's analytical TPH ground
truth is a continuous idealization that ignores the discrete `ceiling()`-based agent
headcount rounding the actual staffing simulation uses, and that rounding overhead shrinks
as realized ticket volume grows — exactly what every scenario's growth injection does. Not a
new bug; a known, carried-forward limitation of the *ground truth*, not of this detector.

**Tier 2 — false-positive check** (5/5 passed): month_1 vs. month_5 flags nothing across all
5 KPIs. Caveat stated plainly in the script's own output: thresholds were calibrated against
this exact noise sample, so this specific check confirms correct wiring more than it proves
an independently-validated false-positive rate. Worth adding a 6th "null" month later for a
truly independent check.

**Tier 3 — informational auto-mode demo:** ran every month against its auto-derived
prior/pooled comparisons. The interesting case: **month_5 gets flagged anomalous on AHT,
TPH, and Total Solves** — not because anything new was injected in month_5, but because its
auto-derived "prior month" is month_4, which was itself elevated. Month_5 vs. month_4 shows
AHT dropping 11.7% and TPH rising 7.3% — a real, large **reversion** back to baseline levels.
This is a correct true positive on an arbitrary month-pair the detector was never
specifically tuned for, confirming the thresholds generalize beyond the exact scenarios they
were validated against.

## Known limitations / carried forward to Step 4

- Thresholds are a single-sample calibration (see above) — fine for this project's scope,
  worth tightening with more null months or a real control-chart method before trusting
  threshold breaches as an unsupervised automation trigger.
- TPH's ground-truth magnitude gap (not the detector's fault) means any future
  precision-sensitive use of TPH's *size* (not just its anomaly/normal call) should account
  for the discrete-staffing-rounding effect documented in Step 2 and reproduced here.
- The false-positive check has the circularity caveat above. A 6th month with a different
  random seed and zero injected effect would make Tier 2 fully independent.
- Every flagged anomaly already carries its full Step 2 decomposition (queue-level
  mix/genuine breakdown) attached in the `decomposition` field of each check record — Step 4
  shouldn't need to re-run the engine, just read what's already attached.
