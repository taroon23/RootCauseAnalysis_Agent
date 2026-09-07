"""
Exact mix-shift / genuine-change bridge decomposition.

This is the core math both the *generator* (to calibrate scenario deltas to
a target contribution split) and, later, the Step-2 decomposition engine
will use. Keeping it in one place guarantees the ground truth we inject is
computed with the exact same formula the agent will later be graded
against.

Convention ("mix-first, then rate", a standard FP&A bridge):

    total_delta   = new_blended - old_blended
    mix_component = sum_q (new_weight_q - old_weight_q) * old_value_q
    genuine_component = sum_q new_weight_q * (new_value_q - old_value_q)

    total_delta == mix_component + genuine_component   (EXACTLY, no residual)

Proof:
    new_blended - old_blended
  = sum(new_w*new_v) - sum(new_w*old_v) + sum(new_w*old_v) - sum(old_w*old_v)
  = sum(new_w*(new_v-old_v)) + sum((new_w-old_w)*old_v)
  = genuine_component + mix_component

Note this convention is NOT symmetric (mix is evaluated at OLD values, genuine
is evaluated at NEW weights). A "genuine-first" convention would swap which
side gets the interaction term. We pick mix-first throughout this project and
document it everywhere so results are comparable. Both conventions are valid;
what matters is using the SAME one for injection and for grading.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BridgeResult:
    old_blended: float
    new_blended: float
    total_delta: float
    mix_component: float
    genuine_component: float
    per_queue: dict[str, dict[str, float]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "old_blended": self.old_blended,
            "new_blended": self.new_blended,
            "total_delta": self.total_delta,
            "mix_component": self.mix_component,
            "genuine_component": self.genuine_component,
            "mix_pct_of_total": _safe_pct(self.mix_component, self.total_delta),
            "genuine_pct_of_total": _safe_pct(self.genuine_component, self.total_delta),
            "per_queue": self.per_queue,
        }


def _safe_pct(numerator: float, denominator: float) -> float | None:
    if abs(denominator) < 1e-12:
        return None
    return numerator / denominator


def weighted_mean(values: dict[str, float], weights: dict[str, float]) -> float:
    return sum(weights[q] * values[q] for q in values)


def mix_genuine_bridge(
    old_values: dict[str, float],
    old_weights: dict[str, float],
    new_values: dict[str, float],
    new_weights: dict[str, float],
) -> BridgeResult:
    """Decompose the change in a weighted-mean/rate KPI into mix-shift vs.
    genuine (within-segment) change, using the mix-first convention above.
    """
    queues = list(old_values.keys())
    old_blended = weighted_mean(old_values, old_weights)
    new_blended = weighted_mean(new_values, new_weights)

    mix_component = sum((new_weights[q] - old_weights[q]) * old_values[q] for q in queues)
    genuine_component = sum(new_weights[q] * (new_values[q] - old_values[q]) for q in queues)

    per_queue = {}
    for q in queues:
        per_queue[q] = {
            "old_value": old_values[q],
            "new_value": new_values[q],
            "old_weight": old_weights[q],
            "new_weight": new_weights[q],
            "mix_contribution": (new_weights[q] - old_weights[q]) * old_values[q],
            "genuine_contribution": new_weights[q] * (new_values[q] - old_values[q]),
        }

    return BridgeResult(
        old_blended=old_blended,
        new_blended=new_blended,
        total_delta=new_blended - old_blended,
        mix_component=mix_component,
        genuine_component=genuine_component,
        per_queue=per_queue,
    )


def solve_genuine_delta_for_target_mix_share(
    old_values: dict[str, float],
    old_weights: dict[str, float],
    new_weights: dict[str, float],
    target_queue: str,
    target_mix_share: float,
) -> float:
    """Back out the absolute delta to apply to `target_queue`'s value (holding
    all other queues' values fixed at baseline) so that, given the ALREADY
    DECIDED weight shift (old_weights -> new_weights), the resulting bridge
    has mix_component / total_delta == target_mix_share.

    Returns the absolute delta (new_value - old_value) to apply to the
    target queue's baseline value.
    """
    queues = list(old_values.keys())
    mix_component = sum((new_weights[q] - old_weights[q]) * old_values[q] for q in queues)

    if target_mix_share <= 0 or target_mix_share >= 1:
        raise ValueError("target_mix_share must be strictly between 0 and 1")

    # mix_component / (mix_component + genuine_component) = target_mix_share
    # => genuine_component = mix_component * (1 - target_mix_share) / target_mix_share
    target_genuine_component = mix_component * (1.0 - target_mix_share) / target_mix_share

    # genuine_component = sum_q new_weight_q * (new_value_q - old_value_q)
    # only target_queue changes => genuine_component = new_weights[target_queue] * delta
    delta = target_genuine_component / new_weights[target_queue]
    return delta


def volume_bridge(old_volumes: dict[str, float], new_volumes: dict[str, float]) -> dict:
    """Decompose a total-volume change into an overall-growth component and a
    per-queue reallocation ("mix") component. Growth is applied uniformly at
    rate g = (new_total - old_total) / old_total; reallocation is the
    deviation of each queue's actual new volume from what uniform growth
    alone would have produced. Reallocation terms sum to exactly zero across
    queues (mix cannot change the total, only how it's distributed) — this
    exact cancellation makes the split correctly non-double-counted.
    """
    old_total = sum(old_volumes.values())
    new_total = sum(new_volumes.values())
    growth_rate = (new_total - old_total) / old_total if old_total else 0.0

    per_queue = {}
    for q in old_volumes:
        expected_if_uniform = old_volumes[q] * (1.0 + growth_rate)
        actual_new = new_volumes[q]
        per_queue[q] = {
            "old_volume": old_volumes[q],
            "new_volume": actual_new,
            "total_delta": actual_new - old_volumes[q],
            "growth_component": expected_if_uniform - old_volumes[q],
            "reallocation_component": actual_new - expected_if_uniform,
        }

    return {
        "old_total": old_total,
        "new_total": new_total,
        "total_delta": new_total - old_total,
        "overall_growth_rate": growth_rate,
        "per_queue": per_queue,
    }
