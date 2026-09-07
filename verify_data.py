"""
Step 1b — Verification / sanity-check script.

Run:
    python verify_data.py

What it does (per the Step 1 spec):
  1. Loads each generated month and computes the 5 KPIs (AHT, TPH, 1-star %,
     5-star %, Total Solves) overall and by queue.
  2. Prints month-over-month KPI changes vs. the baseline month, and saves
     plots so injected effects can be visually confirmed.
  3. Runs an independent "back of envelope" weighted-average bridge
     decomposition directly from the generated data (NOT from
     ground_truth.json's analytical numbers) and compares it against
     ground_truth.json, for every scenario month.
  4. Flags data-quality issues: invalid persona/queue combos, non-positive
     handle times, out-of-range CSAT scores, KPI values outside sane ranges.

Exits non-zero if any hard-fail check fails, so it can be used as a gate
before starting any agent-logic work.
"""
from __future__ import annotations

import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from generator.bridge import mix_genuine_bridge, volume_bridge
from generator.config_loader import load_world_config
from generator.kpi import (
    check_kpi_sane_ranges,
    compute_kpis_by_queue,
    compute_overall_kpis,
    find_invalid_persona_queue_rows,
    find_negative_or_zero_handle_times,
    find_out_of_range_csat,
)

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"
GROUND_TRUTH_DIR = pathlib.Path(__file__).resolve().parent / "ground_truth"
PLOTS_DIR = pathlib.Path(__file__).resolve().parent / "docs" / "plots"

MONTH_ORDER = [
    "month_1_baseline",
    "month_2_scenario_mixshift",
    "month_3_scenario_genuine",
    "month_4_scenario_mixed",
]

BRIDGE_TOLERANCE_PCT_POINTS = 6.0  # allowed drift between analytical & realized mix/genuine split, in percentage points


