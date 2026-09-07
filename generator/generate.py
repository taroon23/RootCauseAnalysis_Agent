"""
Main ticket generator entry point.

Usage:
    python -m generator.generate

Produces, for each of the 4 months defined in generator/scenarios.py:
  - data/<month_key>.csv                  (ticket-level data)
  - ground_truth/<month_key>.json          (what was injected + analytical
                                             expected decomposition, computed
                                             directly from config — NOT from
                                             the generated data, so that
                                             verify_data.py's independent
                                             recomputation from the CSV is a
                                             real check, not a tautology)
"""
from __future__ import annotations

import calendar
import json
import pathlib
from datetime import date

import numpy as np
import pandas as pd

from generator.bridge import mix_genuine_bridge, volume_bridge
from generator.config_loader import WorldConfig, load_world_config
from generator.distributions import (
    apply_unresolved_penalty,
    sample_csat_scores,
    sample_dates,
    sample_handle_time_seconds,
    sample_modality,
    sample_persona_pairs,
    sample_response_mask,
    shift_csat_distribution_negative,
)
from generator.scenarios import ScenarioSpec, build_scenarios
from generator.staffing import assign_agents

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
GROUND_TRUTH_DIR = pathlib.Path(__file__).resolve().parent.parent / "ground_truth"


def _effective_queue_params(world: WorldConfig, scenario: ScenarioSpec):
    """Returns, per queue, the effective mean AHT (seconds), CSAT distribution,
    and resolved rate for this scenario (baseline unless a GenuineChange
    targets that queue).
    """
    genuine_map = scenario.genuine_change_map()
    mean_aht, csat_dist, resolved_rate = {}, {}, {}
    for key, q in world.queues.items():
        gc = genuine_map.get(key)
        if gc is None:
            mean_aht[key] = q.baseline_aht_seconds
            csat_dist[key] = q.csat_distribution
            resolved_rate[key] = world.resolved_rate
        else:
            mean_aht[key] = q.baseline_aht_seconds * gc.handle_time_mean_multiplier
            csat_dist[key] = shift_csat_distribution_negative(q.csat_distribution, gc.csat_shift_amount)
            resolved_rate[key] = world.resolved_rate + gc.resolved_rate_delta
    return mean_aht, csat_dist, resolved_rate


def generate_month_tickets(world: WorldConfig, scenario: ScenarioSpec, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    shares = scenario.new_shares(world)
    total_tickets = scenario.total_tickets(world)
    mean_aht, csat_dist, resolved_rate = _effective_queue_params(world, scenario)

    year, month = (int(x) for x in scenario.month_label.split("-"))
    days_in_month = calendar.monthrange(year, month)[1]

    frames = []
    for key, qcfg in world.queues.items():
        n = round(total_tickets * shares[key])
        if n <= 0:
            continue

        pair_idx = sample_persona_pairs(qcfg.valid_pairs, qcfg.persona_weights, n, rng)
        verticals = np.array([qcfg.valid_pairs[i][0] for i in pair_idx])
        personas = np.array([qcfg.valid_pairs[i][1] for i in pair_idx])

        modality = sample_modality(qcfg.modality_mix, n, rng)
        day_of_month = sample_dates(days_in_month, n, rng)
        dates = np.array([date(year, month, int(d)) for d in day_of_month])

        handle_time = sample_handle_time_seconds(mean_aht[key], qcfg.aht_cv, n, rng)
        resolved = rng.random(n) < resolved_rate[key]

        response_mask = sample_response_mask(
            resolved, world.csat_base_response_rate, world.csat_unresolved_response_multiplier, rng
        )
        raw_scores = sample_csat_scores(csat_dist[key], n, rng)
        unresolved_and_responded = (~resolved) & response_mask
        scores = raw_scores.astype(float)
        if unresolved_and_responded.any():
            scores[unresolved_and_responded] = apply_unresolved_penalty(
                raw_scores[unresolved_and_responded], world.csat_unresolved_score_penalty
            )
        scores[~response_mask] = np.nan

        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "vertical": verticals,
                    "persona": personas,
                    "modality": modality,
                    "queue": key,
                    "handle_time_sec": np.round(handle_time, 1),
                    "csat_score": scores,
                    "resolved": resolved,
                }
            )
        )

    df = pd.concat(frames, ignore_index=True)
    df = df.sample(frac=1.0, random_state=int(rng.integers(0, 1_000_000))).reset_index(drop=True)

    # Staffing / agent-hours simulation (needs queue + date + handle_time).
    utilization_by_queue = {k: q.utilization_target for k, q in world.queues.items()}
    df["agent_id"] = assign_agents(df, utilization_by_queue, world.shift_length_hours, rng)

    df.insert(0, "ticket_id", [f"{scenario.month_key}_{i:06d}" for i in range(len(df))])
    df = df[
        ["ticket_id", "date", "vertical", "persona", "modality", "queue", "agent_id",
         "handle_time_sec", "csat_score", "resolved"]
    ]
    return df


def _analytical_agent_hours_shares(shares: dict, mean_aht: dict, utilization: dict) -> dict:
    raw = {q: shares[q] * mean_aht[q] / utilization[q] for q in shares}
    total = sum(raw.values())
    return {q: v / total for q, v in raw.items()}


