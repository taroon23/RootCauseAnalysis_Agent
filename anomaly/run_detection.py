"""
CLI entrypoint for the anomaly detector.

Two modes:

  Auto mode -- give it a target month, it derives "prior month" and "pooled
  baseline" comparisons from the canonical month sequence automatically:
      python -m anomaly.run_detection --month month_4_scenario_mixed

  Explicit mode -- same shape as engine.run_decomposition, for ad-hoc
  comparisons that aren't just "the usual prior/pooled baseline for this
  month" (e.g. the month_1-vs-month_5 false-positive check):
      python -m anomaly.run_detection --baseline month_1_baseline \
          --current month_5_baseline_null --comparison-type prior_month
"""
from __future__ import annotations

import argparse
import json
import pathlib

import pandas as pd

from anomaly.detector import ALL_KPIS, detect_for_comparison, detect_for_month
from engine.data import load_month
from engine.pooling import build_pooled_period, pooled_period_label
from generator.config_loader import load_world_config


def print_verdicts_table(result: dict) -> None:
    print(f"\n{'='*100}")
    print(f"Anomaly detection: {result.get('target_month') or result.get('period_current')}")
    comparisons_run = result.get("comparisons_run") or [result.get("comparison_type")]
    print(f"Comparisons run: {comparisons_run}")
    print(f"{'='*100}")

    rows = []
    for v in result["kpi_verdicts"]:
        checks = v["checks"]
        example = next(iter(checks.values()))
        rows.append(
            {
                "kpi": v["kpi"],
                "ANOMALY": "YES" if v["is_anomaly"] else "no",
                "flagged_by": ",".join(v["flagged_by"]) or "-",
                "direction": example["business_direction"],
                "observed (prior_month)": _fmt_observed(checks.get("prior_month")),
                "observed (pooled)": _fmt_observed(checks.get("pooled_baseline")),
                "threshold": _fmt_threshold(example),
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))

    anomalous = result.get("anomalous_kpis", [])
    if anomalous:
        print(f"\n>>> {len(anomalous)} KPI(s) flagged as anomalous: {', '.join(anomalous)}")
    else:
        print("\n>>> No KPIs flagged as anomalous.")


def _fmt_observed(check: dict | None) -> str:
    if check is None:
        return "n/a"
    unit = "pp" if check["metric_type"] == "pp_change" else "%"
    return f"{check['observed_value']:+.2f}{unit}"


def _fmt_threshold(check: dict) -> str:
    unit = "pp" if check["metric_type"] == "pp_change" else "%"
    return f"{check['threshold_value']:.1f}{unit}"


def main():
    parser = argparse.ArgumentParser(description="Run the Step 3 anomaly detector.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--month", help="Target month: auto-derive prior/pooled comparisons from canonical sequence")
    mode.add_argument("--current", help="Explicit mode: current month (use with --baseline, --comparison-type)")
    parser.add_argument("--baseline", nargs="+", help="Explicit mode: one (prior_month) or more (pooled_baseline) months")
    parser.add_argument("--comparison-type", choices=["prior_month", "pooled_baseline"], help="Explicit mode only")
    parser.add_argument("--no-pooled", action="store_true", help="Auto mode: skip the pooled_baseline comparison")
    parser.add_argument("--out", default=None, help="Optional path to write JSON output")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    world = load_world_config()

    if args.month:
        result = detect_for_month(args.month, world, include_pooled=not args.no_pooled)
    else:
        if not args.baseline or not args.comparison_type:
            parser.error("Explicit mode requires --baseline and --comparison-type")
        if args.comparison_type == "prior_month" and len(args.baseline) != 1:
            parser.error("--comparison-type prior_month expects exactly one --baseline month")
        if len(args.baseline) == 1:
            df0, label0 = load_month(args.baseline[0]), args.baseline[0]
            baseline_periods_count = 1
        else:
            df0, label0 = build_pooled_period(args.baseline), pooled_period_label(args.baseline)
            baseline_periods_count = len(args.baseline)
        df1 = load_month(args.current)
        checks = detect_for_comparison(df0, df1, world, label0, args.current, args.comparison_type, baseline_periods_count)
        result = {
            "target_month": args.current,
            "comparisons_run": [args.comparison_type],
            "kpi_verdicts": [
                {"kpi": c["kpi"], "is_anomaly": c["is_anomaly"], "flagged_by": [args.comparison_type] if c["is_anomaly"] else [], "checks": {args.comparison_type: c}}
                for c in checks
            ],
            "anomalous_kpis": [c["kpi"] for c in checks if c["is_anomaly"]],
        }

    if not args.quiet:
        print_verdicts_table(result)

    if args.out:
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nWrote JSON output -> {out_path}")
    else:
        print("\n--- JSON output ---")
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
