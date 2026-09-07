"""
Agent pool / shift simulation.

Design (see project chat for the "explicit_shifts" decision):
  - Staffing is *reactive-to-realized-load*, not a forecast: for each
    (queue, date), we look at the total handle-time actually generated that
    day, and staff exactly enough 8h-shift agents to cover it at the
    queue's `utilization_target`. This is a deliberate simplification of
    real-world staffing (which is forecast-based and imperfect) but it
    keeps agent-hours mechanically tied to workload while still being a
    genuine, discrete, shift-based simulation rather than a continuous
    formula — and it means TPH's *mix-shift* signal comes from agent-hours
    reallocating across queues in different proportions than raw ticket
    counts (because AHT differs by queue), while TPH's *genuine-change*
    signal flows from handle-time shifts changing how many agents a queue's
    workload requires.
  - Agents are NOT persistent across days (a fresh discrete pool is
    "scheduled" each day) — that's fine because nothing downstream needs
    agent identity to persist, only agent-HOURS aggregated by queue/day.
  - Within a (queue, date) group, tickets are assigned to on-shift agents
    uniformly at random (round-robin-ish), so no single agent is
    systematically loaded differently from another.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def assign_agents(
    df: pd.DataFrame,
    utilization_target_by_queue: dict[str, float],
    shift_length_hours: float,
    rng: np.random.Generator,
    min_agents_per_group: int = 1,
) -> pd.Series:
    """Given a ticket-level dataframe with columns ['queue', 'date', 'handle_time_sec'],
    return a Series of agent_id strings, one per row.
    """
    agent_ids = np.empty(len(df), dtype=object)
    shift_seconds = shift_length_hours * 3600.0

    # Group by (queue, date) using positional indices so we can assign back safely.
    group_keys = list(zip(df["queue"].values, df["date"].values))
    df_idx = pd.DataFrame({"queue": df["queue"].values, "date": df["date"].values})
    for (queue, date), idx in df_idx.groupby(["queue", "date"]).groups.items():
        idx = np.asarray(idx)
        total_handle_time = df["handle_time_sec"].values[idx].sum()
        utilization = utilization_target_by_queue[queue]
        n_agents = max(min_agents_per_group, int(np.ceil(total_handle_time / utilization / shift_seconds)))
        assigned = rng.integers(low=0, high=n_agents, size=len(idx))
        date_str = pd.Timestamp(date).strftime("%Y%m%d") if not isinstance(date, str) else str(date)
        for i, a in zip(idx, assigned):
            agent_ids[i] = f"{queue}_{date_str}_A{a:03d}"

    return pd.Series(agent_ids, index=df.index, name="agent_id")


def compute_agent_hours(df: pd.DataFrame, shift_length_hours: float, group_cols: list[str] | None = None) -> pd.DataFrame:
    """Reconstruct agent-hours from ticket-level data by counting distinct
    agent_id per (group_cols, date) and multiplying by shift length.

    This is exactly the calculation the verification script and, later, the
    decomposition engine will use for the TPH denominator — implemented once
    here so everything downstream stays consistent with how staffing was
    actually simulated.
    """
    cols = (group_cols or []) + ["date"]
    agent_days = df.groupby(cols)["agent_id"].nunique().rename("n_agents").reset_index()
    agent_days["agent_hours"] = agent_days["n_agents"] * shift_length_hours
    if group_cols:
        return agent_days.groupby(group_cols)["agent_hours"].sum().reset_index()
    return pd.DataFrame({"agent_hours": [agent_days["agent_hours"].sum()]})