def load_month(month_key: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{month_key}.csv", parse_dates=["date"])
    return df


def load_ground_truth(month_key: str) -> dict:
    with open(GROUND_TRUTH_DIR / f"{month_key}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def run_sanity_checks(month_key: str, df: pd.DataFrame, world, overall_kpis: dict) -> list[str]:
    hard_failures = []

    bad_pairs = find_invalid_persona_queue_rows(df, world)
    if len(bad_pairs):
        hard_failures.append(f"[{month_key}] {len(bad_pairs)} rows have a (queue, vertical, persona) combo not in valid_pairs")

    bad_ht = find_negative_or_zero_handle_times(df)
    if len(bad_ht):
        hard_failures.append(f"[{month_key}] {len(bad_ht)} rows have handle_time_sec <= 0")

    bad_csat = find_out_of_range_csat(df)
    if len(bad_csat):
        hard_failures.append(f"[{month_key}] {len(bad_csat)} rows have a csat_score outside {{1,2,3,4,5}}")

    range_issues = check_kpi_sane_ranges(overall_kpis)
    for issue in range_issues:
        hard_failures.append(f"[{month_key}] {issue}")

    return hard_failures


def print_overall_kpi_table(overall_by_month: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for month_key in MONTH_ORDER:
        k = overall_by_month[month_key]
        rows.append(
            {
                "month": month_key,
                "n_tickets": k["n_tickets"],
                "total_solves": k["total_solves"],
                "aht_sec": round(k["aht_sec"], 1),
                "tph": round(k["tph"], 3),
                "csat_1star_pct": round(k["csat_1star_pct"] * 100, 2),
                "csat_5star_pct": round(k["csat_5star_pct"] * 100, 2),
            }
        )
    table = pd.DataFrame(rows).set_index("month")
    print("\n=== Overall KPIs by month ===")
    print(table.to_string())

    baseline = table.loc["month_1_baseline"]
    print("\n=== Month-over-month change vs. month_1_baseline ===")
    delta_rows = []
    for month_key in MONTH_ORDER[1:]:
        row = table.loc[month_key]
        delta_rows.append(
            {
                "month": month_key,
                "d_total_solves": row["total_solves"] - baseline["total_solves"],
                "d_total_solves_pct": round(100 * (row["total_solves"] / baseline["total_solves"] - 1), 2),
                "d_aht_sec": round(row["aht_sec"] - baseline["aht_sec"], 1),
                "d_aht_pct": round(100 * (row["aht_sec"] / baseline["aht_sec"] - 1), 2),
                "d_tph": round(row["tph"] - baseline["tph"], 3),
                "d_tph_pct": round(100 * (row["tph"] / baseline["tph"] - 1), 2),
                "d_csat_1star_pp": round(row["csat_1star_pct"] - baseline["csat_1star_pct"], 2),
                "d_csat_5star_pp": round(row["csat_5star_pct"] - baseline["csat_5star_pct"], 2),
            }
        )
    delta_table = pd.DataFrame(delta_rows).set_index("month")
    print(delta_table.to_string())
    return table


def plot_kpis_by_queue(by_queue: dict[str, pd.DataFrame]):
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    queues = by_queue["month_1_baseline"].index.tolist()

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    metrics = [
        ("aht_sec", "AHT (seconds) by queue"),
        ("tph", "TPH (tickets/agent-hour) by queue"),
        ("csat_1star_pct", "1-star CSAT % by queue"),
        ("csat_5star_pct", "5-star CSAT % by queue"),
    ]
    x = range(len(queues))
    width = 0.2
    for ax, (metric, title) in zip(axes.flat, metrics):
        for i, month_key in enumerate(MONTH_ORDER):
            vals = by_queue[month_key][metric].reindex(queues)
            if metric.startswith("csat"):
                vals = vals * 100
            ax.bar([xi + i * width for xi in x], vals, width=width, label=month_key.replace("month_", "m").replace("_scenario", ""))
        ax.set_xticks([xi + 1.5 * width for xi in x])
        ax.set_xticklabels(queues, rotation=75, ha="right", fontsize=7)
        ax.set_title(title)
        ax.legend(fontsize=7)
    fig.tight_layout()
    out = PLOTS_DIR / "kpis_by_queue.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"\nSaved plot: {out}")

    # Volume share by queue, month over month (the mix-shift story)
    fig2, ax2 = plt.subplots(figsize=(10, 6))
    for month_key in MONTH_ORDER:
        shares = (by_queue[month_key]["n_tickets"] / by_queue[month_key]["n_tickets"].sum()).reindex(queues)
        ax2.plot(queues, shares.values * 100, marker="o", label=month_key)
    ax2.set_xticks(range(len(queues)))
    ax2.set_xticklabels(queues, rotation=75, ha="right", fontsize=8)
    ax2.set_ylabel("% of total ticket volume")
    ax2.set_title("Queue volume share by month (mix-shift visualization)")
    ax2.legend(fontsize=8)
    fig2.tight_layout()
    out2 = PLOTS_DIR / "volume_share_by_queue.png"
    fig2.savefig(out2, dpi=130)
    plt.close(fig2)
    print(f"Saved plot: {out2}")

    # Overall AHT/TPH month-over-month bars
    fig3, axes3 = plt.subplots(1, 2, figsize=(12, 4.5))
    overall_aht = [by_queue[m]["aht_sec"].mul(by_queue[m]["n_tickets"]).sum() / by_queue[m]["n_tickets"].sum() for m in MONTH_ORDER]
    overall_tph = [by_queue[m]["n_tickets"].sum() / by_queue[m]["agent_hours"].sum() for m in MONTH_ORDER]
    axes3[0].bar(MONTH_ORDER, overall_aht, color="steelblue")
    axes3[0].set_title("Overall blended AHT (sec) by month")
    axes3[0].tick_params(axis="x", rotation=30, labelsize=7)
    axes3[1].bar(MONTH_ORDER, overall_tph, color="darkorange")
    axes3[1].set_title("Overall TPH by month")
    axes3[1].tick_params(axis="x", rotation=30, labelsize=7)
    fig3.tight_layout()
    out3 = PLOTS_DIR / "overall_aht_tph_by_month.png"
    fig3.savefig(out3, dpi=130)
    plt.close(fig3)
    print(f"Saved plot: {out3}")


def back_of_envelope_bridge_check(month_key: str, baseline_df: pd.DataFrame, scenario_df: pd.DataFrame, gt: dict) -> list[str]:
    """Recompute the AHT and Total Solves bridges FROM THE RAW GENERATED DATA
    (independent of any generation-time bookkeeping) and compare against the
    analytical expected split logged in ground_truth.json.
    """
    print(f"\n=== Back-of-envelope bridge check: {month_key} vs month_1_baseline ===")
    issues = []

    # ---- AHT bridge, computed purely from realized ticket-level data ----
    old_counts = baseline_df.groupby("queue").size()
    new_counts = scenario_df.groupby("queue").size()
    old_shares = (old_counts / old_counts.sum()).to_dict()
    new_shares = (new_counts / new_counts.sum()).to_dict()
    old_aht = baseline_df.groupby("queue")["handle_time_sec"].mean().to_dict()
    new_aht = scenario_df.groupby("queue")["handle_time_sec"].mean().to_dict()

    realized = mix_genuine_bridge(old_aht, old_shares, new_aht, new_shares)
    realized_d = realized.as_dict()

    expected = gt["expected_decomposition"]["AHT_seconds"]

    print(f"  AHT total_delta   : analytical={expected['total_delta']:.2f}s   realized={realized_d['total_delta']:.2f}s")
    print(f"  AHT mix % of total: analytical={expected['mix_pct_of_total']*100:.1f}%   realized={realized_d['mix_pct_of_total']*100:.1f}%")
    print(f"  AHT genuine % of total: analytical={expected['genuine_pct_of_total']*100:.1f}%   realized={realized_d['genuine_pct_of_total']*100:.1f}%")

    mix_diff_pp = abs(expected["mix_pct_of_total"] - realized_d["mix_pct_of_total"]) * 100
    if mix_diff_pp > BRIDGE_TOLERANCE_PCT_POINTS:
        issues.append(
            f"[{month_key}] AHT mix%% drifted {mix_diff_pp:.1f}pp from analytical expectation "
            f"(tolerance {BRIDGE_TOLERANCE_PCT_POINTS}pp) -- investigate sampling noise or a generator bug"
        )
    else:
        print(f"  -> PASS (mix%% split within {BRIDGE_TOLERANCE_PCT_POINTS}pp tolerance)")

    # ---- Total Solves volume bridge, computed from realized RESOLVED counts ----
    old_resolved_vol = baseline_df.groupby("queue")["resolved"].sum().to_dict()
    new_resolved_vol = scenario_df.groupby("queue")["resolved"].sum().to_dict()
    realized_vb = volume_bridge(old_resolved_vol, new_resolved_vol)
    expected_vb = gt["expected_decomposition"]["total_solves_volume_bridge"]

    print(f"  Total Solves total_delta: analytical={expected_vb['total_delta']:.0f}   realized={realized_vb['total_delta']:.0f}")
    print(f"  Overall growth rate     : analytical={expected_vb['overall_growth_rate']*100:.2f}%   realized={realized_vb['overall_growth_rate']*100:.2f}%")

    growth_diff_pp = abs(expected_vb["overall_growth_rate"] - realized_vb["overall_growth_rate"]) * 100
    if growth_diff_pp > BRIDGE_TOLERANCE_PCT_POINTS:
        issues.append(
            f"[{month_key}] Total Solves growth rate drifted {growth_diff_pp:.1f}pp from analytical expectation"
        )
    else:
        print(f"  -> PASS (growth rate within {BRIDGE_TOLERANCE_PCT_POINTS}pp tolerance)")

    return issues


def main():
    world = load_world_config()

    dfs = {m: load_month(m) for m in MONTH_ORDER}
    ground_truths = {m: load_ground_truth(m) for m in MONTH_ORDER}

    overall_by_month = {}
    by_queue_by_month = {}
    all_hard_failures = []

    for month_key in MONTH_ORDER:
        df = dfs[month_key]
        overall = compute_overall_kpis(df, world)
        by_queue = compute_kpis_by_queue(df, world)
        overall_by_month[month_key] = overall
        by_queue_by_month[month_key] = by_queue

        failures = run_sanity_checks(month_key, df, world, overall)
        all_hard_failures.extend(failures)

    print_overall_kpi_table(overall_by_month)
    plot_kpis_by_queue(by_queue_by_month)

    for month_key in MONTH_ORDER[1:]:
        issues = back_of_envelope_bridge_check(
            month_key, dfs["month_1_baseline"], dfs[month_key], ground_truths[month_key]
        )
        all_hard_failures.extend(issues)

    print("\n=== Data quality flags ===")
    if all_hard_failures:
        for f in all_hard_failures:
            print(f"  FAIL: {f}")
    else:
        print("  None. All sanity checks and bridge cross-checks passed.")

    print("\n=== By-queue KPI tables ===")
    for month_key in MONTH_ORDER:
        print(f"\n--- {month_key} ---")
        print(by_queue_by_month[month_key].round(3).to_string())

    if all_hard_failures:
        print(f"\nVERIFICATION FAILED: {len(all_hard_failures)} issue(s) found. Do not proceed to agent-logic work.")
        sys.exit(1)
    else:
        print("\nVERIFICATION PASSED: generated data behaves as intended. Safe to proceed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
