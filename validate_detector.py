"""
Step 3 validation — hard gate before Step 4.

Two tiers, mirroring the Step 2 validation structure:

1. HARD GATE — stability check: for each scenario (month_2/3/4), compare the
   detector's real-data verdict (month_1 vs. scenario, prior_month) against
   the verdict you'd get by applying the EXACT SAME threshold to the clean,
   noise-free ANALYTICAL value in ground_truth.json. This validates that
   sampling noise doesn't flip the significance call relative to what the
   data was actually designed to show -- not "does the detector flag
   everything injected" (several injected effects are real but too small at
   the blended level to be a company-wide anomaly, which is a correct
   non-detection, not a miss).

2. HARD GATE — false-positive check: month_1 vs. month_5_baseline_null (the
   one pair of months with zero injected effect between them) must produce
   ZERO flagged KPIs. CAVEAT, documented rather than hidden: thresholds were
   calibrated using this exact noise sample, so this specific check is
   partially circular -- it confirms the detector's calibration was wired up
   correctly, not that the chosen margin would hold against independent
   noise. A fully independent false-positive rate would need additional
   null-draw months (see docs/step3_summary.md).

3. INFORMATIONAL — auto mode demo: run detect_for_month() (prior_month +
   pooled_baseline, auto-derived from the canonical sequence) for every
   month that has a predecessor, printed for inspection. Not graded against
   anything -- there's no ground truth for "vs the immediately preceding
   month" except where that preceding month happens to be month_1.

Exits non-zero iff any HARD GATE check fails.
"""
from __future__ import annotations

import json
import pathlib
import sys

from anomaly.detector import ALL_KPIS, detect_for_comparison, detect_for_month
from anomaly.thresholds import THRESHOLDS
from engine.data import CANONICAL_MONTH_ORDER, load_month
from generator.config_loader import load_world_config

GROUND_TRUTH_DIR = pathlib.Path(__file__).resolve().parent / "ground_truth"
BASELINE_MONTH = "month_1_baseline"
SCENARIOS = ["month_2_scenario_mixshift", "month_3_scenario_genuine", "month_4_scenario_mixed"]
NULL_PAIR = ("month_1_baseline", "month_5_baseline_null")

GT_KEY_FOR_KPI = {
    "AHT": "AHT_seconds",
    "TPH": "TPH_tickets_per_agent_hour",
    "CSAT_1STAR": "csat_1star_pct",
    "CSAT_5STAR": "csat_5star_pct",
}


