"""
Core symmetric (Shapley-style) two-factor decomposition for weighted-mean /
rate KPIs: AHT, TPH, 1-star CSAT %, 5-star CSAT %.

This module has ZERO knowledge of what was injected into any period's data.
It only ever looks at two periods' worth of raw ticket-level data (via
generator.kpi, which itself has no injection knowledge either) and computes,
per queue:

    mix_effect_i     = 0.5 * [ (w1_i - w0_i) * v0_i + (w1_i - w0_i) * v1_i ]
    genuine_effect_i  = 0.5 * [ w0_i * (v1_i - v0_i) + w1_i * (v1_i - v0_i) ]

which simplifies to:

    mix_effect_i     = (w1_i - w0_i) * mean(v0_i, v1_i)
    genuine_effect_i  = (v1_i - v0_i) * mean(w0_i, w1_i)

This is symmetric in period order (unlike the "mix-first" convention used by
generator/bridge.py for data generation) and sums EXACTLY to the observed
change in the blended KPI, with no residual/interaction term left over:

    sum_i (mix_effect_i + genuine_effect_i) == blended_1 - blended_0

(see docs/step2_summary.md for the algebraic proof). We assert this identity
every time we compute a decomposition — if it doesn't hold, that's a bug.

Weighting basis:
    AHT, csat_1star_pct, csat_5star_pct  -> ticket-count share per queue
    TPH                                    -> agent-hours share per queue
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from generator.config_loader import WorldConfig, load_world_config
from generator.kpi import compute_kpis_by_queue

RECONSTRUCTION_ATOL = 1e-6  # absolute tolerance for the exact-reconstruction assertion

# KPI registry: which column of compute_kpis_by_queue() to use as the per-queue
# "value", and which weighting basis to use.
KPI_REGISTRY = {
    "AHT": {"value_col": "aht_sec", "weight_basis": "tickets", "unit": "seconds"},
    "TPH": {"value_col": "tph", "weight_basis": "agent_hours", "unit": "tickets_per_agent_hour"},
    "CSAT_1STAR": {"value_col": "csat_1star_pct", "weight_basis": "tickets", "unit": "proportion"},
    "CSAT_5STAR": {"value_col": "csat_5star_pct", "weight_basis": "tickets", "unit": "proportion"},
}


@dataclass
class PeriodQueueStats:
    """Per-queue weight + value for one period, for one KPI."""
    table: pd.DataFrame       # full compute_kpis_by_queue() output, indexed by queue
    weights: pd.Series        # queue -> weight (sums to 1.0)
    values: pd.Series         # queue -> KPI value
    blended_value: float      # weighted mean == the actual overall KPI for that period


def _weight_series(table: pd.DataFrame, weight_basis: str) -> pd.Series:
    if weight_basis == "tickets":
        basis = table["n_tickets"]
    elif weight_basis == "agent_hours":
        basis = table["agent_hours"]
    else:
        raise ValueError(f"Unknown weight_basis '{weight_basis}'")
    total = basis.sum()
    return basis / total


def compute_period_stats(df: pd.DataFrame, world: WorldConfig, kpi: str) -> PeriodQueueStats:
    if kpi not in KPI_REGISTRY:
        raise ValueError(f"Unknown KPI '{kpi}'. Valid: {list(KPI_REGISTRY)}")
    spec = KPI_REGISTRY[kpi]

    table = compute_kpis_by_queue(df, world)
    weights = _weight_series(table, spec["weight_basis"])
    values = table[spec["value_col"]]

    blended = float((weights * values).sum())
    return PeriodQueueStats(table=table, weights=weights, values=values, blended_value=blended)


def symmetric_decompose(stats0: PeriodQueueStats, stats1: PeriodQueueStats) -> pd.DataFrame:
    """Per-queue symmetric decomposition between two periods' stats for the
    SAME KPI. Returns a DataFrame indexed by queue with columns:
    old_weight, new_weight, old_value, new_value, mix_effect, genuine_effect,
    total_effect.

    Queues missing from either period are treated as weight/value 0 -> NaN
    handling: if a queue is entirely absent from one period, we fill its
    value with the other period's value (assumes "no genuine change" for a
    queue we have no data on in one period) so the math stays well-defined;
    in this project's generated data every queue has volume every month, so
    this fallback is not exercised in practice, but it keeps the engine from
    crashing on sparser real-world data later.
    """
    queues = sorted(set(stats0.weights.index) | set(stats1.weights.index))

    w0 = stats0.weights.reindex(queues).fillna(0.0)
    w1 = stats1.weights.reindex(queues).fillna(0.0)
    v0 = stats0.values.reindex(queues)
    v1 = stats1.values.reindex(queues)
    # If a queue has no data in one period, assume its rate/mean is unchanged
    # (fall back to whichever period DOES have a value) rather than NaN-poisoning
    # the whole decomposition.
    v0 = v0.fillna(v1)
    v1 = v1.fillna(v0)

    mix_effect = (w1 - w0) * (v0 + v1) / 2.0
    genuine_effect = (v1 - v0) * (w0 + w1) / 2.0
    total_effect = mix_effect + genuine_effect

    out = pd.DataFrame(
        {
            "old_weight": w0,
            "new_weight": w1,
            "old_value": v0,
            "new_value": v1,
            "mix_effect": mix_effect,
            "genuine_effect": genuine_effect,
            "total_effect": total_effect,
        },
        index=queues,
    )
    out.index.name = "queue"

    # --- Hard assertion: exact reconstruction, no residual ---
    observed_total_change = stats1.blended_value - stats0.blended_value
    reconstructed_total_change = out["total_effect"].sum()
    if not np.isclose(observed_total_change, reconstructed_total_change, atol=RECONSTRUCTION_ATOL):
        raise AssertionError(
            "Symmetric decomposition failed to reconstruct the observed total change exactly: "
            f"observed={observed_total_change!r} reconstructed={reconstructed_total_change!r} "
            f"diff={observed_total_change - reconstructed_total_change!r}"
        )

    return out


def decompose_kpi(
    df0: pd.DataFrame,
    df1: pd.DataFrame,
    world: WorldConfig,
    kpi: str,
    period0_label: str,
    period1_label: str,
    comparison_type: str,
) -> dict:
    """Full structured output for one KPI + one pair of periods."""
    stats0 = compute_period_stats(df0, world, kpi)
    stats1 = compute_period_stats(df1, world, kpi)
    per_queue = symmetric_decompose(stats0, stats1)

    total_change_abs = stats1.blended_value - stats0.blended_value
    total_change_pct = (total_change_abs / stats0.blended_value * 100.0) if stats0.blended_value else None

    total_mix = per_queue["mix_effect"].sum()
    total_genuine = per_queue["genuine_effect"].sum()

    queue_breakdown = []
    for queue, row in per_queue.iterrows():
        display_name = world.queues[queue].display_name if queue in world.queues else queue
        qtotal = row["total_effect"]
        if abs(qtotal) > 1e-9:
            mix_pct_q = row["mix_effect"] / qtotal * 100.0
            genuine_pct_q = row["genuine_effect"] / qtotal * 100.0
        else:
            mix_pct_q = None
            genuine_pct_q = None
        queue_breakdown.append(
            {
                "queue": queue,
                "queue_display_name": display_name,
                "old_weight": row["old_weight"],
                "new_weight": row["new_weight"],
                "old_value": row["old_value"],
                "new_value": row["new_value"],
                "mix_effect": row["mix_effect"],
                "genuine_effect": row["genuine_effect"],
                "total_effect": qtotal,
                "mix_pct_of_queue_effect": mix_pct_q,
                "genuine_pct_of_queue_effect": genuine_pct_q,
            }
        )
    # Sort by absolute total effect, largest driver first -- most useful for
    # an LLM (or human) reasoning layer scanning for "what mattered".
    queue_breakdown.sort(key=lambda r: abs(r["total_effect"]), reverse=True)

    overall_mix_pct = (total_mix / total_change_abs * 100.0) if abs(total_change_abs) > 1e-9 else None
    overall_genuine_pct = (total_genuine / total_change_abs * 100.0) if abs(total_change_abs) > 1e-9 else None

    return {
        "kpi": kpi,
        "unit": KPI_REGISTRY[kpi]["unit"],
        "weight_basis": KPI_REGISTRY[kpi]["weight_basis"],
        "comparison_type": comparison_type,
        "period_baseline": period0_label,
        "period_current": period1_label,
        "baseline_value": stats0.blended_value,
        "current_value": stats1.blended_value,
        "total_change_abs": total_change_abs,
        "total_change_pct": total_change_pct,
        "overall_mix_effect": total_mix,
        "overall_genuine_effect": total_genuine,
        "overall_mix_pct": overall_mix_pct,
        "overall_genuine_pct": overall_genuine_pct,
        "reconstruction_check_passed": True,  # symmetric_decompose() raises if not
        "queue_breakdown": queue_breakdown,
    }