def compute_analytical_ground_truth(world: WorldConfig, baseline: ScenarioSpec, scenario: ScenarioSpec) -> dict:
    """Analytical (pre-sampling-noise) expected decomposition, computed
    directly from config + scenario deltas. This is the ground truth the
    agent will eventually be graded against; verify_data.py independently
    recomputes the same KPIs from the *generated* CSVs and checks they line
    up within sampling noise.
    """
    old_shares = baseline.new_shares(world)
    new_shares = scenario.new_shares(world)
    old_mean_aht, old_csat, old_resolved = _effective_queue_params(world, baseline)
    new_mean_aht, new_csat, new_resolved = _effective_queue_params(world, scenario)
    utilization = {k: q.utilization_target for k, q in world.queues.items()}

    # --- AHT bridge (ticket-count-share weights) ---
    aht_bridge = mix_genuine_bridge(old_mean_aht, old_shares, new_mean_aht, new_shares)

    # --- TPH bridge (agent-hours-share weights) ---
    old_tph_per_queue = {q: 3600.0 * utilization[q] / old_mean_aht[q] for q in old_mean_aht}
    new_tph_per_queue = {q: 3600.0 * utilization[q] / new_mean_aht[q] for q in new_mean_aht}
    old_ah_shares = _analytical_agent_hours_shares(old_shares, old_mean_aht, utilization)
    new_ah_shares = _analytical_agent_hours_shares(new_shares, new_mean_aht, utilization)
    tph_bridge = mix_genuine_bridge(old_tph_per_queue, old_ah_shares, new_tph_per_queue, new_ah_shares)

    # --- CSAT 1-star / 5-star bridges (ticket-count-share weights) ---
    old_1star = {q: old_csat[q][0] for q in old_csat}
    new_1star = {q: new_csat[q][0] for q in new_csat}
    csat1_bridge = mix_genuine_bridge(old_1star, old_shares, new_1star, new_shares)

    old_5star = {q: old_csat[q][4] for q in old_csat}
    new_5star = {q: new_csat[q][4] for q in new_csat}
    csat5_bridge = mix_genuine_bridge(old_5star, old_shares, new_5star, new_shares)

    # --- Total Solves volume bridge (RESOLVED ticket counts, not raw volume) ---
    # "Solves" means resolved tickets, so this also picks up any resolved_rate_delta
    # injected alongside a genuine change (a degraded queue resolves fewer tickets too).
    old_total = baseline.total_tickets(world)
    new_total = scenario.total_tickets(world)
    old_volumes = {q: old_total * old_shares[q] * old_resolved[q] for q in old_shares}
    new_volumes = {q: new_total * new_shares[q] * new_resolved[q] for q in new_shares}
    solves_bridge = volume_bridge(old_volumes, new_volumes)

    return {
        "month_key": scenario.month_key,
        "month_label": scenario.month_label,
        "scenario_type": scenario.scenario_type,
        "description": scenario.description,
        "compared_against": baseline.month_key,
        "injected_effects": {
            "volume_share_deltas": scenario.volume_share_deltas,
            "overall_growth_rate": scenario.overall_growth_rate,
            "genuine_changes": [
                {
                    "queue": gc.queue,
                    "handle_time_mean_multiplier": gc.handle_time_mean_multiplier,
                    "handle_time_mean_pct_change": gc.handle_time_mean_multiplier - 1.0,
                    "csat_shift_amount": gc.csat_shift_amount,
                    "resolved_rate_delta": gc.resolved_rate_delta,
                }
                for gc in scenario.genuine_changes
            ],
            "calibration": (
                {
                    "target_kpi": "AHT",
                    "target_queue": scenario.calibration_target_queue,
                    "target_mix_share": scenario.target_mix_share_for_calibration,
                    "note": (
                        "Only AHT is exactly calibrated to this split. TPH/CSAT/"
                        "Total-Solves splits below are the ANALYTICALLY-derived "
                        "consequence of the same injected deltas, not separately "
                        "targeted -- see docs/step1_summary.md."
                    ),
                }
                if scenario.target_mix_share_for_calibration is not None
                else None
            ),
        },
        "expected_decomposition": {
            "AHT_seconds": aht_bridge.as_dict(),
            "TPH_tickets_per_agent_hour": tph_bridge.as_dict(),
            "csat_1star_pct": csat1_bridge.as_dict(),
            "csat_5star_pct": csat5_bridge.as_dict(),
            "total_solves_volume_bridge": solves_bridge,
        },
    }


def main():
    DATA_DIR.mkdir(exist_ok=True)
    GROUND_TRUTH_DIR.mkdir(exist_ok=True)

    world = load_world_config()
    scenarios = build_scenarios(world)
    baseline = scenarios[0]

    for i, scenario in enumerate(scenarios):
        seed = world.random_seed + i
        print(f"Generating {scenario.month_key} (seed={seed})...")
        df = generate_month_tickets(world, scenario, seed=seed)

        csv_path = DATA_DIR / f"{scenario.month_key}.csv"
        df.to_csv(csv_path, index=False)
        print(f"  wrote {len(df):,} tickets -> {csv_path}")

        gt = compute_analytical_ground_truth(world, baseline, scenario)
        gt_path = GROUND_TRUTH_DIR / f"{scenario.month_key}.json"
        with open(gt_path, "w", encoding="utf-8") as f:
            json.dump(gt, f, indent=2, default=str)
        print(f"  wrote ground truth -> {gt_path}")


if __name__ == "__main__":
    main()