def load_ground_truth(month_key: str) -> dict:
    with open(GROUND_TRUTH_DIR / f"{month_key}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def analytical_observed_value(kpi: str, gt: dict) -> float:
    """The clean, noise-free observed value for `kpi`, in the same units the
    corresponding threshold expects (pct_change -> %, pp_change -> percentage
    points), computed directly from ground_truth.json's analytical blocks.
    """
    if kpi == "TOTAL_SOLVES":
        return gt["expected_decomposition"]["total_solves_volume_bridge"]["overall_growth_rate"] * 100.0
    block = gt["expected_decomposition"][GT_KEY_FOR_KPI[kpi]]
    threshold = THRESHOLDS[kpi]
    if threshold.metric == "pct_change":
        return block["total_delta"] / block["old_blended"] * 100.0
    elif threshold.metric == "pp_change":
        return block["total_delta"] * 100.0
    raise ValueError(f"Unknown metric type for {kpi}")


def hard_gate_stability_check(world) -> tuple[list[str], list[str]]:
    passes, failures = [], []
    df_baseline = load_month(BASELINE_MONTH)

    for scenario in SCENARIOS:
        df_scenario = load_month(scenario)
        gt = load_ground_truth(scenario)
        checks = detect_for_comparison(df_baseline, df_scenario, world, BASELINE_MONTH, scenario, "prior_month")

        for check in checks:
            kpi = check["kpi"]
            threshold = THRESHOLDS[kpi]
            analytical_value = analytical_observed_value(kpi, gt)
            analytical_verdict = abs(analytical_value) > threshold.value
            real_verdict = check["is_anomaly"]
            label = f"{scenario} | {kpi}"

            if real_verdict == analytical_verdict:
                verdict_str = "ANOMALY" if real_verdict else "normal"
                passes.append(
                    f"[PASS] {label}: analytical={analytical_value:+.2f} recovered={check['observed_value']:+.2f} "
                    f"(threshold {threshold.value}) -- both call it '{verdict_str}'"
                )
            else:
                failures.append(
                    f"[VERDICT FLIP] {label}: analytical={analytical_value:+.2f} (verdict={analytical_verdict}) "
                    f"vs recovered={check['observed_value']:+.2f} (verdict={real_verdict}), threshold={threshold.value}. "
                    f"Sampling noise moved this case across the threshold boundary."
                )
    return passes, failures


def hard_gate_false_positive_check(world) -> tuple[list[str], list[str]]:
    passes, failures = [], []
    base_key, null_key = NULL_PAIR
    df0, df1 = load_month(base_key), load_month(null_key)
    checks = detect_for_comparison(df0, df1, world, base_key, null_key, "prior_month")

    for check in checks:
        label = f"{base_key} vs {null_key} | {check['kpi']}"
        if not check["is_anomaly"]:
            passes.append(f"[PASS] {label}: observed={check['observed_value']:+.2f}, correctly NOT flagged")
        else:
            failures.append(
                f"[FALSE POSITIVE] {label}: observed={check['observed_value']:+.2f} crossed threshold "
                f"{check['threshold_value']} on a pair of months with ZERO injected effect between them."
            )
    return passes, failures


def informational_auto_mode_demo(world) -> list[str]:
    info = []
    for month_key in CANONICAL_MONTH_ORDER[1:]:  # skip month_1, it has no predecessor
        result = detect_for_month(month_key, world)
        anomalous = result["anomalous_kpis"]
        info.append(
            f"[INFO] {month_key}: comparisons_run={result['comparisons_run']} "
            f"anomalous_kpis={anomalous or 'none'}"
        )
    return info


def main():
    world = load_world_config()

    print("=" * 90)
    print("TIER 1 -- HARD GATE: stability check (real-data verdict vs. analytical verdict)")
    print("=" * 90)
    stab_passes, stab_failures = hard_gate_stability_check(world)
    for p in stab_passes:
        print(p)
    for f in stab_failures:
        print(f)

    print("\n" + "=" * 90)
    print("TIER 2 -- HARD GATE: false-positive check (month_1 vs. month_5_baseline_null)")
    print("=" * 90)
    print("NOTE: thresholds were calibrated against this exact noise sample -- this check")
    print("confirms correct wiring, not an independently-validated false-positive rate.")
    fp_passes, fp_failures = hard_gate_false_positive_check(world)
    for p in fp_passes:
        print(p)
    for f in fp_failures:
        print(f)

    print("\n" + "=" * 90)
    print("TIER 3 -- INFORMATIONAL: auto-mode demo (prior_month + pooled_baseline per month)")
    print("=" * 90)
    for i in informational_auto_mode_demo(world):
        print(i)

    all_failures = stab_failures + fp_failures

    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"Tier 1 (stability):       {len(stab_passes)} passed, {len(stab_failures)} failed")
    print(f"Tier 2 (false-positive):  {len(fp_passes)} passed, {len(fp_failures)} failed")

    if all_failures:
        print(f"\nVALIDATION FAILED: {len(all_failures)} issue(s). Do not proceed to Step 4.")
        for f in all_failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print(
            "\nVALIDATION PASSED: the detector's real-data verdicts match the clean analytical "
            "verdicts for every scenario x KPI, and it correctly stays silent on the pure-noise "
            "month_1-vs-month_5 comparison. Safe to proceed to Step 4."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
