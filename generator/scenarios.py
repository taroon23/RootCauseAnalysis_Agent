"""
Scenario definitions for the 4 generated months.

Each scenario is expressed as a set of *deltas* relative to Month 1
(baseline/control) — never as new absolute numbers hardcoded independently —
so it's always traceable exactly what was injected relative to the physics
in queues_config.yaml.

Month 1 — baseline/control: no deltas at all.
Month 2 — pure mix shift: volume shares move toward low-volume/high-AHT
          queues (Safety, Fraud, Vehicle) away from high-volume/low-AHT
          queues (Account&Login, Trip Issues, Order Issues). No queue's
          underlying handle-time/CSAT distribution changes. An explicit
          overall volume growth is layered on top purely so Total Solves
          has a real bridge to decompose.
Month 3 — pure genuine change: shares stay exactly at baseline. Technical/
          App Support's handle-time distribution degrades (+35% mean) and
          its CSAT distribution shifts negative, simulating a confusing app
          update. Overall volume grows uniformly (0% mix contribution to
          the Total Solves bridge, by construction).
Month 4 — mixed: BOTH the Month-2-style mix shift (half magnitude) and a
          genuine change in a different queue (Payments & Billing) happen
          together. The genuine-change magnitude is analytically solved
          (see generator/bridge.py) so that the AHT bridge comes out to
          EXACTLY a 60% mix / 40% genuine split — this is the calibrated
          "known target" the future decomposition engine must recover.
          TPH/CSAT/Total-Solves splits are NOT separately calibrated (see
          docs/step1_summary.md for why that's not generally possible) —
          their *actual* resulting splits are computed after generation and
          logged as observed, not targeted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from generator.bridge import solve_genuine_delta_for_target_mix_share
from generator.config_loader import WorldConfig
from generator.distributions import shift_csat_distribution_negative


@dataclass
class GenuineChange:
    queue: str
    handle_time_mean_multiplier: float  # 1.0 = no change
    csat_shift_amount: float            # probability points moved from top2 -> bottom2 buckets
    resolved_rate_delta: float = 0.0    # applied only to this queue


@dataclass
class ScenarioSpec:
    month_key: str
    month_label: str            # calendar label, e.g. "2026-01"
    scenario_type: str          # "baseline" | "mix_shift" | "genuine_change" | "mixed"
    description: str
    volume_share_deltas: dict[str, float] = field(default_factory=dict)  # queue -> delta share points
    overall_growth_rate: float = 0.0     # vs Month-1 baseline total tickets
    genuine_changes: list[GenuineChange] = field(default_factory=list)
    target_mix_share_for_calibration: float | None = None  # documented target (AHT), month 4 only
    calibration_target_queue: str | None = None

    def new_shares(self, world: WorldConfig) -> dict[str, float]:
        shares = {k: q.base_volume_share for k, q in world.queues.items()}
        for q, d in self.volume_share_deltas.items():
            shares[q] += d
        total = sum(shares.values())
        assert abs(total - 1.0) < 1e-6, f"Scenario '{self.month_key}' shares must sum to 1.0, got {total}"
        return shares

    def total_tickets(self, world: WorldConfig) -> int:
        return round(world.baseline_total_tickets * (1.0 + self.overall_growth_rate))

    def genuine_change_map(self) -> dict[str, GenuineChange]:
        return {gc.queue: gc for gc in self.genuine_changes}


# ---------------------------------------------------------------------------
# Mix-shift delta sets (share points). Both reused/scaled across scenarios.
# ---------------------------------------------------------------------------
FULL_MIX_SHIFT = {
    "account_login": -0.030,
    "trip_issues": -0.015,
    "order_issues": -0.015,
    "safety_incidents": +0.020,
    "fraud_risk": +0.020,
    "vehicle_equipment": +0.020,
}
HALF_MIX_SHIFT = {k: v / 2.0 for k, v in FULL_MIX_SHIFT.items()}


def build_scenarios(world: WorldConfig) -> list[ScenarioSpec]:
    baseline = ScenarioSpec(
        month_key="month_1_baseline",
        month_label="2026-01",
        scenario_type="baseline",
        description="Control month. No injected mix-shift or genuine-change effects.",
    )

    mix_shift = ScenarioSpec(
        month_key="month_2_scenario_mixshift",
        month_label="2026-02",
        scenario_type="mix_shift",
        description=(
            "Pure mix shift: volume share moves from high-volume/low-AHT queues "
            "(Account & Login, Trip Issues, Order Issues) into low-volume/high-AHT "
            "queues (Safety & Incidents, Fraud & Risk, Vehicle/Equipment). No "
            "queue's underlying handle-time or CSAT distribution changes. A "
            "+6% overall volume growth is layered on for the Total Solves bridge."
        ),
        volume_share_deltas=dict(FULL_MIX_SHIFT),
        overall_growth_rate=0.06,
    )

    genuine_change = ScenarioSpec(
        month_key="month_3_scenario_genuine",
        month_label="2026-03",
        scenario_type="genuine_change",
        description=(
            "Pure genuine change: volume shares held exactly at baseline (0% mix "
            "contribution by construction). Technical/App Support's mean handle "
            "time rises 35% and its CSAT distribution shifts negative, simulating "
            "a confusing app update. A +3% overall volume growth is layered on "
            "uniformly for the Total Solves bridge (0% mix contribution there too)."
        ),
        volume_share_deltas={},
        overall_growth_rate=0.03,
        genuine_changes=[
            GenuineChange(
                queue="technical_app_support",
                handle_time_mean_multiplier=1.35,
                csat_shift_amount=0.14,
                resolved_rate_delta=-0.04,
            )
        ],
    )

    # --- Month 4: mixed, calibrated to an exact 60% mix / 40% genuine AHT split ---
    old_shares = {k: q.base_volume_share for k, q in world.queues.items()}
    new_shares_month4 = dict(old_shares)
    for q, d in HALF_MIX_SHIFT.items():
        new_shares_month4[q] += d
    old_aht = {k: q.baseline_aht_seconds for k, q in world.queues.items()}
    calibration_target_queue = "payments_billing"
    target_mix_share = 0.60
    delta_seconds = solve_genuine_delta_for_target_mix_share(
        old_values=old_aht,
        old_weights=old_shares,
        new_weights=new_shares_month4,
        target_queue=calibration_target_queue,
        target_mix_share=target_mix_share,
    )
    calibrated_multiplier = (old_aht[calibration_target_queue] + delta_seconds) / old_aht[calibration_target_queue]

    mixed = ScenarioSpec(
        month_key="month_4_scenario_mixed",
        month_label="2026-04",
        scenario_type="mixed",
        description=(
            "Mixed: the same mix-shift direction as Month 2 (half magnitude) "
            "happens simultaneously with a genuine handle-time/CSAT change in "
            "Payments & Billing (a new fraud-check step). The Payments & Billing "
            "handle-time multiplier is analytically calibrated so the resulting "
            "AHT bridge is EXACTLY 60% mix-shift / 40% genuine-change. A +4% "
            "overall volume growth is layered on for the Total Solves bridge."
        ),
        volume_share_deltas=dict(HALF_MIX_SHIFT),
        overall_growth_rate=0.04,
        genuine_changes=[
            GenuineChange(
                queue=calibration_target_queue,
                handle_time_mean_multiplier=calibrated_multiplier,
                csat_shift_amount=0.08,
                resolved_rate_delta=-0.03,
            )
        ],
        target_mix_share_for_calibration=target_mix_share,
        calibration_target_queue=calibration_target_queue,
    )

    return [baseline, mix_shift, genuine_change, mixed]
