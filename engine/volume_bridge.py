"""
Total Solves volume attribution.

Structurally distinct from engine/decomposition.py on purpose: this is NOT a
mix-shift/genuine-change decomposition (there's no "rate" to hold a queue's
volume against — a queue's ticket count is just a ticket count). It's a
direct volume bridge: how many more/fewer resolved tickets did each queue
produce, period over period, and how much of the total swing does that
represent.
"""
from __future__ import annotations

import pandas as pd

from generator.config_loader import WorldConfig
from generator.kpi import compute_kpis_by_queue


def decompose_total_solves(
    df0: pd.DataFrame,
    df1: pd.DataFrame,
    world: WorldConfig,
    period0_label: str,
    period1_label: str,
    comparison_type: str,
    baseline_periods_count: int = 1,
) -> dict:
    """
    baseline_periods_count: how many months' worth of data df0 represents.
    Unlike AHT/TPH/CSAT% (weighted means/rates, invariant to how many months
    got pooled), Total Solves is a raw COUNT -- pooling N months naturally
    multiplies the baseline volume by ~N. For "pooled_baseline" comparisons
    (where df0 is several months concatenated), pass the number of pooled
    months here so the baseline is normalized back to an "average month"
    before comparing against the (single-month) current period. Otherwise
    the volume bridge would be comparing 1 month against N months of ticket
    counts, which is not a meaningful comparison.
    """
    table0 = compute_kpis_by_queue(df0, world)
    table1 = compute_kpis_by_queue(df1, world)

    queues = sorted(set(table0.index) | set(table1.index))
    solves0 = table0["total_solves"].reindex(queues).fillna(0) / baseline_periods_count
    solves1 = table1["total_solves"].reindex(queues).fillna(0)

    total0 = float(solves0.sum())
    total1 = float(solves1.sum())
    total_change_abs = total1 - total0
    total_change_pct = (total_change_abs / total0 * 100.0) if total0 else None

    queue_breakdown = []
    for q in queues:
        display_name = world.queues[q].display_name if q in world.queues else q
        volume_effect = float(solves1[q] - solves0[q])
        pct_of_total_change = (
            volume_effect / total_change_abs * 100.0 if abs(total_change_abs) > 1e-9 else None
        )
        queue_breakdown.append(
            {
                "queue": q,
                "queue_display_name": display_name,
                "old_solves": float(solves0[q]),
                "new_solves": float(solves1[q]),
                "volume_effect": volume_effect,
                "pct_of_total_volume_change": pct_of_total_change,
                "direction": "grew" if volume_effect > 0 else ("shrank" if volume_effect < 0 else "flat"),
            }
        )
    queue_breakdown.sort(key=lambda r: abs(r["volume_effect"]), reverse=True)

    return {
        "kpi": "TOTAL_SOLVES",
        "unit": "tickets",
        "comparison_type": comparison_type,
        "period_baseline": period0_label,
        "period_current": period1_label,
        "baseline_value": total0,
        "current_value": total1,
        "total_change_abs": total_change_abs,
        "total_change_pct": total_change_pct,
        "queue_breakdown": queue_breakdown,
        "baseline_periods_count": baseline_periods_count,
        "note": (
            "Total Solves is a direct volume bridge, not a mix-shift/genuine-change "
            "decomposition -- there is no mix_pct/genuine_pct here by design."
            + (
                f" Baseline was pooled across {baseline_periods_count} months and normalized "
                "to an average-month volume before comparing against the single-month current "
                "period, since raw ticket counts (unlike weighted rates) aren't duration-invariant."
                if baseline_periods_count > 1
                else ""
            )
        ),
    }
