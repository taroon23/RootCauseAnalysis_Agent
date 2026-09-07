"""
Low-level sampling helpers for Layer-1 "physics" draws.

Every function here takes an explicit `rng` (numpy.random.Generator) so that
generation is fully reproducible given a seed — no hidden global random state.
"""
from __future__ import annotations

import numpy as np


def lognormal_params_from_mean_cv(mean: float, cv: float) -> tuple[float, float]:
    """Convert a desired (mean, coefficient-of-variation) into the (mu, sigma)
    parameters of the underlying normal distribution for numpy's lognormal.
    """
    sigma2 = np.log(1.0 + cv**2)
    mu = np.log(mean) - sigma2 / 2.0
    return mu, np.sqrt(sigma2)


def sample_handle_time_seconds(
    mean_seconds: float,
    cv: float,
    size: int,
    rng: np.random.Generator,
    min_seconds: float = 10.0,
    max_multiple_of_mean: float = 12.0,
) -> np.ndarray:
    """Draw handle times from a lognormal with the given mean/CV.

    Clipped to [min_seconds, max_multiple_of_mean * mean_seconds] so that
    long-tail noise stays realistic rather than producing pathological
    outliers that would break KPI sanity checks.
    """
    mu, sigma = lognormal_params_from_mean_cv(mean_seconds, cv)
    draws = rng.lognormal(mean=mu, sigma=sigma, size=size)
    return np.clip(draws, min_seconds, mean_seconds * max_multiple_of_mean)


def sample_csat_scores(
    distribution: list[float],
    size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw CSAT scores 1..5 from a categorical distribution."""
    return rng.choice([1, 2, 3, 4, 5], size=size, p=distribution)


def apply_unresolved_penalty(scores: np.ndarray, penalty_buckets: int) -> np.ndarray:
    """Softly shift scores toward lower stars for unresolved tickets."""
    if penalty_buckets == 0:
        return scores
    shifted = scores - penalty_buckets
    return np.clip(shifted, 1, 5)


def sample_response_mask(
    resolved: np.ndarray,
    base_response_rate: float,
    unresolved_multiplier: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Decide which tickets receive a CSAT survey response at all.

    Resolved tickets respond at `base_response_rate`; unresolved tickets
    respond at `base_response_rate * unresolved_multiplier` (lower — people
    who didn't get their issue solved are less likely to bother rating it,
    which is also *conservative* for the agent: it won't see a flood of
    angry 1-stars from every unresolved ticket).
    """
    rates = np.where(resolved, base_response_rate, base_response_rate * unresolved_multiplier)
    draws = rng.random(size=len(resolved))
    return draws < rates


def shift_csat_distribution_negative(base_dist: list[float], shift_amount: float) -> list[float]:
    """Move `shift_amount` total probability points from the top two buckets
    (4-star, 5-star) to the bottom two buckets (1-star, 2-star), proportional
    to each bucket's existing share of its half. Leaves 3-star untouched.
    Result always sums to 1.0 (probability is conserved, just relocated).
    """
    d = list(base_dist)
    top_mass = d[3] + d[4]
    bottom_mass = d[0] + d[1]
    if top_mass <= 0 or shift_amount <= 0:
        return d
    take4 = shift_amount * (d[3] / top_mass)
    take5 = shift_amount * (d[4] / top_mass)
    d[3] -= take4
    d[4] -= take5
    if bottom_mass > 0:
        add1 = shift_amount * (d[0] / bottom_mass)
        add2 = shift_amount * (d[1] / bottom_mass)
    else:
        add1 = add2 = shift_amount / 2.0
    d[0] += add1
    d[1] += add2
    return d


def sample_modality(modality_mix: dict[str, float], size: int, rng: np.random.Generator) -> np.ndarray:
    modalities = list(modality_mix.keys())
    probs = list(modality_mix.values())
    return rng.choice(modalities, size=size, p=probs)


def sample_persona_pairs(
    valid_pairs: list[tuple[str, str]],
    weights: list[float],
    size: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Returns an array of indices into valid_pairs, one per ticket."""
    idx = np.arange(len(valid_pairs))
    return rng.choice(idx, size=size, p=weights)


def sample_dates(days_in_month: int, size: int, rng: np.random.Generator, weekday_boost: float = 1.15) -> np.ndarray:
    """Uniform-ish day-of-month draws (1..days_in_month) with a mild boost
    for weekdays 1-5 of each 7-day cycle, to avoid perfectly flat ticket
    volume across days (a little realism, not load-bearing for any KPI math).
    """
    day_weights = np.array([
        weekday_boost if (d % 7) not in (5, 6) else 1.0
        for d in range(days_in_month)
    ])
    day_weights = day_weights / day_weights.sum()
    return rng.choice(np.arange(1, days_in_month + 1), size=size, p=day_weights)
