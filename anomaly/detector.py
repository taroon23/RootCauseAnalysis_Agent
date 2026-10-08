"""
Core anomaly detection logic.

Reuses Step 2's decomposition engine as-is (no new KPI math here) -- this
module's only job is to take the engine's output and decide, per KPI, whether
the observed change crosses that KPI's significance threshold. Because the
full decomposition result is attached to every anomaly record, a flagged
anomaly already carries its queue-level mix/genuine breakdown -- ready for
Step 4's agent orchestration to reason over without re-running anything.
"""
from __future__ import annotations

import pandas as pd

from anomaly.thresholds import THRESHOLDS, Threshold
from engine.data import immediately_preceding_month, load_month, months_before
from engine.decomposition import KPI_REGISTRY, decompose_kpi
from engine.pooling import build_pooled_period, pooled_period_label
from engine.volume_bridge import decompose_total_solves
from generator.config_loader import WorldConfig

ALL_KPIS = list(KPI_REGISTRY.keys()) + ["TOTAL_SOLVES"]

# Qualitative read on which DIRECTION of movement is good/bad for each KPI, purely
# for human-readable labeling -- never used in the significance math itself.
DIRECTION_INTERPRETATION = {
    "AHT": {"increase": "worsened", "decrease": "improved"},
    "TPH": {"increase": "improved", "decrease": "worsened"},
    "CSAT_1STAR": {"increase": "worsened", "decrease": "improved"},
    "CSAT_5STAR": {"increase": "improved", "decrease": "worsened"},
    "TOTAL_SOLVES": {"increase": "grew", "decrease": "shrank"},
}


def _observed_value_for_threshold(kpi: str, result: dict, threshold: Threshold) -> float:
    """Pull the right scalar out of a decomposition/volume-bridge result to compare
    against this KPI's threshold, in the units the threshold expects.
    """
    if threshold.metric == "pct_change":
        return result["total_change_pct"]
    elif threshold.metric == "pp_change":
        return result["total_change_abs"] * 100.0
    raise ValueError(f"Unknown threshold metric type '{threshold.metric}'")


def check_kpi_anomaly(kpi: str, result: dict) -> dict:
    """Classify one KPI's decomposition/volume-bridge result as anomalous or not."""
    threshold = THRESHOLDS[kpi]
    observed = _observed_value_for_threshold(kpi, result, threshold)
    is_anomaly = abs(observed) > threshold.value
    direction = "increase" if observed > 0 else ("decrease" if observed < 0 else "flat")
    business_direction = DIRECTION_INTERPRETATION[kpi].get(direction, "unchanged")
    margin_ratio = abs(observed) / threshold.value if threshold.value else None

    return {
        "kpi": kpi,
        "is_anomaly": is_anomaly,
        "metric_type": threshold.metric,
        "observed_value": observed,
        "threshold_value": threshold.value,
        "null_noise_reference": threshold.null_noise,
        "margin_ratio": margin_ratio,  # >1.0 means it crossed the threshold
        "direction": direction,
        "business_direction": business_direction,
        "threshold_rationale": threshold.rationale,
        "comparison_type": result["comparison_type"],
        "period_baseline": result["period_baseline"],
        "period_current": result["period_current"],
        "decomposition": result,  # full Step 2 output, incl. queue_breakdown -- drivers already attached
    }


def detect_for_comparison(
    df0: pd.DataFrame, df1: pd.DataFrame, world: WorldConfig,
    label0: str, label1: str, comparison_type: str,
    baseline_periods_count: int = 1,
) -> list[dict]:
    """Run all 5 KPIs for one pair of periods, return one anomaly-check record each."""
    checks = []
    for kpi in KPI_REGISTRY:
        result = decompose_kpi(df0, df1, world, kpi, label0, label1, comparison_type)
        checks.append(check_kpi_anomaly(kpi, result))
    vb_result = decompose_total_solves(df0, df1, world, label0, label1, comparison_type, baseline_periods_count)
    checks.append(check_kpi_anomaly("TOTAL_SOLVES", vb_result))
    return checks


def detect_for_month(target_month: str, world: WorldConfig, include_pooled: bool = True) -> dict:
    """Auto-derive comparisons for `target_month` from the canonical month sequence
    (engine.data.CANONICAL_MONTH_ORDER): prior_month = immediately preceding month;
    pooled_baseline = all months strictly before it (only run if 2+ exist, since
    pooling 1 month is identical to the prior_month comparison). Runs BOTH available
    comparison types and flags a KPI as anomalous if EITHER crosses its threshold --
    catches a slow drift pooled-baseline would smooth over, and a one-off blip that
    prior-month alone would overreact to.
    """
    df_current = load_month(target_month)
    comparisons: dict[str, list[dict]] = {}

    prior_month = immediately_preceding_month(target_month)
    if prior_month is not None:
        df_prior = load_month(prior_month)
        comparisons["prior_month"] = detect_for_comparison(
            df_prior, df_current, world, prior_month, target_month, "prior_month"
        )

    preceding = months_before(target_month)
    if include_pooled and len(preceding) >= 2:
        pooled_df = build_pooled_period(preceding)
        pooled_label = pooled_period_label(preceding)
        comparisons["pooled_baseline"] = detect_for_comparison(
            pooled_df, df_current, world, pooled_label, target_month, "pooled_baseline",
            baseline_periods_count=len(preceding),
        )

    return _merge_comparisons(target_month, comparisons)


def _merge_comparisons(target_month: str, comparisons: dict[str, list[dict]]) -> dict:
    """Combine per-comparison-type results into one per-KPI verdict: anomalous if
    flagged in EITHER comparison that was run.
    """
    by_kpi: dict[str, dict] = {kpi: {"kpi": kpi, "flagged_by": [], "checks": {}} for kpi in ALL_KPIS}

    for comparison_type, checks in comparisons.items():
        for check in checks:
            kpi = check["kpi"]
            by_kpi[kpi]["checks"][comparison_type] = check
            if check["is_anomaly"]:
                by_kpi[kpi]["flagged_by"].append(comparison_type)

    kpi_verdicts = []
    for kpi in ALL_KPIS:
        entry = by_kpi[kpi]
        entry["is_anomaly"] = len(entry["flagged_by"]) > 0
        kpi_verdicts.append(entry)

    return {
        "target_month": target_month,
        "comparisons_run": list(comparisons.keys()),
        "kpi_verdicts": kpi_verdicts,
        "anomalous_kpis": [v["kpi"] for v in kpi_verdicts if v["is_anomaly"]],
    }
