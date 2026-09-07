"""
Loads config/queues_config.yaml into simple, typed Python structures.

Nothing in here should contain business numbers — those all live in the
YAML file. This module is just plumbing + light validation so that a bad
config fails loudly at load time instead of silently producing garbage data.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml

CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "queues_config.yaml"


@dataclass
class QueueConfig:
    key: str
    display_name: str
    valid_pairs: list[tuple[str, str]]          # (vertical, persona)
    base_volume_share: float
    baseline_aht_seconds: float
    aht_cv: float
    csat_distribution: list[float]               # P(score=1..5)
    modality_mix: dict[str, float]                # {Phone/Chat/Email: prob}
    utilization_target: float
    persona_weights: list[float] = field(default_factory=list)  # aligned to valid_pairs

    def __post_init__(self):
        if not self.persona_weights:
            n = len(self.valid_pairs)
            self.persona_weights = [1.0 / n] * n


@dataclass
class WorldConfig:
    random_seed: int
    baseline_total_tickets: int
    days_in_month: int
    shift_length_hours: float
    csat_base_response_rate: float
    csat_unresolved_response_multiplier: float
    csat_unresolved_score_penalty: int
    resolved_rate: float
    verticals: dict[str, list[str]]               # vertical -> personas
    modalities: list[str]
    queues: dict[str, QueueConfig]

    def queue_share_vector(self) -> dict[str, float]:
        return {k: q.base_volume_share for k, q in self.queues.items()}


def _validate(world: WorldConfig) -> None:
    total_share = sum(q.base_volume_share for q in world.queues.values())
    if abs(total_share - 1.0) > 1e-6:
        raise ValueError(f"Queue base_volume_share must sum to 1.0, got {total_share:.6f}")

    for key, q in world.queues.items():
        if abs(sum(q.csat_distribution) - 1.0) > 1e-6:
            raise ValueError(f"Queue '{key}' csat_distribution must sum to 1.0")
        if len(q.csat_distribution) != 5:
            raise ValueError(f"Queue '{key}' csat_distribution must have 5 entries (scores 1-5)")
        if abs(sum(q.modality_mix.values()) - 1.0) > 1e-6:
            raise ValueError(f"Queue '{key}' modality_mix must sum to 1.0")
        for vertical, persona in q.valid_pairs:
            if vertical not in world.verticals:
                raise ValueError(f"Queue '{key}' references unknown vertical '{vertical}'")
            if persona not in world.verticals[vertical]:
                raise ValueError(
                    f"Queue '{key}' references persona '{persona}' not valid for vertical '{vertical}'"
                )


def load_world_config(path: pathlib.Path = CONFIG_PATH) -> WorldConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    gs = raw["global_settings"]
    queues = {}
    for key, qraw in raw["queues"].items():
        queues[key] = QueueConfig(
            key=key,
            display_name=qraw["display_name"],
            valid_pairs=[tuple(pair) for pair in qraw["valid_pairs"]],
            base_volume_share=float(qraw["base_volume_share"]),
            baseline_aht_seconds=float(qraw["baseline_aht_seconds"]),
            aht_cv=float(qraw["aht_cv"]),
            csat_distribution=[float(x) for x in qraw["csat_distribution"]],
            modality_mix={k: float(v) for k, v in qraw["modality_mix"].items()},
            utilization_target=float(qraw["utilization_target"]),
            persona_weights=list(qraw.get("persona_weights", [])),
        )

    world = WorldConfig(
        random_seed=int(gs["random_seed"]),
        baseline_total_tickets=int(gs["baseline_total_tickets"]),
        days_in_month=int(gs["days_in_month"]),
        shift_length_hours=float(gs["shift_length_hours"]),
        csat_base_response_rate=float(gs["csat_base_response_rate"]),
        csat_unresolved_response_multiplier=float(gs["csat_unresolved_response_multiplier"]),
        csat_unresolved_score_penalty=int(gs["csat_unresolved_score_penalty"]),
        resolved_rate=float(gs["resolved_rate"]),
        verticals={k: list(v["personas"]) for k, v in raw["verticals"].items()},
        modalities=list(raw["modalities"]),
        queues=queues,
    )
    _validate(world)
    return world


if __name__ == "__main__":
    w = load_world_config()
    print(f"Loaded {len(w.queues)} queues, total share = {sum(q.base_volume_share for q in w.queues.values()):.4f}")
    for k, q in w.queues.items():
        print(f"  {k:24s} share={q.base_volume_share:.3f}  aht={q.baseline_aht_seconds:6.0f}s  pairs={q.valid_pairs}")
