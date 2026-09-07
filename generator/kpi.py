"""
KPI computation directly from ticket-level data.

Deliberately independent of generate.py / scenarios.py: this module only
ever looks at a ticket-level DataFrame (as if it just arrived from a real
data warehouse) and the static queue/persona config. It knows nothing about
what was "injected" — which is exactly what makes verify_data.py's use of
this module a genuine independent check against ground_truth.json, not a
tautology.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from generator.config_loader import WorldConfig
from generator.staffing import compute_agent_hours


def compute_kpis_by_queue(df: pd.DataFrame, world: WorldConfig) -> pd.DataFrame:
    rows = []
    agent_hours_by_queue = compute_agent_hours(df, world.shift_length_hours, group_cols=["queue"]).set_index("queue")

    for queue, g in df.groupby("queue"):
        n_tickets = len(g)
        n_resolved = int(g["resolved"].sum())
        aht = g["handle_time_sec"].mean()
        agent_hours = agent_hours_by_queue.loc[queue, "agent_hours"] if queue in agent_hours_by_queue.index else np.nan
        tph = n_tickets / agent_hours if agent_hours else np.nan

        responded = g["csat_score"].notna()
        n_responded = int(responded.sum())
        csat1_pct = (g.loc[responded, "csat_score"] == 1).mean() if n_responded else np.nan
        csat5_pct = (g.loc[responded, "csat_score"] == 5).mean() if n_responded else np.nan

        rows.append(
            {
                "queue": queue,
                "n_tickets": n_tickets,
                "n_resolved": n_resolved,
                "total_solves": n_resolved,
                "resolved_rate": n_resolved / n_tickets if n_tickets else np.nan,
                "aht_sec": aht,
                "agent_hours": agent_hours,
                "tph": tph,
                "n_csat_responses": n_responded,
                "csat_response_rate": n_responded / n_tickets if n_tickets else np.nan,
                "csat_1star_pct": csat1_pct,
                "csat_5star_pct": csat5_pct,
            }
        )
    return pd.DataFrame(rows).set_index("queue").sort_index()


def compute_overall_kpis(df: pd.DataFrame, world: WorldConfig) -> dict:
    n_tickets = len(df)
    n_resolved = int(df["resolved"].sum())
    aht = df["handle_time_sec"].mean()
    agent_hours = compute_agent_hours(df, world.shift_length_hours)["agent_hours"].iloc[0]
    tph = n_tickets / agent_hours if agent_hours else np.nan

    responded = df["csat_score"].notna()
    n_responded = int(responded.sum())
    csat1_pct = (df.loc[responded, "csat_score"] == 1).mean() if n_responded else np.nan
    csat5_pct = (df.loc[responded, "csat_score"] == 5).mean() if n_responded else np.nan

    return {
        "n_tickets": n_tickets,
        "n_resolved": n_resolved,
        "total_solves": n_resolved,
        "resolved_rate": n_resolved / n_tickets if n_tickets else np.nan,
        "aht_sec": aht,
        "agent_hours": agent_hours,
        "tph": tph,
        "n_csat_responses": n_responded,
        "csat_response_rate": n_responded / n_tickets if n_tickets else np.nan,
        "csat_1star_pct": csat1_pct,
        "csat_5star_pct": csat5_pct,
    }


def queue_share_by_ticket_count(df: pd.DataFrame) -> pd.Series:
    return (df["queue"].value_counts(normalize=True)).sort_index()


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------

def find_invalid_persona_queue_rows(df: pd.DataFrame, world: WorldConfig) -> pd.DataFrame:
    """Rows where (queue, vertical, persona) is not one of the queue's valid_pairs."""
    valid_lookup = {q: set(cfg.valid_pairs) for q, cfg in world.queues.items()}
    mask = ~df.apply(lambda r: (r["vertical"], r["persona"]) in valid_lookup.get(r["queue"], set()), axis=1)
    return df.loc[mask]


def find_negative_or_zero_handle_times(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[df["handle_time_sec"] <= 0]


def find_out_of_range_csat(df: pd.DataFrame) -> pd.DataFrame:
    scored = df.loc[df["csat_score"].notna()]
    return scored.loc[~scored["csat_score"].isin([1, 2, 3, 4, 5])]


def check_kpi_sane_ranges(overall: dict) -> list[str]:
    issues = []
    if not (30 <= overall["aht_sec"] <= 3600):
        issues.append(f"Overall AHT {overall['aht_sec']:.1f}s outside sane range [30, 3600]s")
    if not (0 <= overall["resolved_rate"] <= 1):
        issues.append(f"resolved_rate {overall['resolved_rate']} outside [0,1]")
    for key in ("csat_1star_pct", "csat_5star_pct", "csat_response_rate"):
        v = overall[key]
        if v is not None and not np.isnan(v) and not (0 <= v <= 1):
            issues.append(f"{key} {v} outside [0,1]")
    if not (0.1 <= overall["tph"] <= 50):
        issues.append(f"Overall TPH {overall['tph']:.2f} outside sane range [0.1, 50]")
    return issues
