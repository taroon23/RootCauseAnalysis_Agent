"""
CLI entrypoint for the decomposition engine.

Examples:
    # Single KPI, prior-month comparison
    python -m engine.run_decomposition --kpi AHT --comparison-type prior_month \
        --baseline month_1_baseline --current month_2_scenario_mixshift

    # All 5 KPIs, prior-month comparison
    python -m engine.run_decomposition --kpi ALL --comparison-type prior_month \
        --baseline month_3_scenario_genuine --current month_4_scenario_mixed

    # Pooled 3-month baseline vs. latest month
    python -m engine.run_decomposition --kpi ALL --comparison-type pooled_baseline \
        --baseline month_1_baseline month_2_scenario_mixshift month_3_scenario_genuine \
        --current month_4_scenario_mixed \
        --out results/month4_vs_pooled.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import pandas as pd

from engine.data import load_month
from engine.decomposition import KPI_REGISTRY, decompose_kpi
from engine.pooling import build_pooled_period, pooled_period_label
from engine.volume_bridge import decompose_total_solves
from generator.config_loader import load_world_config

ALL_KPIS = list(KPI_REGISTRY.keys()) + ["TOTAL_SOLVES"]


def get_period(month_keys: list[str]) -> tuple[pd.DataFrame, str]:
    """Resolve a list of one-or-more month keys into a single period
    DataFrame + a label. One month key = that month's raw data. Multiple =
    pooled.
    """
    if len(month_keys) == 1:
        return load_month(month_keys[0]), month_keys[0]
    return build_pooled_period(month_keys), pooled_period_label(month_keys)


def run_one_kpi(
    kpi: str, df0: pd.DataFrame, df1: pd.DataFrame, world, label0: str, label1: str,
    comparison_type: str, baseline_periods_count: int = 1,
) -> dict:
    if kpi == "TOTAL_SOLVES":
        return decompose_total_solves(df0, df1, world, label0, label1, comparison_type, baseline_periods_count)
    return decompose_kpi(df0, df1, world, kpi, label0, label1, comparison_type)


def print_decomposition_table(result: dict) -> None:
    print(f"\n{'='*90}")
    print(f"KPI: {result['kpi']}   comparison_type={result['comparison_type']}")
    print(f"  {result['period_baseline']}  ->  {result['period_current']}")
    print(f"{'='*90}")

    if result["kpi"] == "TOTAL_SOLVES":
        print(f"Baseline solves: {result['baseline_value']:.0f}   Current solves: {result['current_value']:.0f}")
        pct = result["total_change_pct"]
        print(f"Total change: {result['total_change_abs']:+.0f} tickets ({pct:+.1f}%)" if pct is not None else f"Total change: {result['total_change_abs']:+.0f} tickets")
        rows = []
        for q in result["queue_breakdown"]:
            rows.append(
                {
                    "queue": q["queue_display_name"],
                    "old_solves": round(q["old_solves"]),
                    "new_solves": round(q["new_solves"]),
                    "volume_effect": round(q["volume_effect"]),
                    "pct_of_total_change": None if q["pct_of_total_volume_change"] is None else round(q["pct_of_total_volume_change"], 1),
                    "direction": q["direction"],
                }
            )
        print(pd.DataFrame(rows).to_string(index=False))
        return

    print(f"Baseline: {result['baseline_value']:.4f}   Current: {result['current_value']:.4f}")
    pct = result["total_change_pct"]
    print(f"Total change: {result['total_change_abs']:+.4f} ({pct:+.1f}%)" if pct is not None else f"Total change: {result['total_change_abs']:+.4f}")
    om, og = result["overall_mix_pct"], result["overall_genuine_pct"]
    if om is not None:
        print(f"Overall split: mix={om:.1f}%   genuine={og:.1f}%")
    rows = []
    for q in result["queue_breakdown"]:
        rows.append(
            {
                "queue": q["queue_display_name"],
                "old_weight": round(q["old_weight"], 4),
                "new_weight": round(q["new_weight"], 4),
                "old_value": round(q["old_value"], 3),
                "new_value": round(q["new_value"], 3),
                "mix_effect": round(q["mix_effect"], 4),
                "genuine_effect": round(q["genuine_effect"], 4),
                "total_effect": round(q["total_effect"], 4),
                "mix_%": None if q["mix_pct_of_queue_effect"] is None else round(q["mix_pct_of_queue_effect"], 1),
                "genuine_%": None if q["genuine_pct_of_queue_effect"] is None else round(q["genuine_pct_of_queue_effect"], 1),
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Run the standalone decomposition engine.")
    parser.add_argument("--kpi", default="ALL", help=f"One of {ALL_KPIS} or ALL")
    parser.add_argument("--comparison-type", required=True, choices=["prior_month", "pooled_baseline"])
    parser.add_argument("--baseline", nargs="+", required=True, help="One month key (prior_month) or multiple (pooled_baseline)")
    parser.add_argument("--current", required=True, help="Current/latest month key")
    parser.add_argument("--out", default=None, help="Optional path to write JSON output")
    parser.add_argument("--quiet", action="store_true", help="Suppress printed tables")
    args = parser.parse_args()

    if args.comparison_type == "prior_month" and len(args.baseline) != 1:
        parser.error("--comparison-type prior_month expects exactly one --baseline month")
    if args.comparison_type == "pooled_baseline" and len(args.baseline) < 2:
        parser.error("--comparison-type pooled_baseline expects 2+ --baseline months to pool")

    world = load_world_config()
    df0, label0 = get_period(args.baseline)
    df1 = load_month(args.current)
    label1 = args.current

    kpis = ALL_KPIS if args.kpi.upper() == "ALL" else [args.kpi.upper()]
    baseline_periods_count = len(args.baseline)
    results = []
    for kpi in kpis:
        result = run_one_kpi(kpi, df0, df1, world, label0, label1, args.comparison_type, baseline_periods_count)
        results.append(result)
        if not args.quiet:
            print_decomposition_table(result)

    output = results if len(results) > 1 else results[0]
    if args.out:
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nWrote JSON output -> {out_path}")
    else:
        print("\n--- JSON output ---")
        print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
