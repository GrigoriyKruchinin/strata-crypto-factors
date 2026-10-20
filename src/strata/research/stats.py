"""Multiple-testing aware statistics (Bailey & Lopez de Prado, 2014)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe(returns: pd.Series, benchmark_sr: float = 0.0) -> float:
    """P(true per-period Sharpe > ``benchmark_sr``) given skew/kurtosis of ``returns``."""
    r = returns.dropna().to_numpy(dtype=float)
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    z = (sr - benchmark_sr) * math.sqrt(t - 1) / denom
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Expected maximum per-period Sharpe among ``n_trials`` skill-less strategies."""
    if n_trials <= 1 or sharpe_variance <= 0:
        return 0.0
    std = math.sqrt(sharpe_variance)
    a = stats.norm.ppf(1 - 1 / n_trials)
    b = stats.norm.ppf(1 - 1 / (n_trials * math.e))
    return float(std * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b))


def deflated_sharpe(returns: pd.Series, n_trials: int, trial_sharpes: np.ndarray) -> float:
    """Probability the strategy's Sharpe beats the best of ``n_trials`` lucky strategies.

    ``trial_sharpes`` are the *per-period* Sharpes of all tested variations.
    """
    var = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
    return probabilistic_sharpe(returns, expected_max_sharpe(n_trials, var))


def percentile_of(value: float, distribution: np.ndarray) -> float:
    """Share of ``distribution`` strictly below ``value`` (0..1)."""
    if len(distribution) == 0:
        return float("nan")
    return float((distribution < value).mean())
